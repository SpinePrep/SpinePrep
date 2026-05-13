"""S6: per-run func->anat registration.

Spec: private/SPEC/S6_func_to_anat_registration.md

Algorithm (Kaptan 2023 verbatim, intensity-agnostic):
  step1: type=seg,algo=centermass
  step2: type=seg,algo=bsplinesyn,metric=MeanSquares,smooth=1,slicewise=1,iter=3

Direction: register anat (moving) -> funcref (destination); invert for
BIDS `from-bold_to-anat` output. fMRI as destination = fewer slices,
faster, no anat-grid resampling of BOLD.

Output xfm is saved as SCT-native .nii.gz displacement field (consistent
with S2's `_warp.nii.gz`). v1.x can convert to .h5 composite for
fMRIPrep compat.
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
# Pre-flight + mask
# ---------------------------------------------------------------------------


def _sync_sform_qform(path: Path) -> None:
    """Set sform = qform on a NIfTI in place. The #1 silent failure mode in
    SCT registration. Cheap and idempotent."""
    img = nib.load(path)
    aff = img.get_qform()
    img.set_sform(aff, code=int(img.header["sform_code"]) or 1)
    nib.save(img, path)


def _world_align_anat_z(
    anat: Path, anat_dseg: Path,
    funcref: Path, funccrop_mask: Path,
    work_dir: Path,
) -> tuple[Path, Path, list[str]]:
    """Header-only Z translation so anat cord COM aligns with BOLD cord
    COM in world coordinates. SCT's centermass step operates slicewise
    (by index), and `step=0,type=im,algo=rigid,metric=MI` can fail to
    converge in Z on T2*-EPI vs T1w due to inverted contrast and the
    cord's near-cylindric symmetry. A pre-flight header shift guarantees
    a Z-aligned starting state. Image data is unchanged.
    """
    flags: list[str] = []
    fimg = nib.load(funcref)
    fmask = nib.load(funccrop_mask).get_fdata() > 0.5
    if not fmask.any():
        return anat, anat_dseg, flags
    bold_com_vox = np.array(np.where(fmask)).mean(axis=1)
    bold_com_world_z = float(nib.affines.apply_affine(fimg.affine, bold_com_vox)[2])

    aimg = nib.load(anat_dseg)
    amask = aimg.get_fdata() > 0.5
    if not amask.any():
        return anat, anat_dseg, flags
    anat_com_vox = np.array(np.where(amask)).mean(axis=1)
    anat_com_world_z = float(nib.affines.apply_affine(aimg.affine, anat_com_vox)[2])

    z_shift = bold_com_world_z - anat_com_world_z
    if abs(z_shift) < 1.0:
        return anat, anat_dseg, flags

    flags.append(f"anat_world_z_prealign ({z_shift:+.1f}mm)")
    out_anat = work_dir / "anat_zshift.nii.gz"
    out_dseg = work_dir / "anat_dseg_zshift.nii.gz"
    for src, dst in [(anat, out_anat), (anat_dseg, out_dseg)]:
        img = nib.load(src)
        aff = img.affine.copy()
        aff[2, 3] += z_shift
        new = nib.Nifti1Image(img.get_fdata(), aff, img.header)
        try:
            qcode = int(img.header.get("qform_code", 1)) or 1
            scode = int(img.header.get("sform_code", 1)) or 1
        except Exception:
            qcode = scode = 1
        new.set_qform(aff, code=qcode)
        new.set_sform(aff, code=scode)
        nib.save(new, dst)
    return out_anat, out_dseg, flags


def _maybe_z_crop_anat(
    anat: Path, anat_dseg: Path,
    funcref: Path, funccrop_mask: Path,
    work_dir: Path,
    margin_mm: float = 10.0,
    min_ratio: float = 0.6,
) -> tuple[Path, Path, list[str]]:
    """Crop anat (cordref + dseg) along Z to roughly the BOLD's cord
    physical extent + margin, centered on the anat cord COM.

    Only kicks in when BOLD_extent / anat_extent < min_ratio (~ partial-
    coverage acquisitions: BOLD covers only a fraction of the anat cord).
    Without this, centermass aligns whole-cord COM with partial-cord COM
    and the registration collapses.

    Assumption: the BOLD targets the middle of the anat cord coverage —
    true for typical cervical motor/sensory protocols.
    """
    flags: list[str] = []
    mask = nib.load(funccrop_mask).get_fdata() > 0.5
    anat_d = nib.load(anat_dseg).get_fdata() > 0.5
    if not mask.any() or not anat_d.any():
        return anat, anat_dseg, flags

    bold_zoom_z = float(nib.load(funcref).header.get_zooms()[2])
    z_idx = np.where(mask.any(axis=(0, 1)))[0]
    bold_z_extent_mm = (int(z_idx.max()) - int(z_idx.min())) * bold_zoom_z

    anat_img = nib.load(anat_dseg)
    anat_zoom_z = float(anat_img.header.get_zooms()[2])
    anat_cord_z = np.where(anat_d.any(axis=(0, 1)))[0]
    anat_z_extent_mm = (int(anat_cord_z.max()) - int(anat_cord_z.min())) * anat_zoom_z

    if anat_z_extent_mm <= 0:
        return anat, anat_dseg, flags
    ratio = bold_z_extent_mm / anat_z_extent_mm
    if ratio >= min_ratio:
        return anat, anat_dseg, flags

    flags.append(f"anat_z_cropped (ratio={ratio:.2f})")
    anat_cord_com_z = int(round(anat_cord_z.mean()))
    half_width_vox = int((bold_z_extent_mm + 2 * margin_mm) / 2 / anat_zoom_z)
    z_min = max(int(anat_cord_z.min()), anat_cord_com_z - half_width_vox)
    z_max = min(int(anat_cord_z.max()), anat_cord_com_z + half_width_vox)
    if z_max - z_min < 5:
        flags.append("anat_z_crop_too_narrow; aborted")
        return anat, anat_dseg, flags

    cropped_anat = work_dir / "anat_zcrop.nii.gz"
    cropped_dseg = work_dir / "anat_dseg_zcrop.nii.gz"
    for src, dst in [(anat, cropped_anat), (anat_dseg, cropped_dseg)]:
        ok, _ = _run_command([
            "sct_crop_image", "-i", str(src),
            "-zmin", str(z_min), "-zmax", str(z_max),
            "-o", str(dst),
        ])
        if not ok or not dst.exists():
            flags.append("anat_z_crop_failed; using originals")
            return anat, anat_dseg, flags
    return cropped_anat, cropped_dseg, flags


def _make_cylindric_mask(
    funcref: Path,
    funccrop_mask: Path,
    work_dir: Path,
    radius_mm: float = 30.0,
) -> tuple[Optional[Path], list[str]]:
    """Build a cylindric cord mask around the funcref centerline.

    Cascade: optic centerline -> fitseg from funccrop_mask -> dilate-2vox
    fitseg. Returns (mask_path or None, failure_flags_added).
    """
    flags: list[str] = []
    centerline = work_dir / "centerline.nii.gz"

    # Try optic
    ok, _ = _run_command([
        "sct_get_centerline", "-i", str(funcref),
        "-method", "optic", "-c", "t2s",
        "-o", str(centerline),
    ])
    if not ok or not centerline.exists():
        # Fallback 1: fitseg from S3.1 funccrop_mask
        ok, _ = _run_command([
            "sct_get_centerline", "-i", str(funcref),
            "-s", str(funccrop_mask),
            "-method", "fitseg",
            "-o", str(centerline),
        ])
    if not ok or not centerline.exists():
        # Fallback 2: dilate funccrop_mask by 2 vox, retry fitseg
        flags.append("centerline_fallback_dilate")
        dilated = work_dir / "funccrop_mask_dil2.nii.gz"
        ok, _ = _run_command([
            "sct_maths", "-i", str(funccrop_mask),
            "-dilate", "2", "-o", str(dilated),
        ])
        if ok:
            ok, _ = _run_command([
                "sct_get_centerline", "-i", str(funcref),
                "-s", str(dilated),
                "-method", "fitseg",
                "-o", str(centerline),
            ])
    if not ok or not centerline.exists():
        flags.append("centerline_failed")
        return None, flags

    mask_func = work_dir / "mask_func.nii.gz"
    ok, _ = _run_command([
        "sct_create_mask", "-i", str(funcref),
        "-p", f"centerline,{centerline}",
        "-size", f"{int(radius_mm)}mm",
        "-f", "cylinder",
        "-o", str(mask_func),
    ])
    if not ok or not mask_func.exists():
        flags.append("cylindric_mask_failed")
        return None, flags
    return mask_func, flags


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def _build_param_string(reg_cfg: dict) -> str:
    parts: list[str] = []
    step0 = reg_cfg.get("step0")
    if step0:
        parts.append(
            f"step=0,type={step0.get('type', 'im')},algo={step0.get('algo', 'rigid')}"
            f",metric={step0.get('metric', 'MI')},iter={step0.get('iter', 10)}"
        )
    step1 = reg_cfg.get("step1", {})
    parts.append(
        f"step=1,type={step1.get('type', 'seg')},algo={step1.get('algo', 'centermass')}"
    )
    step2 = reg_cfg.get("step2", {})
    parts.append(
        f"step=2,type={step2.get('type', 'seg')},algo={step2.get('algo', 'bsplinesyn')}"
        f",metric={step2.get('metric', 'MeanSquares')}"
        f",smooth={step2.get('smooth', 1)}"
        f",slicewise={step2.get('slicewise', 1)}"
        f",iter={step2.get('iter', 3)}"
    )
    return ":".join(parts)


def _run_registration(
    funcref: Path,
    funccrop_mask: Path,
    anat: Path,
    anat_dseg: Path,
    mask_func: Optional[Path],
    work_dir: Path,
    policy: dict,
    reproducibility_strict: bool,
) -> dict[str, Any]:
    """Register anat (moving) -> funcref (destination); produce forward
    warp (funcref->anat space) and inverse warp (anat->funcref space)."""
    reg_cfg = policy.get("registration", {})
    param = _build_param_string(reg_cfg)

    warp_anat2func = work_dir / "warp_anat2func.nii.gz"
    warp_func2anat = work_dir / "warp_func2anat.nii.gz"

    cmd = [
        "sct_register_multimodal",
        "-i", str(anat),
        "-iseg", str(anat_dseg),
        "-d", str(funcref),
        "-dseg", str(funccrop_mask),
        "-param", param,
        "-x", reg_cfg.get("interpolation", "spline"),
        "-ofolder", str(work_dir),
    ]
    if mask_func is not None:
        cmd.extend(["-m", str(mask_func)])

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

    # SCT writes warps as warp_<i>2<d>.nii.gz / warp_<d>2<i>.nii.gz. Locate them.
    anat_stem = anat.name.replace(".nii.gz", "").replace(".nii", "")
    func_stem = funcref.name.replace(".nii.gz", "").replace(".nii", "")
    src_forward = work_dir / f"warp_{anat_stem}2{func_stem}.nii.gz"
    src_inverse = work_dir / f"warp_{func_stem}2{anat_stem}.nii.gz"
    if not src_forward.exists() or not src_inverse.exists():
        # SCT >=7 sometimes drops shorter names; pick anything matching warp_*
        warps = sorted(work_dir.glob("warp_*.nii.gz"))
        if len(warps) >= 2:
            src_forward = next((w for w in warps if "2" + func_stem in w.name), warps[0])
            src_inverse = next((w for w in warps if "2" + anat_stem in w.name), warps[1])

    shutil.copy(src_forward, warp_anat2func)
    shutil.copy(src_inverse, warp_func2anat)
    return {
        "status": "OK",
        "warp_anat2func": warp_anat2func,
        "warp_func2anat": warp_func2anat,
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
    """Push a seg through forward then inverse warp; report drift in voxels."""
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
    # Per-axis center-of-mass drift in voxels
    com_a = np.array(np.where(a)).mean(axis=1)
    com_b = np.array(np.where(b)).mean(axis=1)
    drift = np.linalg.norm(com_a - com_b)
    return float(drift), float(drift)  # med/max are identical for COM-only v1


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
              lower_is_better: bool = True) -> str:
        if value is None:
            return "WARN"
        ok = value <= pass_max if lower_is_better else value >= pass_max
        warn = value <= warn_max if lower_is_better else value >= warn_max
        if ok:
            return "PASS"
        if warn:
            reasons.append(f"{label} WARN: {value:.3f}")
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

    hd95 = metrics.get("cord_hd95_mm")
    t = _tier(hd95, thresholds.get("pass_hd95_mm_max", 2.0),
              thresholds.get("warn_hd95_mm_max", 4.0), "cord_hd95_mm")
    if t == "FAIL": worst = "FAIL"
    elif t == "WARN" and worst == "PASS": worst = "WARN"

    rt_med = metrics.get("centerline_round_trip_med_vox")
    t = _tier(rt_med, thresholds.get("pass_centerline_med_vox_max", 0.5),
              thresholds.get("warn_centerline_med_vox_max", 1.0),
              "centerline_round_trip_med_vox")
    if t == "FAIL": worst = "FAIL"
    elif t == "WARN" and worst == "PASS": worst = "WARN"

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
    subject = bold_run.get("subject")
    session = bold_run.get("session")
    run_id = bold_run.get("run_id") or Path(bold_run.get("path", "")).name.replace(
        "_bold.nii.gz", "").replace("_bold.nii", "")

    # Output dirs
    if session:
        func_dir = (out_dir / "derivatives" / "spinalfmriprep" / f"sub-{subject}"
                    / f"ses-{session}" / "func")
    else:
        func_dir = (out_dir / "derivatives" / "spinalfmriprep" / f"sub-{subject}"
                    / "func")
    func_dir.mkdir(parents=True, exist_ok=True)
    figures_dir = func_dir.parent / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    s6_work_dir = work_dir / step_code / run_id
    s6_work_dir.mkdir(parents=True, exist_ok=True)

    # Anat modality from filename
    anat_modality = "T1w" if "_T1w" in anat_path.name else "T2w" if "_T2w" in anat_path.name else None

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

    # 1a. World-Z header pre-align (centermass operates slicewise-by-index
    # and rigid step=0 MI can fail to find the Z-shift on T1w-anat vs
    # T2*-EPI; this guarantees Z-aligned input).
    anat_pre, anat_dseg_pre, prealign_flags = _world_align_anat_z(
        anat_local, anat_dseg_local, funcref_local, funccrop_local, s6_work_dir,
    )
    failure_reasons.extend(prealign_flags)

    # 1b. Optional anat Z-crop for partial-coverage acquisitions
    anat_for_reg, anat_dseg_for_reg, zcrop_flags = _maybe_z_crop_anat(
        anat_pre, anat_dseg_pre, funcref_local, funccrop_local, s6_work_dir,
    )
    failure_reasons.extend(zcrop_flags)

    # 2. Cylindric cord mask
    mask_radius = policy.get("registration", {}).get(
        "cylindric_mask", {}).get("radius_mm", 30)
    mask_func, mask_flags = _make_cylindric_mask(
        funcref_local, funccrop_local, s6_work_dir, radius_mm=mask_radius,
    )
    failure_reasons.extend(mask_flags)

    # 3. Registration (anat may be Z-cropped)
    repro_strict = bool(policy.get("reproducibility", {}).get("strict", False))
    reg = _run_registration(
        funcref=funcref_local,
        funccrop_mask=funccrop_local,
        anat=anat_for_reg,
        anat_dseg=anat_dseg_for_reg,
        mask_func=mask_func,
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
    _run_command([
        "sct_apply_transfo",
        "-i", str(anat_local),
        "-d", str(funcref_local),
        "-w", str(reg["warp_anat2func"]),
        "-x", "linear",
        "-o", str(anat_in_bold),
    ])
    if anat_in_bold.exists():
        try:
            f = nib.load(funcref_local).get_fdata()
            a = nib.load(anat_in_bold).get_fdata()
            if f.shape == a.shape:
                metrics["mi_after"] = _mutual_information(f, a)
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
    _run_command([
        "sct_apply_transfo",
        "-i", str(bold_mean_local),
        "-d", str(anat_local),
        "-w", str(reg["warp_func2anat"]),
        "-x", "spline",
        "-o", str(bold4d_in_anat),
    ])

    # tSNR funcref (for S7.4 ratio comparison)
    tsnr_path = func_dir / f"{prefix}_desc-tsnr_funcref.nii.gz"
    if bdata.ndim == 4 and bdata.shape[3] >= 5:
        std = bdata.std(axis=3)
        tsnr = np.where(std > 0, bmean / std, 0).astype(np.float32)
        nib.save(nib.Nifti1Image(tsnr, bimg.affine, bimg.header), tsnr_path)

    # 7. Reportlets
    from .reportlets import (
        render_s6_axial, render_s6_sagittal, render_s6_dice_per_slice,
    )
    rep_axial = figures_dir / f"{prefix}_desc-S6_bold_on_anat_axial.png"
    rep_sag   = figures_dir / f"{prefix}_desc-S6_bold_on_anat_sagittal.png"
    rep_dice  = figures_dir / f"{prefix}_desc-S6_cord_dice_per_slice.png"
    try:
        render_s6_axial(bold_mean_local, anat_in_bold if anat_in_bold.exists() else anat_local,
                        funccrop_local, rep_axial)
    except Exception as e:
        failure_reasons.append(f"axial reportlet failed: {e}")
    try:
        render_s6_sagittal(bold_mean_local, anat_in_bold if anat_in_bold.exists() else anat_local,
                           funccrop_local, rep_sag)
    except Exception as e:
        failure_reasons.append(f"sagittal reportlet failed: {e}")
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
            "bold_on_anat_axial": str(rep_axial.relative_to(out_dir)),
            "bold_on_anat_sagittal": str(rep_sag.relative_to(out_dir)),
            "cord_dice_per_slice": str(rep_dice.relative_to(out_dir)),
        },
        "xfm_paths": {
            "from_bold_to_anat": str(xfm_fwd.relative_to(out_dir)),
            "from_anat_to_bold": str(xfm_inv.relative_to(out_dir)),
            "sidecar": str(sidecar.relative_to(out_dir)),
        },
    }
