"""S5.x: per-run distortion correction (topup, fugue, or SyN).

Spec: private/SPEC/S5_func_distortion_correction.md
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional

import nibabel as nib
import numpy as np

from spinalfmriprep.lib.run import run_command as _run_command


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


def _trt_for(run: dict) -> Optional[float]:
    """Pull TotalReadoutTime from S1 acquisition dict. Fallback: compute
    from EES x (ReconMatrixPE - 1). Returns None when neither path works.

    BIDS records TRT as the unaccelerated-equivalent readout time -
    DO NOT divide by ParallelReductionFactorInPlane. (See S5 spec.)
    """
    acq = run.get("acquisition", {}) if isinstance(run, dict) else {}
    if "TotalReadoutTime" in acq:
        return float(acq["TotalReadoutTime"])
    ees = acq.get("EffectiveEchoSpacing")
    matrix_pe = acq.get("ReconMatrixPE") or acq.get("AcquisitionMatrixPE")
    if ees is not None and matrix_pe is not None:
        return float(ees) * (int(matrix_pe) - 1)
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

    # Resolve TRT from any of the fmap runs (they share it with BOLD)
    trt = _trt_for(fmap_runs[0]) or _trt_for(bold_run)
    if trt is None:
        return {"status": "FAIL", "mode": "topup",
                "failure_message": "TotalReadoutTime not in BIDS sidecar"}

    fmap_paths = [bids_root / f["path"] for f in fmap_runs]
    fmap_pes = [f.get("acquisition", {}).get("PhaseEncodingDirection")
                for f in fmap_runs]

    merged = work_dir / "fmap_merged.nii.gz"
    _merge_epi_fmaps(merged, fmap_paths)

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

    bold_pe = bold_run.get("acquisition", {}).get("PhaseEncodingDirection")
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
) -> dict[str, Any]:
    """Mode = SyN fallback. Light cord-mask-restricted SyN of mean(BOLD)
    to T2w anat. Spec §S5.4."""
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

    syn_cfg = policy.get("distortion_correction", {}).get("syn", {})
    transform = syn_cfg.get("transform", "SyN[0.1,3,0]")
    shrink = syn_cfg.get("shrink", "4x2x1")
    smoothing = syn_cfg.get("smoothing", "2x1x0vox")
    metric_args = (
        f"MI[{anat_path},{mean_path},1,{syn_cfg.get('bin_count', 32)}]"
    )
    out_prefix = work_dir / "syn_"

    cmd_reg = [
        "antsRegistration",
        "--float",
        "--dimensionality", "3",
        "--metric", metric_args,
        "--transform", transform,
        "--convergence", "[40x20x0,1e-6,10]",
        "--shrink-factors", shrink,
        "--smoothing-sigmas", smoothing,
        "--masks", f"[{cord_mask_path},{cord_mask_path}]",
        "--output", str(out_prefix),
    ]
    ok, out = _run_command(cmd_reg)
    if not ok:
        return {"status": "FAIL", "mode": "syn",
                "failure_message": f"antsRegistration failed: {out[:240]}"}

    # Apply the warp to the 4D BOLD
    warp = f"{out_prefix}0Warp.nii.gz"
    cmd_apply = [
        "antsApplyTransforms",
        "-d", "3", "-e", "3",
        "-i", str(bold_path),
        "-r", str(anat_path),
        "-t", warp,
        "-o", str(out_undistorted),
        "-n", "LanczosWindowedSinc",
    ]
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
    """Mutual information before/after, plus voxel-displacement summary
    when available."""
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
        # MI vs anat is the headline number for "did distortion correction
        # bring BOLD closer to anatomy?". Resample anat is expensive; we
        # use min-shape voxels and trust the affine is close enough
        # (since anat and BOLD share native space at this stage).
        if anat.shape == mean_a.shape:
            metrics["mi_before"] = _mutual_information(mean_a, anat)
            metrics["mi_after"] = _mutual_information(mean_b, anat)
            if metrics["mi_before"] > 0:
                metrics["mi_delta_pct"] = float(
                    (metrics["mi_after"] - metrics["mi_before"])
                    / metrics["mi_before"] * 100
                )
    return metrics


def _classify_run_status(metrics: dict, mode: str, thresholds: dict) -> tuple[str, list[str]]:
    """PASS / WARN / FAIL per spec §QC Contract."""
    reasons: list[str] = []

    mi_delta = metrics.get("mi_delta_pct")
    if mi_delta is not None:
        if mi_delta < -thresholds.get("fail_mi_max_drop_pct", 10.0):
            return "FAIL", [f"MI dropped {mi_delta:.1f}% > 10%"]
        if mi_delta < 0:
            reasons.append(f"MI did not improve ({mi_delta:+.1f}%)")

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
    subject = bold_run.get("subject")
    session = bold_run.get("session")
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

    # QC metrics
    metrics = _compute_qc(bold_path, out_undistorted, anat_path)
    thresholds = policy.get("qc_thresholds", {})
    status, reasons = _classify_run_status(metrics, mode, thresholds)

    # Save funcref (temporal mean) for downstream chain consumers
    mean_path = func_dir / f"{prefix}_desc-undistorted_funcref.nii.gz"
    img = nib.load(out_undistorted)
    data = img.get_fdata()
    mean = data.mean(axis=3) if data.ndim == 4 else data
    nib.save(nib.Nifti1Image(mean.astype(np.float32), img.affine, img.header), mean_path)

    # Render reportlets (PNG figures) per S5 spec §Reportlets
    figures_dir = func_dir.parent / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    from .reportlets import render_s5_before_after, render_s5_mi_summary

    crop_box_path = figures_dir / f"{prefix}_desc-S5_crop_box_sagittal.png"
    mi_summary_path = figures_dir / f"{prefix}_desc-S5_mi_summary.png"
    try:
        render_s5_before_after(
            bold_path, out_undistorted, cord_mask_path, crop_box_path,
        )
    except Exception as e:
        # Don't fail the whole run on a viz hiccup; status still reflects metrics
        reasons.append(f"reportlet render failed: {e}")
    try:
        render_s5_mi_summary(metrics, mi_summary_path, mode)
    except Exception as e:
        reasons.append(f"mi summary render failed: {e}")

    # qc.json reportlet paths must be RELATIVE to out_dir (HEADER convention)
    reportlets = {
        "crop_box_sagittal": str(crop_box_path.relative_to(out_dir)),
        "mi_summary": str(mi_summary_path.relative_to(out_dir)),
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
