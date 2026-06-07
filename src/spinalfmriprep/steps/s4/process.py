"""S4 per-run motion correction processing.

Implements the main ``run_S4_func_motion_correction`` function that
orchestrates preflight, coarse correction, slice-wise correction,
metrics computation, and reportlet generation for a single functional run.
"""

import json
import shutil
import logging
import subprocess

import numpy as np
import pandas as pd
import nibabel as nib
from pathlib import Path
from typing import Optional, Dict, Any

from spinalfmriprep.lib import moco

logger = logging.getLogger(__name__)


def run_S4_func_motion_correction(
    s3_run_dir: Path,
    policy: dict,
    out_dir: Path,
    work_dir: Path,
    dataset_key: str,
) -> Dict[str, Any]:
    """
    S4: Cord-aware motion correction.

    Orchestrates:
    1. Preflight checks.
    2. Stage 1: Coarse Bulk XY Correction (2DOF).
    3. Stage 2: Slice-wise Correction (sct_fmri_moco).
    4. Metrics & Reportlets.
    5. QC JSON generation.

    Args:
        s3_run_dir: Path to the S3 run output directory containing
                    funccrop_bold.nii.gz, func_ref.nii.gz, funccrop_mask.nii.gz
    """

    # -------------------------------------------------------------------------
    # S4.0: Preflight & Inputs
    # -------------------------------------------------------------------------
    step_code = "S4_func_motion_correction"
    run_name = s3_run_dir.name  # e.g. "sub-02_task-motorL" or "sub-02_ses-01_task-handgrasp"
    logger.info(f"[{step_code}] Starting for {run_name}")

    # --- Resolve S3 input files (generic names in S3 run dir) ---
    bold_crop_path = s3_run_dir / "funccrop_bold.nii.gz"
    robust_ref_path = s3_run_dir / "func_ref.nii.gz"
    crop_mask_path = s3_run_dir / "funccrop_mask.nii.gz"

    if not bold_crop_path.exists():
        logger.error(f"Missing S3 input: {bold_crop_path}")
        return {"status": "FAIL", "reason": f"Missing S3 input: {bold_crop_path}"}
    if not robust_ref_path.exists():
        logger.error(f"Missing S3 input: {robust_ref_path}")
        return {"status": "FAIL", "reason": f"Missing S3 input: {robust_ref_path}"}

    # Parse BIDS entities from run directory name
    parts = run_name.split("_")
    subject = parts[0] if parts[0].startswith("sub-") else None
    session = None
    run_entity = None  # the BIDS run-XX token only (used to decide is_run1)
    for p in parts[1:]:
        if p.startswith("ses-"):
            session = p
        if p.startswith("run-"):
            run_entity = p

    # run_id stored in qc.json must equal the work-dir name so downstream
    # consumers (mark_done, --reportlets-only, dashboards) can locate the
    # run's artifacts. S3 follows the same convention. Earlier S4 stored
    # only the BIDS run token (e.g. "run-01"), which silently broke
    # reportlets-only because work/<step>/run-01 doesn't exist - the real
    # dir is work/<step>/sub-02_task-..._run-01.
    run_id = run_name

    # Use the run_name as a filename prefix for output BIDS naming
    prefix = run_name

    # Moco mask: must be in the SAME space as the cropped BOLD input passed to
    # sct_fmri_moco. The non-cropped S3.1 discovery seg (func_ref_fast_seg)
    # has the FULL EPI dims (e.g. 128x128x12); using it silently produces zero
    # slice-wise shifts because the SCT-internal mask resample collapses to a
    # near-empty mask. Prefer the cropped variant; then funccrop_mask; never
    # the uncropped seg.
    cord_seg_path_cropped = s3_run_dir / "init" / "localize" / "func_ref_fast_seg_crop.nii.gz"
    cord_seg_path = s3_run_dir / "init" / "localize" / "func_ref_fast_seg.nii.gz"
    if cord_seg_path_cropped.exists():
        moco_mask_path = cord_seg_path_cropped
    elif crop_mask_path.exists():
        moco_mask_path = crop_mask_path
    else:
        # Last resort - the uncropped seg. Will warn downstream if shape
        # doesn't match the BOLD.
        moco_mask_path = cord_seg_path

    # Work and Output setup
    s4_work_dir = work_dir / step_code / run_name
    s4_work_dir.mkdir(parents=True, exist_ok=True)

    # Output paths (BIDS derivatives structure)
    if session:
        func_dir = out_dir / "derivatives" / "spinalfmriprep" / subject / session / "func"
    else:
        func_dir = out_dir / "derivatives" / "spinalfmriprep" / subject / "func"
    func_dir.mkdir(parents=True, exist_ok=True)

    # Mode from policy
    mode = policy.get("motion_correction", {}).get("mode", "3d+2d")

    # -------------------------------------------------------------------------
    # S4.1: Optional Inter-run Z-shift Detection & Correction
    # -------------------------------------------------------------------------
    z_shift_detected_mm = 0.0
    z_shift_slices = 0
    z_shift_corrected = False

    # Only applicable if this run has a run entity and is not the first run.
    # run_entity is the BIDS run-XX token only (or None for single-run datasets).
    is_run1 = (
        run_entity is None
        or run_entity == "run-1"
        or run_entity == "run-01"
    )

    correction_enabled = policy.get("motion_correction", {}).get("z_shift_correction", {}).get("enabled", False)
    threshold_mm = policy.get("motion_correction", {}).get("z_shift_correction", {}).get("threshold_mm", 2.0)

    current_bold_path = bold_crop_path

    # Find run-1 reference from sibling S3 run directories
    run1_ref_path = None
    if not is_run1:
        s3_runs_parent = s3_run_dir.parent
        for sibling in sorted(s3_runs_parent.iterdir()):
            if sibling == s3_run_dir or not sibling.is_dir():
                continue
            # Match same subject (and session if present), with run-1 or run-01
            if subject and sibling.name.startswith(subject):
                if session and session not in sibling.name:
                    continue
                if "_run-01" in sibling.name or "_run-1_" in sibling.name or sibling.name.endswith("_run-1"):
                    candidate = sibling / "func_ref.nii.gz"
                    if candidate.exists():
                        run1_ref_path = candidate
                        break

    if run1_ref_path and not is_run1:
        logger.info(f"[{step_code}] Checking Z-shift relative to {run1_ref_path.name}")

        # Determine slice thickness from header
        img_current_ref = nib.load(robust_ref_path)
        slice_thickness = img_current_ref.header.get_zooms()[2]

        # Compute shift
        shift_mm, shift_slices = moco.detect_z_shift(
            img_current_ref.get_fdata(),
            nib.load(run1_ref_path).get_fdata(),
            slice_thickness_mm=float(slice_thickness)
        )
        z_shift_detected_mm = shift_mm
        z_shift_slices = shift_slices

        if abs(shift_mm) > threshold_mm:
            logger.warning(f"[{step_code}] Large Z-shift detected: {shift_mm:.2f}mm ({shift_slices} slices)")

            if correction_enabled:
                logger.info(f"[{step_code}] Applying Z-shift correction...")
                # Apply to BOLD
                bold_img = nib.load(current_bold_path)
                corrected_bold_data = moco.apply_z_shift_correction(bold_img.get_fdata(), shift_slices)

                # Save as new intermediate
                z_corrected_path = s4_work_dir / "bold_z_corrected.nii.gz"
                nib.save(nib.Nifti1Image(corrected_bold_data, bold_img.affine, bold_img.header), z_corrected_path)
                current_bold_path = z_corrected_path
                z_shift_corrected = True

                # Also correct the reference
                ref_img = nib.load(robust_ref_path)
                corrected_ref_data = moco.apply_z_shift_correction(ref_img.get_fdata()[..., np.newaxis], shift_slices)
                corrected_ref_data = corrected_ref_data[..., 0]

                z_corrected_ref_path = s4_work_dir / "ref_z_corrected.nii.gz"
                nib.save(nib.Nifti1Image(corrected_ref_data, ref_img.affine, ref_img.header), z_corrected_ref_path)
                robust_ref_path = z_corrected_ref_path  # Point subsequent stages to corrected ref

    # -------------------------------------------------------------------------
    # S4.2: Stage 1 - Coarse Bulk XY Correction
    # -------------------------------------------------------------------------
    # Outputs of Stage 1
    stage1_bold_path = s4_work_dir / "bold_coarse.nii.gz"
    stage1_params_path = s4_work_dir / "moco_params_coarse.tsv"

    if "3d" in mode:
        logger.info(f"[{step_code}] Running Stage 1: Coarse Bulk XY")

        # Load data (use current_bold_path which might be Z-corrected)
        bold_img = nib.load(current_bold_path)
        ref_img = nib.load(robust_ref_path)

        bold_data = bold_img.get_fdata()
        ref_data = ref_img.get_fdata()

        # Run correction
        corrected_data, params_df = moco.coarse_bulk_xy_correction(
            bold_data,
            ref_data,
            work_dir=s4_work_dir,
            upsample_factor=policy["motion_correction"]["stage1_coarse"].get("upsample_factor", 10),
            interpolation_order=policy["motion_correction"]["stage1_coarse"].get("interpolation_order", 1)
        )

        # Save Stage 1 output
        stage1_img = nib.Nifti1Image(corrected_data, bold_img.affine, bold_img.header)
        nib.save(stage1_img, stage1_bold_path)

        params_df.to_csv(stage1_params_path, sep="\t", index=False)

        current_bold_path = stage1_bold_path
    else:
        # Skip Stage 1
        pass

    # -------------------------------------------------------------------------
    # S4.3: Stage 2 - Slice-wise Correction (sct_fmri_moco)
    # -------------------------------------------------------------------------
    stage2_bold_path = func_dir / f"{prefix}_desc-mocoref_bold.nii.gz"
    stage2_params_path = func_dir / f"{prefix}_moco_params.tsv"

    if "2d" in mode:
        logger.info(f"[{step_code}] Running Stage 2: sct_fmri_moco")

        sct_input_path = s4_work_dir / "sct_input.nii.gz"
        if sct_input_path.exists(): sct_input_path.unlink()
        sct_input_path.symlink_to(current_bold_path.resolve())

        sct_mask_path = s4_work_dir / "sct_mask.nii.gz"
        if sct_mask_path.exists(): sct_mask_path.unlink()
        sct_mask_path.symlink_to(moco_mask_path.resolve())

        # Defensive: mask must share the in-plane dims with the input BOLD or
        # sct_fmri_moco silently returns all-zero shifts. Fail loudly instead.
        try:
            _bold_shape = nib.load(current_bold_path).shape[:3]
            _mask_shape = nib.load(moco_mask_path).shape[:3]
            if _bold_shape != _mask_shape:
                msg = (f"Moco mask shape {_mask_shape} != BOLD shape {_bold_shape}. "
                       f"sct_fmri_moco would emit zero shifts. Mask file: {moco_mask_path}")
                logger.error(msg)
                return {"status": "FAIL", "reason": msg}
        except Exception as _e:
            logger.warning(f"Could not validate moco mask shape: {_e}")

        sct_ref_path = s4_work_dir / "sct_ref.nii.gz"
        if sct_ref_path.exists(): sct_ref_path.unlink()
        sct_ref_path.symlink_to(robust_ref_path.resolve())

        # Policy params from "stage2_slicereg"
        poly_order = policy["motion_correction"]["stage2_slicereg"].get("poly_order", 2)
        metric = policy["motion_correction"]["stage2_slicereg"].get("metric", "MeanSquares")
        iter_count = policy["motion_correction"]["stage2_slicereg"].get("iterations", 10)

        cmd = [
            "sct_fmri_moco",
            "-i", str(sct_input_path),
            "-m", str(sct_mask_path),
            "-param", f"poly={poly_order},metric={metric},iter={iter_count}",
            "-x", "spline",
            "-v", "0"  # Quiet
        ]

        logger.info(f"Executing: {' '.join(cmd)}")
        result = subprocess.run(cmd, cwd=s4_work_dir, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error(f"sct_fmri_moco failed: {result.stderr}")
            return {"status": "FAIL", "reason": "sct_fmri_moco failed"}

        sct_output_bold = s4_work_dir / "sct_input_moco.nii.gz"

        shutil.move(str(sct_output_bold), str(stage2_bold_path))

        sct_tsv = s4_work_dir / "moco_params.tsv"
        if sct_tsv.exists():
            shutil.copy(str(sct_tsv), str(stage2_params_path))

        final_bold_path = stage2_bold_path

    else:
        # No 2D stage
        final_bold_path = current_bold_path
        if final_bold_path != stage2_bold_path:
             shutil.copy(str(final_bold_path), str(stage2_bold_path))

    # -------------------------------------------------------------------------
    # S4.4: Metrics & Reportlets
    # -------------------------------------------------------------------------
    logger.info(f"[{step_code}] Computing metrics")

    # Load Before/After
    img_before = nib.load(bold_crop_path)
    img_after = nib.load(stage2_bold_path)
    after_data = img_after.get_fdata()
    mask = np.mean(after_data, axis=-1) > 0

    # Compute Metrics
    dvars = moco.compute_dvars(after_data, mask)

    tsnr_map_before, tsnr_mean_before = moco.compute_tsnr(img_before.get_fdata(), mask)
    tsnr_map_after, tsnr_mean_after = moco.compute_tsnr(img_after.get_fdata(), mask)

    # Save tSNR maps
    tsnr_before_path = s4_work_dir / "tsnr_before.nii.gz"
    tsnr_after_path = s4_work_dir / "tsnr_after.nii.gz"
    nib.save(nib.Nifti1Image(tsnr_map_before, img_before.affine), tsnr_before_path)
    nib.save(nib.Nifti1Image(tsnr_map_after, img_after.affine), tsnr_after_path)

    # FD and Motion Params
    params_total = pd.DataFrame()
    if stage1_params_path.exists():
        p1 = pd.read_csv(stage1_params_path, sep="\t")
        params_total['tx'] = p1.get('tx_coarse', 0.0)
        params_total['ty'] = p1.get('ty_coarse', 0.0)
    else:
        params_total['tx'] = np.zeros(img_after.shape[3])
        params_total['ty'] = np.zeros(img_after.shape[3])

    # Stage-2 slicewise contribution. SCT writes signed per-volume slicewise
    # translations as 4D NIfTI fields (moco_params_x/_y.nii.gz, shape
    # (1,1,n_slices,n_vol)) in the moco cwd (s4_work_dir); the sidecar
    # moco_params.tsv only has a single unsigned magnitude column
    # `mean(sqrt(X^2+Y^2))` (NOT 'X'/'Y' — the old `if 'X' in p2.columns` guard
    # was always false, silently dropping Stage-2 from FD). Mean over space per
    # volume (same reduction S8 uses) and add to the Stage-1 bulk so FD reflects
    # bulk + slicewise total motion. See BUG-1, meeting-2026-05-29-task-audit.
    moco_x_path = s4_work_dir / "moco_params_x.nii.gz"
    moco_y_path = s4_work_dir / "moco_params_y.nii.gz"
    if moco_x_path.exists() and moco_y_path.exists():
        mx = nib.load(moco_x_path).get_fdata()
        my = nib.load(moco_y_path).get_fdata()
        if mx.ndim == 4 and mx.shape[-1] == len(params_total):
            params_total['tx'] += mx.mean(axis=(0, 1, 2))
            params_total['ty'] += my.mean(axis=(0, 1, 2))
        else:
            logger.warning(
                f"[{step_code}] SCT moco_params_x/y shape {mx.shape} incompatible "
                f"with {len(params_total)} volumes; FD reflects bulk stage only"
            )
    elif "2d" in mode:
        logger.warning(
            f"[{step_code}] SCT moco_params_x/_y.nii.gz not found in {s4_work_dir}; "
            f"FD reflects bulk stage only"
        )

    # Compute FD
    fd = moco.compute_framewise_displacement(params_total)

    # High Motion Frames
    fd_threshold = policy["qc_thresholds"].get("fd_threshold_mm", 0.5)
    high_motion_mask = fd > fd_threshold
    high_motion_count = int(np.sum(high_motion_mask))
    high_motion_fraction = high_motion_count / len(fd)

    # Metrics Summary
    qc_metrics = {
        "z_shift_detected_mm": z_shift_detected_mm,
        "z_shift_corrected": z_shift_corrected,
        "max_fd_mm": float(np.max(fd)),
        "mean_fd_mm": float(np.mean(fd)),
        "high_motion_frame_count": high_motion_count,
        "high_motion_fraction": high_motion_fraction,
        "tsnr_before_mean": tsnr_mean_before,
        "tsnr_after_mean": tsnr_mean_after,
        "tsnr_improvement_pct": float((tsnr_mean_after - tsnr_mean_before) / tsnr_mean_before * 100) if tsnr_mean_before > 0 else 0.0,
        "dvars_mean": float(np.mean(dvars)),
        "dvars_max": float(np.max(dvars))
    }

    # -------------------------------------------------------------------------
    # QC Reportlets (Using viz_s4)
    # -------------------------------------------------------------------------
    if session:
        figures_dir = out_dir / "derivatives" / "spinalfmriprep" / subject / session / "figures"
    else:
        figures_dir = out_dir / "derivatives" / "spinalfmriprep" / subject / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"[{step_code}] Generating reportlets in {figures_dir}")
    from spinalfmriprep.lib import viz_s4

    # 1. Motion Traces
    viz_s4.render_motion_traces(
        params_total,
        fd_threshold=fd_threshold,
        output_path=figures_dir / f"{prefix}_desc-S4_motion_traces.png",
        figsize=tuple(policy["qc"]["motion_traces"]["figsize"]),
        dpi=policy["qc"]["motion_traces"]["dpi"],
        colors=policy["qc"]["motion_traces"]["colors"]
    )

    # 2. tSNR Comparison
    zooms = img_before.header.get_zooms()
    viz_s4.render_tsnr_comparison(
        tsnr_map_before,
        tsnr_map_after,
        mask,
        zooms=zooms[:3],
        output_path=figures_dir / f"{prefix}_desc-S4_tsnr_comparison.png",
        colormap=policy["qc"]["tsnr_comparison"]["colormap"]
    )

    # 3. DVARS Plot
    viz_s4.render_dvars_plot(
        dvars,
        threshold=policy["outlier_gating"]["metrics"]["dvars"]["threshold"] if "outlier_gating" in policy else 0.5,
        output_path=figures_dir / f"{prefix}_desc-S4_dvars_plot.png"
    )

    # The S4 moco-comparison reportlet was removed: an audit showed motion is
    # sub-voxel in 10/11 reg runs, so neither a sagittal GIF nor an axial
    # PNG/GIF can convey the correction visibly. tSNR before/after carries
    # the moco-quality story; motion_traces + DVARS cover the diagnostic.

    # -------------------------------------------------------------------------
    # S4.5: Write QC JSON
    # -------------------------------------------------------------------------
    # Determine Status
    status = "PASS"
    failure_reasons = []

    # Check thresholds
    if qc_metrics["max_fd_mm"] > policy["qc_thresholds"]["max_fd_mm"]:
        status = "FAIL"
        failure_reasons.append(f"Max FD {qc_metrics['max_fd_mm']:.2f} > {policy['qc_thresholds']['max_fd_mm']}")
    elif qc_metrics["max_fd_mm"] > policy["qc_thresholds"]["warn_fd_mm"]:
        status = "WARN"
        failure_reasons.append("High Max FD")

    if qc_metrics["tsnr_after_mean"] < policy["qc_thresholds"]["min_tsnr"]:
        status = "FAIL"
        failure_reasons.append(f"tSNR {qc_metrics['tsnr_after_mean']:.2f} < {policy['qc_thresholds']['min_tsnr']}")

    qc_status = {
        "status": status,
        "step_code": step_code,
        "dataset_key": dataset_key,
        "subject": subject,
        "session": session,
        "run_id": run_id,
        "metrics": qc_metrics,
        "failure_reasons": failure_reasons,
        "reportlets": {
            # Store paths RELATIVE to out_dir so the dashboard can resolve them
            # in chain workfolders (S2/S3 already follow this convention).
            "S4_motion_traces": str((figures_dir / f"{prefix}_desc-S4_motion_traces.png").relative_to(out_dir)),
            "S4_tsnr_comparison": str((figures_dir / f"{prefix}_desc-S4_tsnr_comparison.png").relative_to(out_dir)),
            "S4_dvars_plot": str((figures_dir / f"{prefix}_desc-S4_dvars_plot.png").relative_to(out_dir)),
        }
    }

    return qc_status
