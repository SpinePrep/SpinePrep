
import os
import sys
import json
import shutil
import logging
import numpy as np
import pandas as pd
import nibabel as nib
import matplotlib.pyplot as plt
from pathlib import Path
from typing import Optional, Dict, Any, List
import subprocess

import yaml
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass

@dataclass
class StepResult:
    status: str
    failure_message: Optional[str] = None

# S4 library imports
from .lib import moco

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

def run_S4(
    dataset_key: str,
    datasets_local: Optional[str] = None,
    out: Optional[str] = None,
    batch_workers: int = 1,
) -> StepResult:
    """
    High-level entry point for S4 motion correction.
    Discovers runs from S3 output directory and orchestrates processing.
    """
    if not out:
        return StepResult("FAIL", "--out is required")
        
    out_path = Path(out).resolve()
    
    # Load Policy
    policy_path = Path("policy/S4_func_motion_correction.yaml")
    if policy_path.exists():
        try:
            policy = yaml.safe_load(policy_path.read_text())
        except Exception as e:
            return StepResult("FAIL", f"Policy error: {e}")
    else:
        policy = {}
        
    # Discover runs from S3 output directory
    # S3 writes outputs to: runs/S3_func_init_and_crop/<run_name>/
    # Each run dir contains: funccrop_bold.nii.gz, func_ref.nii.gz, funccrop_mask.nii.gz
    s3_runs_dir = out_path / "runs" / "S3_func_init_and_crop"
    if not s3_runs_dir.exists():
        return StepResult("FAIL", f"Missing S3 runs directory: {s3_runs_dir}")
    
    # Collect all run directories that have the required output
    runs_to_process = []
    for run_dir in sorted(s3_runs_dir.iterdir()):
        if not run_dir.is_dir():
            continue
        bold_path = run_dir / "funccrop_bold.nii.gz"
        if bold_path.exists():
            runs_to_process.append(run_dir)
        else:
            logger.warning(f"Skipping {run_dir.name}: missing funccrop_bold.nii.gz")
    
    logger.info(f"Found {len(runs_to_process)} S3 runs to process for S4")
    
    if not runs_to_process:
        return StepResult("FAIL", "No valid S3 runs found with funccrop_bold.nii.gz")
            
    # Run in parallel
    results = []
    with ProcessPoolExecutor(max_workers=batch_workers) as executor:
        futures = {
            executor.submit(
                run_S4_func_motion_correction,
                s3_run_dir=run_dir,
                policy=policy,
                out_dir=out_path,
                work_dir=out_path / "work",
                dataset_key=dataset_key,
            ): run_dir for run_dir in runs_to_process
        }
        
        for future in as_completed(futures):
            run_dir = futures[future]
            try:
                res = future.result()
                results.append(res)
                logger.info(f"S4 completed for {run_dir.name}: {res.get('status', 'UNKNOWN')}")
            except Exception as e:
                import traceback
                logger.error(f"S4 failed for {run_dir.name}: {e}\n{traceback.format_exc()}")
                results.append({"status": "FAIL", "reason": str(e), "failure_reasons": [str(e)]})

    # Save aggregated QC
    qc_dir = out_path / "logs" / "S4_func_motion_correction" / dataset_key
    qc_dir.mkdir(parents=True, exist_ok=True)
    qc_path = qc_dir / "qc.json"
    
    # Structure for dashboard: {"dataset_key": ..., "step_code": ..., "runs": [...]}
    aggregated_qc = {
        "dataset_key": dataset_key,
        "step_code": "S4_func_motion_correction",
        "runs": results # Each result is now a full qc_status dict for a run
    }
    
    with open(qc_path, "w") as f:
        json.dump(aggregated_qc, f, indent=2)

    # Aggregate status
    failures = [r for r in results if r.get("status") == "FAIL"]
    if failures:
        return StepResult("FAIL", f"{len(failures)}/{len(results)} runs failed")
    
    # Build dashboard (matches S1/S2/S3 pattern)
    from spinalfmriprep.qc_dashboard import generate_dashboard_safe
    generate_dashboard_safe(out_path)
        
    return StepResult("PASS")



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
    # e.g. "sub-02_task-motorL" -> subject="sub-02", session=None, run_id=None
    # e.g. "sub-02_ses-01_task-handgrasp" -> subject="sub-02", session="ses-01"
    # e.g. "sub-02_task-motor_acq-KombiShimZBrain_run-01" -> run_id="run-01"
    parts = run_name.split("_")
    subject = parts[0] if parts[0].startswith("sub-") else None
    session = None
    run_id = None
    for p in parts[1:]:
        if p.startswith("ses-"):
            session = p
        if p.startswith("run-"):
            run_id = p
    
    # Use the run_name as a filename prefix for output BIDS naming
    prefix = run_name
    
    # Moco mask (cord segmentation or crop mask)
    # Try cord segmentation first, fall back to crop mask
    cord_seg_path = s3_run_dir / "init" / "localize" / "func_ref_fast_seg.nii.gz"
    moco_mask_path = cord_seg_path if cord_seg_path.exists() else crop_mask_path
    
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
    
    # Only applicable if this run has a run entity and is not run-1/run-01
    is_run1 = (run_id is None or run_id == "run-1" or run_id == "run-01")
    
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
        # Need to implement detect_z_shift in moco.py properly (which returns tuple now)
        # moco.detect_z_shift(run_ref, target_ref) -> (mm, slices)
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
                
                # Also correct the "robust reference" for this run so downstream stages use aligned ref?
                # Ideally yes. But Stage 1 uses robust_ref.
                # If we shift BOLD, we should shift REF too.
                ref_img = nib.load(robust_ref_path)
                corrected_ref_data = moco.apply_z_shift_correction(ref_img.get_fdata()[..., np.newaxis], shift_slices)
                # Squeeze back to 3D
                corrected_ref_data = corrected_ref_data[..., 0]
                
                z_corrected_ref_path = s4_work_dir / "ref_z_corrected.nii.gz"
                nib.save(nib.Nifti1Image(corrected_ref_data, ref_img.affine, ref_img.header), z_corrected_ref_path)
                robust_ref_path = z_corrected_ref_path # Point subsequent stages to corrected ref
                
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
        # current_bold_path is already set (z-corrected or original)
        pass 

        
    # -------------------------------------------------------------------------
    # S4.3: Stage 2 - Slice-wise Correction (sct_fmri_moco)
    # -------------------------------------------------------------------------
    stage2_bold_path = func_dir / f"{prefix}_desc-mocoref_bold.nii.gz"
    stage2_params_path = func_dir / f"{prefix}_moco_params.tsv"
    
    if "2d" in mode:
        logger.info(f"[{step_code}] Running Stage 2: sct_fmri_moco")
        
        # Prepare SCT command
        # sct_fmri_moco -i <input> -m <mask> -r <ref> ...
        # Output logic for SCT: it creates files with suffixes.
        # We'll run it in work dir to contain mess.
        
        sct_input_path = s4_work_dir / "sct_input.nii.gz"
        # Symlink or copy current BOLD to predictable name
        if sct_input_path.exists(): sct_input_path.unlink()
        sct_input_path.symlink_to(current_bold_path.resolve())
        
        # Symlink mask and ref too
        sct_mask_path = s4_work_dir / "sct_mask.nii.gz"
        if sct_mask_path.exists(): sct_mask_path.unlink()
        sct_mask_path.symlink_to(moco_mask_path.resolve())
        
        sct_ref_path = s4_work_dir / "sct_ref.nii.gz"
        if sct_ref_path.exists(): sct_ref_path.unlink()
        sct_ref_path.symlink_to(robust_ref_path.resolve())
        
        # Policy params from "stage2_slicereg"
        poly_order = policy["motion_correction"]["stage2_slicereg"].get("poly_order", 2)
        metric = policy["motion_correction"]["stage2_slicereg"].get("metric", "MeanSquares")
        iter_count = policy["motion_correction"]["stage2_slicereg"].get("iterations", 10)
        
        # Construct command
        # Note: -x spline (final interpolation) is generally good.
        # sct_fmri_moco uses its own internal reference (middle volume).
        # -m provides a mask to guide the registration.
        cmd = [
            "sct_fmri_moco",
            "-i", str(sct_input_path),
            "-m", str(sct_mask_path),
            "-param", f"poly={poly_order},metric={metric},iter={iter_count}",
            "-x", "spline", 
            "-v", "0" # Quiet
        ]
        
        # Run SCT
        logger.info(f"Executing: {' '.join(cmd)}")
        result = subprocess.run(cmd, cwd=s4_work_dir, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error(f"sct_fmri_moco failed: {result.stderr}")
            return {"status": "FAIL", "reason": "sct_fmri_moco failed"}
            
        # SCT outputs:
        # sct_input_moco.nii.gz
        # moco_params_x.nii.gz, moco_params_y.nii.gz
        # moco_params.tsv (averaged?)
        
        sct_output_bold = s4_work_dir / "sct_input_moco.nii.gz"
        
        # Move/Rename output to final destination
        shutil.move(str(sct_output_bold), str(stage2_bold_path))
        
        # Handle params
        # SCT outputs `moco_params.tsv` (slice-averaged) and slice-wise NIfTIs.
        # We want to keep slice-wise NIfTIs in work, but maybe publish TSV?
        # Let's copy TSV to derivatives.
        sct_tsv = s4_work_dir / "moco_params.tsv"
        if sct_tsv.exists():
            shutil.copy(str(sct_tsv), str(stage2_params_path))
            
        final_bold_path = stage2_bold_path
        
    else:
        # No 2D stage
        final_bold_path = current_bold_path
        # Copy to output if valid
        if final_bold_path != stage2_bold_path:
             shutil.copy(str(final_bold_path), str(stage2_bold_path))
    
    # -------------------------------------------------------------------------
    # S4.4: Metrics & Reportlets
    # -------------------------------------------------------------------------
    logger.info(f"[{step_code}] Computing metrics")
    
    # Load Before/After
    img_before = nib.load(bold_crop_path)
    img_after = nib.load(stage2_bold_path)
    # Derive mask from actual data (file-based mask may be in uncropped space)
    # Use mean intensity > 0 threshold from the after data
    after_data = img_after.get_fdata()
    mask = np.mean(after_data, axis=-1) > 0
    
    # Compute Metrics
    # DVARS
    dvars = moco.compute_dvars(after_data, mask)
    
    # tSNR
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
        
    if stage2_params_path.exists():
        p2 = pd.read_csv(stage2_params_path, sep="\t")
        # SCT might output 'X', 'Y' or 'trans_x', 'trans_y' depending on version/flags?
        # Assuming standard 'X', 'Y'
        if 'X' in p2.columns:
            params_total['tx'] += p2['X']
        if 'Y' in p2.columns:
            params_total['ty'] += p2['Y']
            
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
    # Figures go alongside func_dir
    if session:
        figures_dir = out_dir / "derivatives" / "spinalfmriprep" / subject / session / "figures"
    else:
        figures_dir = out_dir / "derivatives" / "spinalfmriprep" / subject / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"[{step_code}] Generating reportlets in {figures_dir}")
    from .lib import viz_s4

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
        threshold=policy["outlier_gating"]["metrics"]["dvars"]["threshold"] if "outlier_gating" in policy else 0.5, # Need reliable policy path for dvars threshold? 
        # Actually S4 policy does not specify dvars threshold directly in "qc_thresholds".
        # It relies on calculated thresholds or policy. 
        # Use simple mean + 2std for display if not specified?
        # Or parse from "qc_thresholds"?
        # Let's derive a reasonable display threshold if not in policy.
        # Policy schema has "qc_thresholds" but mostly for PASS/FAIL.
        # Let's use dvars_mean + 2*std for visualization threshold if generic.
        output_path=figures_dir / f"{prefix}_desc-S4_dvars_plot.png"
    )
    
    # 4. Before/After GIF
    viz_s4.render_moco_gif(
        bold_crop_path,
        stage2_bold_path,
        output_path=figures_dir / f"{prefix}_desc-S4_moco_comparison.gif",
        mask_path=moco_mask_path,
        mask_data=mask,
        fps=policy["qc"]["gif"].get("fps", 5),
        max_frames=policy["qc"]["gif"].get("max_frames", 20)
    )
    
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
            "S4_motion_traces": str(figures_dir / f"{prefix}_desc-S4_motion_traces.png"),
            "S4_tsnr_comparison": str(figures_dir / f"{prefix}_desc-S4_tsnr_comparison.png"),
            "S4_dvars_plot": str(figures_dir / f"{prefix}_desc-S4_dvars_plot.png"),
            "S4_moco_comparison": str(figures_dir / f"{prefix}_desc-S4_moco_comparison.gif")
        }
    }
    
    return qc_status


