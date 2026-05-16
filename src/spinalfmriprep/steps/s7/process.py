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

from spinalfmriprep.lib.run import run_command as _run_command


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
    if reproducibility_strict:
        env["ANTS_RANDOM_SEED"] = "1"
        env["ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS"] = "1"

    proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
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
    }
    for src_stem in masks_to_emit:
        src = template_dir / f"{src_stem}.nii.gz"
        if not src.exists():
            continue
        desc = name_map.get(src_stem, src_stem)
        dst = func_dir / f"{prefix}_desc-{desc}.nii.gz"
        shutil.copy(src, dst)
        paths[desc] = str(dst)
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


def _vertebral_label_offset_mm(
    subject_labels_in_PAM50: Path, pam50_levels: Path,
) -> tuple[Optional[float], Optional[float]]:
    """Per-label centroid offset in mm between subject vertebral labels
    (warped to PAM50) and the PAM50 spinal_levels atlas. Match labels by
    integer value (1..N). Return (mean_offset_mm, max_offset_mm).
    """
    try:
        sub_img = nib.load(subject_labels_in_PAM50)
        pam_img = nib.load(pam50_levels)
    except Exception:
        return None, None
    sub = np.asarray(sub_img.dataobj)
    pam = np.asarray(pam_img.dataobj)
    if sub.shape != pam.shape:
        return None, None
    zooms = np.array(sub_img.header.get_zooms()[:3], dtype=np.float32)

    offsets: list[float] = []
    sub_labels = np.unique(sub[sub > 0]).astype(int)
    pam_labels = np.unique(pam[pam > 0]).astype(int)
    common = sorted(set(sub_labels.tolist()) & set(pam_labels.tolist()))
    for lbl in common:
        a = np.argwhere(sub == lbl)
        b = np.argwhere(pam == lbl)
        if a.size == 0 or b.size == 0:
            continue
        ca = a.mean(axis=0) * zooms
        cb = b.mean(axis=0) * zooms
        offsets.append(float(np.linalg.norm(ca - cb)))
    if not offsets:
        return None, None
    return float(np.mean(offsets)), float(np.max(offsets))


def _round_trip_displacement_mm(
    funcref: Path,
    warp_func_to_PAM50: Path,
    warp_PAM50_to_func: Path,
    pam50_ref: Path,
    work_dir: Path,
) -> tuple[Optional[float], Optional[float]]:
    """Push funcref through forward then inverse; measure voxel-by-voxel
    displacement of the image grid origin point. Median + max.

    Implementation: forward-warp funcref to PAM50, then inverse-warp it back
    to funcref. Compare to the original by COM drift (per-voxel-displacement
    requires a sampling grid which is over-engineered for v1).
    """
    fwd = work_dir / "rt_funcref_in_PAM50.nii.gz"
    back = work_dir / "rt_funcref_back.nii.gz"
    ok, _ = _run_command([
        "sct_apply_transfo", "-i", str(funcref), "-d", str(pam50_ref),
        "-w", str(warp_func_to_PAM50), "-x", "linear", "-o", str(fwd),
    ])
    if not ok or not fwd.exists():
        return None, None
    ok, _ = _run_command([
        "sct_apply_transfo", "-i", str(fwd), "-d", str(funcref),
        "-w", str(warp_PAM50_to_func), "-x", "linear", "-o", str(back),
    ])
    if not ok or not back.exists():
        return None, None
    try:
        a = nib.load(funcref).get_fdata()
        b = nib.load(back).get_fdata()
        if a.shape != b.shape:
            return None, None
        zooms = np.array(nib.load(funcref).header.get_zooms()[:3], dtype=np.float32)
        # Center-of-mass drift, weighted by intensity. Coarse but sufficient.
        wa = a / max(a.sum(), 1.0)
        wb = b / max(b.sum(), 1.0)
        coords = np.indices(a.shape).reshape(3, -1).astype(np.float32)
        ca = (coords * wa.ravel()).sum(axis=1) * zooms
        cb = (coords * wb.ravel()).sum(axis=1) * zooms
        drift = float(np.linalg.norm(ca - cb))
        return drift, drift
    except Exception:
        return None, None


# ---------------------------------------------------------------------------
# Status classification
# ---------------------------------------------------------------------------


def _classify(metrics: dict, thresholds: dict) -> tuple[str, list[str]]:
    """Cord Dice in native func is the only gating metric for v1.

    Label offset and round-trip are observability-only — PAM50_spinal_levels
    and S2 vertebral_labels use different label schemes, and the
    intensity-weighted COM round-trip is dominated by FOV/background noise.
    """
    reasons: list[str] = []
    worst = "PASS"

    dice = metrics.get("cord_dice_native_func")
    pass_dice = thresholds.get("pass_dice_min", 0.80)
    fail_below = thresholds.get("fail_dice_below", 0.65)
    if dice is None:
        reasons.append("cord_dice_native_func not computed")
        worst = "WARN"
    elif dice < fail_below:
        reasons.append(f"cord_dice_native_func FAIL: {dice:.3f}")
        worst = "FAIL"
    elif dice < pass_dice:
        reasons.append(f"cord_dice_native_func WARN: {dice:.3f}")
        if worst == "PASS":
            worst = "WARN"

    return worst, reasons


