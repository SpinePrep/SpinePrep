"""S7: per-run template (PAM50) normalization.

Spec: .claude/specs/s7-template-normalization.md

Direction: SCT-canonical batch_processing.sh fMRI recipe. We never resample
4D BOLD into PAM50 (Eippert 2017 / CoSpi convention). Instead:

  1. Compose S2 anat<->PAM50 warps with S6 bold<->anat warps via
     sct_concat_transfo to produce a single initial PAM50<->func warp.
  2. Refine the warp at the EPI level with sct_register_multimodal,
     `step=1,type=seg,algo=slicereg,smooth=2:`
     `step=2,type=im,algo=bsplinesyn,iter=5,gradStep=0.5`,
     initialised from the composed warps via -initwarp/-initwarpinv.
  3. Warp the full PAM50 atlas into native func space with
     sct_warp_template (-a 1) and re-export key masks under BIDS-Derivatives.
  4. QC: cord Dice in native func, vertebral-label centroid offset in PAM50,
     funcref round-trip displacement.

Outputs are SCT-native .nii.gz displacement fields (consistent with S2/S6).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional

import nibabel as nib
import numpy as np

from spineprep.lib.run import run_command as _run_command
from spineprep.lib.timing import timed_step
from spineprep.lib.timing import timed_subprocess_run


# ---------------------------------------------------------------------------
# NIfTI helpers (mirrors S6)
# ---------------------------------------------------------------------------


def _sync_sform_qform(path: Path) -> None:
    """Set sform = qform on a NIfTI in place. Silent failure mode in SCT."""
    img = nib.load(path)
    aff = img.get_qform()
    img.set_sform(aff, code=int(img.header["sform_code"]) or 1)
    nib.save(img, path)


def _pam50_path(template_data_dir: Optional[Path], filename: str) -> Path:
    """Resolve a PAM50 file. None -> $SCT_DIR/data/PAM50/."""
    if template_data_dir is not None:
        return template_data_dir / filename
    sct_dir = os.environ.get("SCT_DIR")
    if not sct_dir:
        raise RuntimeError(
            "$SCT_DIR is not set and no template.data_dir given in policy"
        )
    return Path(sct_dir) / "data" / "PAM50" / filename


# ---------------------------------------------------------------------------
# Warp composition
# ---------------------------------------------------------------------------


def _concat_transfo(
    warps: list[Path], dest: Path, out: Path,
) -> tuple[bool, Optional[str]]:
    """sct_concat_transfo — concatenate ordered warps into a single file.

    Order convention (SCT): the *application* order of warps. When applying
    a warp to pull image A into space B (`-i A -d B -w w_A2B`), composing
    `w_A2X` then `w_X2B` produces `w_A2B`.
    """
    cmd = ["sct_concat_transfo", "-w"] + [str(w) for w in warps] + [
        "-d", str(dest), "-o", str(out),
    ]
    ok, stderr = _run_command(cmd)
    if not ok or not out.exists():
        return False, stderr or "sct_concat_transfo produced no output"
    return True, None


# ---------------------------------------------------------------------------
# EPI-template refinement (SCT batch_processing.sh fMRI block)
# ---------------------------------------------------------------------------


def _build_refine_param(refine_cfg: dict) -> str:
    """SCT canonical fMRI refinement: slicereg (seg, smooth=2) -> bsplinesyn (im, iter=5)."""
    def _step(step_id: int, step_cfg: dict, defaults: dict) -> str:
        parts = [f"step={step_id}"]
        for key in ("type", "algo", "metric", "smooth", "iter", "gradStep"):
            val = step_cfg.get(key, defaults.get(key))
            if val is not None:
                parts.append(f"{key}={val}")
        return ",".join(parts)
    pieces = [
        _step(1, refine_cfg.get("step1", {}),
              {"type": "seg", "algo": "slicereg",
               "metric": "MeanSquares", "smooth": 2}),
        _step(2, refine_cfg.get("step2", {}),
              {"type": "im", "algo": "bsplinesyn",
               "metric": "MeanSquares", "iter": 5, "gradStep": 0.5}),
    ]
    return ":".join(pieces)


def _run_refinement(
    pam50_t2s: Path,
    pam50_cord: Path,
    funcref: Path,
    func_cord_seg: Path,
    init_pam50_to_func: Path,
    init_func_to_pam50: Path,
    work_dir: Path,
    refine_cfg: dict,
    reproducibility_strict: bool,
) -> dict[str, Any]:
    """Refine the PAM50<->func warp at the EPI level.

    Direction in SCT semantics:
      -i PAM50_t2s -d funcref means PAM50 is moving, funcref is destination.
      `-owarp` ends up being `warp_PAM50_to_funcref` (pulls PAM50 -> func grid).
      `-owarpinv` is `warp_funcref_to_PAM50`.
    """
    param = _build_refine_param(refine_cfg)

    warp_PAM50_to_func = work_dir / "warp_PAM50_to_func_refined.nii.gz"
    warp_func_to_PAM50 = work_dir / "warp_func_to_PAM50_refined.nii.gz"

    cmd = [
        "sct_register_multimodal",
        "-i", str(pam50_t2s),
        "-iseg", str(pam50_cord),
        "-d", str(funcref),
        "-dseg", str(func_cord_seg),
        "-param", param,
        "-initwarp", str(init_pam50_to_func),
        "-initwarpinv", str(init_func_to_pam50),
        "-x", refine_cfg.get("interpolation", "spline"),
        "-ofolder", str(work_dir),
        "-owarp", str(warp_PAM50_to_func),
        "-owarpinv", str(warp_func_to_PAM50),
    ]
    env = os.environ.copy()
    # The seed is free and removes the dominant source of run-to-run variation
    # (ANTs' stochastic sampler), so it is always set. Pinning ITK to a single
    # thread additionally fixes the parallel reduction order, which is what
    # bit-identical output requires -- but it costs real wall-clock, so it stays
    # behind `reproducibility.strict`. Before 2026-07-19 both were behind that
    # flag and the flag shipped false, so registration ran fully unseeded while
    # the docs claimed "byte-identical re-run".
    env.setdefault("ANTS_RANDOM_SEED", "1")
    if reproducibility_strict:
        env["ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS"] = "1"

    proc = timed_subprocess_run(cmd, capture_output=True, text=True, env=env)
    if proc.returncode != 0:
        return {
            "status": "FAIL",
            "failure_message": f"sct_register_multimodal (S7 refine): {proc.stderr[-240:]}",
            "param_string": param,
        }
    if not warp_PAM50_to_func.exists() or not warp_func_to_PAM50.exists():
        return {
            "status": "FAIL",
            "failure_message": "S7 refinement produced no warp files",
            "param_string": param,
        }
    return {
        "status": "OK",
        "warp_PAM50_to_func": warp_PAM50_to_func,
        "warp_func_to_PAM50": warp_func_to_PAM50,
        "param_string": param,
    }


# ---------------------------------------------------------------------------
# Atlas → native func
# ---------------------------------------------------------------------------


def _warp_template_to_native(
    funcref: Path,
    warp_PAM50_to_func: Path,
    work_dir: Path,
    warp_full_atlas: bool = True,
) -> tuple[bool, Optional[Path], Optional[str]]:
    """sct_warp_template -d funcref -w warp_PAM50_to_func -a {0|1}.

    -a 1 brings the full PAM50 white-matter atlas in addition to the
    template + masks. Output dir layout (SCT default):
      <work>/label/template/PAM50_cord.nii.gz, _csf.nii.gz, _wm.nii.gz,
                            _gm.nii.gz, _spinal_levels.nii.gz, ...
      <work>/label/atlas/PAM50_atlas_*.nii.gz
    """
    label_dir = work_dir / "label"
    cmd = [
        "sct_warp_template",
        "-d", str(funcref),
        "-w", str(warp_PAM50_to_func),
        "-a", "1" if warp_full_atlas else "0",
        "-ofolder", str(label_dir),
    ]
    ok, stderr = _run_command(cmd)
    if not ok or not (label_dir / "template" / "PAM50_cord.nii.gz").exists():
        return False, None, stderr or "sct_warp_template produced no output"
    return True, label_dir, None


def _copy_native_atlas(
    label_dir: Path, masks_to_emit: list[str], func_dir: Path, prefix: str,
) -> dict[str, str]:
    """Copy selected PAM50 masks from label/template/ to func/ with BIDS names."""
    paths: dict[str, str] = {}
    template_dir = label_dir / "template"
    name_map = {
        "PAM50_cord":          "PAM50cord_mask",
        "PAM50_csf":           "PAM50csf_mask",
        "PAM50_wm":            "PAM50wm_mask",
        "PAM50_gm":            "PAM50gm_mask",
        "PAM50_spinal_levels": "PAM50spinallevels",
        # Added 2026-07-21 for the analysis endpoints. sct_warp_template already
        # produces all of these -- they were computed on every run and then left
        # in the work tree. Emitting them costs a copy, not a recomputation.
        "PAM50_levels":        "PAM50vertlevels",     # VERTEBRAL, not spinal
        "PAM50_rootlets":      "PAM50rootlets",
    }
    for src_stem in masks_to_emit:
        src = template_dir / f"{src_stem}.nii.gz"
        if not src.exists():
            continue
        desc = name_map.get(src_stem, src_stem)
        dst = func_dir / f"{prefix}_desc-{desc}.nii.gz"
        shutil.copy(src, dst)
        paths[desc] = str(dst)

    # Probabilistic tract/grey-matter atlas (label/atlas/PAM50_atlas_NN.nii.gz).
    # Emitted as a single 4D file plus its label table rather than 37 separate
    # volumes: it keeps the derivatives directory readable and makes the
    # parcel index unambiguous at analysis time. The grey-matter parcels
    # (dorsal horn, ventral horn, intermediate zone) are the ones the cord
    # literature cares about; note they are only 8-17 voxels at EPI
    # resolution, so anything computed on them is noisy by construction.
    atlas_dir = label_dir / "atlas"
    info = atlas_dir / "info_label.txt"
    if atlas_dir.is_dir() and info.exists():
        try:
            import nibabel as _nib
            import numpy as _np
            entries: list[tuple[int, str, str]] = []
            for line in info.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 3 and parts[0].isdigit():
                    entries.append((int(parts[0]), parts[1], parts[2]))
            vols, labels = [], []
            ref = None
            for idx, name, fname in sorted(entries):
                f = atlas_dir / fname
                if not f.exists():
                    continue
                img = _nib.load(f)
                if ref is None:
                    ref = img
                vols.append(_np.asarray(img.dataobj, dtype=_np.float32))
                labels.append({"index": len(vols) - 1, "atlas_id": idx, "name": name})
            if vols and ref is not None:
                stack = _np.stack(vols, axis=-1)
                dst = func_dir / f"{prefix}_desc-PAM50atlas_probseg.nii.gz"
                _nib.save(_nib.Nifti1Image(stack, ref.affine, ref.header), dst)
                (func_dir / f"{prefix}_desc-PAM50atlas_probseg.json").write_text(
                    json.dumps({
                        "Description": ("PAM50 probabilistic atlas warped to native "
                                        "functional space; 4th dimension indexes the "
                                        "parcels listed in Labels."),
                        "Space": "native functional",
                        "Labels": labels,
                    }, indent=2))
                paths["PAM50atlas_probseg"] = str(dst)
        except Exception:
            # Never fail the run over an optional analysis convenience.
            pass
    return paths


# ---------------------------------------------------------------------------
# QC metrics
# ---------------------------------------------------------------------------


def _binarize(arr: np.ndarray, threshold: float = 0.5) -> np.ndarray:
    return (arr > threshold).astype(bool)


def _dice(a: np.ndarray, b: np.ndarray) -> float:
    a = _binarize(a); b = _binarize(b)
    n = a.sum() + b.sum()
    if n == 0:
        return 0.0
    return float(2 * (a & b).sum() / n)


def _cord_round_trip_mm(
    cord_seg: Path,
    warp_func_to_PAM50: Path,
    warp_PAM50_to_func: Path,
    pam50_ref: Path,
    work_dir: Path,
) -> tuple[Optional[float], Optional[float]]:
    """Cord-mask-restricted round-trip drift in mm.

    Push the native cord seg through forward then inverse warps and
    measure (median, max) per-Z-slice in-plane centroid drift. Replaces
    the FOV-wide intensity-weighted COM round-trip (audit Finding 4 of
    s7-algorithm-audit.md), which was dominated by background voxels.
    """
    fwd = work_dir / "rt_cord_in_PAM50.nii.gz"
    back = work_dir / "rt_cord_back.nii.gz"
    ok, _ = _run_command([
        "sct_apply_transfo", "-i", str(cord_seg), "-d", str(pam50_ref),
        "-w", str(warp_func_to_PAM50), "-x", "nn", "-o", str(fwd),
    ])
    if not ok or not fwd.exists():
        return None, None
    ok, _ = _run_command([
        "sct_apply_transfo", "-i", str(fwd), "-d", str(cord_seg),
        "-w", str(warp_PAM50_to_func), "-x", "nn", "-o", str(back),
    ])
    if not ok or not back.exists():
        return None, None
    try:
        zooms = np.array(nib.load(cord_seg).header.get_zooms()[:3], dtype=np.float32)
        a = nib.load(cord_seg).get_fdata() > 0.5
        b = nib.load(back).get_fdata() > 0.5
        if a.shape != b.shape:
            return None, None
        drifts: list[float] = []
        for z in range(a.shape[2]):
            az = a[:, :, z]
            bz = b[:, :, z]
            if not az.any() or not bz.any():
                continue
            ca = np.array(np.where(az)).mean(axis=1) * zooms[:2]
            cb = np.array(np.where(bz)).mean(axis=1) * zooms[:2]
            drifts.append(float(np.linalg.norm(ca - cb)))
        if not drifts:
            return None, None
        return float(np.median(drifts)), float(np.max(drifts))
    except Exception:
        return None, None


def _cord_dice_per_level(
    pam50_cord_in_func: Path,
    func_cord_seg: Path,
    pam50_levels_in_func: Path,
) -> tuple[dict[int, float], list[int]]:
    """Compute per-vertebral-level cord Dice + the level coverage list.

    For each integer value present in PAM50_spinal_levels (warped into
    native func), compute the Dice between the PAM50_cord (restricted
    to that level's Z slices) and the native cord seg (same Z slices).

    Returns ({level_id: dice}, [level_ids_in_FOV_sorted_ascending]).
    The Kaptan 2023 / CoSpine 2025 / Valošek 2025 standard per-level
    diagnostic.
    """
    try:
        cord_pam50 = nib.load(pam50_cord_in_func).get_fdata() > 0.5
        cord_func = nib.load(func_cord_seg).get_fdata() > 0.5
        lvls = nib.load(pam50_levels_in_func).get_fdata().astype(np.int32)
    except Exception:
        return {}, []
    if cord_pam50.shape != cord_func.shape or cord_pam50.shape != lvls.shape:
        return {}, []
    coverage_set: set[int] = set()
    per_level: dict[int, float] = {}
    for lvl in sorted(int(v) for v in np.unique(lvls) if v > 0):
        lvl_mask = lvls == lvl
        if not lvl_mask.any():
            continue
        coverage_set.add(lvl)
        # Restrict Dice to Z slices where this level is present
        z_mask = lvl_mask.any(axis=(0, 1))
        if not z_mask.any():
            continue
        a = cord_pam50[:, :, z_mask] & lvl_mask[:, :, z_mask]
        b = cord_func[:, :, z_mask] & lvl_mask[:, :, z_mask]
        denom = int(a.sum()) + int(b.sum())
        if denom == 0:
            continue
        per_level[lvl] = float(2 * int((a & b).sum()) / denom)
    return per_level, sorted(coverage_set)


# ---------------------------------------------------------------------------
# Status classification
# ---------------------------------------------------------------------------


def _classify(metrics: dict, thresholds: dict) -> tuple[str, list[str]]:
    """Registration-quality gate, scored PER VERTEBRAL LEVEL (coverage-independent).

    The whole-volume ``cord_dice_native_func`` is confounded by how many cord
    levels the FUNCTIONAL FOV covers: a corticospinal / brain+cord acquisition
    images only a few cervical levels, so the whole-volume overlap tops out
    ~0.84 even for a perfect registration (a run covering 3 levels perfectly
    still scores ~0.5 overall). Gating on it therefore rejects good runs for
    having a naturally short cord extent.

    We instead gate on the MEDIAN per-level cord Dice — registration quality
    where the cord actually is — with a min-per-level guard for a single broken
    edge level. The whole-volume Dice is kept as an observability metric. Falls
    back to the legacy overall-Dice gate when per-level Dice is unavailable.

    The gate is three-banded (PASS / WARN / FAIL), matching the shape of the
    whole-volume fallback below. A single hard cliff at the PASS level was the
    original design, calibrated on CoSpiGVS alone, where good runs clustered at
    0.95-1.00 and failures at 0.87-0.88. That separation did not transfer: on
    the full 9-dataset cohort (n=456, median 0.978, p5 0.915) a 0.90 cliff sits
    inside the distribution's own low tail and split runs of the SAME subject
    and acquisition — 0.8997 FAIL beside 0.9019 PASS, a difference within
    run-to-run noise. The intermediate band routes those to visual inspection
    (invariant 4) instead of discarding them, while genuine outliers — the
    cohort's real failure group sits at <=0.82 — still FAIL.
    """
    import statistics as _stats

    reasons: list[str] = []
    worst = "PASS"

    per_level = metrics.get("cord_dice_per_level") or {}
    pl_vals = [v for v in per_level.values() if isinstance(v, (int, float))]
    ov = metrics.get("cord_dice_native_func")

    if pl_vals:
        pass_med = thresholds.get("per_level_pass_min", 0.90)
        fail_med = thresholds.get("per_level_fail_below", 0.85)
        broken_below = thresholds.get("per_level_broken_below", 0.50)
        med = _stats.median(pl_vals)
        lo = min(pl_vals)
        if med < fail_med:
            reasons.append(f"per-level median cord Dice FAIL: {med:.3f} (< {fail_med:.2f})")
            worst = "FAIL"
        elif med < pass_med:
            reasons.append(
                f"per-level median cord Dice WARN: {med:.3f} "
                f"(in [{fail_med:.2f}, {pass_med:.2f}) — inspect the bold_on_anat overlay)")
            worst = "WARN"
        # Independent of the median band: a single broken level is its own
        # diagnostic and must still be reported inside the WARN band.
        if lo < broken_below:
            reasons.append(
                f"one level Dice={lo:.3f} (< {broken_below:.2f}) — exclude that level "
                f"(per-level median {med:.3f})")
            if worst == "PASS":
                worst = "WARN"
        if ov is not None:
            reasons.append(
                f"whole-volume cord_dice_native_func={ov:.3f} (observability; "
                f"coverage-confounded, not gated)")
        return worst, reasons

    # Fallback: legacy whole-volume gate when per-level Dice is missing.
    pass_dice = thresholds.get("pass_dice_min", 0.80)
    fail_below = thresholds.get("fail_dice_below", 0.65)
    if ov is None:
        reasons.append("cord_dice_native_func not computed")
        worst = "WARN"
    elif ov < fail_below:
        reasons.append(f"cord_dice_native_func FAIL: {ov:.3f}")
        worst = "FAIL"
    elif ov < pass_dice:
        reasons.append(f"cord_dice_native_func WARN: {ov:.3f}")
        if worst == "PASS":
            worst = "WARN"

    return worst, reasons


# ---------------------------------------------------------------------------
# Public per-run entry
# ---------------------------------------------------------------------------


@timed_step
def run_S7_template_normalization(
    funcref_path: Path,
    func_cord_seg_path: Path,
    s6_warp_func_to_anat: Path,
    s6_warp_anat_to_func: Path,
    s2_warp_anat_to_PAM50: Path,
    s2_warp_PAM50_to_anat: Path,
    bold_run: dict,
    out_dir: Path,
    work_dir: Path,
    dataset_key: str,
    policy: dict[str, Any],
    s2_init_method: Optional[str] = None,
    subject_vertebral_labels: Optional[Path] = None,
) -> dict[str, Any]:
    """Run S7 for a single BOLD run.

    s2_init_method is "rootlet" | "disc" | "auto" — carried from S2 QC for
    reporting only; S7 trusts whatever warp S2 wrote.
    subject_vertebral_labels is optional; when None, the label-offset metric
    is skipped.
    """
    step_code = "S7_template_normalization"
    subject_raw = bold_run.get("subject") or ""
    session_raw = bold_run.get("session")
    subject = subject_raw[4:] if str(subject_raw).startswith("sub-") else subject_raw
    session = None
    if session_raw:
        session = (str(session_raw)[4:] if str(session_raw).startswith("ses-")
                   else session_raw)
    run_id = bold_run.get("run_id") or Path(bold_run.get("path", "")).name.replace(
        "_bold.nii.gz", "").replace("_bold.nii", "")

    if session:
        func_dir = (out_dir / "derivatives" / "spineprep" / dataset_key
                    / f"sub-{subject}" / f"ses-{session}" / "func")
        figures_dir = (out_dir / "derivatives" / "spineprep" / dataset_key
                       / f"sub-{subject}" / f"ses-{session}" / "figures")
    else:
        func_dir = (out_dir / "derivatives" / "spineprep" / dataset_key
                    / f"sub-{subject}" / "func")
        figures_dir = (out_dir / "derivatives" / "spineprep" / dataset_key
                       / f"sub-{subject}" / "figures")
    func_dir.mkdir(parents=True, exist_ok=True)
    figures_dir.mkdir(parents=True, exist_ok=True)
    s7_work_dir = work_dir / step_code / dataset_key / run_id
    s7_work_dir.mkdir(parents=True, exist_ok=True)

    failure_reasons: list[str] = []

    # 0. Pre-flight: sync sform/qform on local copies (don't mutate chain inputs)
    funcref_local = s7_work_dir / "funcref.nii.gz"
    func_seg_local = s7_work_dir / "func_cord_seg.nii.gz"
    shutil.copy(funcref_path, funcref_local)
    shutil.copy(func_cord_seg_path, func_seg_local)
    for p in (funcref_local, func_seg_local):
        try:
            _sync_sform_qform(p)
        except Exception as e:
            failure_reasons.append(f"sform/qform sync failed for {p.name}: {e}")

    # 1. Resolve PAM50 reference files
    template_cfg = policy.get("template", {})
    refmod = template_cfg.get("reference_modality", "T2s")
    pam50_ref_filename = {
        "T2s": "PAM50_t2s.nii.gz",
        "T2":  "PAM50_t2.nii.gz",
        "T1":  "PAM50_t1.nii.gz",
    }.get(refmod, "PAM50_t2s.nii.gz")
    data_dir = template_cfg.get("data_dir")
    template_data_dir = Path(data_dir) / "template" if data_dir else None
    pam50_t2s = _pam50_path(template_data_dir, f"template/{pam50_ref_filename}") \
        if template_data_dir is None else (template_data_dir / pam50_ref_filename)
    pam50_cord = _pam50_path(template_data_dir, "template/PAM50_cord.nii.gz") \
        if template_data_dir is None else (template_data_dir / "PAM50_cord.nii.gz")
    # F5 (s7-algorithm-audit.md): honor policy template_data_dir for the
    # spinal_levels lookup too (was hardcoded to $SCT_DIR).
    pam50_levels = (template_data_dir / "PAM50_spinal_levels.nii.gz"
                    if template_data_dir is not None
                    else _pam50_path(None, "template/PAM50_spinal_levels.nii.gz"))

    if not pam50_t2s.exists() or not pam50_cord.exists():
        return {
            "status": "FAIL", "step_code": step_code,
            "dataset_key": dataset_key,
            "subject": subject, "session": session, "run_id": run_id,
            "failure_message": f"PAM50 refs not found: {pam50_t2s}",
            "failure_reasons": failure_reasons + ["pam50_ref_missing"],
            "metrics": {}, "reportlets": {},
            "anat_to_pam50_init_method": s2_init_method,
            "refinement_enabled": False,
        }

    # 2. Compose initial PAM50<->func warps via S2+S6
    #    PAM50 -> func = (PAM50 -> anat) then (anat -> func)
    #    func -> PAM50 = (func -> anat) then (anat -> PAM50)
    init_PAM50_to_func = s7_work_dir / "warp_PAM50_to_func_init.nii.gz"
    init_func_to_PAM50 = s7_work_dir / "warp_func_to_PAM50_init.nii.gz"
    ok, err = _concat_transfo(
        [s2_warp_PAM50_to_anat, s6_warp_anat_to_func],
        dest=funcref_local, out=init_PAM50_to_func,
    )
    if not ok:
        return {
            "status": "FAIL", "step_code": step_code,
            "dataset_key": dataset_key,
            "subject": subject, "session": session, "run_id": run_id,
            "failure_message": f"compose PAM50->func init: {err}",
            "failure_reasons": failure_reasons + ["concat_pam50_to_func_failed"],
            "metrics": {}, "reportlets": {},
            "anat_to_pam50_init_method": s2_init_method,
            "refinement_enabled": False,
        }
    ok, err = _concat_transfo(
        [s6_warp_func_to_anat, s2_warp_anat_to_PAM50],
        dest=pam50_t2s, out=init_func_to_PAM50,
    )
    if not ok:
        return {
            "status": "FAIL", "step_code": step_code,
            "dataset_key": dataset_key,
            "subject": subject, "session": session, "run_id": run_id,
            "failure_message": f"compose func->PAM50 init: {err}",
            "failure_reasons": failure_reasons + ["concat_func_to_pam50_failed"],
            "metrics": {}, "reportlets": {},
            "anat_to_pam50_init_method": s2_init_method,
            "refinement_enabled": False,
        }

    # 3. Refinement (SCT batch_processing fMRI block). Optional via policy.
    refine_cfg = policy.get("refinement", {})
    refinement_enabled = bool(refine_cfg.get("enable", True))
    repro_strict = bool(policy.get("reproducibility", {}).get("strict", False))
    if refinement_enabled:
        ref = _run_refinement(
            pam50_t2s=pam50_t2s,
            pam50_cord=pam50_cord,
            funcref=funcref_local,
            func_cord_seg=func_seg_local,
            init_pam50_to_func=init_PAM50_to_func,
            init_func_to_pam50=init_func_to_PAM50,
            work_dir=s7_work_dir,
            refine_cfg=refine_cfg,
            reproducibility_strict=repro_strict,
        )
        if ref.get("status") != "OK":
            return {
                "status": "FAIL", "step_code": step_code,
                "dataset_key": dataset_key,
                "subject": subject, "session": session, "run_id": run_id,
                "failure_message": ref.get("failure_message"),
                "failure_reasons": failure_reasons + [ref.get("failure_message", "refine failed")],
                "metrics": {}, "reportlets": {},
                "anat_to_pam50_init_method": s2_init_method,
                "refinement_enabled": True,
            }
        warp_PAM50_to_func = ref["warp_PAM50_to_func"]
        warp_func_to_PAM50 = ref["warp_func_to_PAM50"]
        param_string = ref["param_string"]
    else:
        warp_PAM50_to_func = init_PAM50_to_func
        warp_func_to_PAM50 = init_func_to_PAM50
        param_string = "compose-only (refinement disabled)"

    # 4. Atlas -> native func space
    atlas_cfg = policy.get("atlas", {})
    ok, label_dir, err = _warp_template_to_native(
        funcref=funcref_local,
        warp_PAM50_to_func=warp_PAM50_to_func,
        work_dir=s7_work_dir,
        warp_full_atlas=bool(atlas_cfg.get("warp_full_atlas", True)),
    )
    if not ok:
        return {
            "status": "FAIL", "step_code": step_code,
            "dataset_key": dataset_key,
            "subject": subject, "session": session, "run_id": run_id,
            "failure_message": f"sct_warp_template: {err}",
            "failure_reasons": failure_reasons + ["warp_template_failed"],
            "metrics": {}, "reportlets": {},
            "anat_to_pam50_init_method": s2_init_method,
            "refinement_enabled": refinement_enabled,
        }

    prefix = run_id
    atlas_paths = _copy_native_atlas(
        label_dir=label_dir,
        masks_to_emit=atlas_cfg.get("masks_to_emit", [
            "PAM50_cord", "PAM50_csf", "PAM50_wm", "PAM50_gm",
            "PAM50_spinal_levels",
        ]),
        func_dir=func_dir,
        prefix=prefix,
    )

    # 5. Save warps under BIDS-Derivatives names + sidecar
    xfm_fwd = func_dir / f"{prefix}_from-bold_to-PAM50_xfm.nii.gz"
    xfm_inv = func_dir / f"{prefix}_from-PAM50_to-bold_xfm.nii.gz"
    sidecar = func_dir / f"{prefix}_from-bold_to-PAM50_xfm.json"
    shutil.copy(warp_func_to_PAM50, xfm_fwd)
    shutil.copy(warp_PAM50_to_func, xfm_inv)

    policy_sha = hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()
    sidecar.write_text(json.dumps({
        "Type": "ANTs displacement field (.nii.gz)",
        "From": "bold", "To": "PAM50",
        "AnatToPAM50InitMethod": s2_init_method,
        "RefinementEnabled": refinement_enabled,
        "RefinementParams": param_string,
        "Source": ["S2 anat<->PAM50 warps", "S6 bold<->anat warps", "S5 funcref"],
        "Software": "Spinal Cord Toolbox (sct_concat_transfo + sct_register_multimodal + sct_warp_template)",
        "AntsRandomSeed": 1 if repro_strict else None,
        "ItkThreads": 1 if repro_strict else None,
        "PolicySha256": policy_sha,
    }, indent=2), encoding="utf-8")

    # 6. QC metrics
    metrics: dict[str, Any] = {}

    pam_cord_in_func = label_dir / "template" / "PAM50_cord.nii.gz"
    pam_levels_in_func = label_dir / "template" / "PAM50_spinal_levels.nii.gz"

    # 6a. cord Dice in native func (overall, headline gate)
    if pam_cord_in_func.exists():
        try:
            a = nib.load(pam_cord_in_func).get_fdata() > 0.5
            b = nib.load(func_seg_local).get_fdata() > 0.5
            if a.shape == b.shape:
                metrics["cord_dice_native_func"] = _dice(a, b)
        except Exception as e:
            failure_reasons.append(f"cord_dice failed: {e}")

    # 6b. per-vertebral-level Dice + level coverage (Kaptan 2023 standard).
    # Replaces the mismatched-scheme label_offset_* metrics (audit
    # Finding 3 of s7-algorithm-audit.md, see s7-reportlet-set-audit.md).
    if pam_cord_in_func.exists() and pam_levels_in_func.exists():
        per_level, coverage = _cord_dice_per_level(
            pam_cord_in_func, func_seg_local, pam_levels_in_func,
        )
        if per_level:
            metrics["cord_dice_per_level"] = {str(k): v for k, v in per_level.items()}
        if coverage:
            metrics["vertebral_level_coverage"] = coverage

    # 6c. cord-restricted round-trip drift (audit Finding 4: replaces
    # FOV-wide intensity-weighted COM which was background-dominated).
    rt_med, rt_max = _cord_round_trip_mm(
        cord_seg=func_seg_local,
        warp_func_to_PAM50=warp_func_to_PAM50,
        warp_PAM50_to_func=warp_PAM50_to_func,
        pam50_ref=pam50_t2s,
        work_dir=s7_work_dir,
    )
    metrics["cord_round_trip_med_mm"] = rt_med
    metrics["cord_round_trip_max_mm"] = rt_max

    # 7. Funcref in PAM50 (QC-only single 3D; we never push 4D BOLD there)
    funcref_in_PAM50 = func_dir / f"{prefix}_space-PAM50_desc-funcref.nii.gz"
    ok_fp, err_fp = _run_command([
        "sct_apply_transfo",
        "-i", str(funcref_local),
        "-d", str(pam50_t2s),
        "-w", str(warp_func_to_PAM50),
        "-x", policy.get("interpolation", {}).get("bold", "spline"),
        "-o", str(funcref_in_PAM50),
    ])
    if not ok_fp:
        # QC-only PAM50 funcref preview; surface the failure rather than emit a
        # clean status with the preview silently missing.
        failure_reasons.append(f"funcref->PAM50 QC preview failed: {err_fp[:120]}")

    # 8. Classify
    status, reasons = _classify(metrics, policy.get("qc_thresholds", {}))
    failure_reasons.extend(reasons)

    # 9. Reportlets — 2 figures matching the field-standard
    # "composite + quantitative" pattern (see s7-reportlet-set-audit.md):
    #   1. pam50_on_func        — composite axial + sagittal overlays
    #   2. cord_dice_per_level  — per-vertebral-level Dice bar chart
    from .reportlets import (
        render_s7_pam50_on_func,
        render_s7_cord_dice_per_level,
    )
    rep_composite = figures_dir / f"{prefix}_desc-S7_pam50_on_func.png"
    rep_levels = figures_dir / f"{prefix}_desc-S7_cord_dice_per_level.png"
    dice_val = metrics.get("cord_dice_native_func")
    try:
        render_s7_pam50_on_func(
            funcref_path=funcref_local,
            pam50_cord_in_func_path=pam_cord_in_func,
            pam50_levels_in_func_path=pam_levels_in_func if pam_levels_in_func.exists() else None,
            func_cord_seg_path=func_seg_local,
            output_path=rep_composite,
            dice=dice_val,
        )
    except Exception as e:
        failure_reasons.append(f"pam50_on_func reportlet failed: {e}")
    try:
        render_s7_cord_dice_per_level(
            per_level=metrics.get("cord_dice_per_level") or {},
            thresholds=policy.get("qc_thresholds", {}),
            output_path=rep_levels,
        )
    except Exception as e:
        failure_reasons.append(f"cord_dice_per_level reportlet failed: {e}")

    # Record only reportlets that exist; a missing diagnostic downgrades PASS
    # to WARN. Paths were already existence-gated here, but status was computed
    # before rendering and never revisited, so a render failure left the run
    # reporting PASS with an empty reportlet path and no way to verify it.
    from spineprep.reportlets_common import resolve_reportlets
    reportlets, status = resolve_reportlets(
        {"pam50_on_func": rep_composite, "cord_dice_per_level": rep_levels},
        out_dir, status, failure_reasons,
        required=("pam50_on_func", "cord_dice_per_level"),
    )

    # 10. Save work-side qc_metrics.json
    provenance = {
        "policy_sha256": policy_sha,
        # Record what actually ran, not what was requested: the receipt is the
        # only way to tell after the fact which mode produced the numbers.
        "ants_random_seed": 1,
        "itk_threads": 1 if repro_strict else None,
        "reproducibility_strict": bool(repro_strict),
        "determinism": ("bit-identical" if repro_strict
                        else "seeded (thread reduction order not pinned)"),
    }
    (s7_work_dir / "qc_metrics.json").write_text(json.dumps({
        "metrics": metrics,
        "failure_reasons": failure_reasons,
        "provenance": provenance,
        "param_string": param_string,
        "anat_to_pam50_init_method": s2_init_method,
        "refinement_enabled": refinement_enabled,
    }, indent=2, default=str))

    return {
        "status": status,
        "step_code": step_code,
        "dataset_key": dataset_key,
        "subject": subject,
        "session": session,
        "run_id": run_id,
        "anat_to_pam50_init_method": s2_init_method,
        "refinement_enabled": refinement_enabled,
        "metrics": metrics,
        "failure_reasons": failure_reasons,
        "failure_message": "; ".join(failure_reasons) if failure_reasons else None,
        "reportlets": reportlets,
        "xfm_paths": {
            "from_bold_to_PAM50": str(xfm_fwd.relative_to(out_dir)),
            "from_PAM50_to_bold": str(xfm_inv.relative_to(out_dir)),
            "sidecar": str(sidecar.relative_to(out_dir)),
        },
        "atlas_paths": {
            "cord_mask": atlas_paths.get("PAM50cord_mask", ""),
            "csf_mask":  atlas_paths.get("PAM50csf_mask", ""),
            "wm_mask":   atlas_paths.get("PAM50wm_mask", ""),
            "gm_mask":   atlas_paths.get("PAM50gm_mask", ""),
            "spinal_levels": atlas_paths.get("PAM50spinallevels", ""),
        },
    }
