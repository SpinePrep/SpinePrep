"""Motion metrics: FD (Power) and DVARS computation."""

from __future__ import annotations

import numpy as np


def compute_fd_power(motion_params: np.ndarray, radius_mm: float = 50.0) -> np.ndarray:
    """
    Compute framewise displacement using Power et al. 2012 method.

    FD = sum of absolute translational displacements +
         sum of absolute rotational displacements (converted to mm using radius)

    Args:
        motion_params: Array of shape (n_timepoints, 6) with columns:
                       trans_x, trans_y, trans_z (mm), rot_x, rot_y, rot_z (radians)
        radius_mm: Head/body radius for rotation-to-displacement conversion (default 50mm)

    Returns:
        FD array of shape (n_timepoints,) in float32, with FD[0] = 0

    References:
        Power JD et al. (2012). Spurious but systematic correlations in functional
        connectivity MRI networks arise from subject motion. NeuroImage 59:2142-2154.
    """
    if motion_params.shape[1] != 6:
        raise ValueError(
            f"Expected 6 motion parameters (3 trans + 3 rot), got {motion_params.shape[1]}"
        )

    n_timepoints = motion_params.shape[0]
    fd = np.zeros(n_timepoints, dtype=np.float32)

    if n_timepoints < 2:
        return fd

    # Compute temporal differences
    delta = np.diff(motion_params, axis=0).astype(np.float32)

    # FD = sum of absolute translations + radius * sum of absolute rotations
    # Power method: summation of absolute values
    trans_sum = np.sum(np.abs(delta[:, :3]), axis=1)
    rot_sum = np.sum(np.abs(delta[:, 3:6]), axis=1)

    fd_vals = trans_sum + radius_mm * rot_sum

    # First timepoint has FD=0, rest have computed values
    fd[1:] = fd_vals.astype(np.float32)

    return fd


def compute_dvars(img_4d: np.ndarray, mask: np.ndarray | None = None) -> np.ndarray:
    """
    Compute DVARS (temporal derivative RMS over masked voxels).

    DVARS = sqrt(mean(voxelwise squared differences)) within mask

    Args:
        img_4d: 4D array of shape (x, y, z, t) in float32 or float64
        mask: Optional 3D boolean mask. If None, uses voxels above median of first volume

    Returns:
        DVARS array of shape (t,) in float32, with DVARS[0] = 0

    References:
        Power JD et al. (2012). Spurious but systematic correlations in functional
        connectivity MRI networks arise from subject motion. NeuroImage 59:2142-2154.
    """
    if len(img_4d.shape) != 4:
        raise ValueError(f"Expected 4D image data, got {len(img_4d.shape)}D")

    n_timepoints = img_4d.shape[3]
    dvars = np.zeros(n_timepoints, dtype=np.float32)

    if n_timepoints < 2:
        return dvars

    # Create mask if not provided
    if mask is None:
        first_vol = img_4d[:, :, :, 0]
        threshold = np.median(first_vol)
        mask = first_vol > threshold

    # Ensure mask is boolean
    mask = mask.astype(bool)

    # Validate mask has voxels
    n_voxels = mask.sum()
    if n_voxels == 0:
        return dvars

    # Compute temporal differences
    delta_4d = np.diff(img_4d, axis=3).astype(np.float32)

    # Compute DVARS for each timepoint
    for t in range(n_timepoints - 1):
        delta_vol = delta_4d[:, :, :, t]
        masked_vals = delta_vol[mask]

        # RMS within mask (robust to NaNs)
        masked_vals = masked_vals[~np.isnan(masked_vals)]
        if len(masked_vals) > 0:
            dvars[t + 1] = np.sqrt(np.mean(masked_vals**2))
        else:
            dvars[t + 1] = 0.0

    return dvars.astype(np.float32)
