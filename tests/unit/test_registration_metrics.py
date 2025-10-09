"""Unit tests for registration metrics computation (SSIM/PSNR)."""

from __future__ import annotations

import numpy as np
import pytest


def test_ssim_identical_images():
    """SSIM should be 1.0 for identical images."""
    from spineprep.registration.metrics import compute_ssim

    img = np.random.rand(64, 64).astype(np.float32)
    ssim = compute_ssim(img, img.copy())
    assert ssim == pytest.approx(1.0, abs=1e-6)


def test_ssim_different_images():
    """SSIM should be < 1.0 for different images."""
    from spineprep.registration.metrics import compute_ssim

    img1 = np.random.rand(64, 64).astype(np.float32)
    img2 = np.random.rand(64, 64).astype(np.float32)
    ssim = compute_ssim(img1, img2)
    assert 0.0 <= ssim < 1.0


def test_ssim_3d_images():
    """SSIM should work on 3D volumes."""
    from spineprep.registration.metrics import compute_ssim

    img = np.random.rand(32, 32, 16).astype(np.float32)
    ssim = compute_ssim(img, img.copy())
    assert ssim == pytest.approx(1.0, abs=1e-6)


def test_ssim_shape_mismatch():
    """SSIM should raise ValueError for mismatched shapes."""
    from spineprep.registration.metrics import compute_ssim

    img1 = np.random.rand(64, 64).astype(np.float32)
    img2 = np.random.rand(32, 32).astype(np.float32)
    with pytest.raises(ValueError, match="Shape mismatch"):
        compute_ssim(img1, img2)


def test_psnr_identical_images():
    """PSNR should be inf for identical images."""
    from spineprep.registration.metrics import compute_psnr

    img = np.random.rand(64, 64).astype(np.float32)
    psnr = compute_psnr(img, img.copy())
    assert np.isinf(psnr) or psnr > 100.0  # Very high PSNR for identical


def test_psnr_different_images():
    """PSNR should be finite for different images."""
    from spineprep.registration.metrics import compute_psnr

    img1 = np.random.rand(64, 64).astype(np.float32)
    img2 = np.random.rand(64, 64).astype(np.float32)
    psnr = compute_psnr(img1, img2)
    assert psnr > 0.0 and not np.isinf(psnr)


def test_psnr_shape_mismatch():
    """PSNR should raise ValueError for mismatched shapes."""
    from spineprep.registration.metrics import compute_psnr

    img1 = np.random.rand(64, 64).astype(np.float32)
    img2 = np.random.rand(32, 32).astype(np.float32)
    with pytest.raises(ValueError, match="Shape mismatch"):
        compute_psnr(img1, img2)


def test_normalize_intensity_clip():
    """Test intensity normalization with percentile clipping."""
    from spineprep.registration.metrics import normalize_intensity

    img = np.random.rand(64, 64).astype(np.float32) * 1000
    normalized = normalize_intensity(img, clip_percentiles=(2, 98))
    # Should be z-scored
    assert normalized.mean() == pytest.approx(0.0, abs=0.1)
    assert normalized.std() == pytest.approx(1.0, abs=0.1)


def test_normalize_intensity_with_mask():
    """Test intensity normalization with mask."""
    from spineprep.registration.metrics import normalize_intensity

    img = np.random.rand(64, 64).astype(np.float32)
    mask = np.zeros((64, 64), dtype=bool)
    mask[16:48, 16:48] = True  # Center region

    normalized = normalize_intensity(img, mask=mask)
    # Should normalize based on mask region
    assert normalized.shape == img.shape
    # Mean and std computed from masked region should be ~0 and ~1
    masked_vals = normalized[mask]
    assert masked_vals.mean() == pytest.approx(0.0, abs=0.1)
    assert masked_vals.std() == pytest.approx(1.0, abs=0.1)


def test_normalize_intensity_handles_nan():
    """Test that normalization handles NaN gracefully."""
    from spineprep.registration.metrics import normalize_intensity

    img = np.random.rand(64, 64).astype(np.float32)
    img[0, 0] = np.nan
    normalized = normalize_intensity(img)
    # Should not propagate NaN everywhere
    assert np.isfinite(normalized[10, 10])


def test_ssim_psnr_integration():
    """Test SSIM and PSNR on a realistic registration scenario."""
    from spineprep.registration.metrics import compute_psnr, compute_ssim

    # Create a simple test pattern
    img1 = np.zeros((64, 64), dtype=np.float32)
    img1[20:44, 20:44] = 1.0  # Square

    # Slightly shifted version
    img2 = np.zeros((64, 64), dtype=np.float32)
    img2[21:45, 21:45] = 1.0

    ssim = compute_ssim(img1, img2)
    psnr = compute_psnr(img1, img2)

    # Should have decent but not perfect similarity
    assert 0.7 < ssim < 1.0
    assert 10.0 < psnr < 50.0
