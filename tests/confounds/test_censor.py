"""Tests for censoring logic."""

from __future__ import annotations

import numpy as np
import pytest

from spineprep.confounds.censor import make_censor_columns


def test_censor_fd_basic():
    """Test FD-based censoring with simple threshold."""
    fd = np.array([0.0, 0.2, 0.6, 0.3, 1.2, 0.1], dtype=np.float32)
    dvars = np.zeros(6, dtype=np.float32)

    cfg = {"fd_thresh": 0.5, "dvars_thresh": 1.5}

    censor_fd, censor_dvars, censor_any = make_censor_columns(fd, dvars, cfg)

    # Expected: censor where fd > 0.5
    expected_fd = np.array([0, 0, 1, 0, 1, 0], dtype=np.int8)

    np.testing.assert_array_equal(censor_fd, expected_fd)
    assert censor_fd.dtype == np.int8


def test_censor_dvars_basic():
    """Test DVARS-based censoring."""
    fd = np.zeros(6, dtype=np.float32)
    dvars = np.array([0.0, 1.0, 1.2, 2.0, 0.5, 0.3], dtype=np.float32)

    cfg = {"fd_thresh": 0.5, "dvars_thresh": 1.5}

    censor_fd, censor_dvars, censor_any = make_censor_columns(fd, dvars, cfg)

    # Expected: censor where dvars > 1.5
    expected_dvars = np.array([0, 0, 0, 1, 0, 0], dtype=np.int8)

    np.testing.assert_array_equal(censor_dvars, expected_dvars)
    assert censor_dvars.dtype == np.int8


def test_censor_any_combination():
    """Test censor_any combines FD and DVARS."""
    fd = np.array([0.0, 0.6, 0.3, 0.8, 0.1, 0.2], dtype=np.float32)
    dvars = np.array([0.0, 0.5, 2.0, 0.3, 1.8, 0.2], dtype=np.float32)

    cfg = {"fd_thresh": 0.5, "dvars_thresh": 1.5}

    censor_fd, censor_dvars, censor_any = make_censor_columns(fd, dvars, cfg)

    # FD censors: indices 1, 3 (fd > 0.5)
    # DVARS censors: indices 2, 4 (dvars > 1.5)
    # ANY censors: indices 1, 2, 3, 4

    expected_any = np.array([0, 1, 1, 1, 1, 0], dtype=np.int8)

    np.testing.assert_array_equal(censor_any, expected_any)

    # Verify logical OR relationship
    np.testing.assert_array_equal(censor_any, np.maximum(censor_fd, censor_dvars))


def test_censor_all_pass():
    """Test that no frames are censored when all below threshold."""
    fd = np.array([0.1, 0.2, 0.3, 0.2], dtype=np.float32)
    dvars = np.array([0.5, 0.8, 0.7, 0.6], dtype=np.float32)

    cfg = {"fd_thresh": 0.5, "dvars_thresh": 1.0}

    censor_fd, censor_dvars, censor_any = make_censor_columns(fd, dvars, cfg)

    # All should pass (no censoring)
    np.testing.assert_array_equal(censor_fd, np.zeros(4, dtype=np.int8))
    np.testing.assert_array_equal(censor_dvars, np.zeros(4, dtype=np.int8))
    np.testing.assert_array_equal(censor_any, np.zeros(4, dtype=np.int8))


def test_censor_all_fail():
    """Test that all frames are censored when all above threshold."""
    fd = np.array([0.8, 1.0, 1.5, 0.9], dtype=np.float32)
    dvars = np.array([2.0, 2.5, 3.0, 2.2], dtype=np.float32)

    cfg = {"fd_thresh": 0.5, "dvars_thresh": 1.5}

    censor_fd, censor_dvars, censor_any = make_censor_columns(fd, dvars, cfg)

    # All should be censored
    np.testing.assert_array_equal(censor_fd, np.ones(4, dtype=np.int8))
    np.testing.assert_array_equal(censor_dvars, np.ones(4, dtype=np.int8))
    np.testing.assert_array_equal(censor_any, np.ones(4, dtype=np.int8))


def test_censor_length_mismatch():
    """Test that mismatched FD and DVARS lengths raise error."""
    fd = np.array([0.1, 0.2, 0.3], dtype=np.float32)
    dvars = np.array([0.5, 0.8], dtype=np.float32)  # Different length

    cfg = {"fd_thresh": 0.5, "dvars_thresh": 1.0}

    with pytest.raises(ValueError, match="FD and DVARS.*length"):
        make_censor_columns(fd, dvars, cfg)


def test_censor_boundary_conditions():
    """Test censoring at exact threshold boundaries."""
    # Values exactly at threshold
    fd = np.array([0.5, 0.51, 0.49], dtype=np.float32)
    dvars = np.array([1.5, 1.51, 1.49], dtype=np.float32)

    cfg = {"fd_thresh": 0.5, "dvars_thresh": 1.5}

    censor_fd, censor_dvars, censor_any = make_censor_columns(fd, dvars, cfg)

    # > threshold, not >=
    # So 0.5 should NOT be censored, but 0.51 should be
    assert censor_fd[0] == 0  # Exactly at threshold
    assert censor_fd[1] == 1  # Just above
    assert censor_fd[2] == 0  # Just below


def test_censor_count_summary():
    """Test that we can compute censoring statistics."""
    fd = np.array([0.1, 0.6, 0.3, 0.8, 0.2, 1.0], dtype=np.float32)
    dvars = np.array([0.5, 0.8, 2.0, 0.4, 1.8, 0.3], dtype=np.float32)

    cfg = {"fd_thresh": 0.5, "dvars_thresh": 1.5}

    censor_fd, censor_dvars, censor_any = make_censor_columns(fd, dvars, cfg)

    # Count censored frames
    n_fd = censor_fd.sum()
    n_dvars = censor_dvars.sum()
    n_any = censor_any.sum()

    # FD censors: 1, 3, 5 (3 frames)
    # DVARS censors: 2, 4 (2 frames)
    # ANY: 1, 2, 3, 4, 5 (5 frames)

    assert n_fd == 3
    assert n_dvars == 2
    assert n_any == 5

    # ANY should be >= individual counts
    assert n_any >= n_fd
    assert n_any >= n_dvars