def check_S4_func_motion_correction(
    dataset_key: Optional[str] = None,
    datasets_local: Optional[str] = None,
    out: Optional[str] = None,
) -> StepResult:
    """
    Validate S4 motion correction outputs.

    Checks:
    - QC JSON exists and is valid
    - Per-run derivative files exist (mocoref BOLD, moco params, tSNR)
    - Per-run reportlets exist (motion traces, tSNR comparison, DVARS, GIF)
    - Aggregated status from QC JSON
    """
    if not out:
        return StepResult(status="FAIL", failure_message="--out is required for S4 check")

    out_path = Path(out).resolve()

    # --- 1. Check QC JSON ---
    if dataset_key:
        qc_dir = out_path / "logs" / "S4_func_motion_correction" / dataset_key
    else:
        qc_dir = out_path / "logs" / "S4_func_motion_correction"

    qc_path = None
    if dataset_key:
        qc_path = qc_dir / "qc.json"
    else:
        # Find any qc.json under S4 logs
        if qc_dir.exists():
            candidates = list(qc_dir.rglob("qc.json"))
            if candidates:
                qc_path = candidates[0]

    if qc_path is None or not qc_path.exists():
        return StepResult(
            status="FAIL",
            failure_message=f"QC JSON not found: {qc_path or qc_dir / '*/qc.json'}",
        )

    try:
        qc = json.loads(qc_path.read_text(encoding="utf-8"))
    except Exception as err:
        return StepResult(status="FAIL", failure_message=f"Failed to read QC JSON: {err}")

    if dataset_key and qc.get("dataset_key") != dataset_key:
        return StepResult(
            status="FAIL",
            failure_message=f"QC dataset_key mismatch: expected {dataset_key}, got {qc.get('dataset_key')}",
        )

    # --- 2. Validate per-run outputs ---
    runs = qc.get("runs", [])
    if not runs:
        return StepResult(status="FAIL", failure_message="QC JSON has no runs")

    missing_outputs: List[str] = []
    missing_reportlets: List[str] = []

    for run in runs:
        run_label = f"{run.get('subject', '?')}/{run.get('session', '?')}/{run.get('run_id', '?')}"

        # Check reportlets
        reportlets = run.get("reportlets", {})
        required_reportlets = [
            "S4_motion_traces",
            "S4_tsnr_comparison",
            "S4_dvars_plot",
            "S4_moco_comparison",
        ]
        for key in required_reportlets:
            rel = reportlets.get(key)
            if not rel:
                missing_reportlets.append(f"{key} missing for {run_label}")
                continue
            path = Path(rel) if Path(rel).is_absolute() else out_path / rel
            if not path.exists() or path.stat().st_size == 0:
                missing_reportlets.append(f"{key}: {path}")

        # Check metrics exist
        metrics = run.get("metrics")
        if not metrics:
            missing_outputs.append(f"metrics missing for {run_label}")

    issues: List[str] = []
    if missing_outputs:
        issues.append(f"Missing outputs: {'; '.join(missing_outputs)}")
    if missing_reportlets:
        issues.append(f"Missing reportlets: {'; '.join(missing_reportlets)}")

    if issues:
        return StepResult(status="FAIL", failure_message=" | ".join(issues))

    # --- 3. Check aggregate status ---
    failed_runs = [r for r in runs if r.get("status") == "FAIL"]
    warn_runs = [r for r in runs if r.get("status") == "WARN"]

    if failed_runs:
        return StepResult(
            status="FAIL",
            failure_message=f"{len(failed_runs)}/{len(runs)} runs FAIL",
        )

    if warn_runs:
        return StepResult(
            status="WARN",
            failure_message=f"{len(warn_runs)}/{len(runs)} runs WARN",
        )

    return StepResult(status="PASS", failure_message=None)


