"""Tests for CompCor (aCompCor and tCompCor) computation."""

from __future__ import annotations

import nibabel as nib
import numpy as np

from spineprep.confounds.compcor import (
    extract_timeseries,
    fit_compcor,
    select_tcompcor_voxels,
)


def test_extract_timeseries_basic():
    """Test timeseries extraction from 4D volume with mask."""
    # Create synthetic 4D data
    np.random.seed(42)
    data_4d = np.random.randn(4, 4, 3, 10).astype(np.float32) + 100.0

    # Create mask
    mask = np.zeros((4, 4, 3), dtype=bool)
    mask[1:3, 1:3, 1] = True  # 4 voxels

    # Extract timeseries
    ts = extract_timeseries(data_4d, mask)

    # Should have shape (timepoints, n_voxels)
    assert ts.shape == (10, 4)
    assert ts.dtype == np.float32


def test_fit_compcor_deterministic():
    """Test that CompCor PCA is deterministic."""
    np.random.seed(100)

    # Create synthetic timeseries with known structure
    n_timepoints = 50
    n_voxels = 20

    # Add structured signal
    t = np.arange(n_timepoints, dtype=np.float32)
    comp1 = np.sin(2 * np.pi * t / 10)
    comp2 = np.cos(2 * np.pi * t / 15)

    # Create timeseries with these components plus noise
    ts = np.zeros((n_timepoints, n_voxels), dtype=np.float32)
    for i in range(n_voxels):
        weight1 = np.random.rand()
        weight2 = np.random.rand()
        ts[:, i] = (
            weight1 * comp1 + weight2 * comp2 + np.random.randn(n_timepoints) * 0.1
        )

    # Fit CompCor twice
    components1, variance1 = fit_compcor(ts, n_components=5)
    components2, variance2 = fit_compcor(ts, n_components=5)

    # Should be identical (deterministic)
    np.testing.assert_array_equal(components1, components2)
    np.testing.assert_array_equal(variance1, variance2)

    # Shape checks
    assert components1.shape == (n_timepoints, 5)
    assert len(variance1) == 5
    assert components1.dtype == np.float32


def test_fit_compcor_variance_ordered():
    """Test that variance explained is in descending order."""
    np.random.seed(200)

    n_timepoints = 30
    n_voxels = 15
    ts = np.random.randn(n_timepoints, n_voxels).astype(np.float32)

    components, variance = fit_compcor(ts, n_components=5)

    # Variance should be in descending order
    assert np.all(np.diff(variance) <= 0), "Variance not in descending order"

    # Variance should sum to <= 1.0 (explained variance ratio)
    assert np.sum(variance) <= 1.0


def test_fit_compcor_sign_convention():
    """Test that sign convention is enforced (first nonzero > 0)."""
    np.random.seed(300)

    n_timepoints = 40
    n_voxels = 10
    ts = np.random.randn(n_timepoints, n_voxels).astype(np.float32)

    components, _ = fit_compcor(ts, n_components=3)

    # Check sign convention for each component
    for i in range(3):
        comp = components[:, i]
        # Find first nonzero element
        nonzero_idx = np.where(np.abs(comp) > 1e-10)[0]
        if len(nonzero_idx) > 0:
            first_nonzero = comp[nonzero_idx[0]]
            assert first_nonzero > 0, f"Component {i} violates sign convention"


def test_select_tcompcor_voxels():
    """Test tCompCor voxel selection based on temporal variance."""
    np.random.seed(400)

    # Create 4D data with varying temporal variance
    data_4d = np.random.randn(6, 6, 3, 20).astype(np.float32)

    # Add high variance to specific voxels
    data_4d[2, 2, 1, :] += np.random.randn(20) * 10.0  # High variance
    data_4d[3, 3, 1, :] += np.random.randn(20) * 10.0  # High variance

    # Create mask
    mask = np.ones((6, 6, 3), dtype=bool)

    # Select top 5% variance voxels
    tcompcor_mask = select_tcompcor_voxels(data_4d, mask, topk_percent=5.0)

    # Should have selected some voxels
    n_selected = tcompcor_mask.sum()
    n_total = mask.sum()
    expected_count = int(np.ceil(n_total * 0.05))

    assert n_selected == expected_count
    assert tcompcor_mask.dtype == bool

    # High-variance voxels should be selected
    assert tcompcor_mask[2, 2, 1]
    assert tcompcor_mask[3, 3, 1]


def test_acompcor_with_fixtures():
    """Test aCompCor extraction with real mask fixtures."""
    # Load mask fixtures
    mask_csf = nib.load("tests/data/mask_csf.nii.gz").get_fdata().astype(bool)
    mask_wm = nib.load("tests/data/mask_wm.nii.gz").get_fdata().astype(bool)

    # Create synthetic BOLD data
    np.random.seed(500)
    data_4d = np.random.randn(8, 8, 4, 30).astype(np.float32) + 100.0

    # Combine masks
    combined_mask = mask_csf | mask_wm

    # Extract timeseries
    ts = extract_timeseries(data_4d, combined_mask)

    # Fit aCompCor
    components, variance = fit_compcor(ts, n_components=6)

    assert components.shape == (30, 6)
    assert len(variance) == 6
    assert variance[0] > variance[-1]  # First PC explains more variance


def test_tcompcor_full_pipeline():
    """Test full tCompCor pipeline: select voxels, extract, fit."""
    np.random.seed(600)

    # Create 4D data
    data_4d = np.random.randn(8, 8, 4, 40).astype(np.float32) + 50.0

    # Load cord mask
    mask_cord = nib.load("tests/data/mask_cord.nii.gz").get_fdata().astype(bool)

    # Select tCompCor voxels (top 10% to ensure enough voxels for 6 components)
    tcompcor_mask = select_tcompcor_voxels(data_4d, mask_cord, topk_percent=10.0)

    # Extract timeseries
    ts = extract_timeseries(data_4d, tcompcor_mask)

    # Fit tCompCor (request 6 but might get fewer if not enough voxels)
    components, variance = fit_compcor(ts, n_components=6)

    # Should have some components (at least 1)
    assert components.shape[0] == 40  # Same number of timepoints
    assert components.shape[1] >= 1  # At least 1 component
    assert components.shape[1] <= 6  # No more than requested
    assert components.dtype == np.float32
    assert len(variance) == components.shape[1]

    # Variance should be valid
    assert np.all(variance >= 0)
    assert np.all(variance <= 1.0)


def test_compcor_with_insufficient_voxels():
    """Test CompCor when fewer voxels than requested components."""
    # Create timeseries with only 3 voxels
    ts = np.random.randn(20, 3).astype(np.float32)

    # Request 6 components (more than available)
    components, variance = fit_compcor(ts, n_components=6)

    # Should return min(n_voxels, n_timepoints-1, n_components) components
    # In this case: min(3, 19, 6) = 3
    assert components.shape[1] <= 3
    assert len(variance) == components.shape[1]
