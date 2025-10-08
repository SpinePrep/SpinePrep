"""Unit tests for aCompCor mathematical functions."""

import numpy as np

from workflow.lib.confounds import acompcor_pcs


def test_pcs_shapes_and_variance():
    """Test that aCompCor produces correct shapes and monotonic variance."""
    T, V = 120, 400
    rng = np.random.default_rng(0)
    X = rng.standard_normal((T, V)).astype(np.float32)

    pcs, ev = acompcor_pcs(
        X, n_components=5, highpass_hz=0.0, tr_s=2.0, detrend=True, standardize=True
    )

    assert pcs.shape == (T, 5)
    assert len(ev) == 5
    cum = np.cumsum(ev)
    assert np.all(np.diff(cum) >= -1e-9)  # non-decreasing


def test_empty_mask_handling():
    """Test that empty masks are handled gracefully."""
    T, V = 60, 0  # No voxels in mask
    X = np.zeros((T, V), dtype=np.float32)

    pcs, ev = acompcor_pcs(
        X, n_components=5, highpass_hz=0.0, tr_s=2.0, detrend=True, standardize=True
    )

    assert pcs.shape == (T, 0)  # No components possible
    assert len(ev) == 0


def test_rank_limitation():
    """Test that components are limited by available rank."""
    T, V = 10, 5  # More components requested than rank allows
    rng = np.random.default_rng(0)
    X = rng.standard_normal((T, V)).astype(np.float32)

    pcs, ev = acompcor_pcs(
        X, n_components=10, highpass_hz=0.0, tr_s=2.0, detrend=True, standardize=True
    )

    # Should be limited by min(T, V) - 1 = 4
    assert pcs.shape == (T, 4)
    assert len(ev) == 4


def test_highpass_filtering():
    """Test that high-pass filtering works correctly."""
    T, V = 100, 50
    rng = np.random.default_rng(0)
    X = rng.standard_normal((T, V)).astype(np.float32)

    # Add low-frequency drift
    t = np.arange(T)
    drift = 0.1 * np.sin(2 * np.pi * 0.01 * t)[:, np.newaxis]
    X_drift = X + drift

    pcs_no_filter, _ = acompcor_pcs(
        X_drift,
        n_components=3,
        highpass_hz=0.0,
        tr_s=2.0,
        detrend=False,
        standardize=True,
    )

    pcs_filtered, _ = acompcor_pcs(
        X_drift,
        n_components=3,
        highpass_hz=0.01,
        tr_s=2.0,
        detrend=False,
        standardize=True,
    )

    # Filtered PCs should be different from unfiltered
    assert not np.allclose(pcs_no_filter, pcs_filtered, atol=1e-6)


def test_detrending():
    """Test that detrending works correctly."""
    T, V = 100, 50
    rng = np.random.default_rng(0)
    X = rng.standard_normal((T, V)).astype(np.float32)

    # Add linear trend
    t = np.arange(T)
    trend = 0.01 * t[:, np.newaxis]
    X_trend = X + trend

    pcs_no_detrend, _ = acompcor_pcs(
        X_trend,
        n_components=3,
        highpass_hz=0.0,
        tr_s=2.0,
        detrend=False,
        standardize=True,
    )

    pcs_detrended, _ = acompcor_pcs(
        X_trend,
        n_components=3,
        highpass_hz=0.0,
        tr_s=2.0,
        detrend=True,
        standardize=True,
    )

    # Detrended PCs should be different from non-detrended
    assert not np.allclose(pcs_no_detrend, pcs_detrended, atol=1e-6)
