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

from spineprep.lib import moco

logger = logging.getLogger(__name__)


def _select_moco_mask(s3_run_dir: Path, crop_mask_path: Path) -> Path:
    """Choose the mask handed to sct_fmri_moco -m.

    Must be in the SAME space as the cropped BOLD, or sct_fmri_moco's internal
    mask resample collapses to near-empty and it silently returns zero shifts
    (the bug that produced 0/223 corrected frames on wf_reg_035). Prefer the
    cropped S3.1 discovery seg; then funccrop_mask; never the uncropped seg
    unless nothing else exists.
    """
    cord_seg_path_cropped = (
        s3_run_dir / "init" / "localize" / "func_ref_fast_seg_crop.nii.gz"
    )
    cord_seg_path = s3_run_dir / "init" / "localize" / "func_ref_fast_seg.nii.gz"
    if cord_seg_path_cropped.exists():
        return cord_seg_path_cropped
    if crop_mask_path.exists():
        return crop_mask_path
    return cord_seg_path


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
    moco_mask_path = _select_moco_mask(s3_run_dir, crop_mask_path)

    # Work and Output setup
    s4_work_dir = work_dir / step_code / run_name
    s4_work_dir.mkdir(parents=True, exist_ok=True)

    # Output paths (BIDS derivatives structure)
    if session:
        func_dir = out_dir / "derivatives" / "spineprep" / subject / session / "func"
    else:
        func_dir = out_dir / "derivatives" / "spineprep" / subject / "func"
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
        cur_ref_data = img_current_ref.get_fdata()
        run1_ref_data = nib.load(run1_ref_path).get_fdata()

        # S3 crops each run to its OWN cord bounding box, so sibling-run
        # references routinely differ in-plane (e.g. (33,34,11) vs (33,33,11)).
        # Cross-run z-shift detection uses phase_cross_correlation, which raises
        # "images must be same shape" on a mismatch. Detection is observability-
        # only and z-shift correction is off by default, so skip (don't crash)
        # when the shapes differ.
        shift_mm, shift_slices = 0.0, 0
        if cur_ref_data.shape != run1_ref_data.shape:
            logger.warning(
                f"[{step_code}] Skipping Z-shift detection: ref shape "
                f"{cur_ref_data.shape} != run-01 ref {run1_ref_data.shape}")
        else:
            try:
                shift_mm, shift_slices = moco.detect_z_shift(
                    cur_ref_data, run1_ref_data,
                    slice_thickness_mm=float(slice_thickness),
                )
                z_shift_detected_mm = shift_mm
                z_shift_slices = shift_slices
            except Exception as _ze:
                logger.warning(f"[{step_code}] Z-shift detection failed: {_ze}")

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
    # S4.2: Stage 1 - Coarse Bulk XY (FLIRT 2-DOF on the Z-projection)
    # -------------------------------------------------------------------------
    # Outputs of Stage 1
    stage1_bold_path = s4_work_dir / "bold_coarse.nii.gz"
    stage1_params_path = s4_work_dir / "moco_params_coarse.tsv"

    if "3d" in mode:
        logger.info(f"[{step_code}] Running Stage 1: Coarse Bulk XY (FLIRT 2-DOF)")

        # Coarse in-plane X/Y bulk correction (FLIRT 2-DOF on the Z-projected
        # volume; sign-corrected per BUG-1c). NOTE: CoSpi's MCFLIRT 3D 6-DOF was
        # evaluated and REVERTED — the dev-cohort A/B showed it gives LOWER cord
        # tSNR than this 2-DOF approach on all 11 reg runs (MCFLIRT over-corrects
        # on the cord-cropped FOV). FLIRT-2DOF is the default. See ledger
        # meeting-2026-05-29-task-audit "S4 Stage-1 A/B".
        bold_img = nib.load(current_bold_path)
        ref_img = nib.load(robust_ref_path)
        corrected_data, params_df = moco.coarse_bulk_xy_correction(
            bold_img.get_fdata(),
            ref_img.get_fdata(),
            work_dir=s4_work_dir,
            interpolation_order=policy["motion_correction"]["stage1_coarse"].get("interpolation_order", 1),
        )
        nib.save(nib.Nifti1Image(corrected_data, bold_img.affine, bold_img.header), stage1_bold_path)
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

        # NOTE: sct_fmri_moco in SCT 7.1 (the pinned version) has NO
        # external-reference flag -- it builds its own target by iterative
        # averaging (iterAvg/num_target). The S3 robust reference therefore
        # governs only Stage 1 (FLIRT) and the tSNR comparison, never the
        # slice-wise stage. (SCT 7.2 added a -ref flag; wire it here when the
        # pinned version moves.) An earlier `sct_ref.nii.gz` symlink here was
        # dead code -- it was never passed to the command -- and is removed.

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

    # tSNR and DVARS are the step-local truth metric, so they must be measured
    # CORD-RESTRICTED, not over the whole cropped FOV. The field computes cord/
    # gray-matter tSNR inside the cord ROI (Kaptan 2023: voxel temporal mean /
    # temporal SD, averaged within the cord); the cropped FOV also contains the
    # pulsatile CSF ring, which deflates tSNR and makes a "cord" metric that is
    # not cord-specific. Use the same cord segmentation passed to sct_fmri_moco;
    # fall back to the nonzero-FOV mask only if the seg is missing or mis-shaped.
    mask = None
    try:
        seg_data = nib.load(moco_mask_path).get_fdata() > 0
        if seg_data.shape == after_data.shape[:3] and seg_data.any():
            mask = seg_data
    except Exception as _me:
        logger.warning(f"[{step_code}] Could not load cord mask for tSNR/DVARS: {_me}")
    if mask is None:
        logger.warning(
            f"[{step_code}] Falling back to nonzero-FOV mask for tSNR/DVARS "
            f"(cord seg unavailable or mis-shaped); metric is not cord-restricted"
        )
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

    # FD and Motion Params. Stage 1 (FLIRT 2-DOF) gives in-plane X/Y bulk
    # translations only; tz/rx/ry/rz are structurally zero for this cord-2D
    # engine (kept so any 6-column consumer still sees a full frame). The
    # cord FD used downstream is the 2-D |Δtx|+|Δty| (see lib/moco.py).
    params_total = pd.DataFrame()
    if stage1_params_path.exists():
        p1 = pd.read_csv(stage1_params_path, sep="\t")
        n = len(p1)
        params_total['tx'] = p1.get('tx_coarse', pd.Series(np.zeros(n)))
        params_total['ty'] = p1.get('ty_coarse', pd.Series(np.zeros(n)))
        params_total['tz'] = np.zeros(n)
        params_total['rx'] = np.zeros(n)
        params_total['ry'] = np.zeros(n)
        params_total['rz'] = np.zeros(n)
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
    slicewise_x = slicewise_y = None   # kept for the slicewise heatmap reportlet
    if moco_x_path.exists() and moco_y_path.exists():
        mx = nib.load(moco_x_path).get_fdata()
        my = nib.load(moco_y_path).get_fdata()
        if mx.ndim == 4 and mx.shape[-1] == len(params_total):
            slicewise_x, slicewise_y = mx, my
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

    # Compute FD by composing the two stages in MATCHED UNITS, per slice.
    # See moco.compose_cord_fd: Stage 1 is in voxels (FLIRT on identity-affine
    # temporaries), Stage 2 is in mm (ANTs warp); the old code summed them and
    # thresholded in mm, and averaged the SIGNED slice field so opposing slice
    # shifts cancelled. Both are fixed there.
    _zooms_bold = img_before.header.get_zooms()
    _axcodes = nib.orientations.aff2axcodes(img_before.affine)
    fd, fd_info = moco.compose_cord_fd(
        stage1_tx=params_total['tx'].values,
        stage1_ty=params_total['ty'].values,
        slicewise_x=slicewise_x,
        slicewise_y=slicewise_y,
        voxsize_x=float(_zooms_bold[0]),
        voxsize_y=float(_zooms_bold[1]),
        axcodes=_axcodes,
    )
    if fd_info.get("orientation_warning"):
        logger.warning(f"[{step_code}] {fd_info['orientation_warning']}")

    # The trace panel plots the two stages in mm. Stage 1 is scaled here so the
    # plotted series carries the same units as the FD beneath it.
    params_total['tx'] = params_total['tx'].values * float(_zooms_bold[0])
    params_total['ty'] = params_total['ty'].values * float(_zooms_bold[1])
    if slicewise_x is not None:
        params_total['tx_slicewise_mean'] = slicewise_x.reshape(
            -1, slicewise_x.shape[-1]).mean(axis=0)
        params_total['ty_slicewise_mean'] = slicewise_y.reshape(
            -1, slicewise_y.shape[-1]).mean(axis=0)

    # "High motion" is only definable against a threshold, and none ships (see
    # policy). With fd_threshold_mm null the flagged count/fraction are null
    # rather than computed against an invalid reference: a fraction-above-an-
    # invalid-threshold is a claim, and S10 used to publish it as a headline
    # "% high motion". The threshold-free statistics below describe the motion
    # without judging it. Setting fd_threshold_mm restores all of this.
    fd_threshold = policy["qc_thresholds"].get("fd_threshold_mm")
    if fd_threshold is None:
        high_motion_count = None
        high_motion_fraction = None
    else:
        high_motion_count = int(np.sum(fd > fd_threshold))
        high_motion_fraction = high_motion_count / len(fd)

    # Metrics Summary
    qc_metrics = {
        "z_shift_detected_mm": z_shift_detected_mm,
        "z_shift_corrected": z_shift_corrected,
        "max_fd_mm": float(np.max(fd)),
        "mean_fd_mm": float(np.mean(fd)),
        "median_fd_mm": float(np.median(fd)),
        "p95_fd_mm": float(np.percentile(fd, 95)),
        "high_motion_frame_count": high_motion_count,
        "high_motion_fraction": high_motion_fraction,
        "tsnr_before_mean": tsnr_mean_before,
        "tsnr_after_mean": tsnr_mean_after,
        "tsnr_improvement_pct": float((tsnr_mean_after - tsnr_mean_before) / tsnr_mean_before * 100) if tsnr_mean_before > 0 else 0.0,
        "dvars_mean": float(np.mean(dvars)),
        "dvars_max": float(np.max(dvars)),
        # How FD was composed (units, slice reduction, orientation). Recorded so
        # a reader can tell whether a run predates the 2026-07-16 unit fix.
        "fd_composition": fd_info,
    }

    # -------------------------------------------------------------------------
    # QC Reportlets (Using viz_s4)
    # -------------------------------------------------------------------------
    if session:
        figures_dir = out_dir / "derivatives" / "spineprep" / subject / session / "figures"
    else:
        figures_dir = out_dir / "derivatives" / "spineprep" / subject / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"[{step_code}] Generating reportlets in {figures_dir}")
    from spineprep.lib import viz_s4

    # DVARS is a raw RMS intensity change on a run-specific scale, so a fixed
    # threshold (the old 0.5 default) is meaningless and flags every volume.
    # Use a Tukey upper fence (Q3 + 1.5*IQR), the same data-driven rule S8 uses.
    _q1, _q3 = np.percentile(dvars, [25, 75])
    dvars_threshold = float(_q3 + 1.5 * (_q3 - _q1))
    zooms = img_before.header.get_zooms()
    cord_z = np.where(mask.any(axis=(0, 1)))[0]
    cord_z_extent = (int(cord_z.min()), int(cord_z.max())) if cord_z.size else None

    # Figure 1 — trace panel: total X/Y motion + FD + DVARS (shared time axis)
    viz_s4.render_motion_traces(
        params_total, fd, dvars,
        fd_threshold=fd_threshold,
        dvars_threshold=dvars_threshold,
        output_path=figures_dir / f"{prefix}_desc-S4_motion_traces.png",
        dpi=policy["qc"]["motion_traces"]["dpi"],
    )

    # Figure 2 — slicewise heatmap (Stage-2 per-slice shift, signed mm). Only
    # emitted when the Stage-2 slicewise fields exist (2D stage ran).
    slicewise_rel = None
    if slicewise_x is not None and slicewise_y is not None:
        sw_path = figures_dir / f"{prefix}_desc-S4_slicewise_heatmap.png"
        viz_s4.render_slicewise_heatmap(
            slicewise_x, slicewise_y, output_path=sw_path,
            cord_z_extent=cord_z_extent, dpi=policy["qc"]["motion_traces"]["dpi"],
        )
        slicewise_rel = str(sw_path.relative_to(out_dir))

    # Figure 3 — tSNR before/after + per-slice cord-tSNR profile
    viz_s4.render_tsnr_comparison(
        tsnr_map_before, tsnr_map_after, mask,
        zooms=zooms[:3],
        output_path=figures_dir / f"{prefix}_desc-S4_tsnr_comparison.png",
        improvement_pct=qc_metrics["tsnr_improvement_pct"],
        colormap=policy["qc"]["tsnr_comparison"]["colormap"],
    )

    # -------------------------------------------------------------------------
    # S4.5: Write QC JSON
    # -------------------------------------------------------------------------
    # Determine Status
    status = "PASS"
    failure_reasons = []

    # S4 does NOT reject a run for MOTION (changed 2026-07-16; evidence in
    # .claude/specs/s4-fd-threshold.md). S4's job is motion CORRECTION, so the
    # gate asks whether the correction succeeded -- cord tSNR -- not whether the
    # subject moved. Motion magnitude is a property of the DATA. Censoring is
    # S8's job, on dVARS/refRMS at a within-run distributional rule, which is what
    # the cord field does (Kaptan 2023 never uses FD; it censors on dVARS/refRMS
    # at mean+2SD and uses the slice-wise translations as regressors) and is the
    # only metric here with a principled null (Afyouni & Nichols 2018).
    #
    # The old absolute FD gate flagged a MEDIAN 48% of frames while post-moco
    # residual DVARS is FLAT below 0.5 mm -- it discarded clean data -- and its
    # FAIL pattern tracked TR (1.55-3.26 s across the cohort), not motion.
    qt = policy["qc_thresholds"]
    frac = qc_metrics["high_motion_fraction"]

    # Optional operator levers; all null by default, so none of this runs. They
    # need fd_threshold_mm to be set, since `frac` is null without it.
    max_frac = qt.get("max_high_motion_fraction")
    warn_frac = qt.get("warn_high_motion_fraction")
    if frac is not None and max_frac is not None and frac > max_frac:
        status = "FAIL"
        failure_reasons.append(
            f"{frac:.0%} of frames exceed FD>{qt['fd_threshold_mm']}mm "
            f"(> {max_frac:.0%} usable-data floor; operator-set gate)")
    elif frac is not None and warn_frac is not None and frac > warn_frac:
        status = "WARN"
        failure_reasons.append(
            f"elevated motion: {frac:.0%} of frames over "
            f"FD>{qt['fd_threshold_mm']}mm (observability; not a rejection)")

    warn_fd = qt.get("warn_fd_mm")
    if warn_fd is not None and qc_metrics["max_fd_mm"] > warn_fd:
        if status == "PASS":
            status = "WARN"
        failure_reasons.append(
            f"motion/artifact spike: max FD {qc_metrics['max_fd_mm']:.2f}mm "
            f"(censored downstream, not a rejection)")

    # The real S4 failure mode: the correction made cord temporal stability WORSE.
    # Only meaningful now that tSNR is cord-restricted rather than whole-FOV.
    if qt.get("warn_tsnr_degraded", True) and qc_metrics["tsnr_improvement_pct"] < 0:
        if status == "PASS":
            status = "WARN"
        failure_reasons.append(
            f"motion correction reduced cord tSNR by "
            f"{abs(qc_metrics['tsnr_improvement_pct']):.1f}%")

    # tSNR floor: a technical failure of the correction, not a motion judgement.
    if qc_metrics["tsnr_after_mean"] < qt["min_tsnr"]:
        status = "FAIL"
        failure_reasons.append(f"tSNR {qc_metrics['tsnr_after_mean']:.2f} < {qt['min_tsnr']}")

    from spineprep.reportlets_common import resolve_reportlets
    _s4_reportlets, status = resolve_reportlets(
        {
            "S4_motion_traces": figures_dir / f"{prefix}_desc-S4_motion_traces.png",
            "S4_slicewise_heatmap": ((out_dir / slicewise_rel)
                                     if slicewise_rel else None),
            "S4_tsnr_comparison": figures_dir / f"{prefix}_desc-S4_tsnr_comparison.png",
        },
        out_dir, status, failure_reasons,
        required=("S4_motion_traces", "S4_tsnr_comparison"),
    )

    qc_status = {
        "status": status,
        "step_code": step_code,
        "dataset_key": dataset_key,
        "subject": subject,
        "session": session,
        "run_id": run_id,
        "metrics": qc_metrics,
        "failure_reasons": failure_reasons,
        # Paths are stored RELATIVE to out_dir so the dashboard can resolve them
        # in chain workfolders (S2/S3 follow the same convention). Recorded only
        # when the file exists: this dict was previously built unconditionally,
        # and S4's reportlet regeneration swallows render failures with a bare
        # `except Exception: pass`, so a failed render left qc.json naming PNGs
        # that were never written.
        "reportlets": _s4_reportlets,
    }

    return qc_status
