"""S5.x: per-run distortion correction (topup, fugue, or SyN).

Spec: private/SPEC/S5_func_distortion_correction.md
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional

import nibabel as nib
import numpy as np

from spinalfmriprep.lib.run import run_command as _run_command


_ANTS_DOCKER_IMAGE = "vnmd/ants_2.6.0:20250424"
_ANTS_LOCAL_AVAILABLE: Optional[bool] = None


def _ants_local_available() -> bool:
    """Cache the result of looking up antsRegistration on PATH."""
    global _ANTS_LOCAL_AVAILABLE
    if _ANTS_LOCAL_AVAILABLE is None:
        _ANTS_LOCAL_AVAILABLE = shutil.which("antsRegistration") is not None
    return _ANTS_LOCAL_AVAILABLE


def _ants_command(cmd: list[str]) -> list[str]:
    """Wrap an ANTs command in a Docker invocation if no local install.

    Mounts the SpinalfMRIprep project root so absolute paths inside cmd
    resolve identically inside the container. The S0_SETUP spec already
    pins the image; this just makes S5 use it when needed.
    """
    if _ants_local_available():
        return cmd
    project_root = Path(__file__).resolve().parents[4]
    return [
        "docker", "run", "--rm",
        "-v", f"{project_root}:{project_root}",
        "-w", str(Path.cwd()),
        _ANTS_DOCKER_IMAGE,
        *cmd,
    ]


# BIDS PE direction -> FSL acqparams first-three-columns row.
# Spec §S5.2 step 2.
_BIDS_PE_TO_ACQPARAMS = {
    "i":  (1, 0, 0),
    "i-": (-1, 0, 0),
    "j":  (0, 1, 0),
    "j-": (0, -1, 0),
    "k":  (0, 0, 1),
    "k-": (0, 0, -1),
}


def _trt_for(run: dict, bids_root: Optional[Path] = None) -> Optional[float]:
    """Pull TotalReadoutTime from S1 acquisition dict. Fallback: compute
    from EES x (ReconMatrixPE - 1). Last resort: open the BIDS JSON sidecar
    directly (for old S1 inventories that pre-date the A5 fmap-extraction).
    Returns None when no source works.

    BIDS records TRT as the unaccelerated-equivalent readout time -
    DO NOT divide by ParallelReductionFactorInPlane. (See S5 spec.)
    """
    acq = run.get("acquisition", {}) if isinstance(run, dict) else {}
    if isinstance(acq, dict) and "TotalReadoutTime" in acq:
        return float(acq["TotalReadoutTime"])
    if isinstance(acq, dict):
        ees = acq.get("EffectiveEchoSpacing")
        matrix_pe = acq.get("ReconMatrixPE") or acq.get("AcquisitionMatrixPE")
        if ees is not None and matrix_pe is not None:
            return float(ees) * (int(matrix_pe) - 1)
    # Last resort: parse the BIDS sidecar of this run from disk
    if bids_root is not None and run.get("path"):
        bids_path = Path(bids_root) / run["path"]
        sidecar = bids_path.with_name(
            bids_path.name.replace(".nii.gz", ".json").replace(".nii", ".json")
        )
        if sidecar.exists():
            try:
                d = json.loads(sidecar.read_text())
                if "TotalReadoutTime" in d:
                    return float(d["TotalReadoutTime"])
                ees = d.get("EffectiveEchoSpacing")
                matrix_pe = d.get("ReconMatrixPE") or d.get("AcquisitionMatrixPE")
                if ees is not None and matrix_pe is not None:
                    return float(ees) * (int(matrix_pe) - 1)
            except Exception:
                pass
    return None


def _bold_pe_index_in_acqparams(
    bold_pe: str, fmap_pes: list[str]
) -> int:
    """applytopup --inindex (1-based) of the acqparams row whose PE matches
    the BOLD's PE direction. Spec §S5.2 step 4."""
    for i, pe in enumerate(fmap_pes, start=1):
        if pe == bold_pe:
            return i
    # Defensive: when the BOLD PE doesn't exactly match either fmap row
    # (e.g. j vs j-), use the first row whose axis matches.
    for i, pe in enumerate(fmap_pes, start=1):
        if pe and pe.rstrip("-") == bold_pe.rstrip("-"):
            return i
    return 1  # last resort


def _write_acqparams(
    path: Path,
    fmap_pes: list[str],
    trt: float,
) -> None:
    """Write FSL acqparams.txt with one row per fmap volume."""
    rows: list[str] = []
    for pe in fmap_pes:
        if pe not in _BIDS_PE_TO_ACQPARAMS:
            raise ValueError(f"Unsupported PhaseEncodingDirection {pe!r}")
        x, y, z = _BIDS_PE_TO_ACQPARAMS[pe]
        rows.append(f"{x} {y} {z} {trt:.6f}")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def _merge_epi_fmaps(
    out_path: Path,
    fmap_nifti_paths: list[Path],
) -> None:
    """Concatenate single-volume EPI fmaps into a 4D file for topup."""
    imgs = [nib.load(p) for p in fmap_nifti_paths]
    data = [img.get_fdata() for img in imgs]
    # Each fmap volume may be 3D (single timepoint) - stack along time
    stacked = np.stack([d if d.ndim == 3 else d[..., 0] for d in data], axis=-1)
    nib.save(nib.Nifti1Image(stacked.astype(np.float32), imgs[0].affine,
                             imgs[0].header), out_path)