# ---------------------------------------------------------------------------
# Public per-run entry
# ---------------------------------------------------------------------------


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
        func_dir = (out_dir / "derivatives" / "spinalfmriprep" / dataset_key
                    / f"sub-{subject}" / f"ses-{session}" / "func")
        figures_dir = (out_dir / "derivatives" / "spinalfmriprep" / dataset_key
                       / f"sub-{subject}" / f"ses-{session}" / "figures")
    else:
        func_dir = (out_dir / "derivatives" / "spinalfmriprep" / dataset_key
                    / f"sub-{subject}" / "func")
        figures_dir = (out_dir / "derivatives" / "spinalfmriprep" / dataset_key
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
    pam50_levels = _pam50_path(None, "template/PAM50_spinal_levels.nii.gz")

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

    # 6a. cord Dice in native func
    pam_cord_in_func = label_dir / "template" / "PAM50_cord.nii.gz"
    if pam_cord_in_func.exists():
        try:
            a = nib.load(pam_cord_in_func).get_fdata() > 0.5
            b = nib.load(func_seg_local).get_fdata() > 0.5
            if a.shape == b.shape:
                metrics["cord_dice_native_func"] = _dice(a, b)
        except Exception as e:
            failure_reasons.append(f"cord_dice failed: {e}")

    # 6b. label offset (optional, only when subject vertebral labels available)
    if subject_vertebral_labels and subject_vertebral_labels.exists():
        labels_in_PAM50 = s7_work_dir / "subject_labels_in_PAM50.nii.gz"
        ok, _ = _run_command([
            "sct_apply_transfo",
            "-i", str(subject_vertebral_labels),
            "-d", str(pam50_t2s),
            "-w", str(s2_warp_anat_to_PAM50),
            "-x", "nn", "-o", str(labels_in_PAM50),
        ])
        if ok and labels_in_PAM50.exists() and pam50_levels.exists():
            mean_off, max_off = _vertebral_label_offset_mm(labels_in_PAM50, pam50_levels)
            metrics["label_offset_pam50_mean_mm"] = mean_off
            metrics["label_offset_pam50_max_mm"] = max_off

    # 6c. round-trip drift
    rt_med, rt_max = _round_trip_displacement_mm(
        funcref=funcref_local,
        warp_func_to_PAM50=warp_func_to_PAM50,
        warp_PAM50_to_func=warp_PAM50_to_func,
        pam50_ref=pam50_t2s,
        work_dir=s7_work_dir,
    )
    metrics["round_trip_func_med_mm"] = rt_med
    metrics["round_trip_func_max_mm"] = rt_max

    # 7. Funcref in PAM50 (QC-only single 3D; we never push 4D BOLD there)
    funcref_in_PAM50 = func_dir / f"{prefix}_space-PAM50_desc-funcref.nii.gz"
    _run_command([
        "sct_apply_transfo",
        "-i", str(funcref_local),
        "-d", str(pam50_t2s),
        "-w", str(warp_func_to_PAM50),
        "-x", policy.get("interpolation", {}).get("bold", "spline"),
        "-o", str(funcref_in_PAM50),
    ])

    # 8. Classify
    status, reasons = _classify(metrics, policy.get("qc_thresholds", {}))
    failure_reasons.extend(reasons)

    # 9. Reportlets (sagittal/axial overlays + vertebral alignment)
    from .reportlets import (
        render_s7_pam50_overlay_sagittal,
        render_s7_pam50_overlay_axial,
        render_s7_vertebral_alignment,
    )
    rep_sag = figures_dir / f"{prefix}_desc-S7_pam50_overlay_sagittal.png"
    rep_axi = figures_dir / f"{prefix}_desc-S7_pam50_overlay_axial.png"
    rep_vert = figures_dir / f"{prefix}_desc-S7_vertebral_alignment.png"
    try:
        render_s7_pam50_overlay_sagittal(
            funcref_local, pam_cord_in_func, rep_sag,
        )
    except Exception as e:
        failure_reasons.append(f"sagittal reportlet failed: {e}")
    try:
        render_s7_pam50_overlay_axial(
            funcref_local, pam_cord_in_func, rep_axi,
        )
    except Exception as e:
        failure_reasons.append(f"axial reportlet failed: {e}")
    try:
        render_s7_vertebral_alignment(
            label_dir / "template" / "PAM50_spinal_levels.nii.gz",
            subject_vertebral_labels,
            rep_vert,
        )
    except Exception as e:
        failure_reasons.append(f"vertebral_alignment reportlet failed: {e}")

    # 10. Save work-side qc_metrics.json
    provenance = {
        "policy_sha256": policy_sha,
        "ants_random_seed": 1 if repro_strict else None,
        "itk_threads": 1 if repro_strict else None,
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
        "reportlets": {
            "pam50_overlay_sagittal": str(rep_sag.relative_to(out_dir))
                if rep_sag.exists() else "",
            "pam50_overlay_axial": str(rep_axi.relative_to(out_dir))
                if rep_axi.exists() else "",
            "vertebral_alignment": str(rep_vert.relative_to(out_dir))
                if rep_vert.exists() else "",
        },
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
