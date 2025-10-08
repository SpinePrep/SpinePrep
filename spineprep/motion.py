"""Motion metrics: FD and DVARS computation."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict

import matplotlib.pyplot as plt
import nibabel as nib
import numpy as np


def compute_fd(motion_params: np.ndarray, radius_mm: float = 50.0) -> np.ndarray:
    """
    Compute framewise displacement (Power et al.).

    Args:
        motion_params: Array of shape (n_timepoints, 6) with columns:
                       trans_x, trans_y, trans_z, rot_x, rot_y, rot_z
                       Translations in mm, rotations in radians.
        radius_mm: Head radius for rotation-to-displacement conversion (default 50mm).

    Returns:
        FD array of shape (n_timepoints,), with FD[0] = 0.
    """
    n_timepoints = motion_params.shape[0]
    fd = np.zeros(n_timepoints)

    if n_timepoints < 2:
        return fd

    # Compute temporal differences
    delta = np.diff(motion_params, axis=0)

    # FD = sum of absolute translations + radius * sum of absolute rotations
    fd_vals = np.sum(np.abs(delta[:, :3]), axis=1) + radius_mm * np.sum(
        np.abs(delta[:, 3:6]), axis=1
    )

    # First timepoint has FD=0, rest have computed values
    fd[1:] = fd_vals

    return fd


def compute_dvars(img_4d: np.ndarray, mask: np.ndarray | None = None) -> np.ndarray:
    """
    Compute DVARS (temporal derivative RMS over masked voxels).

    Args:
        img_4d: 4D array of shape (x, y, z, t)
        mask: Optional 3D boolean mask. If None, uses voxels above median of first volume.

    Returns:
        DVARS array of shape (t,), with DVARS[0] = 0.
    """
    n_timepoints = img_4d.shape[3]
    dvars = np.zeros(n_timepoints)

    if n_timepoints < 2:
        return dvars

    # Create mask if not provided
    if mask is None:
        first_vol = img_4d[:, :, :, 0]
        threshold = np.median(first_vol)
        mask = first_vol > threshold

    # Compute temporal differences
    delta_4d = np.diff(img_4d, axis=3)

    # Compute DVARS for each timepoint
    for t in range(n_timepoints - 1):
        delta_vol = delta_4d[:, :, :, t]
        masked_vals = delta_vol[mask]
        dvars[t + 1] = np.sqrt(np.mean(masked_vals**2))

    return dvars


def write_confounds_tsv(
    output_path: Path,
    motion_params: np.ndarray,
    fd: np.ndarray,
    dvars: np.ndarray,
) -> None:
    """
    Write confounds TSV with motion parameters, FD, and DVARS.

    Args:
        output_path: Path to output TSV file
        motion_params: Array of shape (n_timepoints, 6)
        fd: FD array
        dvars: DVARS array
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(
            ["trans_x", "trans_y", "trans_z", "rot_x", "rot_y", "rot_z", "fd", "dvars"]
        )
        for i in range(len(fd)):
            row = list(motion_params[i]) + [fd[i], dvars[i]]
            writer.writerow(row)


def plot_metric(values: np.ndarray, output_path: Path, title: str, ylabel: str) -> None:
    """
    Create a simple line plot for a motion metric.

    Args:
        values: 1D array of metric values
        output_path: Path to save PNG
        title: Plot title
        ylabel: Y-axis label
    """
    plt.figure(figsize=(8, 3))
    plt.plot(values, linewidth=1.5)
    plt.title(title)
    plt.xlabel("Timepoint")
    plt.ylabel(ylabel)
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, dpi=100)
    plt.close()


def process_run(
    nifti_path: Path,
    output_dir: Path,
    motion_params: np.ndarray | None = None,
) -> Dict[str, Path]:
    """
    Process a single functional run: compute FD/DVARS, write TSV and plots.

    Args:
        nifti_path: Path to functional NIfTI file
        output_dir: Output directory for derivatives
        motion_params: Optional pre-computed motion parameters (n_timepoints, 6).
                      If None, uses zeros (stub for real motion correction).

    Returns:
        Dictionary with paths to created files.
    """
    # Load 4D image
    img = nib.load(nifti_path)
    data_4d = img.get_fdata()
    n_timepoints = data_4d.shape[3]

    # Use provided motion params or zeros (stub)
    if motion_params is None:
        motion_params = np.zeros((n_timepoints, 6))

    # Compute metrics
    fd = compute_fd(motion_params)
    dvars = compute_dvars(data_4d)

    # Determine output paths (mirror BIDS structure in derivatives)
    rel_path = nifti_path.stem.replace(".nii", "")  # Remove .nii from .nii.gz
    confounds_tsv = output_dir / f"{rel_path}_desc-confounds_timeseries.tsv"
    fd_png = output_dir / f"{rel_path}_fd.png"
    dvars_png = output_dir / f"{rel_path}_dvars.png"

    # Write outputs
    write_confounds_tsv(confounds_tsv, motion_params, fd, dvars)
    plot_metric(fd, fd_png, "Framewise Displacement", "FD (mm)")
    plot_metric(dvars, dvars_png, "DVARS", "DVARS")

    return {
        "confounds_tsv": confounds_tsv,
        "fd_png": fd_png,
        "dvars_png": dvars_png,
    }


def process_from_manifest(manifest_path: Path, output_dir: Path) -> Dict[str, int]:
    """
    Process all functional runs from a manifest.

    Args:
        manifest_path: Path to manifest CSV
        output_dir: Output directory

    Returns:
        Dictionary with processing stats.
    """
    processed = 0
    with manifest_path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["modality"] == "func" and row["ext"] in {".nii.gz", ".nii"}:
                nifti_path = Path(row["path"])
                if nifti_path.exists():
                    process_run(nifti_path, output_dir)
                    processed += 1

    return {"processed": processed}