# ---------------------------------------------------------------------------
# Mode entry points
# ---------------------------------------------------------------------------


def _run_topup(
    bold_path: Path,
    fmap_runs: list[dict],
    bids_root: Path,
    bold_run: dict,
    work_dir: Path,
    out_undistorted: Path,
    policy: dict,
) -> dict[str, Any]:
    """Mode = topup. Estimate field from reversed-phase EPI pair, then
    applytopup to the BOLD."""
    work_dir.mkdir(parents=True, exist_ok=True)

    # Resolve TRT from any of the fmap runs (they share it with BOLD).
    # If S1 inventory predates the A5 commit, the acquisition dict will be
    # absent; falls through to reading the BIDS sidecar directly.
    trt = (_trt_for(fmap_runs[0], bids_root)
           or _trt_for(bold_run, bids_root))
    if trt is None:
        return {"status": "FAIL", "mode": "topup",
                "failure_message": "TotalReadoutTime not in BIDS sidecar"}

    from .mode import _pe_from_run
    fmap_paths = [bids_root / f["path"] for f in fmap_runs]
    fmap_pes = [_pe_from_run(f) for f in fmap_runs]
    if any(pe is None for pe in fmap_pes):
        return {"status": "FAIL", "mode": "topup",
                "failure_message": "could not resolve PE direction for one of the fmaps"}

    # Resample each fmap onto the BOLD's geometry (typically S3-cropped, ~30x30
    # voxels). applytopup does NOT auto-resample, and topup must be estimated in
    # the same space as the BOLD it will unwarp. flirt -applyxfm -usesqform uses
    # the NIfTI sform/qform to figure out the rigid transform from fmap-space
    # to BOLD-space, then resamples. Cheap (single 3D resample per fmap).
    resampled_fmaps: list[Path] = []
    for i, fp in enumerate(fmap_paths):
        out_r = work_dir / f"fmap_{i:02d}_in_bold.nii.gz"
        cmd = [
            "flirt",
            "-in", str(fp),
            "-ref", str(bold_path),
            "-applyxfm", "-usesqform",
            "-interp", "trilinear",
            "-out", str(out_r),
        ]
        ok, out = _run_command(cmd)
        if not ok:
            return {"status": "FAIL", "mode": "topup",
                    "failure_message": f"flirt resample fmap[{i}] failed: {out[:200]}"}
        resampled_fmaps.append(out_r)

    merged = work_dir / "fmap_merged.nii.gz"
    _merge_epi_fmaps(merged, resampled_fmaps)

    acqparams = work_dir / "acqparams.txt"
    _write_acqparams(acqparams, fmap_pes, trt)

    topup_base = work_dir / "topup"
    config = policy.get("distortion_correction", {}).get("topup", {}).get(
        "config", "b02b0.cnf"
    )
    cmd_topup = [
        "topup",
        f"--imain={merged}",
        f"--datain={acqparams}",
        f"--config={config}",
        f"--out={topup_base}",
    ]
    ok, out = _run_command(cmd_topup)
    if not ok:
        return {"status": "FAIL", "mode": "topup",
                "failure_message": f"topup failed: {out[:240]}"}

    bold_pe = _pe_from_run(bold_run) or "j"  # safe default for cervical EPI
    inindex = _bold_pe_index_in_acqparams(bold_pe, fmap_pes)
    apply_method = policy.get("distortion_correction", {}).get(
        "topup", {}).get("apply_method", "jac")

    cmd_apply = [
        "applytopup",
        f"--imain={bold_path}",
        f"--datain={acqparams}",
        f"--inindex={inindex}",
        f"--topup={topup_base}",
        f"--method={apply_method}",
        f"--out={out_undistorted}",
    ]
    ok, out = _run_command(cmd_apply)
    if not ok:
        return {"status": "FAIL", "mode": "topup",
                "failure_message": f"applytopup failed: {out[:240]}"}

    return {"status": "OK", "mode": "topup",
            "acqparams_path": str(acqparams),
            "topup_basename": str(topup_base),
            "trt": trt}


def _run_fugue(*args, **kwargs) -> dict[str, Any]:
    """Mode = fugue. Not exercised by v1_validation; spec'd for completeness.
    Implementation deferred to follow-up; falls back to syn for v1.0."""
    return {"status": "FAIL", "mode": "fugue",
            "failure_message": "FUGUE mode not implemented in v1.0 - falls back to SyN"}


