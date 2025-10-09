"""CompCor: anatomical and temporal component extraction."""

from __future__ import annotations

import numpy as np


def extract_timeseries(
    img_4d: np.ndarray, mask: np.ndarray, standardize: bool = True
) -> np.ndarray:
    """
    Extract timeseries from 4D volume using a 3D mask.

    Args:
        img_4d: 4D array of shape (x, y, z, t)
        mask: 3D boolean mask of shape (x, y, z)
        standardize: Whether to demean and standardize each voxel's timeseries

    Returns:
        Timeseries array of shape (t, n_voxels) in float32
    """
    if img_4d.shape[:3] != mask.shape:
        raise ValueError(
            f"Image spatial dimensions {img_4d.shape[:3]} don't match mask {mask.shape}"
        )

    # Ensure mask is boolean
    mask = mask.astype(bool)

    n_voxels = mask.sum()
    if n_voxels == 0:
        raise ValueError("Mask contains no voxels")

    img_4d.shape[3]

    # Extract masked voxels: shape (n_voxels, t)
    masked_data = img_4d[mask].T  # Transpose to (t, n_voxels)

    # Convert to float32
    ts = masked_data.astype(np.float32)

    if standardize:
        # Demean each voxel
        ts = ts - ts.mean(axis=0)

        # Standardize (divide by std, avoid division by zero)
        std = ts.std(axis=0)
        std[std == 0] = 1.0
        ts = ts / std

    return ts


def fit_compcor(ts: np.ndarray, n_components: int) -> tuple[np.ndarray, np.ndarray]:
    """
    Fit CompCor using deterministic SVD-based PCA.

    Args:
        ts: Timeseries array of shape (n_timepoints, n_voxels)
        n_components: Number of principal components to extract

    Returns:
        Tuple of (components, variance_explained):
        - components: array of shape (n_timepoints, n_components) in float32
        - variance_explained: array of shape (n_components,) with variance ratios

    References:
        Behzadi Y et al. (2007). A component based noise correction method (CompCor)
        for BOLD and perfusion based fMRI. NeuroImage 37:90-101.
    """
    n_timepoints, n_voxels = ts.shape

    # Determine actual number of components we can extract
    # Limited by min(n_voxels, n_timepoints-1, n_components)
    max_components = min(n_voxels, n_timepoints - 1, n_components)

    if max_components <= 0:
        # Return empty arrays
        return (
            np.zeros((n_timepoints, 0), dtype=np.float32),
            np.array([], dtype=np.float32),
        )

    # Ensure consistent dtype
    ts = ts.astype(np.float32)

    # Center the data (demean each voxel)
    ts_centered = ts - ts.mean(axis=0)

    # Compute SVD: ts = U @ S @ Vt
    # U: (n_timepoints, n_timepoints)
    # S: (min(n_timepoints, n_voxels),)
    # Vt: (n_voxels, n_voxels)
    # We want principal components in time, so we use U
    U, S, Vt = np.linalg.svd(ts_centered, full_matrices=False)

    # Extract first n_components from U
    components = U[:, :max_components].astype(np.float32)

    # Compute variance explained by each component
    # Variance explained = (singular value)^2 / sum of squared singular values
    total_variance = np.sum(S**2)
    if total_variance > 0:
        variance_explained = (S[:max_components] ** 2) / total_variance
    else:
        variance_explained = np.zeros(max_components)

    variance_explained = variance_explained.astype(np.float32)

    # Enforce sign convention: first nonzero element of each component should be positive
    for i in range(max_components):
        comp = components[:, i]
        nonzero_idx = np.where(np.abs(comp) > 1e-10)[0]
        if len(nonzero_idx) > 0:
            if comp[nonzero_idx[0]] < 0:
                components[:, i] *= -1

    return components, variance_explained


def select_tcompcor_voxels(
    img_4d: np.ndarray, mask: np.ndarray, topk_percent: float = 2.0
) -> np.ndarray:
    """
    Select high-variance voxels for tCompCor.

    Args:
        img_4d: 4D array of shape (x, y, z, t)
        mask: 3D boolean mask of shape (x, y, z) defining search region
        topk_percent: Percentage of highest variance voxels to select (default 2.0)

    Returns:
        3D boolean mask of selected voxels
    """
    if img_4d.shape[:3] != mask.shape:
        raise ValueError(
            f"Image spatial dimensions {img_4d.shape[:3]} don't match mask {mask.shape}"
        )

    # Ensure mask is boolean
    mask = mask.astype(bool)

    n_voxels = mask.sum()
    if n_voxels == 0:
        raise ValueError("Mask contains no voxels")

    # Compute temporal variance for each voxel within mask
    variance_map = np.zeros(img_4d.shape[:3], dtype=np.float32)

    # Extract masked voxels and compute variance along time axis
    masked_data = img_4d[mask]  # Shape: (n_voxels, t)
    voxel_variances = np.var(masked_data, axis=1, dtype=np.float32)

    # Put variances back into spatial map
    variance_map[mask] = voxel_variances

    # Select top k% voxels by variance
    n_select = int(np.ceil(n_voxels * topk_percent / 100.0))
    n_select = max(1, n_select)  # At least 1 voxel

    # Get variance threshold for top k%
    masked_variances = variance_map[mask]
    threshold = np.partition(masked_variances, -n_select)[-n_select]

    # Create output mask
    tcompcor_mask = np.zeros(img_4d.shape[:3], dtype=bool)
    tcompcor_mask[mask] = masked_variances >= threshold

    return tcompcor_mask
