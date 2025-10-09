"""Basic confounds: motion parameters, FD, DVARS, and spike detection."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np


def compute_fd_power(motion_params: np.ndarray, radius: float = 50.0) -> np.ndarray:
    """
    Compute framewise displacement using Power method.

    FD_t = |Δdx| + |Δdy| + |Δdz| + radius * (|Δα| + |Δβ| + |Δγ|)

    Args:
        motion_params: Array of shape (T, 6) with columns [tx, ty, tz, rx, ry, rz]
                      Translations in mm, rotations in radians
        radius: Head radius in mm (default: 50.0)

    Returns:
        FD array of length T, first volume is 0
    """
    if motion_params.shape[0] == 0:
        return np.array([])

    T = motion_params.shape[0]
    fd = np.zeros(T)

    # Compute differences
    diff = np.diff(motion_params, axis=0)

    # FD = sum of absolute translation diffs + radius * sum of absolute rotation diffs
    trans_disp = np.sum(np.abs(diff[:, :3]), axis=1)
    rot_disp = np.sum(np.abs(diff[:, 3:]), axis=1)

    fd[1:] = trans_disp + radius * rot_disp

    return fd


def compute_dvars(data_4d: np.ndarray) -> np.ndarray:
    """
    Compute DVARS (temporal derivative of RMS variance).

    Args:
        data_4d: 4D array of shape (X, Y, Z, T)

    Returns:
        DVARS array of length T, first volume is 0
    """
    if data_4d.ndim != 4:
        raise ValueError(f"Expected 4D data, got shape {data_4d.shape}")

    T = data_4d.shape[3]
    dvars = np.zeros(T)

    # Create implicit mask: voxels with finite values and non-zero variance
    # Compute variance across time for each voxel
    with np.errstate(invalid="ignore"):
        voxel_var = np.var(data_4d, axis=3)
        mask = np.isfinite(voxel_var) & (voxel_var > 0)

    if not np.any(mask):
        # No valid voxels, return zeros
        return dvars

    # Get masked data
    masked_data = data_4d[mask, :]  # Shape: (n_voxels, T)

    # Compute temporal derivative
    diff = np.diff(masked_data, axis=1)  # Shape: (n_voxels, T-1)

    # RMS across voxels for each timepoint
    dvars[1:] = np.sqrt(np.mean(diff**2, axis=0))

    return dvars


def detect_spikes(
    fd: np.ndarray, dvars: np.ndarray, fd_thr: float = 0.5, dvars_z: float = 2.5
) -> np.ndarray:
    """
    Detect spike volumes based on FD and DVARS thresholds.

    A volume is marked as spike if:
    - FD >= fd_thr, OR
    - Z-score of DVARS >= dvars_z

    Args:
        fd: Framewise displacement array (length T)
        dvars: DVARS array (length T)
        fd_thr: FD threshold in mm (default: 0.5)
        dvars_z: DVARS Z-score threshold (default: 2.5)

    Returns:
        Binary spike array (0/1) of length T
    """
    T = len(fd)
    spike = np.zeros(T, dtype=int)

    # FD threshold
    spike[fd >= fd_thr] = 1

    # DVARS Z-score threshold
    # Compute Z-score (exclude first volume which is always 0)
    if T > 1:
        dvars_nonzero = dvars[1:]
        if len(dvars_nonzero) > 0 and np.std(dvars_nonzero) > 0:
            dvars_mean = np.mean(dvars_nonzero)
            dvars_std = np.std(dvars_nonzero)
            z_scores = np.zeros(T)
            z_scores[1:] = (dvars[1:] - dvars_mean) / dvars_std
            spike[np.abs(z_scores) >= dvars_z] = 1

    # First volume always 0
    spike[0] = 0

    return spike


def write_confounds_tsv(
    out_path: Path | str, confounds_dict: dict[str, np.ndarray]
) -> None:
    """
    Write confounds to TSV file.

    Args:
        out_path: Output TSV path
        confounds_dict: Dict with keys matching column names
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Expected columns in exact order
    columns = [
        "trans_x",
        "trans_y",
        "trans_z",
        "rot_x",
        "rot_y",
        "rot_z",
        "fd_power",
        "dvars",
        "spike",
    ]

    # Get length
    T = len(confounds_dict.get("fd_power", []))

    # Write TSV
    with open(out_path, "w") as f:
        # Header
        f.write("\t".join(columns) + "\n")

        # Data rows
        for t in range(T):
            row_values = []
            for col in columns:
                val = confounds_dict.get(col, np.zeros(T))[t]
                if col == "spike":
                    row_values.append(f"{int(val)}")
                else:
                    row_values.append(f"{val:.6f}")
            f.write("\t".join(row_values) + "\n")


def write_sidecar_json(out_path: Path | str, metadata: dict) -> None:
    """
    Write confounds sidecar JSON.

    Args:
        out_path: Output JSON path
        metadata: Dict with method metadata
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with open(out_path, "w") as f:
        json.dump(metadata, f, indent=2)