def _run_syn(
    bold_path: Path,
    anat_path: Path,
    cord_mask_path: Path,
    work_dir: Path,
    out_undistorted: Path,
    policy: dict,
    bold_space_cord_mask: Optional[Path] = None,
    anat_in_bold: Optional[Path] = None,
) -> dict[str, Any]:
    """Mode = SyN fallback. Light cord-mask-restricted SyN of mean(BOLD)
    to T2w anat. Spec §S5.4.

    Operates entirely in BOLD geometry so the output preserves BOLD shape
    for downstream consumers (S6+) and reportlets. Caller passes
    `anat_in_bold` (anat already resampled to BOLD grid); SyN runs with
    mean_BOLD (moving) and anat_in_bold (fixed). The warp is applied to
    the 4D BOLD with BOLD as reference, leaving geometry untouched.
    """
    work_dir.mkdir(parents=True, exist_ok=True)

    # Compute temporal mean BOLD
    bold_img = nib.load(bold_path)
    bold_data = bold_img.get_fdata()
    if bold_data.ndim == 4:
        mean_bold = bold_data.mean(axis=3)
    else:
        mean_bold = bold_data
    mean_path = work_dir / "mean_bold.nii.gz"
    nib.save(nib.Nifti1Image(mean_bold.astype(np.float32), bold_img.affine,
                             bold_img.header), mean_path)

    if anat_in_bold is None or not Path(anat_in_bold).exists():
        return {"status": "FAIL", "mode": "syn",
                "failure_message": "anat_in_bold missing (caller must resample)"}

    # Prefer a BOLD-space cord mask. Fall back to resampling the anat-space
    # cord mask onto BOLD geometry (nearest-neighbour to keep it binary).
    if bold_space_cord_mask is not None and bold_space_cord_mask.exists():
        syn_mask = bold_space_cord_mask
    else:
        syn_mask = work_dir / "cord_mask_in_bold.nii.gz"
        ok, out = _run_command([
            "flirt",
            "-in", str(cord_mask_path),
            "-ref", str(mean_path),
            "-applyxfm", "-usesqform",
            "-interp", "nearestneighbour",
            "-out", str(syn_mask),
        ])
        if not ok:
            return {"status": "FAIL", "mode": "syn",
                    "failure_message": f"flirt mask->bold failed: {out[:240]}"}

    syn_cfg = policy.get("distortion_correction", {}).get("syn", {})
    transform = syn_cfg.get("transform", "SyN[0.1,3,0]")
    shrink = syn_cfg.get("shrink", "4x2x1")
    smoothing = syn_cfg.get("smoothing", "2x1x0vox")
    metric_args = (
        f"MI[{anat_in_bold},{mean_path},1,{syn_cfg.get('bin_count', 32)}]"
    )
    out_prefix = work_dir / "syn_"

    cmd_reg = _ants_command([
        "antsRegistration",
        "--float",
        "--dimensionality", "3",
        "--metric", metric_args,
        "--transform", transform,
        "--convergence", "[40x20x0,1e-6,10]",
        "--shrink-factors", shrink,
        "--smoothing-sigmas", smoothing,
        "--masks", f"[{syn_mask},{syn_mask}]",
        "--output", str(out_prefix),
    ])
    ok, out = _run_command(cmd_reg)
    if not ok:
        return {"status": "FAIL", "mode": "syn",
                "failure_message": f"antsRegistration failed: {out[:240]}"}

    # Apply the warp to the 4D BOLD, keeping BOLD geometry as output grid.
    warp = f"{out_prefix}0Warp.nii.gz"
    cmd_apply = _ants_command([
        "antsApplyTransforms",
        "-d", "3", "-e", "3",
        "-i", str(bold_path),
        "-r", str(mean_path),
        "-t", warp,
        "-o", str(out_undistorted),
        "-n", "LanczosWindowedSinc",
    ])
    ok, out = _run_command(cmd_apply)
    if not ok:
        return {"status": "FAIL", "mode": "syn",
                "failure_message": f"antsApplyTransforms failed: {out[:240]}"}

    return {"status": "OK", "mode": "syn",
            "warp_path": warp}


# ---------------------------------------------------------------------------
# QC metrics
# ---------------------------------------------------------------------------


def _mutual_information(a: np.ndarray, b: np.ndarray, bins: int = 32) -> float:
    """Simple histogram-based MI for QC (joint vs marginal entropies)."""
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


def _compute_qc(
    bold_before: Path,
    bold_after: Path,
    anat_path: Optional[Path],
) -> dict[str, Any]:
    """Mutual information before/after, retained as a secondary metric
    on qc.json (no longer plotted as the primary reportlet). The CoSpine
    geometric metrics (cord-Dice, A–P displacement) are the headline
    measures; see ``_compute_cospine_metrics``.

    `anat_path` must be in the same geometry as the BOLDs (i.e. anat
    already resampled to BOLD space — produced once by the caller). When
    shapes still mismatch we skip MI rather than report a garbage value.
    """
    a = nib.load(bold_before).get_fdata()
    b = nib.load(bold_after).get_fdata()
    mean_a = a.mean(axis=3) if a.ndim == 4 else a
    mean_b = b.mean(axis=3) if b.ndim == 4 else b

    metrics: dict[str, Any] = {
        "mean_before_voxels": int(np.isfinite(mean_a).sum()),
        "mean_after_voxels": int(np.isfinite(mean_b).sum()),
    }
    if anat_path is not None and Path(anat_path).exists():
        anat = nib.load(anat_path).get_fdata()
        if anat.shape == mean_a.shape:
            metrics["mi_before"] = _mutual_information(mean_a, anat)
            metrics["mi_after"] = _mutual_information(mean_b, anat)
            if metrics["mi_before"] > 0:
                metrics["mi_delta_pct"] = float(
                    (metrics["mi_after"] - metrics["mi_before"])
                    / metrics["mi_before"] * 100
                )
    return metrics


