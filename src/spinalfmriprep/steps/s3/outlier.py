"""S3.2: DVARS/ref-RMS gating, robust reference."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Optional

import nibabel as nib
import numpy as np
import matplotlib.pyplot as plt

from spinalfmriprep.subtask import (
    should_exit_after_subtask,
    subtask,
    subtask_context,
)

from .io import _extract_subject_session_from_work_dir


@subtask("S3.2")
def _process_s3_2_outlier_gating(
    bold_data_path: Path,
    func_ref0_path: Path,
    cordmask_func_path: Path,
    work_dir: Path,
    policy: dict[str, Any],
) -> dict[str, Any]:
    """
    S3.2: Mask-aware outlier gating + robust reference.

    This function:
    1. Computes DVARS and ref-RMS per frame (within cord mask)
    2. Flags outliers using boxplot cutoff
    3. Computes robust func_ref from good frames
    4. Renders S3.2 figure

    Returns:
        Dictionary with outlier gating results.
    """
    metrics_dir = work_dir / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)

    # Define output paths
    func_ref_path = work_dir / "func_ref.nii.gz"
    frame_metrics_path = metrics_dir / "frame_metrics.tsv"
    outlier_mask_path = metrics_dir / "outlier_mask.json"

    # OPTIMIZATION: Skip heavy computation if outputs exist
    if func_ref_path.exists() and frame_metrics_path.exists() and outlier_mask_path.exists():
         try:
             with open(outlier_mask_path, "r") as f:
                 outlier_info = json.load(f)
             outlier_frac = outlier_info.get("outlier_fraction", 0.0)
         except Exception:
             outlier_frac = 0.0

         # Reconstruct figure path
         subject, session, out_root = _extract_subject_session_from_work_dir(work_dir)
         # Use work_dir name as run_id for unique per-run filenames
         run_id = work_dir.name if work_dir.name.startswith("sub-") else None
         figure_prefix = run_id if run_id else (f"sub-{subject}_ses-{session}" if session else f"sub-{subject}")
         if out_root:
             fig_path = out_root / "derivatives" / "spinalfmriprep" / f"sub-{subject}" / (f"ses-{session}" if session else "") / "figures" / f"{figure_prefix}_desc-S3_frame_metrics.png"
         else:
             fig_path = None

         return {
            "outlier_status": "PASS",
            "failure_message": None,
            "func_ref_path": func_ref_path,
            "frame_metrics_path": frame_metrics_path,
            "outlier_mask_path": outlier_mask_path,
            "outlier_fraction": outlier_frac,
            "figure_path": fig_path
         }

    # Load inputs
    bold_img = nib.load(bold_data_path)
    bold_data = bold_img.get_fdata()  # (X, Y, Z, T)

    ref0_img = nib.load(func_ref0_path)
    ref0_data = ref0_img.get_fdata()

    mask_img = nib.load(cordmask_func_path)
    mask_data = mask_img.get_fdata() > 0

    # Drop dummy volumes (must match S3.1)
    dummy_count = policy.get("dummy_volumes", {}).get("count", 4)
    if bold_data.ndim == 4 and bold_data.shape[3] > dummy_count:
        bold_data = bold_data[..., dummy_count:]
    else:
        # If already dropped or short, use as is (warn?)
        pass

    n_frames = bold_data.shape[3]

    # Compute Metrics within Mask
    # dvars: sum((vol_t - vol_t-1)^2) / N_mask
    dvars = np.zeros(n_frames)
    ref_rms = np.zeros(n_frames)

    # Ensure mask shape matches bold slice
    if mask_data.shape != bold_data.shape[:3]:
        return {
            "outlier_status": "FAIL",
            "failure_message": f"Shape mismatch: Mask {mask_data.shape} vs BOLD {bold_data.shape[:3]}"
        }

    mask_indices = np.where(mask_data)
    n_voxels = len(mask_indices[0])

    if n_voxels == 0:
        return {"outlier_status": "FAIL", "failure_message": "Cord mask is empty"}

    # Extract masked time series: (N_voxels, N_frames)
    bold_masked = bold_data[mask_indices]  # shape (N_voxels, N_frames)
    ref0_masked = ref0_data[mask_indices]  # shape (N_voxels,)

    # RefRMS
    diff_ref = (bold_masked.T - ref0_masked).T
    ref_rms = np.sqrt(np.mean(diff_ref ** 2, axis=0))

    # DVARS
    diff_temp = np.diff(bold_masked, axis=1)  # (N_voxels, N_frames-1)
    dvars_val = np.sqrt(np.mean(diff_temp ** 2, axis=0))
    dvars = np.insert(dvars_val, 0, 0)
    if len(dvars) > 1:
        dvars[0] = dvars[1]

    # Outlier Detection (Boxplot)
    def get_cutoff(values):
        p75 = np.percentile(values, 75)
        p25 = np.percentile(values, 25)
        iqr = p75 - p25
        return p75 + 1.5 * iqr

    dvars_thresh = get_cutoff(dvars)
    ref_rms_thresh = get_cutoff(ref_rms)

    outliers_dvars = dvars > dvars_thresh
    outliers_ref = ref_rms > ref_rms_thresh

    outliers_combined = outliers_dvars | outliers_ref
    n_outliers = int(np.sum(outliers_combined))
    outlier_frac = n_outliers / n_frames

    # Robust Reference
    good_indices = np.where(~outliers_combined)[0]

    if len(good_indices) < 2:
        robust_ref_data = np.median(bold_data, axis=3)
        robust_ref_indices = list(range(n_frames))
    else:
        robust_ref_data = np.median(bold_data[..., good_indices], axis=3)
        robust_ref_indices = good_indices.tolist()

    # Save Results
    func_ref_path = work_dir / "func_ref.nii.gz"
    nib.save(nib.Nifti1Image(robust_ref_data, bold_img.affine), func_ref_path)

    # Save Metrics
    frame_metrics_path = metrics_dir / "frame_metrics.tsv"
    with open(frame_metrics_path, "w", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(["frame", "dvars", "ref_rms", "outlier"])
        for i in range(n_frames):
            writer.writerow([i, dvars[i], ref_rms[i], int(outliers_combined[i])])

    # Save Outlier Mask (JSON)
    outlier_mask_info = {
        "total_frames": n_frames,
        "dummy_dropped": dummy_count,
        "outlier_count": n_outliers,
        "outlier_fraction": float(outlier_frac),
        "thresholds": {
            "dvars": float(dvars_thresh),
            "ref_rms": float(ref_rms_thresh)
        },
        "outlier_indices": np.where(outliers_combined)[0].tolist()
    }
    outlier_mask_path = metrics_dir / "outlier_mask.json"
    with open(outlier_mask_path, "w") as f:
        json.dump(outlier_mask_info, f, indent=2)

    # Render Plot
    subject, session, out_root = _extract_subject_session_from_work_dir(work_dir)
    run_id = work_dir.name if work_dir.name.startswith("sub-") else None
    if subject and out_root:
        if session:
            figures_dir = out_root / "derivatives" / "spinalfmriprep" / f"sub-{subject}" / f"ses-{session}" / "figures"
        else:
            figures_dir = out_root / "derivatives" / "spinalfmriprep" / f"sub-{subject}" / "figures"
        figure_prefix = run_id if run_id else (f"sub-{subject}_ses-{session}" if session else f"sub-{subject}")
        fig_name = f"{figure_prefix}_desc-S3_frame_metrics.png"
    else:
        figures_dir = work_dir.parent.parent / "derivatives" / "spinalfmriprep" / "sub-test" / "ses-none" / "figures"
        fig_name = "test_desc-S3_frame_metrics.png"

    figures_dir.mkdir(parents=True, exist_ok=True)
    figure_path = figures_dir / fig_name

    try:
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6), sharex=True)

        frames = np.arange(n_frames)

        # Plot DVARS
        ax1.plot(frames, dvars, label='DVARS', color='blue')
        ax1.axhline(dvars_thresh, color='red', linestyle='--', label='Threshold')
        out_idx = np.where(outliers_dvars)[0]
        ax1.scatter(out_idx, dvars[out_idx], color='red', marker='x')
        ax1.set_ylabel("DVARS")
        ax1.legend()
        ax1.grid(True, alpha=0.3)

        # Plot RefRMS
        ax2.plot(frames, ref_rms, label='RefRMS', color='green')
        ax2.axhline(ref_rms_thresh, color='red', linestyle='--', label='Threshold')
        out_idx_ref = np.where(outliers_ref)[0]
        ax2.scatter(out_idx_ref, ref_rms[out_idx_ref], color='red', marker='x')
        ax2.set_ylabel("RefRMS")
        ax2.set_xlabel("Frame (after dummy drop)")
        ax2.legend()
        ax2.grid(True, alpha=0.3)

        plt.tight_layout()
        plt.savefig(figure_path)
        plt.close(fig)
    except Exception as e:
        pass  # Failed to plot metrics

    result = {
        "outlier_status": "PASS",
        "failure_message": None,
        "func_ref_path": func_ref_path,
        "frame_metrics_path": frame_metrics_path,
        "outlier_mask_path": outlier_mask_path,
        "outlier_fraction": outlier_frac,
        "figure_path": figure_path
    }

    # Check if we should exit after S3.2
    if should_exit_after_subtask("S3.2"):
        return result

    return result