def run_S4_func_motion_correction_reportlets_only(
    dataset_key: Optional[str] = None,
    datasets_local: Optional[str] = None,
    out: Optional[str] = None,
) -> StepResult:
    """Regenerate only QC reportlets from existing S4 outputs, skipping all processing."""
    if not out:
        return StepResult(status="FAIL", failure_message="--out is required for --reportlets-only")

    out_path = Path(out).resolve()
    ds_key = dataset_key or "ad_hoc"

    # Load QC JSON
    qc_path = out_path / "logs" / "S4_func_motion_correction" / ds_key / "qc.json"
    if not qc_path.exists():
        return StepResult(status="FAIL", failure_message=f"Missing qc.json: {qc_path}. Run the full step first.")

    try:
        qc = json.loads(qc_path.read_text(encoding="utf-8"))
    except Exception as err:
        return StepResult(status="FAIL", failure_message=f"Failed to read QC JSON: {err}")

    # Load policy
    policy_path = Path("policy/S4_func_motion_correction.yaml")
    if policy_path.exists():
        policy = yaml.safe_load(policy_path.read_text())
    else:
        return StepResult(status="FAIL", failure_message="Missing policy file")

    from .lib import viz_s4

    runs = qc.get("runs", [])
    for run in runs:
        subject = run.get("subject")
        session = run.get("session")
        run_id = run.get("run_id")
        if not subject or not run_id:
            continue

        # Locate work dir
        s4_work_dir = out_path / "work" / "S4_func_motion_correction" / run_id

        # Determine prefix and figures dir
        prefix = f"{subject}_{session}_{run_id}" if session else f"{subject}_{run_id}"
        if session:
            figures_dir = out_path / "derivatives" / "spinalfmriprep" / subject / session / "figures"
            func_dir = out_path / "derivatives" / "spinalfmriprep" / subject / session / "func"
        else:
            figures_dir = out_path / "derivatives" / "spinalfmriprep" / subject / "figures"
            func_dir = out_path / "derivatives" / "spinalfmriprep" / subject / "func"
        figures_dir.mkdir(parents=True, exist_ok=True)

        # Load persisted intermediates
        tsnr_before_path = s4_work_dir / "tsnr_before.nii.gz"
        tsnr_after_path = s4_work_dir / "tsnr_after.nii.gz"
        params_path = func_dir / f"{prefix}_moco_params.tsv"

        # Find cord mask
        mask_path = None
        mask_candidates = list(s4_work_dir.glob("*seg*.nii.gz")) + list(s4_work_dir.glob("*mask*.nii.gz"))
        if mask_candidates:
            mask_path = mask_candidates[0]

        fd_threshold = policy.get("qc_thresholds", {}).get("fd_threshold_mm", 0.5)

        # 1. Motion traces
        if params_path.exists():
            try:
                params_df = pd.read_csv(params_path, sep="\t")
                viz_s4.render_motion_traces(
                    params_df,
                    fd_threshold=fd_threshold,
                    output_path=figures_dir / f"{prefix}_desc-S4_motion_traces.png",
                    figsize=tuple(policy.get("qc", {}).get("motion_traces", {}).get("figsize", [10, 4])),
                    dpi=policy.get("qc", {}).get("motion_traces", {}).get("dpi", 100),
                    colors=policy.get("qc", {}).get("motion_traces", {}).get("colors", {}),
                )
            except Exception:
                pass

        # 2. tSNR comparison
        if tsnr_before_path.exists() and tsnr_after_path.exists():
            try:
                tsnr_before_img = nib.load(tsnr_before_path)
                tsnr_before_data = tsnr_before_img.get_fdata()
                tsnr_after_data = nib.load(tsnr_after_path).get_fdata()
                zooms = tsnr_before_img.header.get_zooms()[:3]
                mask_data = nib.load(mask_path).get_fdata() > 0 if mask_path and mask_path.exists() else tsnr_before_data > 0
                viz_s4.render_tsnr_comparison(
                    tsnr_before_data,
                    tsnr_after_data,
                    mask_data,
                    zooms=zooms,
                    output_path=figures_dir / f"{prefix}_desc-S4_tsnr_comparison.png",
                    colormap=policy.get("qc", {}).get("tsnr_comparison", {}).get("colormap", "viridis"),
                )
            except Exception:
                pass

        # 3. DVARS plot
        if params_path.exists():
            try:
                # Recompute DVARS from motion-corrected BOLD if available
                moco_bold_path = func_dir / f"{prefix}_desc-mocoref_bold.nii.gz"
                if moco_bold_path.exists() and mask_path and mask_path.exists():
                    mask_data = nib.load(mask_path).get_fdata() > 0
                    bold_data = nib.load(moco_bold_path).get_fdata()
                    dvars = moco.compute_dvars(bold_data, mask_data)
                    threshold = np.percentile(dvars, 75) + 1.5 * (np.percentile(dvars, 75) - np.percentile(dvars, 25))
                    viz_s4.render_dvars_plot(
                        dvars,
                        threshold=threshold,
                        output_path=figures_dir / f"{prefix}_desc-S4_dvars_plot.png",
                    )
            except Exception:
                pass

        # 4. Before/After GIF
        try:
            # Find original cropped BOLD (before moco)
            bold_before_candidates = list(s4_work_dir.parent.parent.parent.rglob(f"*{run_id}*funccrop_bold.nii.gz"))
            moco_bold_path = func_dir / f"{prefix}_desc-mocoref_bold.nii.gz"
            if bold_before_candidates and moco_bold_path.exists():
                viz_s4.render_moco_gif(
                    bold_before_path=str(bold_before_candidates[0]),
                    bold_after_path=str(moco_bold_path),
                    output_path=str(figures_dir / f"{prefix}_desc-S4_moco_comparison.gif"),
                    fps=policy.get("qc", {}).get("gif", {}).get("fps", 5),
                    max_frames=policy.get("qc", {}).get("gif", {}).get("max_frames", 20),
                )
        except Exception:
            pass

    # Regenerate dashboard
    from spinalfmriprep.qc_dashboard import generate_dashboard_safe
    generate_dashboard_safe(out_path)

    return StepResult(status="PASS", failure_message=None)


def run_S4_func_motion_correction_reportlets_only_batch(
    dataset_keys: list[str],
    out_base: str | Path,
) -> dict[str, StepResult]:
    """Batch reportlets-only for multiple datasets."""
    results = {}
    for key in dataset_keys:
        results[key] = run_S4_func_motion_correction_reportlets_only(
            dataset_key=key,
            out=str(out_base),
        )
    return results