# ---------------------------------------------------------------------------
# CoSpine-style effectiveness metrics: per-slice A–P cord-centerline
# displacement and per-slice 2D cord-Dice (EPI ∩ anat), both Before and
# After distortion correction. See Wei et al., Sci Data 2025
# (CoSpine database) §"Slice-by-slice Y-axis displacement" and
# §"Spinal cord DSC".
#
# Pipeline (geometry-faithful, mode-agnostic):
#   1. Resample S2 anat cord_dseg → BOLD voxel grid via
#      `flirt -applyxfm -usesqform -interp nearestneighbour`. The header
#      sforms encode the rigid scanner→world mapping; this gives the
#      same anat-cord reference for both Before and After (S5 is in-grid,
#      so BOLD-before and BOLD-after share the voxel lattice).
#   2. Save mean BOLD Before/After, write them to disk.
#   3. Run `sct_deepseg_sc -c t2s` on each mean BOLD → EPI cord seg in
#      BOLD geometry. Matches CoSpine §Methods.
#   4. Per Z-slice intersecting all three masks: compute Y-centroid of
#      each binary slice and the 2D Dice (EPI ∩ anat). Aggregate into
#      mean/std and a 3D Dice pooled across all evaluated voxels.
# ---------------------------------------------------------------------------


def _centroid_y(slice2d: np.ndarray) -> Optional[float]:
    """Voxel-coord Y centroid of a binary 2D slice. Returns None when empty."""
    if slice2d.sum() <= 0:
        return None
    ys, xs = np.nonzero(slice2d > 0)
    if ys.size == 0:
        return None
    # convention: first array axis is X (RL), second is Y (AP) for RPI/RAS.
    # _slice2d here is mask[:, :, z], so axis 0 = X, axis 1 = Y.
    # np.nonzero returns (axis0, axis1) ⇒ axis1 indices are Y.
    return float(xs.mean())


def _dice_2d(a: np.ndarray, b: np.ndarray) -> Optional[float]:
    sa = int((a > 0).sum())
    sb = int((b > 0).sum())
    if sa + sb == 0:
        return None
    inter = int(((a > 0) & (b > 0)).sum())
    return float(2.0 * inter / (sa + sb))


def _resample_mask_to_bold(
    mask_path: Path, bold_ref: Path, out_path: Path,
) -> bool:
    """Resample a binary mask to BOLD geometry using FLIRT sform-applyxfm
    with nearest-neighbour interpolation. Returns True on success."""
    ok, _ = _run_command([
        "flirt",
        "-in", str(mask_path),
        "-ref", str(bold_ref),
        "-applyxfm", "-usesqform",
        "-interp", "nearestneighbour",
        "-out", str(out_path),
    ])
    return ok and out_path.exists()


