"""S6: per-run func->anat registration.

Spec: ``.claude/specs/s6-func-to-anat-registration.md``
Audit: ``.claude/specs/s6-algorithm-audit.md``

Algorithm — SpinePrep's own 3-stage seg-driven chain (`spi06_1fov_reg.sh`),
built from SCT's standard sct_register_multimodal primitives; intensity-agnostic
(seg-driven cost). NOT "Kaptan 2023 verbatim": Kaptan's code is 2 steps
(centermass -> bsplinesyn, iter=3) registering template->func directly; SCT's
default is also 2 steps (centermassrot -> bsplinesyn). columnwise and iter=20 are
SpinePrep tuning. See .claude/specs/s6-algorithm-audit-v2.md.

  step=1, type=seg, algo=centermassrot, metric=MeanSquares,
          slicewise=1, smooth=1            # bulk slicewise COM + roll
  step=2, type=seg, algo=columnwise, metric=MeanSquares,
          slicewise=1, smooth=1            # R-L scaling + A-P column
  step=3, type=seg, algo=bsplinesyn, metric=MeanSquares,
          slicewise=1, iter=20             # non-linear refinement

Direction: ``-i funcref -d anat`` (func is moving, anat is dest).
Anat is pre-cropped to a dilated cord region via ``sct_crop_image
-m anat_dseg -dilate 10x10x10``. We keep both the forward warp
(``warp_func2anat`` ↔ BIDS ``from-bold_to-anat_xfm``) and the
inverse (``warp_anat2func`` ↔ ``from-anat_to-bold_xfm``).

Pre-flight: sform=qform sync on local copies of all four inputs
(the #1 silent SCT failure mode).

Output xfm files are SCT-native ``.nii.gz`` displacement fields,
matching S2's ``_warp.nii.gz`` convention. Each xfm carries a JSON
sidecar with policy SHA, registration params, software version, and
the repro seed/thread settings.
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


# ---------------------------------------------------------------------------
# Pre-flight + mask
# ---------------------------------------------------------------------------


def _sync_sform_qform(path: Path) -> None:
    """Set sform = qform on a NIfTI in place. The #1 silent failure mode in
    SCT registration. Cheap and idempotent."""
    img = nib.load(path)
    aff = img.get_qform()
    img.set_sform(aff, code=int(img.header["sform_code"]) or 1)
    nib.save(img, path)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def _build_param_string(reg_cfg: dict) -> str:
    """CoSpi recipe: centermassrot -> columnwise -> bsplinesyn,iter=20.

    All three steps are slicewise=1, type=seg, MeanSquares. centermassrot
    handles oblique cord (slicewise COM + rotation); columnwise handles
    cord cross-section variation along the axis; bsplinesyn iter=20 is
    the final non-linear refinement.
    """
    def _step(step_id: int, step_cfg: dict, defaults: dict) -> str:
        parts = [f"step={step_id}"]
        for key in ("type", "algo", "metric", "slicewise", "smooth", "iter"):
            val = step_cfg.get(key, defaults.get(key))
            if val is not None:
                parts.append(f"{key}={val}")
        return ",".join(parts)

    pieces = []
    pieces.append(_step(1, reg_cfg.get("step1", {}),
                        {"type": "seg", "algo": "centermassrot",
                         "metric": "MeanSquares", "slicewise": 1, "smooth": 1}))
    pieces.append(_step(2, reg_cfg.get("step2", {}),
                        {"type": "seg", "algo": "columnwise",
                         "metric": "MeanSquares", "slicewise": 1, "smooth": 1}))
    pieces.append(_step(3, reg_cfg.get("step3", {}),
                        {"type": "seg", "algo": "bsplinesyn",
                         "metric": "MeanSquares", "slicewise": 1, "iter": 20}))
    return ":".join(pieces)


def _maybe_crop_anat(
    anat: Path, anat_dseg: Path, work_dir: Path, dilate: str = "10x10x10",
) -> tuple[Path, Path]:
    """sct_crop_image -m anat_dseg -dilate ... (CoSpi pre-flight).

    Crops anat (and its dseg) to a dilated cord region. This is what the
    CoSpi 1FOV pipeline does instead of any world-Z prealign or our
    earlier extent-ratio gating.
    """
    cropped_anat = work_dir / "anat_cr.nii.gz"
    cropped_dseg = work_dir / "anat_cr_seg.nii.gz"
    for src, dst in [(anat, cropped_anat), (anat_dseg, cropped_dseg)]:
        ok, _ = _run_command([
            "sct_crop_image", "-i", str(src),
            "-m", str(anat_dseg), "-dilate", dilate,
            "-o", str(dst),
        ])
        if not ok or not dst.exists():
            return anat, anat_dseg
    return cropped_anat, cropped_dseg


def _run_registration(
    funcref: Path,
    funccrop_mask: Path,
    anat: Path,
    anat_dseg: Path,
    work_dir: Path,
    policy: dict,
    reproducibility_strict: bool,
) -> dict[str, Any]:
    """CoSpi-style func->anat registration.

    Direction: `-i funcref -d anat` (func is moving, anat is destination,
    cropped to dilated cord). The forward warp (`warp_func2anat.nii.gz`)
    is the `from-bold_to-anat` direction we save. SCT writes both
    forward and inverse; we keep both via `-owarp/-owarpinv`.
    """
    reg_cfg = policy.get("registration", {})
    param = _build_param_string(reg_cfg)

    warp_func2anat = work_dir / "warp_func2anat.nii.gz"     # forward, from-bold_to-anat
    warp_anat2func = work_dir / "warp_anat2func.nii.gz"     # inverse, from-anat_to-bold

    cmd = [
        "sct_register_multimodal",
        "-i", str(funcref),
        "-iseg", str(funccrop_mask),
        "-d", str(anat),
        "-dseg", str(anat_dseg),
        "-param", param,
        "-x", reg_cfg.get("interpolation", "spline"),
        "-ofolder", str(work_dir),
        "-owarp", str(warp_func2anat),
        "-owarpinv", str(warp_anat2func),
    ]

    env = os.environ.copy()
    if reproducibility_strict:
        env["ANTS_RANDOM_SEED"] = "1"
        env["ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS"] = "1"

    proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if proc.returncode != 0:
        return {
            "status": "FAIL",
            "failure_message": f"sct_register_multimodal: {proc.stderr[-240:]}",
            "param_string": param,
        }
    if not warp_func2anat.exists() or not warp_anat2func.exists():
        return {
            "status": "FAIL",
            "failure_message": "SCT did not produce expected warp files",
            "param_string": param,
        }
    return {
        "status": "OK",
        "warp_func2anat": warp_func2anat,
        "warp_anat2func": warp_anat2func,
        "param_string": param,
    }


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


def _surface_points(mask: np.ndarray, zooms: tuple[float, float, float]) -> np.ndarray:
    """Return (N, 3) surface voxel coords in mm. Surface = mask XOR eroded(mask)."""
    from scipy.ndimage import binary_erosion
    boundary = mask & ~binary_erosion(mask, iterations=1)
    coords = np.argwhere(boundary).astype(np.float32)
    coords *= np.array(zooms, dtype=np.float32)
    return coords


def _hd95_and_asd(
    a: np.ndarray, b: np.ndarray, zooms: tuple[float, float, float]
) -> tuple[Optional[float], Optional[float]]:
    """Hausdorff-95 and average-surface-distance in mm."""
    from scipy.spatial import cKDTree
    pa = _surface_points(_binarize(a), zooms)
    pb = _surface_points(_binarize(b), zooms)
    if pa.size == 0 or pb.size == 0:
        return None, None
    d_a_to_b = cKDTree(pb).query(pa)[0]
    d_b_to_a = cKDTree(pa).query(pb)[0]
    pooled = np.concatenate([d_a_to_b, d_b_to_a])
    return float(np.percentile(pooled, 95)), float(pooled.mean())


def _resample_warp_to_target(
    moving_mask: Path, warp: Path, ref: Path, out: Path,
) -> bool:
    """Apply an SCT warp to a binary mask (NN interp)."""
    ok, _ = _run_command([
        "sct_apply_transfo",
        "-i", str(moving_mask),
        "-d", str(ref),
        "-w", str(warp),
        "-x", "nn",
        "-o", str(out),
    ])
    return ok and out.exists()


def _centerline_round_trip(
    seg: Path, warp_forward: Path, warp_inverse: Path,
    ref_dest: Path, ref_src: Path, work_dir: Path,
) -> tuple[Optional[float], Optional[float]]:
    """Push a seg through forward then inverse warp; report per-slice
    (median, max) centerline drift in voxels.

    For each Z slice present in BOTH the original and the round-tripped
    seg, compute the in-plane (X, Y) displacement of the slice's
    centroid. Return the median and max across cord-bearing slices.
    Previously this returned a single COM-norm value for both fields
    (audit-v2 Finding 5); fixed to a true per-slice array.
    """
    fwd = work_dir / "rt_forward.nii.gz"
    back = work_dir / "rt_roundtrip.nii.gz"
    if not _resample_warp_to_target(seg, warp_forward, ref_dest, fwd):
        return None, None
    if not _resample_warp_to_target(fwd, warp_inverse, ref_src, back):
        return None, None
    a = nib.load(seg).get_fdata() > 0.5
    b = nib.load(back).get_fdata() > 0.5
    if not a.any() or not b.any():
        return None, None

    drifts: list[float] = []
    for z in range(a.shape[2]):
        az = a[:, :, z]
        bz = b[:, :, z]
        if not az.any() or not bz.any():
            continue
        ca = np.array(np.where(az)).mean(axis=1)
        cb = np.array(np.where(bz)).mean(axis=1)
        drifts.append(float(np.linalg.norm(ca - cb)))
    if not drifts:
        return None, None
    return float(np.median(drifts)), float(np.max(drifts))


def _mutual_information(a: np.ndarray, b: np.ndarray, bins: int = 32) -> float:
    a = a.ravel(); b = b.ravel()
    finite = np.isfinite(a) & np.isfinite(b)
    a = a[finite]; b = b[finite]
    if a.size == 0:
        return 0.0
    H, _, _ = np.histogram2d(a, b, bins=bins)
    Pxy = H / max(H.sum(), 1)
    Px = Pxy.sum(axis=1, keepdims=True)
    Py = Pxy.sum(axis=0, keepdims=True)
    Pxy_safe = np.where(Pxy > 0, Pxy, 1)
    Px_safe = np.where(Px > 0, Px, 1)
    Py_safe = np.where(Py > 0, Py, 1)
    return float(np.sum(Pxy * np.log(Pxy_safe / (Px_safe * Py_safe))))


# ---------------------------------------------------------------------------
# Status classification
# ---------------------------------------------------------------------------


def _classify(metrics: dict, thresholds: dict, syn_fallback: bool) -> tuple[str, list[str]]:
    reasons: list[str] = []
    worst = "PASS"

    def _tier(value: Optional[float], pass_max: float, warn_max: float, label: str,
              lower_is_better: bool = True, gates: bool = True) -> str:
        """PASS/WARN/FAIL band for one metric.

        ``gates=False`` caps the result at WARN, for metrics the policy declares
        observability-only. ``lower_is_better=False`` inverts both comparisons;
        previously the warn bound was compared with the same direction as the
        pass bound, which would misclassify any higher-is-better metric (latent
        -- no call site used it).
        """
        if value is None:
            reasons.append(f"{label} not computed")
            return "WARN"
        if lower_is_better:
            ok, warn = value <= pass_max, value <= warn_max
        else:
            ok, warn = value >= pass_max, value >= warn_max
        if ok:
            return "PASS"
        if warn:
            reasons.append(f"{label} WARN: {value:.3f}")
            return "WARN"
        if not gates:
            reasons.append(f"{label} WARN: {value:.3f} (observability-only, does not gate)")
            return "WARN"
        reasons.append(f"{label} FAIL: {value:.3f}")
        return "FAIL"

    dice = metrics.get("cord_dice")
    pass_dice = (thresholds.get("pass_dice_min_syn_fallback", 0.80)
                 if syn_fallback else thresholds.get("pass_dice_min", 0.85))
    if dice is None:
        reasons.append("cord_dice not computed")
        worst = "WARN"
    elif dice < thresholds.get("fail_dice_below", 0.65):
        reasons.append(f"cord_dice FAIL: {dice:.3f}")
        worst = "FAIL"
    elif dice < pass_dice:
        reasons.append(f"cord_dice WARN: {dice:.3f}")
        worst = "WARN"

    # HD95 is observability-only (WARN ceiling, NEVER FAIL). It is quantized to
    # the EPI slice thickness (~5mm) and dominated by a single rostral/caudal
    # end-slice segmentation dropout, so it FAILed runs whose registration is
    # good by the step-local truth metric — cord Dice (CLAUDE.md principle #3).
    # E.g. exp pain sub-19: Dice 0.886, ASD ~1mm, but HD95 10mm -> wrongly FAILed
    # and lost the subject. Gate on Dice; surface HD95 as a soft flag only.
    hd95 = metrics.get("cord_hd95_mm")
    if hd95 is not None and hd95 > thresholds.get("pass_hd95_mm_max", 4.0):
        reasons.append(f"cord_hd95_mm WARN: {hd95:.3f}")
        if worst == "PASS":
            worst = "WARN"

    # Centerline round-trip drift is observability-only, as the policy states:
    # bsplinesyn optimizes the forward and inverse warps separately, so some
    # drift is intrinsic even at Dice 0.95. The code used to FAIL on it anyway,
    # contradicting the policy comment ("Setting permissive thresholds so it
    # does not gate"). gates=False makes the code match the documented intent.
    rt_med = metrics.get("centerline_round_trip_med_vox")
    t = _tier(rt_med, thresholds.get("pass_centerline_med_vox_max", 3.0),
              thresholds.get("warn_centerline_med_vox_max", 6.0),
              "centerline_round_trip_med_vox", gates=False)
    if t == "WARN" and worst == "PASS": worst = "WARN"

    rt_max = metrics.get("centerline_round_trip_max_vox")
    t = _tier(rt_max, thresholds.get("pass_centerline_max_vox_max", 5.0),
              thresholds.get("warn_centerline_max_vox_max", 10.0),
              "centerline_round_trip_max_vox", gates=False)
    if t == "WARN" and worst == "PASS": worst = "WARN"

    return worst, reasons


# ---------------------------------------------------------------------------
# Public per-run entry
# ---------------------------------------------------------------------------


def run_S6_func_to_anat_registration(
    funcref_path: Path,
    bold_path: Path,
    funccrop_mask_path: Path,
    anat_path: Path,
    anat_dseg_path: Path,
    bold_run: dict,
    out_dir: Path,
    work_dir: Path,
    dataset_key: str,
    policy: dict[str, Any],
    s5_mode: Optional[str] = None,
) -> dict[str, Any]:
    """Run S6 for a single BOLD run.

    Returns a qc-style dict with status, metrics, failure_reasons,
    reportlets (relative paths), xfm_paths (relative paths).
    """
    step_code = "S6_func_to_anat_registration"
    subject_raw = bold_run.get("subject") or ""
    session_raw = bold_run.get("session")
    subject = subject_raw[4:] if str(subject_raw).startswith("sub-") else subject_raw
    session = None
    if session_raw:
        session = (str(session_raw)[4:] if str(session_raw).startswith("ses-")
                   else session_raw)
    run_id = bold_run.get("run_id") or Path(bold_run.get("path", "")).name.replace(
        "_bold.nii.gz", "").replace("_bold.nii", "")

    # Output dirs
    if session:
        func_dir = (out_dir / "derivatives" / "spineprep" / f"sub-{subject}"
                    / f"ses-{session}" / "func")
    else:
        func_dir = (out_dir / "derivatives" / "spineprep" / f"sub-{subject}"
                    / "func")
    func_dir.mkdir(parents=True, exist_ok=True)
    figures_dir = func_dir.parent / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    s6_work_dir = work_dir / step_code / run_id
    s6_work_dir.mkdir(parents=True, exist_ok=True)

    # Anat modality from filename. Order matters: T2star must come
    # before T2w so the `_T2w` substring check doesn't eat T2star.
    # Audit-v2 Finding 7: previously this only handled T1w/T2w, so
    # balgrist's `*_desc-cordref_T2star.nii.gz` was recorded as None.
    anat_modality: Optional[str] = None
    for mod in ("T2star", "T2w", "T1w", "PD", "T1map"):
        if f"_{mod}" in anat_path.name:
            anat_modality = mod
            break

    failure_reasons: list[str] = []

    # 0. Pre-flight: sform/qform sync (local copies to avoid mutating chain inputs)
    funcref_local = s6_work_dir / "funcref.nii.gz"
    funccrop_local = s6_work_dir / "funccrop_mask.nii.gz"
    anat_local = s6_work_dir / f"anat_{anat_modality or 'mod'}.nii.gz"
    anat_dseg_local = s6_work_dir / f"anat_dseg_{anat_modality or 'mod'}.nii.gz"
    for src, dst in [
        (funcref_path, funcref_local),
        (funccrop_mask_path, funccrop_local),
        (anat_path, anat_local),
        (anat_dseg_path, anat_dseg_local),
    ]:
        shutil.copy(src, dst)
        try:
            _sync_sform_qform(dst)
        except Exception as e:
            failure_reasons.append(f"sform/qform sync failed for {dst.name}: {e}")

    # 1. Crop anat to dilated cord region (CoSpi pre-flight)
    anat_crop_cfg = policy.get("registration", {}).get("anat_crop", {})
    if anat_crop_cfg.get("enable", True):
        anat_for_reg, anat_dseg_for_reg = _maybe_crop_anat(
            anat_local, anat_dseg_local, s6_work_dir,
            dilate=anat_crop_cfg.get("dilate", "10x10x10"),
        )
    else:
        anat_for_reg, anat_dseg_for_reg = anat_local, anat_dseg_local

    # 2. Registration: func->anat (CoSpi recipe)
    repro_strict = bool(policy.get("reproducibility", {}).get("strict", False))
    reg = _run_registration(
        funcref=funcref_local,
        funccrop_mask=funccrop_local,
        anat=anat_for_reg,
        anat_dseg=anat_dseg_for_reg,
        work_dir=s6_work_dir,
        policy=policy,
        reproducibility_strict=repro_strict,
    )
    if reg.get("status") != "OK":
        return {
            "status": "FAIL", "step_code": step_code,
            "dataset_key": dataset_key,
            "subject": subject, "session": session, "run_id": run_id,
            "anat_modality": anat_modality,
            "distortion_correction_mode_inherited": s5_mode,
            "failure_message": reg.get("failure_message"),
            "failure_reasons": failure_reasons + [reg.get("failure_message", "reg failed")],
            "metrics": {},
            "reportlets": {},
        }

    # 4. Resample anat cord seg into funcref geometry via the inverse warp
    #    (warp_func2anat is the SCT inverse — i.e. takes points in BOLD space to
    #    anat space; to push anat_dseg into BOLD we apply warp_anat2func).
    anat_dseg_in_bold = s6_work_dir / "anat_dseg_in_bold.nii.gz"
    _resample_warp_to_target(
        anat_dseg_for_reg, reg["warp_anat2func"], funcref_local, anat_dseg_in_bold,
    )

    # 4. QC metrics
    metrics: dict[str, Any] = {}
    if anat_dseg_in_bold.exists():
        a = nib.load(funccrop_local).get_fdata() > 0.5
        b = nib.load(anat_dseg_in_bold).get_fdata() > 0.5
        if a.shape == b.shape:
            metrics["cord_dice"] = _dice(a, b)
            zooms = nib.load(funcref_local).header.get_zooms()[:3]
            hd95, asd = _hd95_and_asd(a, b, tuple(zooms))
            metrics["cord_hd95_mm"] = hd95
            metrics["cord_asd_mm"] = asd

    rt_med, rt_max = _centerline_round_trip(
        funccrop_local, reg["warp_func2anat"], reg["warp_anat2func"],
        anat_local, funcref_local, s6_work_dir,
    )
    metrics["centerline_round_trip_med_vox"] = rt_med
    metrics["centerline_round_trip_max_vox"] = rt_max

    # MI in funcref geometry: funcref vs anat resampled into BOLD via warp_anat2func
    anat_in_bold = s6_work_dir / "anat_in_bold.nii.gz"
    ok_aib, err_aib = _run_command([
        "sct_apply_transfo",
        "-i", str(anat_local),
        "-d", str(funcref_local),
        "-w", str(reg["warp_anat2func"]),
        "-x", "linear",
        "-o", str(anat_in_bold),
    ])
    if not ok_aib:
        # QC-auxiliary transform (feeds the MI metric + reportlet overlay, not the
        # primary warp). Don't fail the step, but make the failure visible instead
        # of silently dropping the metric.
        failure_reasons.append(f"anat->bold QC transform failed: {err_aib[:120]}")
    if anat_in_bold.exists():
        try:
            f = nib.load(funcref_local).get_fdata()
            a = nib.load(anat_in_bold).get_fdata()
            if f.shape == a.shape:
                # Whole-image MI (legacy). Dominated by the air/background overlap
                # on cord-cropped EPI, so it is a weak sanity check, not a gate.
                metrics["mi_after"] = _mutual_information(f, a)
                # Cord-restricted intensity MI -- the INDEPENDENT validator
                # (audit-v2 F3). The registration cost is type=seg (cord-MASK
                # overlap), so cord Dice is the optimiser's own objective and
                # cannot certify the alignment. MI between the EPI and the warped
                # anat INTENSITIES, inside the cord, is a quantity the
                # registration never optimised, so it is orthogonal to Dice: it
                # rises only if the actual cord tissue lands on the actual cord
                # tissue, and it catches an axial mis-registration that Dice on a
                # smooth cord tube is blind to. Cross-modal (BOLD EPI vs T1w/T2w/
                # T2star), so MI rather than correlation. Observability-only.
                cord = nib.load(funccrop_local).get_fdata() > 0.5
                if cord.shape == f.shape and int(cord.sum()) >= 20:
                    metrics["mi_cord_after"] = _mutual_information(
                        f[cord], a[cord], bins=16,
                    )
        except Exception:
            pass

    # 5. Classify status
    syn_fallback = (s5_mode == "syn")
    status, reasons = _classify(
        metrics, policy.get("qc_thresholds", {}), syn_fallback,
    )
    failure_reasons.extend(reasons)
    if syn_fallback:
        failure_reasons.append("syn_fallback_inherited (S5 mode=syn)")

    # 6. Save artifacts: xfm + sidecar + mean-bold-in-anat + tsnr funcref
    prefix = run_id
    xfm_fwd = func_dir / f"{prefix}_from-bold_to-anat_xfm.nii.gz"
    xfm_inv = func_dir / f"{prefix}_from-anat_to-bold_xfm.nii.gz"
    sidecar = func_dir / f"{prefix}_from-bold_to-anat_xfm.json"
    shutil.copy(reg["warp_func2anat"], xfm_fwd)
    shutil.copy(reg["warp_anat2func"], xfm_inv)

    policy_sha = hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()
    sidecar.write_text(json.dumps({
        "Type": "ANTs displacement field (.nii.gz)",
        "From": "bold", "To": "anat",
        "AnatModality": anat_modality,
        "Source": [str(funcref_path.relative_to(out_dir))
                   if str(funcref_path).startswith(str(out_dir)) else funcref_path.name],
        "RegistrationMethod": "SCT sct_register_multimodal",
        "RegistrationParams": reg.get("param_string"),
        "Software": "Spinal Cord Toolbox",
        "AntsRandomSeed": 1 if repro_strict else None,
        "ItkThreads": 1 if repro_strict else None,
        "PolicySha256": policy_sha,
    }, indent=2), encoding="utf-8")

    # Mean BOLD in anat geometry (QC view)
    bold4d_in_anat = func_dir / f"{prefix}_space-anat_desc-mean_bold.nii.gz"
    bold_mean_local = s6_work_dir / "bold_mean.nii.gz"
    bimg = nib.load(bold_path)
    bdata = bimg.get_fdata()
    bmean = bdata.mean(axis=3) if bdata.ndim == 4 else bdata
    nib.save(nib.Nifti1Image(bmean.astype(np.float32), bimg.affine,
                             bimg.header), bold_mean_local)
    ok_bia, err_bia = _run_command([
        "sct_apply_transfo",
        "-i", str(bold_mean_local),
        "-d", str(anat_local),
        "-w", str(reg["warp_func2anat"]),
        "-x", "spline",
        "-o", str(bold4d_in_anat),
    ])
    if not ok_bia:
        # QC view only (mean BOLD shown in anat space); surface the failure
        # rather than emit a clean status with a missing QC image.
        failure_reasons.append(f"mean-bold->anat QC view failed: {err_bia[:120]}")

    # tSNR funcref (for S7.4 ratio comparison)
    tsnr_path = func_dir / f"{prefix}_desc-tsnr_funcref.nii.gz"
    if bdata.ndim == 4 and bdata.shape[3] >= 5:
        std = bdata.std(axis=3)
        tsnr = np.where(std > 0, bmean / std, 0).astype(np.float32)
        nib.save(nib.Nifti1Image(tsnr, bimg.affine, bimg.header), tsnr_path)

    # 7. Reportlets
    from .reportlets import render_s6_composite, render_s6_dice_per_slice
    rep_composite = figures_dir / f"{prefix}_desc-S6_bold_on_anat.png"
    rep_dice = figures_dir / f"{prefix}_desc-S6_cord_dice_per_slice.png"
    # Audit Finding 8: pass the warped anat cord SEGMENTATION (not the
    # warped anat intensity image) so the reportlet contour traces the
    # cord boundary instead of an arbitrary intensity percentile.
    dice_val = metrics.get("cord_dice")
    hd95_val = metrics.get("cord_hd95_mm")
    if anat_dseg_in_bold.exists():
        # Pass anat_in_bold (warped anat INTENSITY) too so the reportlet
        # can show BOLD vs Anat in dual-modality side-by-side. The cord
        # is unambiguous on the anat T1w/T2w panel — without it, the
        # eye reads the bright CSF in T2*-EPI as the cord.
        anat_intensity_arg = anat_in_bold if anat_in_bold.exists() else None
        try:
            render_s6_composite(
                bold_mean_path=bold_mean_local,
                anat_dseg_in_bold_path=anat_dseg_in_bold,
                cord_mask_path=funccrop_local,
                output_path=rep_composite,
                anat_in_bold_path=anat_intensity_arg,
                funcref_path=funcref_local,
                dice=dice_val, hd95=hd95_val,
                status=status,
            )
        except Exception as e:
            failure_reasons.append(f"composite reportlet failed: {e}")
    else:
        from spineprep.reportlets_common import stub_figure
        try:
            stub_figure(rep_composite, "anat cord seg not resampled into BOLD geometry")
        except Exception as e:
            failure_reasons.append(f"reportlet stub failed: {e}")
    try:
        render_s6_dice_per_slice(
            funccrop_local, anat_dseg_in_bold if anat_dseg_in_bold.exists() else None,
            rep_dice, policy.get("qc_thresholds", {}),
        )
    except Exception as e:
        failure_reasons.append(f"dice-per-slice reportlet failed: {e}")

    # 8. Save qc_metrics.json with provenance
    provenance = {
        "policy_sha256": policy_sha,
        "ants_random_seed": 1 if repro_strict else None,
        "itk_threads": 1 if repro_strict else None,
    }
    qc_metrics_path = s6_work_dir / "qc_metrics.json"
    qc_metrics_path.write_text(json.dumps({
        "metrics": metrics,
        "failure_reasons": failure_reasons,
        "provenance": provenance,
        "param_string": reg.get("param_string"),
        "anat_modality": anat_modality,
        "syn_fallback_inherited": syn_fallback,
    }, indent=2, default=str))

    return {
        "status": status,
        "step_code": step_code,
        "dataset_key": dataset_key,
        "subject": subject,
        "session": session,
        "run_id": run_id,
        "anat_modality": anat_modality,
        "distortion_correction_mode_inherited": s5_mode,
        "metrics": metrics,
        "failure_reasons": failure_reasons,
        "failure_message": "; ".join(failure_reasons) if failure_reasons else None,
        "reportlets": {
            "bold_on_anat": str(rep_composite.relative_to(out_dir)),
            "cord_dice_per_slice": str(rep_dice.relative_to(out_dir)),
        },
        "xfm_paths": {
            "from_bold_to_anat": str(xfm_fwd.relative_to(out_dir)),
            "from_anat_to_bold": str(xfm_inv.relative_to(out_dir)),
            "sidecar": str(sidecar.relative_to(out_dir)),
        },
    }
