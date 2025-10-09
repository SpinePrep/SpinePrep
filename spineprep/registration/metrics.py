"""Image quality metrics for registration (SSIM/PSNR) with normalization."""

from __future__ import annotations

import numpy as np
from skimage.metrics import peak_signal_noise_ratio, structural_similarity


def normalize_intensity(
    img: np.ndarray,
    mask: np.ndarray | None = None,
    clip_percentiles: tuple[float, float] | None = None,
) -> np.ndarray:
    """
    Normalize image intensity to zero mean and unit variance.

    Args:
        img: Input image array
        mask: Optional binary mask to constrain normalization region
        clip_percentiles: Optional (low, high) percentiles for clipping before normalization

    Returns:
        Normalized image array (z-scored)
    """
    img_copy = img.copy().astype(np.float64)

    # Remove NaNs for computation
    valid_mask = np.isfinite(img_copy)
    if mask is not None:
        valid_mask = valid_mask & mask

    if not np.any(valid_mask):
        return img_copy

    # Clip outliers if requested
    if clip_percentiles is not None:
        low, high = clip_percentiles
        p_low = np.percentile(img_copy[valid_mask], low)
        p_high = np.percentile(img_copy[valid_mask], high)
        img_copy = np.clip(img_copy, p_low, p_high)

    # Compute mean and std from valid/masked region
    mean_val = np.mean(img_copy[valid_mask])
    std_val = np.std(img_copy[valid_mask])

    if std_val < 1e-10:  # Avoid division by zero
        return img_copy - mean_val

    # Z-score normalization
    normalized = (img_copy - mean_val) / std_val

    # Preserve NaNs in original positions
    normalized[~np.isfinite(img)] = np.nan

    return normalized.astype(img.dtype)


def compute_ssim(
    img1: np.ndarray,
    img2: np.ndarray,
    mask: np.ndarray | None = None,
) -> float:
    """
    Compute Structural Similarity Index (SSIM) between two images.

    For 3D volumes, computes slice-wise SSIM and returns the mean.

    Args:
        img1: First image array
        img2: Second image array
        mask: Optional mask to constrain comparison region

    Returns:
        SSIM value (0-1, higher is better)

    Raises:
        ValueError: If image shapes don't match
    """
    if img1.shape != img2.shape:
        raise ValueError(f"Shape mismatch: img1={img1.shape}, img2={img2.shape}")

    # Handle 3D volumes (compute slice-wise and average)
    if len(img1.shape) == 3:
        ssim_vals = []
        for z in range(img1.shape[2]):
            slice1 = img1[:, :, z]
            slice2 = img2[:, :, z]

            # Skip empty slices
            if slice1.max() == 0 or slice2.max() == 0:
                continue

            # Compute SSIM for this slice
            data_range = max(slice1.max() - slice1.min(), slice2.max() - slice2.min())
            if data_range > 0:
                ssim = structural_similarity(slice1, slice2, data_range=data_range)
                ssim_vals.append(ssim)

        return float(np.mean(ssim_vals)) if ssim_vals else 0.0

    # For 2D images
    data_range = max(img1.max() - img1.min(), img2.max() - img2.min())
    if data_range == 0:
        return 1.0 if np.allclose(img1, img2) else 0.0

    return float(structural_similarity(img1, img2, data_range=data_range))


def compute_psnr(
    img1: np.ndarray,
    img2: np.ndarray,
) -> float:
    """
    Compute Peak Signal-to-Noise Ratio (PSNR) between two images.

    Args:
        img1: First image array
        img2: Second image array

    Returns:
        PSNR value in dB (higher is better, typically 20-50 dB)

    Raises:
        ValueError: If image shapes don't match
    """
    if img1.shape != img2.shape:
        raise ValueError(f"Shape mismatch: img1={img1.shape}, img2={img2.shape}")

    data_range = max(img1.max() - img1.min(), img2.max() - img2.min())
    if data_range == 0:
        # Identical constant images
        return np.inf

    return float(peak_signal_noise_ratio(img1, img2, data_range=data_range))
