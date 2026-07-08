"""S9: per-run primary functional derivatives.

Spec: .claude/specs/s9-primary-functional-derivatives.md

Pipeline:
  1. Native smoothing via sct_smooth_spinalcord per-volume (CoSpi
     spi14_2 lineage). σ = 1,1,5 mm (R-L, A-P, S-I) default.
  2. Warp the smoothed native 4D into PAM50 via S7's composite
     from-bold_to-PAM50 xfm. Also produce the un-smoothed PAM50 4D
     for analysts who want unsmoothed PAM50.
  3. tSNR maps: native (smoothed), PAM50 (smoothed).
  4. Per-vertebral-level tSNR TSV using S7's PAM50spinallevels in
     native func.
  5. Residual FWHM verification via voxelwise autocorrelation in
     cord mask.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

import nibabel as nib
import numpy as np
import pandas as pd

from spineprep.lib.run import run_command as _run_command


# ---------------------------------------------------------------------------
# Smoothing — per-volume sct_smooth_spinalcord (CoSpi pattern)
# ---------------------------------------------------------------------------


def _split_4d(bold_path: Path, out_dir: Path) -> list[Path]:
    """Split 4D BOLD into per-volume 3D NIfTI files."""
    img = nib.load(bold_path)
    data = img.get_fdata()
    if data.ndim != 4:
        raise ValueError(f"BOLD not 4D: shape={data.shape}")
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    n = data.shape[3]
    for i in range(n):
        p = out_dir / f"vol_{i:04d}.nii.gz"
        vol = nib.Nifti1Image(data[..., i].astype(np.float32),
                              img.affine, img.header)
        nib.save(vol, p)
        paths.append(p)
    return paths


def _merge_4d(vol_paths: list[Path], ref_4d: Path, out_path: Path) -> bool:
    """Concatenate per-volume 3D NIfTIs back to 4D using the reference 4D's
    affine + header. Returns True on success.
    """
    ref = nib.load(ref_4d)
    stack = []
    for p in vol_paths:
        stack.append(nib.load(p).get_fdata().astype(np.float32))
    arr = np.stack(stack, axis=3)
    out = nib.Nifti1Image(arr, ref.affine, ref.header)
    nib.save(out, out_path)
    return out_path.exists()


def _run_sct_smooth_per_volume(
    bold_path: Path, cord_seg_path: Path,
    sigma_xyz_mm: list[float], work_dir: Path,
    out_path: Path,
) -> tuple[bool, Optional[str], float]:
    """sct_smooth_spinalcord per-volume loop (CoSpi spi14_2 pattern).

    sigma_xyz_mm: [σ_RL, σ_AP, σ_SI] in mm.
    Returns (ok, error_msg, runtime_s).
    """
    t0 = time.time()
    work_dir = work_dir / "smooth_per_volume"
    work_dir.mkdir(parents=True, exist_ok=True)
    try:
        in_vols = _split_4d(bold_path, work_dir / "in")
    except Exception as e:
        return False, f"4D split failed: {e}", time.time() - t0
    sigma_str = ",".join(f"{s}" for s in sigma_xyz_mm)
    out_vols: list[Path] = []
    for i, v in enumerate(in_vols):
        ov = work_dir / "out" / f"vol_{i:04d}_sm.nii.gz"
        ov.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            "sct_smooth_spinalcord",
            "-i", str(v), "-s", str(cord_seg_path),
            "-smooth", sigma_str,
            "-r", "1", "-v", "0",
            "-o", str(ov),
        ]
        ok, stderr = _run_command(cmd)
        if not ok or not ov.exists():
            return (False,
                    f"sct_smooth_spinalcord failed at vol {i}: {stderr or 'no stderr'}",
                    time.time() - t0)
        out_vols.append(ov)
    # Merge 4D
    if not _merge_4d(out_vols, bold_path, out_path):
        return False, "4D merge failed", time.time() - t0
    return True, None, time.time() - t0


def _run_sct_smooth_batched(
    bold_path: Path, cord_seg_path: Path,
    sigma_xyz_mm: list[float], work_dir: Path,
    out_path: Path,
) -> tuple[bool, Optional[str], float]:
    """Cord-aware smoothing, batched over the time axis.

    sct_smooth_spinalcord straightens the cord (the expensive step) then
    smooths in straight space. The straightening depends only on the cord
    centerline -- identical for every volume of a run -- so the per-volume
    loop recomputes/cache-reuses the same warp ~T times, and (because SCT
    drops warp_curve2straight.nii.gz + straightening.cache into the *cwd*)
    concurrent workers race on those shared files.

    Here we straighten ONCE in a private cwd, apply the warp to the whole 4D
    in one sct_apply_transfo, smooth each volume in straight space (sigma 0
    along time = no temporal blur), de-straighten the whole 4D, and restore
    zeroed voxels. Numerically identical to the per-volume loop (same single
    centerline -> same warp -> same per-volume gaussian), with ~T fewer SCT
    spawns and no cache race.

    Faithful to spinalcordtoolbox/scripts/sct_smooth_spinalcord.py: RPI
    orientation, bspline straightening with spline resampling, sigma_mm/pixdim
    voxel conversion, scipy gaussian_filter(order=0, truncate=4.0), and the
    issue-#937 zero-voxel restore.
    """
    t0 = time.time()
    wd = work_dir / "smooth_batched"
    wd.mkdir(parents=True, exist_ok=True)
    # SCT calls run with cwd=wd (to isolate the straightening cache), so all
    # input paths handed to them must be absolute.
    bold_path = Path(bold_path).resolve()
    cord_seg_path = Path(cord_seg_path).resolve()
    orig = nib.load(bold_path)

    def _sct(cmd: list[str]) -> tuple[bool, Optional[str]]:
        ok, err = _run_command(cmd, cwd=str(wd))
        return ok, (None if ok else err)

    try:
        # 1. RPI orientation (SCT's smoothing axes are R-L, A-P, S-I).
        bold_rpi = wd / "bold_rpi.nii.gz"
        seg_rpi = wd / "seg_rpi.nii.gz"
        ok, err = _sct(["sct_image", "-i", str(bold_path),
                        "-setorient", "RPI", "-o", str(bold_rpi)])
        if not ok:
            return False, f"setorient bold failed: {err}", time.time() - t0
        ok, err = _sct(["sct_image", "-i", str(cord_seg_path),
                        "-setorient", "RPI", "-o", str(seg_rpi)])
        if not ok:
            return False, f"setorient seg failed: {err}", time.time() - t0

        # 2. 3D reference (temporal mean) for the straightening pass.
        ref3d = wd / "ref3d.nii.gz"
        bimg = nib.load(bold_rpi)
        bdata = bimg.get_fdata().astype(np.float32)
        if bdata.ndim != 4:
            return False, f"BOLD not 4D: {bdata.shape}", time.time() - t0
        nib.save(nib.Nifti1Image(bdata.mean(axis=3), bimg.affine, bimg.header),
                 ref3d)

        # 3. Straighten ONCE (warps land in wd; -s drives the warp geometry).
        ok, err = _sct([
            "sct_straighten_spinalcord", "-i", str(ref3d), "-s", str(seg_rpi),
            "-o", "ref3d_straight.nii.gz", "-x", "spline",
            "-param", "algo_fitting=bspline", "-v", "0",
        ])
        w_c2s = wd / "warp_curve2straight.nii.gz"
        w_s2c = wd / "warp_straight2curve.nii.gz"
        straight_ref = wd / "straight_ref.nii.gz"
        if not ok or not w_c2s.exists() or not w_s2c.exists():
            return False, f"straighten failed: {err or 'no warp produced'}", time.time() - t0

        # 4. Apply curve->straight to the whole 4D.
        straightened = wd / "bold_straight.nii.gz"
        ok, err = _sct(["sct_apply_transfo", "-i", str(bold_rpi),
                        "-w", str(w_c2s), "-d", str(straight_ref),
                        "-x", "spline", "-o", str(straightened), "-v", "0"])
        if not ok or not straightened.exists():
            return False, f"curve2straight apply failed: {err}", time.time() - t0

        # 5. Smooth in straight space: sigma_mm/pixdim per axis, 0 along time.
        simg = nib.load(straightened)
        sdata = simg.get_fdata().astype(np.float32)
        px = simg.header.get_zooms()[:3]
        sigma_vox = [sigma_xyz_mm[i] / max(float(px[i]), 1e-6) for i in range(3)]
        sigma_vox4 = sigma_vox + [0.0]
        from scipy.ndimage import gaussian_filter
        sdata_sm = gaussian_filter(sdata, sigma_vox4, order=0, truncate=4.0
                                   ).astype(np.float32)
        straight_sm = wd / "bold_straight_smooth.nii.gz"
        nib.save(nib.Nifti1Image(sdata_sm, simg.affine, simg.header), straight_sm)

        # 6. De-straighten the whole 4D back to the native grid. The
        #    destination MUST be 3D (sct_apply_transfo mis-resamples against a
        #    4D -d -> round-trip corr NaN) and in the ORIGINAL orientation:
        #    warps act in physical space, so a native-orientation 3D dest yields
        #    output already in the original grid -- no reorientation needed.
        ref3d_orig = wd / "ref3d_orig.nii.gz"
        odata = orig.get_fdata().astype(np.float32)
        nib.save(nib.Nifti1Image(odata.mean(axis=3), orig.affine, orig.header),
                 ref3d_orig)
        destraight = wd / "bold_destraight.nii.gz"
        ok, err = _sct(["sct_apply_transfo", "-i", str(straight_sm),
                        "-w", str(w_s2c), "-d", str(ref3d_orig),
                        "-x", "spline", "-o", str(destraight), "-v", "0"])
        if not ok or not destraight.exists():
            return False, f"straight2curve apply failed: {err}", time.time() - t0

        # 7. Restore zeroed voxels from the original (SCT issue #937) and write
        #    with the input's exact affine+header so downstream geometry matches
        #    the per-volume path.
        ddata = nib.load(destraight).get_fdata().astype(np.float32)
        if ddata.shape != odata.shape:
            return (False, f"shape mismatch: {ddata.shape} vs {odata.shape}",
                    time.time() - t0)
        zero = ddata == 0
        ddata[zero] = odata[zero]
        nib.save(nib.Nifti1Image(ddata, orig.affine, orig.header), out_path)
        return out_path.exists(), None, time.time() - t0
    except Exception as e:
        return False, f"batched smoothing failed: {e}", time.time() - t0


# ---------------------------------------------------------------------------
# In-plane Gaussian alternative (no Z blur)
# ---------------------------------------------------------------------------


def _gaussian_inplane(
    bold_path: Path, sigma_xy_mm: list[float], out_path: Path,
) -> tuple[bool, Optional[str], float]:
    """scipy.ndimage.gaussian_filter on 4D BOLD with σ=(σ_x, σ_y, 0, 0)
    in voxel units derived from the BOLD's affine zooms.
    """
    t0 = time.time()
    try:
        from scipy.ndimage import gaussian_filter
        img = nib.load(bold_path)
        zooms = img.header.get_zooms()[:3]
        sigma_vox = (
            sigma_xy_mm[0] / max(zooms[0], 1e-6),
            sigma_xy_mm[1] / max(zooms[1], 1e-6),
            0.0, 0.0,
        )
        data = img.get_fdata().astype(np.float32)
        smoothed = gaussian_filter(data, sigma=sigma_vox)
        nib.save(nib.Nifti1Image(smoothed, img.affine, img.header), out_path)
        return out_path.exists(), None, time.time() - t0
    except Exception as e:
        return False, str(e), time.time() - t0


# ---------------------------------------------------------------------------
# Warp 4D BOLD to PAM50 via S7 composite
# ---------------------------------------------------------------------------


def _warp_4d_to_pam50(
    bold_path: Path, warp_bold_to_pam50: Path, pam50_ref: Path,
    out_path: Path, interp: str = "spline",
) -> tuple[bool, Optional[str]]:
    cmd = [
        "sct_apply_transfo",
        "-i", str(bold_path), "-d", str(pam50_ref),
        "-w", str(warp_bold_to_pam50),
        "-x", interp,
        "-o", str(out_path),
    ]
    ok, stderr = _run_command(cmd)
    if not ok or not out_path.exists():
        return False, stderr or "sct_apply_transfo produced no output"
    return True, None


# ---------------------------------------------------------------------------
# PAM50 cord-FOV cropping (keeps the 4D template-space BOLD ~1-2 GB instead of
# ~17 GB: we crop the 0.5 mm PAM50 reference to the run's cord coverage and warp
# DIRECTLY into that cropped grid, so no full-grid intermediate is ever written)
# ---------------------------------------------------------------------------


def _pam50_cord_template(pam50_ref: Path) -> Optional[Path]:
    """PAM50_cord.nii.gz lives next to PAM50_t2s.nii.gz in $SCT_DIR template."""
    cand = pam50_ref.parent / "PAM50_cord.nii.gz"
    return cand if cand.exists() else None


def _cord_fov_bbox(
    funcref_path: Path, cord_path: Path,
    xy_margin: int = 8, z_pad: int = 4,
) -> Optional[tuple[slice, slice, slice]]:
    """Bounding box for the PAM50 4D crop: cord cross-section (x,y from the
    PAM50 cord mask + margin) by functional coverage (z from the warped
    funcref's nonzero extent + pad, clamped to the cord's z-range).

    Cropping to the cord ROI rather than the whole warped imaging slab keeps
    the 4D small and CONSISTENT across acquisitions: a wide-FOV run (e.g. rest)
    warps to a large PAM50 region, but only the ~24x18-voxel cord cross-section
    is relevant to cord analysis. (The earlier funcref-nonzero bbox left x,y
    unbounded -> 3 GB/run on wide-FOV data, which filled the disk.)
    """
    cord = nib.load(cord_path).get_fdata()
    cnz = np.argwhere(cord > 0)
    fimg = nib.load(funcref_path)
    fdata = fimg.get_fdata()
    if fdata.ndim == 4:
        fdata = fdata.mean(axis=3)
    fnz = np.argwhere(np.abs(fdata) > 1e-6)
    if cnz.size == 0 or fnz.size == 0:
        return None
    shape = np.array(cord.shape[:3])
    lo = np.empty(3, int); hi = np.empty(3, int)
    # x, y: cord cross-section + margin (peri-cord tissue for CSF/aCompCor view)
    for i in (0, 1):
        lo[i] = max(int(cnz[:, i].min()) - xy_margin, 0)
        hi[i] = min(int(cnz[:, i].max()) + 1 + xy_margin, int(shape[i]))
    # z: functional coverage, clamped to where the cord exists
    lo[2] = max(int(fnz[:, 2].min()) - z_pad, int(cnz[:, 2].min()), 0)
    hi[2] = min(int(fnz[:, 2].max()) + 1 + z_pad, int(cnz[:, 2].max()) + 1, int(shape[2]))
    if hi[2] <= lo[2]:
        return None
    return tuple(slice(int(lo[i]), int(hi[i])) for i in range(3))


def _crop_to_bbox(in_path: Path, bbox: tuple, out_path: Path) -> None:
    """Crop a NIfTI to bbox using nibabel's slicer (affine-correct, memory-light:
    the array proxy reads only the cropped region)."""
    img = nib.load(in_path)
    sx, sy, sz = bbox
    cropped = (img.slicer[sx, sy, sz, :] if img.ndim == 4
               else img.slicer[sx, sy, sz])
    nib.save(cropped, out_path)


# ---------------------------------------------------------------------------
# BIDS sidecars (a GLM needs RepetitionTime; BIDS-Derivatives needs the sidecar)
# ---------------------------------------------------------------------------


def _bold_tr(bold_path: Path) -> Optional[float]:
    """RepetitionTime (s) from the BOLD header pixdim[4]. SCT preserves it."""
    z = nib.load(bold_path).header.get_zooms()
    return float(z[3]) if len(z) > 3 and z[3] and z[3] > 0 else None


def _task_from_run_id(run_id: str) -> Optional[str]:
    import re
    m = re.search(r"task-([A-Za-z0-9]+)", run_id)
    return m.group(1) if m else None


def _write_bold_sidecar(
    bold_path: Path, tr: Optional[float], task: Optional[str],
    *, space: Optional[str] = None,
    smoothing_fwhm: Optional[list[float]] = None,
) -> None:
    """Emit a `*_bold.json` next to the BOLD with the minimum a GLM needs."""
    meta: dict[str, Any] = {"SkullStripped": False}
    if tr is not None:
        meta["RepetitionTime"] = tr
    if task:
        meta["TaskName"] = task
    if space:
        meta["SpatialReference"] = space
    if smoothing_fwhm is not None:
        meta["SmoothingFWHM"] = [round(float(s), 4) for s in smoothing_fwhm]
    meta["GeneratedBy"] = [{
        "Name": "SpinePrep",
        "Step": "S9_primary_functional_derivatives",
    }]
    out = bold_path.with_name(
        bold_path.name.replace(".nii.gz", ".json").replace(".nii", ".json"))
    out.write_text(json.dumps(meta, indent=2))


def _ensure_dataset_description(deriv_spinalprep_root: Path) -> None:
    """Minimal BIDS-Derivatives manifest so S9 outputs are self-contained.
    Idempotent: S10 later overwrites with the richer (CITATION-linked) version."""
    dd = deriv_spinalprep_root / "dataset_description.json"
    if dd.exists():
        return
    deriv_spinalprep_root.mkdir(parents=True, exist_ok=True)
    dd.write_text(json.dumps({
        "Name": "SpinePrep derivatives",
        "BIDSVersion": "1.11.0",
        "DatasetType": "derivative",
        "GeneratedBy": [{
            "Name": "SpinePrep",
            "Description": "Cervical spinal cord fMRI preprocessing pipeline",
        }],
    }, indent=2))


# ---------------------------------------------------------------------------
# tSNR + per-vertebral-level tSNR
# ---------------------------------------------------------------------------


def _tsnr_map(bold_path: Path, out_path: Path) -> Optional[float]:
    """Per-voxel tSNR = mean/std along time. Returns median in non-zero region."""
    img = nib.load(bold_path)
    data = img.get_fdata().astype(np.float32)
    if data.ndim != 4 or data.shape[3] < 2:
        return None
    m = data.mean(axis=3)
    s = data.std(axis=3)
    tsnr = np.where(s > 0, m / s, 0).astype(np.float32)
    nib.save(nib.Nifti1Image(tsnr, img.affine, img.header), out_path)
    finite = tsnr[(tsnr > 0) & np.isfinite(tsnr)]
    return float(np.median(finite)) if finite.size else None


def _median_tsnr_in_mask(
    bold_path: Path, mask_path: Path,
) -> Optional[float]:
    img = nib.load(bold_path)
    data = img.get_fdata().astype(np.float32)
    mask = nib.load(mask_path).get_fdata() > 0.5
    if data.ndim != 4 or not mask.any() or mask.shape != data.shape[:3]:
        return None
    m = data.mean(axis=3); s = data.std(axis=3)
    tsnr = np.where(s > 0, m / s, 0)
    vals = tsnr[mask]
    vals = vals[(vals > 0) & np.isfinite(vals)]
    return float(np.median(vals)) if vals.size else None


def _per_vertebral_level_tsnr(
    bold_path: Path, levels_path: Path, out_tsv: Path,
) -> int:
    """Emit per-level (level, mean, std, n_voxels) TSV using PAM50 level labels.
    Returns number of levels with non-zero voxel count.
    """
    img = nib.load(bold_path)
    data = img.get_fdata().astype(np.float32)
    levels = nib.load(levels_path).get_fdata().astype(np.int32)
    if data.ndim != 4 or levels.shape != data.shape[:3]:
        out_tsv.write_text("level\tmean_tsnr\tstd_tsnr\tn_voxels\n")
        return 0
    m = data.mean(axis=3); s = data.std(axis=3)
    tsnr = np.where(s > 0, m / s, 0)
    rows: list[tuple[int, float, float, int]] = []
    for lvl in sorted(int(v) for v in np.unique(levels) if v > 0):
        mask = (levels == lvl)
        vals = tsnr[mask]
        vals = vals[(vals > 0) & np.isfinite(vals)]
        if vals.size == 0:
            continue
        rows.append((lvl, float(vals.mean()), float(vals.std()), int(vals.size)))
    out_tsv.write_text(
        "level\tmean_tsnr\tstd_tsnr\tn_voxels\n"
        + "\n".join(f"{l}\t{m:.4f}\t{s:.4f}\t{n}" for l, m, s, n in rows)
        + "\n"
    )
    return len(rows)


# ---------------------------------------------------------------------------
# Residual FWHM estimate (autocorrelation in cord mask)
# ---------------------------------------------------------------------------


def _estimate_fwhm_axis(
    data: np.ndarray, mask: np.ndarray, axis: int, zoom_mm: float,
) -> Optional[float]:
    """One-sided autocorrelation FWHM along a single axis in voxel units,
    then convert to mm.

    Method: per-voxel temporal-mean of cord BOLD; compute autocorr at lag 1
    along the axis; full-width-at-half-max approximation from the lag-1
    correlation using FWHM = 2 √(−2 log(r1)) under Gaussian field theory.
    Reference: FSL `smoothest` / Forman 1995.
    """
    if data.ndim != 3 or not mask.any():
        return None
    # Restrict to mask
    arr = data * mask
    # Shift by 1 along axis
    sl_a = [slice(None)] * 3
    sl_b = [slice(None)] * 3
    sl_a[axis] = slice(None, -1)
    sl_b[axis] = slice(1, None)
    m1 = mask[tuple(sl_a)]
    m2 = mask[tuple(sl_b)]
    both = m1 & m2
    a = arr[tuple(sl_a)][both]
    b = arr[tuple(sl_b)][both]
    if a.size < 5:
        return None
    a = a - a.mean(); b = b - b.mean()
    denom = float(np.sqrt((a * a).sum() * (b * b).sum()))
    if denom < 1e-12:
        return None
    r1 = float((a * b).sum() / denom)
    if r1 <= 0 or r1 >= 1.0:
        return None
    fwhm_vox = 2.0 * np.sqrt(-2.0 * np.log(r1))
    return float(fwhm_vox * zoom_mm)


def _estimate_residual_fwhm(
    bold_path: Path, cord_mask_path: Path,
) -> dict[str, Optional[float]]:
    img = nib.load(bold_path)
    data = img.get_fdata().astype(np.float32)
    if data.ndim != 4:
        return {"x": None, "y": None, "z": None}
    mean = data.mean(axis=3)
    mask = nib.load(cord_mask_path).get_fdata() > 0.5
    zooms = img.header.get_zooms()[:3]
    return {
        "x": _estimate_fwhm_axis(mean, mask, axis=0, zoom_mm=zooms[0]),
        "y": _estimate_fwhm_axis(mean, mask, axis=1, zoom_mm=zooms[1]),
        "z": _estimate_fwhm_axis(mean, mask, axis=2, zoom_mm=zooms[2]),
    }


# ---------------------------------------------------------------------------
# Cord-mask preservation check (pre vs post smoothed cord seg via fast thresh)
# ---------------------------------------------------------------------------


def _cord_dice_pre_post(
    pre_bold: Path, post_bold: Path, cord_mask: Path,
) -> Optional[float]:
    """Approximate cord boundary preservation: temporal-mean threshold within
    cord region, Dice between pre/post binary maps.
    """
    try:
        pre = nib.load(pre_bold).get_fdata().mean(axis=3)
        post = nib.load(post_bold).get_fdata().mean(axis=3)
        cord = nib.load(cord_mask).get_fdata() > 0.5
        # Threshold = 50% of the in-cord median for each
        pre_thr = float(np.median(pre[cord]) * 0.5) if cord.any() else 0
        post_thr = float(np.median(post[cord]) * 0.5) if cord.any() else 0
        a = (pre > pre_thr) & cord
        b = (post > post_thr) & cord
        n = a.sum() + b.sum()
        if n == 0:
            return None
        return float(2 * (a & b).sum() / n)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Status classification
# ---------------------------------------------------------------------------


def _classify(
    metrics: dict, thresholds: dict, fwhm_cfg: dict | None = None,
) -> tuple[str, list[str]]:
    """Three gates: tSNR ratio, cord-mask preservation, and per-axis FWHM
    landing in the policy tolerance band (audit Issue 2 in
    .claude/specs/s9-reportlet-set-audit.md — the FWHM tolerance keys
    used to be declared in policy but never enforced).
    """
    reasons: list[str] = []
    worst = "PASS"

    # Gate 1: tSNR ratio (smoothing improvement).
    r = metrics.get("tsnr_ratio_median")
    pass_r = thresholds.get("pass_tsnr_ratio_min", 1.5)
    warn_r = thresholds.get("warn_tsnr_ratio_min", 1.2)
    fail_r = thresholds.get("fail_tsnr_ratio_below", 1.0)
    if r is None:
        reasons.append("tsnr_ratio_median not computed")
        worst = "WARN"
    elif r < fail_r:
        reasons.append(f"tsnr_ratio_median FAIL: {r:.2f}")
        worst = "FAIL"
    elif r < warn_r:
        reasons.append(f"tsnr_ratio_median WARN: {r:.2f}")
        if worst == "PASS":
            worst = "WARN"
    elif r < pass_r:
        reasons.append(f"tsnr_ratio_median WARN: {r:.2f}")
        if worst == "PASS":
            worst = "WARN"

    # Gate 2: cord-mask preservation across smoothing.
    cd = metrics.get("cord_dice_pre_post")
    pass_d = thresholds.get("pass_cord_dice", 0.95)
    warn_d = thresholds.get("warn_cord_dice", 0.85)
    if cd is not None:
        if cd < warn_d:
            reasons.append(f"cord_dice FAIL: {cd:.3f}")
            worst = "FAIL"
        elif cd < pass_d:
            reasons.append(f"cord_dice WARN: {cd:.3f}")
            if worst == "PASS":
                worst = "WARN"

    # Gate 3: median in-cord tSNR floor (signal-quality headline; the
    # per-level reportlet colors against the same thresholds). Cord tSNR
    # typically 8-20 (Eippert 2017); below the warn floor the cord signal
    # is questionable, below the fail floor it is unusable.
    mt = metrics.get("tsnr_post_median")
    pass_t = thresholds.get("pass_median_in_cord_tsnr", 5.0)
    warn_t = thresholds.get("warn_median_in_cord_tsnr", 3.0)
    if mt is not None:
        if mt < warn_t:
            reasons.append(f"median_in_cord_tsnr FAIL: {mt:.1f}")
            worst = "FAIL"
        elif mt < pass_t:
            reasons.append(f"median_in_cord_tsnr WARN: {mt:.1f}")
            if worst == "PASS":
                worst = "WARN"

    # FWHM is observability-only — not a gate. Autocorrelation-based
    # residual-FWHM estimators systematically under-report applied
    # kernel width on small ROIs (well-known limitation in fMRIPrep /
    # AFNI 3dFWHMx; whole-brain ROIs needed for accurate recovery).
    # Empirically on the 11-run reg cohort: requested 2.4/2.4/11.8 mm
    # but measured ~0.5-1.8 / 0.6-1.8 / 3.2-11.4 mm. The cord-only
    # estimator literally cannot reach the requested value, so ANY
    # gating threshold (FAIL OR WARN) produces false alarms on every
    # run. The metric remains in qc.json + the smoothness_summary
    # reportlet (with policy tolerance bands for analyst review) but
    # does NOT enter the PASS/WARN/FAIL classifier. See
    # .claude/specs/s9-reportlet-set-audit.md.

    return worst, reasons


# ---------------------------------------------------------------------------
# Public per-run entry
# ---------------------------------------------------------------------------


def run_S9_primary_functional_derivatives(
    bold_path: Path,
    cord_mask_path: Path,
    warp_bold_to_pam50: Path,
    pam50_ref: Path,
    pam50_levels_native: Optional[Path],
    bold_run: dict,
    out_dir: Path,
    work_dir: Path,
    dataset_key: str,
    policy: dict[str, Any],
) -> dict[str, Any]:
    """Run S9 for a single BOLD run.

    bold_path: S5 undistorted_bold (native 4D)
    cord_mask_path: S3 cord seg in BOLD geometry
    warp_bold_to_pam50: S7 composite warp
    pam50_ref: PAM50_t2s.nii.gz
    pam50_levels_native: S7's PAM50spinallevels in native func grid (optional)
    """
    step_code = "S9_primary_functional_derivatives"
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
    s9_work_dir = work_dir / step_code / dataset_key / run_id
    s9_work_dir.mkdir(parents=True, exist_ok=True)

    failure_reasons: list[str] = []
    prefix = run_id
    sm = policy.get("smoothing", {})
    method = str(sm.get("method", "sct_cord"))
    # Cord-smoothing sigma (mm). Overridable at runtime via the
    # SPINEPREP_SIGMA_MM env var (set by the BIDS-App --smoothing-sigma-mm
    # flag) so a user can tune the kernel without editing policy YAML.
    import os
    _env_sigma = os.environ.get("SPINEPREP_SIGMA_MM")
    sigma_xyz = list(sm.get("sigma_mm", [1.0, 1.0, 5.0]))
    if _env_sigma:
        try:
            sigma_xyz = [float(x) for x in _env_sigma.replace(",", " ").split()][:3]
        except Exception:
            pass
    sigma_fwhm = [s * 2.3548 for s in sigma_xyz]

    # --- 1. Native un-smoothed: copy S5 BOLD to canonical name -----------
    unsmoothed_native = func_dir / f"{prefix}_desc-unsmoothed_bold.nii.gz"
    shutil.copy(bold_path, unsmoothed_native)

    # --- 2. Native smoothed ----------------------------------------------
    smoothed_native = func_dir / f"{prefix}_desc-preproc_bold.nii.gz"
    if method == "gaussian_inplane":
        ok, err, sm_runtime = _gaussian_inplane(
            bold_path, sigma_xyz[:2], smoothed_native,
        )
    elif method == "sct_cord_pervolume":
        # Legacy per-volume loop (escape hatch; ~T SCT spawns, shared cache).
        ok, err, sm_runtime = _run_sct_smooth_per_volume(
            bold_path, cord_mask_path, sigma_xyz, s9_work_dir, smoothed_native,
        )
    else:  # "sct_cord" (default): straighten once, smooth the 4D in batch
        ok, err, sm_runtime = _run_sct_smooth_batched(
            bold_path, cord_mask_path, sigma_xyz, s9_work_dir, smoothed_native,
        )
    if not ok:
        return {
            "status": "FAIL", "step_code": step_code,
            "dataset_key": dataset_key,
            "subject": subject, "session": session, "run_id": run_id,
            "smoothing_method": method, "sigma_mm": sigma_xyz,
            "failure_message": err,
            "failure_reasons": [err], "metrics": {}, "reportlets": {},
        }

    # --- 3. tSNR maps (native pre + post) --------------------------------
    tsnr_native_pre = s9_work_dir / "tsnr_native_pre.nii.gz"
    tsnr_native_post = func_dir / f"{prefix}_desc-tsnr_native.nii.gz"
    _tsnr_map(bold_path, tsnr_native_pre)
    _tsnr_map(smoothed_native, tsnr_native_post)
    pre_median = _median_tsnr_in_mask(bold_path, cord_mask_path)
    post_median = _median_tsnr_in_mask(smoothed_native, cord_mask_path)
    tsnr_ratio = None
    if pre_median is not None and post_median is not None and pre_median > 0:
        tsnr_ratio = float(post_median / pre_median)

    # --- 4. PAM50 outputs (3D only by default) -------------------------
    # NOTE: A full PAM50 4D BOLD at the template's 0.5mm isotropic grid
    # for a 200-vol run is ~17 GB on disk and similar RAM. For v1 we emit
    # only 3D PAM50-space outputs (funcref, tSNR) which are sufficient
    # for visualization and analysis QC. Analysts wanting 4D BOLD in PAM50
    # can apply the saved `from-bold_to-PAM50_xfm.nii.gz` themselves, OR
    # set policy.pam50_4d_output.enabled = true (off by default).
    pam50_smoothed = func_dir / f"{prefix}_space-PAM50_desc-preproc_bold.nii.gz"
    pam50_unsmoothed = func_dir / f"{prefix}_space-PAM50_desc-unsmoothed_bold.nii.gz"
    pam50_tsnr_path = func_dir / f"{prefix}_space-PAM50_desc-tsnr.nii.gz"
    pam50_funcref = func_dir / f"{prefix}_space-PAM50_desc-preproc_funcref.nii.gz"

    # Always emit PAM50 funcref by warping the SMOOTHED native temporal
    # mean (single 3D image — cheap).
    smoothed_mean_native = s9_work_dir / "smoothed_native_mean.nii.gz"
    try:
        p = nib.load(smoothed_native)
        arr = p.get_fdata().astype(np.float32)
        ref = arr.mean(axis=3) if arr.ndim == 4 else arr
        nib.save(nib.Nifti1Image(ref, p.affine, p.header), smoothed_mean_native)
        _warp_4d_to_pam50(
            smoothed_mean_native, warp_bold_to_pam50, pam50_ref, pam50_funcref,
            interp="spline",
        )
    except Exception as e:
        failure_reasons.append(f"PAM50 funcref failed: {e}")

    # Emit native tSNR warped to PAM50 (3D, cheap, useful for group QC).
    try:
        _warp_4d_to_pam50(
            tsnr_native_post, warp_bold_to_pam50, pam50_ref, pam50_tsnr_path,
            interp="linear",
        )
    except Exception as e:
        failure_reasons.append(f"PAM50 tSNR warp failed: {e}")

    # Full 4D BOLD in PAM50, cropped to the CORD ROI (cord cross-section x
    # functional z-coverage), then warp the 4D DIRECTLY into that cropped grid
    # -- output is ~0.5 GB (not ~17 GB full-grid, and not the ~3 GB the old
    # funcref-nonzero bbox produced on wide-FOV runs) and is co-gridded with the
    # cord mask below. Warps act in physical/world space, so cropping the
    # destination FOV preserves alignment.
    pam50_cord_mask = func_dir / f"{prefix}_space-PAM50_desc-cord_mask.nii.gz"
    p4d_cfg = policy.get("pam50_4d_output", {})
    if p4d_cfg.get("enabled", False):
        cord_tmpl = _pam50_cord_template(pam50_ref)
        if not pam50_funcref.exists():
            failure_reasons.append("PAM50 4D skipped: funcref-in-PAM50 missing")
        elif cord_tmpl is None:
            failure_reasons.append("PAM50 4D skipped: PAM50_cord.nii.gz not found")
        else:
            bbox = _cord_fov_bbox(
                pam50_funcref, cord_tmpl,
                xy_margin=int(p4d_cfg.get("cord_xy_margin_vox", 8)),
                z_pad=int(p4d_cfg.get("fov_pad_vox", 4)))
            if bbox is None:
                failure_reasons.append("PAM50 4D skipped: empty cord FOV")
            else:
                cropped_ref = s9_work_dir / "pam50_ref_cropfov.nii.gz"
                _crop_to_bbox(pam50_ref, bbox, cropped_ref)
                # The smoothed and unsmoothed PAM50 4D warps are INDEPENDENT
                # sct_apply_transfo calls — same warp + cropped reference, but
                # distinct inputs/outputs and each with its own tmp dir. They are
                # the S9 wall-clock bottleneck on large PAM50 grids (~5 min each;
                # see .claude/specs/s9-smoothing-bottleneck.md).
                #
                # `parallel_emit` runs the two concurrently — byte-identical
                # output, ~halved per-run PAM50 time. DEFAULT OFF: within-run
                # parallelism MULTIPLIES with the orchestrator's --batch-workers
                # (across-run parallelism), so enabling it under batched runs
                # oversubscribes the machine (measured load ~52 on 32 cores with
                # batch-workers=4 -> each apply CPU-starved, net SLOWER). Use it
                # only for single-run / low-batch contexts; for batched releases,
                # scale --batch-workers instead.
                from concurrent.futures import ThreadPoolExecutor
                jobs: dict[str, tuple] = {"smoothed": (smoothed_native, pam50_smoothed)}
                if p4d_cfg.get("emit_unsmoothed", True):
                    jobs["unsmoothed"] = (bold_path, pam50_unsmoothed)
                _mw = len(jobs) if p4d_cfg.get("parallel_emit", False) else 1
                with ThreadPoolExecutor(max_workers=_mw) as _ex:
                    _futs = {
                        name: _ex.submit(_warp_4d_to_pam50, src,
                                         warp_bold_to_pam50, cropped_ref, dst,
                                         "spline")
                        for name, (src, dst) in jobs.items()
                    }
                    for name, fut in _futs.items():
                        ok_w, err_w = fut.result()
                        if not ok_w:
                            failure_reasons.append(
                                f"PAM50 4D {name} warp failed: {err_w}")
                # Co-gridded cord mask: crop PAM50_cord with the SAME bbox so it
                # shares the cropped grid (identical affine+shape) with the 4D.
                try:
                    _crop_to_bbox(cord_tmpl, bbox, pam50_cord_mask)
                except Exception as e:
                    failure_reasons.append(f"PAM50 cord mask crop failed: {e}")

    # --- 5. Native funcref (temporal mean of smoothed native) ----------
    funcref_native = func_dir / f"{prefix}_desc-preproc_funcref.nii.gz"
    try:
        p = nib.load(smoothed_native)
        arr = p.get_fdata().astype(np.float32)
        ref = arr.mean(axis=3) if arr.ndim == 4 else arr
        nib.save(nib.Nifti1Image(ref, p.affine, p.header), funcref_native)
    except Exception as e:
        failure_reasons.append(f"native funcref failed: {e}")

    # --- 6. Per-vertebral-level tSNR ----------------------------------
    per_level_tsv = func_dir / f"{prefix}_desc-tsnr_per_level.tsv"
    n_levels = 0
    if (policy.get("per_level_tsnr", {}).get("enabled", True)
            and pam50_levels_native and pam50_levels_native.exists()):
        n_levels = _per_vertebral_level_tsnr(
            smoothed_native, pam50_levels_native, per_level_tsv,
        )
    elif policy.get("per_level_tsnr", {}).get("enabled", True):
        per_level_tsv.write_text("level\tmean_tsnr\tstd_tsnr\tn_voxels\n")
        failure_reasons.append("PAM50 spinal_levels not found; per_level skipped")

    # --- 7. Residual FWHM estimate -------------------------------------
    fwhm_meta: dict[str, Optional[float]] = {}
    if policy.get("fwhm_estimate", {}).get("enabled", True):
        fwhm_meta = _estimate_residual_fwhm(smoothed_native, cord_mask_path)

    # --- 8. Cord mask preservation -------------------------------------
    cord_dice = _cord_dice_pre_post(bold_path, smoothed_native, cord_mask_path)

    metrics = {
        "n_volumes": int(nib.load(bold_path).shape[3]),
        "tsnr_pre_median": pre_median,
        "tsnr_post_median": post_median,
        "tsnr_ratio_median": tsnr_ratio,
        "fwhm_x_measured_mm": fwhm_meta.get("x"),
        "fwhm_y_measured_mm": fwhm_meta.get("y"),
        "fwhm_z_measured_mm": fwhm_meta.get("z"),
        "fwhm_x_requested_mm": sigma_fwhm[0],
        "fwhm_y_requested_mm": sigma_fwhm[1],
        "fwhm_z_requested_mm": sigma_fwhm[2],
        "cord_dice_pre_post": cord_dice,
        "n_levels_with_tsnr": int(n_levels),
        "smoothing_runtime_s": float(sm_runtime),
    }

    status, reasons = _classify(
        metrics,
        policy.get("qc_thresholds", {}),
        fwhm_cfg=policy.get("fwhm_estimate", {}),
    )
    failure_reasons.extend(reasons)

    # --- 9. Reportlets ------------------------------------------------
    from .reportlets import (
        render_s9_tsnr_map_axial,
        render_s9_tsnr_per_level,
        render_s9_smoothness_summary,
    )
    rep_tsnrmap = figures_dir / f"{prefix}_desc-S9_tsnr_map_axial.png"
    rep_perlevel = figures_dir / f"{prefix}_desc-S9_tsnr_per_level.png"
    rep_smsum = figures_dir / f"{prefix}_desc-S9_smoothness_summary.png"
    qct = policy.get("qc_thresholds", {})
    fwhm_cfg_p = policy.get("fwhm_estimate", {})
    try:
        render_s9_tsnr_map_axial(
            tsnr_native_post, cord_mask_path, rep_tsnrmap,
            status=status,
            tsnr_ratio=metrics.get("tsnr_ratio_median"),
        )
    except Exception as e:
        failure_reasons.append(f"tsnr_map reportlet failed: {e}")
    try:
        render_s9_tsnr_per_level(
            per_level_tsv, rep_perlevel,
            status=status,
            pass_threshold=float(qct.get("pass_median_in_cord_tsnr", 5.0)),
            warn_threshold=float(qct.get("warn_median_in_cord_tsnr", 3.0)),
        )
    except Exception as e:
        failure_reasons.append(f"tsnr_per_level reportlet failed: {e}")
    try:
        render_s9_smoothness_summary(
            requested=sigma_fwhm, measured=fwhm_meta, output_path=rep_smsum,
            status=status,
            tolerance_xy=float(fwhm_cfg_p.get("tolerance_mm_xy", 0.5)),
            tolerance_xy_warn=float(fwhm_cfg_p.get("tolerance_mm_xy_warn", 1.0)),
            tolerance_z=float(fwhm_cfg_p.get("tolerance_mm_z", 1.0)),
            tolerance_z_warn=float(fwhm_cfg_p.get("tolerance_mm_z_warn", 2.0)),
        )
    except Exception as e:
        failure_reasons.append(f"smoothness_summary reportlet failed: {e}")

    # --- 9b. BIDS sidecars for every BOLD + dataset_description --------
    # A GLM needs RepetitionTime; BIDS-Derivatives needs the sidecar.
    # Prefer the authoritative TR from the raw BIDS sidecar (passed in via
    # bold_run); the processed header's pixdim[4] is unreliable (defaults to 1.0).
    tr = bold_run.get("RepetitionTime") or _bold_tr(bold_path)
    task = _task_from_run_id(run_id)
    try:
        _write_bold_sidecar(smoothed_native, tr, task, smoothing_fwhm=sigma_fwhm)
        _write_bold_sidecar(unsmoothed_native, tr, task)
        if pam50_smoothed.exists():
            _write_bold_sidecar(pam50_smoothed, tr, task, space="PAM50",
                                smoothing_fwhm=sigma_fwhm)
        if pam50_unsmoothed.exists():
            _write_bold_sidecar(pam50_unsmoothed, tr, task, space="PAM50")
        _ensure_dataset_description(
            out_dir / "derivatives" / "spineprep")
    except Exception as e:
        failure_reasons.append(f"sidecar/dataset_description failed: {e}")

    # --- 10. Save work qc + sidecar ----------------------------------
    policy_sha = hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()
    (s9_work_dir / "qc_metrics.json").write_text(json.dumps({
        "metrics": metrics,
        "method": method, "sigma_xyz_mm": sigma_xyz,
        "policy_sha256": policy_sha,
        "failure_reasons": failure_reasons,
    }, indent=2, default=str))

    return {
        "status": status,
        "step_code": step_code,
        "dataset_key": dataset_key,
        "subject": subject,
        "session": session,
        "run_id": run_id,
        "smoothing_method": method,
        "sigma_mm": sigma_xyz,
        "metrics": metrics,
        "failure_reasons": failure_reasons,
        "failure_message": "; ".join(failure_reasons) if failure_reasons else None,
        "reportlets": {
            "tsnr_map_axial":               str(rep_tsnrmap.relative_to(out_dir))
                if rep_tsnrmap.exists() else "",
            "tsnr_per_level":               str(rep_perlevel.relative_to(out_dir))
                if rep_perlevel.exists() else "",
            "smoothness_summary":           str(rep_smsum.relative_to(out_dir))
                if rep_smsum.exists() else "",
        },
        "output_paths": {
            "preproc_bold_native":     str(smoothed_native.relative_to(out_dir)),
            "unsmoothed_bold_native":  str(unsmoothed_native.relative_to(out_dir)),
            "preproc_bold_pam50":      str(pam50_smoothed.relative_to(out_dir))
                if pam50_smoothed.exists() else "",
            "unsmoothed_bold_pam50":   str(pam50_unsmoothed.relative_to(out_dir))
                if pam50_unsmoothed.exists() else "",
            "cord_mask_pam50":         str(pam50_cord_mask.relative_to(out_dir))
                if pam50_cord_mask.exists() else "",
            "tsnr_native":             str(tsnr_native_post.relative_to(out_dir)),
            "tsnr_pam50":              str(pam50_tsnr_path.relative_to(out_dir))
                if pam50_tsnr_path.exists() else "",
            "tsnr_per_level_tsv":      str(per_level_tsv.relative_to(out_dir)),
        },
    }