def _sct_deepseg_cord(
    mean_path: Path, out_seg: Path, work_dir: Path,
) -> bool:
    """Run sct_deepseg_sc on a 3D mean BOLD to produce a cord mask in the
    same geometry. Returns True on success.

    Output path of sct_deepseg_sc is derived from -i (suffix _seg);
    we run inside ``work_dir`` and move the result to ``out_seg``.
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    # sct_deepseg_sc writes to the input's directory with _seg suffix.
    local_in = work_dir / mean_path.name
    if local_in.resolve() != mean_path.resolve():
        if local_in.exists():
            local_in.unlink()
        local_in.symlink_to(mean_path.resolve())
    ok, _ = _run_command([
        "sct_deepseg_sc",
        "-i", str(local_in),
        "-c", "t2s",
        "-ofolder", str(work_dir),
    ])
    if not ok:
        return False
    produced = work_dir / f"{local_in.stem.replace('.nii', '')}_seg.nii.gz"
    if not produced.exists():
        # Some SCT versions emit alongside .nii (no .gz). Try both.
        alt = work_dir / f"{local_in.stem}_seg.nii.gz"
        if alt.exists():
            produced = alt
        else:
            return False
    shutil.copy(produced, out_seg)
    return out_seg.exists()


def _compute_cospine_metrics(
    bold_before: Path,
    bold_after: Path,
    anat_cord_mask_path: Optional[Path],
    bold_mean_ref: Optional[Path],
    work_dir: Path,
) -> dict[str, Any]:
    """Per-Z A–P displacement and 2D cord-Dice between EPI cord seg and
    anat cord mask, Before and After distortion correction.

    Returns a flat dict ready to merge into qc.json metrics. When inputs
    are missing or sct_deepseg_sc fails, the dict carries a single
    ``cospine_skip_reason`` key and nothing else.
    """
    out: dict[str, Any] = {}
    work_dir.mkdir(parents=True, exist_ok=True)
    if anat_cord_mask_path is None or not Path(anat_cord_mask_path).exists():
        out["cospine_skip_reason"] = "anat cord mask unavailable"
        return out
    if bold_mean_ref is None or not bold_mean_ref.exists():
        # Build it from bold_after as a last-resort fallback.
        img = nib.load(bold_after)
        d = img.get_fdata()
        m = d.mean(axis=3) if d.ndim == 4 else d
        bold_mean_ref = work_dir / "bold_after_mean.nii.gz"
        nib.save(nib.Nifti1Image(m.astype(np.float32), img.affine, img.header),
                 bold_mean_ref)

    # 1. anat cord mask → BOLD grid (NN)
    anat_in_bold = work_dir / "anat_cord_dseg_in_bold.nii.gz"
    if not _resample_mask_to_bold(Path(anat_cord_mask_path),
                                   bold_mean_ref, anat_in_bold):
        out["cospine_skip_reason"] = "flirt resample of anat cord mask failed"
        return out
    anat_arr = nib.load(anat_in_bold).get_fdata() > 0
    if anat_arr.sum() == 0:
        out["cospine_skip_reason"] = "resampled anat cord mask is empty"
        return out

    # 2. mean BOLDs in BOLD geometry
    mean_b_path = work_dir / "bold_before_mean.nii.gz"
    img_b = nib.load(bold_before)
    db = img_b.get_fdata()
    mean_b = db.mean(axis=3) if db.ndim == 4 else db
    nib.save(nib.Nifti1Image(mean_b.astype(np.float32),
                              img_b.affine, img_b.header), mean_b_path)

    mean_a_path = work_dir / "bold_after_mean.nii.gz"
    img_a = nib.load(bold_after)
    da = img_a.get_fdata()
    mean_a = da.mean(axis=3) if da.ndim == 4 else da
    nib.save(nib.Nifti1Image(mean_a.astype(np.float32),
                              img_a.affine, img_a.header), mean_a_path)

    # 3. EPI cord segs via sct_deepseg_sc (CoSpine recipe)
    bold_cord_b = work_dir / "bold_before_cord_seg.nii.gz"
    bold_cord_a = work_dir / "bold_after_cord_seg.nii.gz"
    seg_work = work_dir / "deepseg"
    if not _sct_deepseg_cord(mean_b_path, bold_cord_b, seg_work / "before"):
        out["cospine_skip_reason"] = "sct_deepseg_sc failed on BOLD-before"
        return out
    if not _sct_deepseg_cord(mean_a_path, bold_cord_a, seg_work / "after"):
        out["cospine_skip_reason"] = "sct_deepseg_sc failed on BOLD-after"
        return out
    epi_b = nib.load(bold_cord_b).get_fdata() > 0
    epi_a = nib.load(bold_cord_a).get_fdata() > 0

    # Voxel size along Y (AP) from BOLD header
    zooms = img_a.header.get_zooms()[:3]
    voxsize_y_mm = float(zooms[1]) if len(zooms) >= 2 else 1.0

    # 4. Per-slice metrics on the Z range where the anat reference has cord.
    anat_z_with_cord = np.where(anat_arr.any(axis=(0, 1)))[0]
    if anat_z_with_cord.size == 0:
        out["cospine_skip_reason"] = "anat cord mask has no Z coverage"
        return out

    per_z: list[int] = []
    disp_b: list[float] = []
    disp_a: list[float] = []
    dice_b: list[float] = []
    dice_a: list[float] = []
    valid_voxels_b = 0
    valid_voxels_a = 0
    inter_b = 0
    inter_a = 0
    sum_anat = 0
    for z in anat_z_with_cord.tolist():
        a_sl = anat_arr[:, :, z]
        b_sl = epi_b[:, :, z]
        a2_sl = epi_a[:, :, z]
        cy_ref = _centroid_y(a_sl)
        cy_b = _centroid_y(b_sl)
        cy_a = _centroid_y(a2_sl)
        if cy_ref is None:
            continue
        # Need at least one EPI mask on this slice to score it. If a
        # slice has no EPI cord on either side, skip — that's a coverage
        # gap, not a distortion measurement.
        if cy_b is None and cy_a is None:
            continue
        per_z.append(int(z))
        disp_b.append(abs(cy_b - cy_ref) * voxsize_y_mm
                      if cy_b is not None else float("nan"))
        disp_a.append(abs(cy_a - cy_ref) * voxsize_y_mm
                      if cy_a is not None else float("nan"))
        d2_b = _dice_2d(a_sl, b_sl)
        d2_a = _dice_2d(a_sl, a2_sl)
        dice_b.append(d2_b if d2_b is not None else 0.0)
        dice_a.append(d2_a if d2_a is not None else 0.0)
        # 3D pooled accumulators over the same Z range
        sum_anat += int(a_sl.sum())
        valid_voxels_b += int(b_sl.sum())
        valid_voxels_a += int(a2_sl.sum())
        inter_b += int((a_sl & b_sl).sum())
        inter_a += int((a_sl & a2_sl).sum())

    if not per_z:
        out["cospine_skip_reason"] = (
            "no Z slices with both anat and EPI cord coverage")
        return out

    db_arr = np.asarray(disp_b, dtype=float)
    da_arr = np.asarray(disp_a, dtype=float)
    dice_b_arr = np.asarray(dice_b, dtype=float)
    dice_a_arr = np.asarray(dice_a, dtype=float)

    def _fmean(a: np.ndarray) -> Optional[float]:
        v = a[np.isfinite(a)]
        return float(v.mean()) if v.size else None

    def _fmax(a: np.ndarray) -> Optional[float]:
        v = a[np.isfinite(a)]
        return float(v.max()) if v.size else None

    def _fmin(a: np.ndarray) -> Optional[float]:
        v = a[np.isfinite(a)]
        return float(v.min()) if v.size else None

    d3b = (2.0 * inter_b / (sum_anat + valid_voxels_b)
           if (sum_anat + valid_voxels_b) > 0 else None)
    d3a = (2.0 * inter_a / (sum_anat + valid_voxels_a)
           if (sum_anat + valid_voxels_a) > 0 else None)

    out["per_slice_z"] = per_z
    out["displacement_before_mm"] = db_arr.tolist()
    out["displacement_after_mm"] = da_arr.tolist()
    out["displacement_mean_before_mm"] = _fmean(db_arr)
    out["displacement_mean_after_mm"] = _fmean(da_arr)
    out["displacement_max_after_mm"] = _fmax(da_arr)
    out["displacement_delta_mm"] = (
        out["displacement_mean_after_mm"] - out["displacement_mean_before_mm"]
        if (out["displacement_mean_after_mm"] is not None
            and out["displacement_mean_before_mm"] is not None)
        else None
    )
    out["dice_per_slice_before"] = dice_b_arr.tolist()
    out["dice_per_slice_after"] = dice_a_arr.tolist()
    out["dice_mean_before"] = _fmean(dice_b_arr)
    out["dice_mean_after"] = _fmean(dice_a_arr)
    out["dice_min_after"] = _fmin(dice_a_arr)
    out["dice_3d_before"] = d3b
    out["dice_3d_after"] = d3a
    out["dice_delta"] = (
        out["dice_mean_after"] - out["dice_mean_before"]
        if (out["dice_mean_after"] is not None
            and out["dice_mean_before"] is not None)
        else None
    )
    out["voxsize_y_mm"] = voxsize_y_mm
    out["n_slices_evaluated"] = len(per_z)
    return out


def _classify_run_status(metrics: dict, mode: str, thresholds: dict) -> tuple[str, list[str]]:
    """PASS / WARN / FAIL on the CoSpine-style geometric metrics.

    Headline gates (After distortion correction):
      - cord ``dice_mean_after`` ≥ ``pass_dice_min`` and ≥ Before − ε
      - per-slice ``displacement_mean_after_mm`` ≤
        ``pass_displacement_max_mm`` and ≤ Before + ε
    Plus the legacy MI sanity check (PASS requires Δ ≥ 0%, but a
    catastrophic drop fails outright). SyN always degrades to WARN
    (no fmap = inherently weaker correction).

    When the CoSpine metrics could not be computed (anat unavailable),
    fall back to MI gating alone so the step still meaningfully runs.
    """
    reasons: list[str] = []

    # Catastrophic MI drop: fail outright regardless of mode.
    mi_delta = metrics.get("mi_delta_pct")
    if mi_delta is not None and mi_delta < -thresholds.get(
            "fail_mi_max_drop_pct", 10.0):
        return "FAIL", [f"MI dropped {mi_delta:.1f}% > 10%"]

    skip = metrics.get("cospine_skip_reason")
    if skip:
        reasons.append(f"CoSpine metrics skipped: {skip}")
        if mi_delta is not None and mi_delta < 0:
            reasons.append(f"MI did not improve ({mi_delta:+.1f}%)")
    else:
        dice_a = metrics.get("dice_mean_after")
        dice_b = metrics.get("dice_mean_before")
        disp_a = metrics.get("displacement_mean_after_mm")
        disp_b = metrics.get("displacement_mean_before_mm")
        pass_dice = float(thresholds.get("pass_dice_min", 0.50))
        warn_dice = float(thresholds.get("warn_dice_min", 0.30))
        pass_disp = float(thresholds.get("pass_displacement_max_mm", 1.0))
        warn_disp = float(thresholds.get("warn_displacement_max_mm", 2.0))
        eps_dice = float(thresholds.get("epsilon_dice", 0.02))
        eps_disp = float(thresholds.get("epsilon_displacement_mm", 0.2))

        if dice_a is None or disp_a is None:
            reasons.append("CoSpine metrics incomplete")
        else:
            if dice_a < warn_dice:
                return "FAIL", [f"cord Dice after = {dice_a:.2f} < "
                                f"warn floor {warn_dice:.2f}"]
            if disp_a > warn_disp:
                return "FAIL", [f"cord A–P displacement after = "
                                f"{disp_a:.2f} mm > warn ceiling "
                                f"{warn_disp:.2f} mm"]
            if dice_a < pass_dice:
                reasons.append(f"cord Dice after = {dice_a:.2f} < pass "
                               f"floor {pass_dice:.2f}")
            if disp_a > pass_disp:
                reasons.append(f"cord A–P displacement after = "
                               f"{disp_a:.2f} mm > pass ceiling "
                               f"{pass_disp:.2f} mm")
            if dice_b is not None and dice_a < dice_b - eps_dice:
                reasons.append(f"cord Dice degraded ({dice_b:.2f} → "
                               f"{dice_a:.2f})")
            if disp_b is not None and disp_a > disp_b + eps_disp:
                reasons.append(f"cord A–P displacement increased "
                               f"({disp_b:.2f} → {disp_a:.2f} mm)")

    if mode == "syn":
        # SyN always marked WARN per spec (no fmap = degraded capability)
        reasons.append("SyN fallback used (no fieldmap available)")
        return "WARN", reasons

    return "PASS" if not reasons else "WARN", reasons


# ---------------------------------------------------------------------------
# Public per-run entry
# ---------------------------------------------------------------------------


def run_S5_func_distortion_correction(
    bold_path: Path,
    bold_run: dict,
    fmap_runs: list[dict],
    bids_root: Path,
    cord_mask_path: Optional[Path],
    anat_path: Optional[Path],
    out_dir: Path,
    work_dir: Path,
    dataset_key: str,
    policy: dict[str, Any],
) -> dict[str, Any]:
    """Run distortion correction for a single BOLD run.

    Returns a qc-style dict with status, mode, metrics, failure_reasons,
    reportlets (relative-to-out_dir paths).
    """
    step_code = "S5_func_distortion_correction"
    subject_raw = bold_run.get("subject") or ""
    session_raw = bold_run.get("session")
    # subject sometimes arrives bare ("02") and sometimes already prefixed
    # ("sub-02") depending on which orchestrator produced bold_run.
    subject = subject_raw[4:] if str(subject_raw).startswith("sub-") else subject_raw
    session = None
    if session_raw:
        session = (str(session_raw)[4:] if str(session_raw).startswith("ses-")
                   else session_raw)
    run_id = Path(bold_run["path"]).name.replace("_bold.nii.gz", "").replace("_bold.nii", "")

    # Output paths
    if session:
        func_dir = out_dir / "derivatives" / "spinalfmriprep" / f"sub-{subject}" / f"ses-{session}" / "func"
    else:
        func_dir = out_dir / "derivatives" / "spinalfmriprep" / f"sub-{subject}" / "func"
    func_dir.mkdir(parents=True, exist_ok=True)
    prefix = run_id  # already includes subject/session/task entities
    out_undistorted = func_dir / f"{prefix}_desc-undistorted_bold.nii.gz"

    s5_work_dir = work_dir / step_code / run_id
    s5_work_dir.mkdir(parents=True, exist_ok=True)

    # Locate a BOLD-space cord mask (S3.1's funccrop_mask) — used by SyN and
    # by the reportlet. The anat-space cord_mask_path from S2 is the wrong
    # geometry for both. Search local work first, then the chained
    # workfolder, then the project-relative chain.
    bold_space_cord_mask = None
    project_root = out_dir.parent.parent if out_dir.name.startswith("wf_") \
        else Path.cwd()
    rel = Path("runs") / "S3_func_init_and_crop" / run_id / "funccrop_mask.nii.gz"
    for cand in (
        out_dir / "work" / "S3_func_init_and_crop" / run_id / "funccrop_mask.nii.gz",
        project_root / "work" / "done" / "reg" / "S3" / rel,
        Path("work") / "done" / "reg" / "S3" / rel,
    ):
        if cand.exists():
            bold_space_cord_mask = cand
            break

    # Resample anat into BOLD geometry once — both SyN (fixed image) and the
    # QC MI metric need them in the same grid. Without this, _compute_qc
    # falls through the anat.shape == mean.shape gate and reports
    # "MI not computed" on every run. flirt -applyxfm -usesqform uses the
    # sform/qform to compute the rigid mapping, then resamples (cheap).
    anat_in_bold: Optional[Path] = None
    if anat_path is not None and Path(anat_path).exists():
        bold_mean_ref = s5_work_dir / "bold_mean_ref.nii.gz"
        bimg = nib.load(bold_path)
        bdat = bimg.get_fdata()
        bmean = bdat.mean(axis=3) if bdat.ndim == 4 else bdat
        nib.save(nib.Nifti1Image(bmean.astype(np.float32), bimg.affine,
                                 bimg.header), bold_mean_ref)
        anat_resampled = s5_work_dir / "anat_in_bold.nii.gz"
        ok, _ = _run_command([
            "flirt",
            "-in", str(anat_path),
            "-ref", str(bold_mean_ref),
            "-applyxfm", "-usesqform",
            "-interp", "trilinear",
            "-out", str(anat_resampled),
        ])
        if ok and anat_resampled.exists():
            anat_in_bold = anat_resampled

    # Mode selection (orchestrator already passes filtered fmap_runs)
    from .mode import select_mode
    mode, eligible_fmaps = select_mode(bold_run, fmap_runs)

    # Dispatch
    if mode == "topup":
        modeinfo = _run_topup(
            bold_path=bold_path,
            fmap_runs=eligible_fmaps,
            bids_root=bids_root,
            bold_run=bold_run,
            work_dir=s5_work_dir,
            out_undistorted=out_undistorted,
            policy=policy,
        )
    elif mode == "fugue":
        modeinfo = _run_fugue()
        # Fall through to SyN on fugue not-implemented
        if modeinfo.get("status") != "OK":
            mode = "syn"

    if mode == "syn":
        if cord_mask_path is None or anat_path is None:
            return {
                "status": "FAIL",
                "mode": "syn",
                "step_code": step_code,
                "dataset_key": dataset_key,
                "subject": subject,
                "session": session,
                "run_id": run_id,
                "failure_message": "SyN mode requires cord_mask + anat_path",
                "failure_reasons": ["missing inputs for SyN"],
                "reportlets": {},
            }
        modeinfo = _run_syn(
            bold_path=bold_path,
            anat_path=anat_path,
            cord_mask_path=cord_mask_path,
            work_dir=s5_work_dir,
            out_undistorted=out_undistorted,
            policy=policy,
            bold_space_cord_mask=bold_space_cord_mask,
            anat_in_bold=anat_in_bold,
        )

    if modeinfo.get("status") != "OK":
        return {
            "status": "FAIL",
            "mode": mode,
            "step_code": step_code,
            "dataset_key": dataset_key,
            "subject": subject,
            "session": session,
            "run_id": run_id,
            "failure_message": modeinfo.get("failure_message"),
            "failure_reasons": [modeinfo.get("failure_message", "unknown")],
            "reportlets": {},
        }

    # QC metrics. Use anat_in_bold so MI compares matched-geometry volumes;
    # fall back to anat_path only as a defensive last resort (which will
    # short-circuit inside _compute_qc on the shape check, as before).
    qc_anat = anat_in_bold if anat_in_bold is not None else anat_path
    metrics = _compute_qc(bold_path, out_undistorted, qc_anat)

    # CoSpine-style geometric effectiveness metrics (cord-Dice + per-slice
    # A–P cord-centerline displacement). cord_mask_path is anat-space
    # cord_dseg from S2 — we resample it to BOLD voxel grid inside
    # `_compute_cospine_metrics`. The bold_mean_ref we already built
    # above (used by the MI path) is reused as the FLIRT reference.
    bold_mean_ref_path: Optional[Path] = None
    if anat_in_bold is not None:
        bold_mean_ref_path = s5_work_dir / "bold_mean_ref.nii.gz"
        if not bold_mean_ref_path.exists():
            bold_mean_ref_path = None
    cospine = _compute_cospine_metrics(
        bold_before=bold_path,
        bold_after=out_undistorted,
        anat_cord_mask_path=cord_mask_path,
        bold_mean_ref=bold_mean_ref_path,
        work_dir=s5_work_dir / "cospine",
    )
    metrics.update(cospine)

    thresholds = policy.get("qc_thresholds", {})
    status, reasons = _classify_run_status(metrics, mode, thresholds)

    # Save funcref (temporal mean) for downstream chain consumers
    mean_path = func_dir / f"{prefix}_desc-undistorted_funcref.nii.gz"
    img = nib.load(out_undistorted)
    data = img.get_fdata()
    mean = data.mean(axis=3) if data.ndim == 4 else data
    nib.save(nib.Nifti1Image(mean.astype(np.float32), img.affine, img.header), mean_path)

    # Render reportlets (PNG figures) — CoSpine recipe (Sci Data 2025):
    # per-slice A–P displacement + per-slice 2D cord-Dice. Replaces the
    # earlier qualitative axial montage + MI bar.
    figures_dir = func_dir.parent / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    from .reportlets import (
        render_s5_cord_dice_per_slice,
        render_s5_slice_displacement,
    )

    disp_path = figures_dir / f"{prefix}_desc-S5_slice_displacement.png"
    dice_path = figures_dir / f"{prefix}_desc-S5_cord_dice_per_slice.png"
    try:
        render_s5_slice_displacement(metrics, disp_path, mode)
    except Exception as e:
        # Don't fail the whole run on a viz hiccup; status still reflects metrics
        reasons.append(f"slice_displacement render failed: {e}")
    try:
        render_s5_cord_dice_per_slice(metrics, dice_path, mode)
    except Exception as e:
        reasons.append(f"cord_dice_per_slice render failed: {e}")

    # qc.json reportlet paths must be RELATIVE to out_dir (HEADER convention)
    reportlets = {
        "slice_displacement": str(disp_path.relative_to(out_dir)),
        "cord_dice_per_slice": str(dice_path.relative_to(out_dir)),
    }

    qc_metrics_path = s5_work_dir / "qc_metrics.json"
    s5_work_dir.mkdir(parents=True, exist_ok=True)
    qc_metrics_path.write_text(json.dumps({
        "mode": mode,
        "metrics": metrics,
        "failure_reasons": reasons,
        "mode_info": {k: v for k, v in modeinfo.items() if k != "status"},
    }, indent=2, default=str))

    return {
        "status": status,
        "mode": mode,
        "step_code": step_code,
        "dataset_key": dataset_key,
        "subject": subject,
        "session": session,
        "run_id": run_id,
        "metrics": metrics,
        "failure_reasons": reasons,
        "failure_message": "; ".join(reasons) if reasons else None,
        "reportlets": reportlets,
        "distortion_correction_mode": mode,
    }
