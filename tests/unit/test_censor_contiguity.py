"""Unit tests for censor contiguity logic in confounds.py"""

import numpy as np

from workflow.lib.confounds import build_censor


def test_min_contig_and_pad():
    """Test minimum contiguity with padding."""
    fd = np.zeros(12)
    dvars = np.zeros(12)
    fd[[1, 5, 9]] = 0.6  # Sparse outliers

    cfg = {
        "fd_thresh_mm": 0.5,
        "dvars_thresh": 9.9,  # High threshold to avoid DVARS censoring
        "min_contig_vols": 4,
        "pad_vols": 1,
    }

    c = build_censor(fd, dvars, cfg)

    # Should have censored the outliers and their padding
    assert c["censor"].sum() >= 3  # At least the three outliers
    assert c["n_kept"] + c["n_censored"] == 12

    # Check that kept segments meet minimum contiguity
    kept_segments = c["kept_segments"]
    for start, end in kept_segments:
        assert end - start >= cfg["min_contig_vols"]


def test_short_segments_removed():
    """Test that short segments are removed."""
    fd = np.array([0.0, 0.0, 0.6, 0.0, 0.0, 0.0, 0.6, 0.0, 0.0])
    dvars = np.zeros_like(fd)

    cfg = {
        "fd_thresh_mm": 0.5,
        "dvars_thresh": 9.9,
        "min_contig_vols": 3,
        "pad_vols": 0,
    }

    c = build_censor(fd, dvars, cfg)

    # The two short segments (2 frames each) should be removed
    # Only the middle segment (3 frames) should remain
    assert c["n_kept"] <= 3  # At most the middle segment


def test_edge_cases():
    """Test edge cases for contiguity."""
    # Test with min_contig_vols = 1 (no filtering)
    fd = np.array([0.0, 0.6, 0.0, 0.6, 0.0])
    dvars = np.zeros_like(fd)

    cfg = {
        "fd_thresh_mm": 0.5,
        "dvars_thresh": 9.9,
        "min_contig_vols": 1,
        "pad_vols": 0,
    }

    c = build_censor(fd, dvars, cfg)

    # Should keep the single frames
    assert c["n_kept"] == 3  # Three single frames
    assert c["n_censored"] == 2  # Two outliers


def test_padding_with_contiguity():
    """Test padding combined with contiguity filtering."""
    fd = np.array([0.0, 0.0, 0.6, 0.0, 0.0, 0.0, 0.0])
    dvars = np.zeros_like(fd)

    cfg = {
        "fd_thresh_mm": 0.5,
        "dvars_thresh": 9.9,
        "min_contig_vols": 3,
        "pad_vols": 1,
    }

    c = build_censor(fd, dvars, cfg)

    # With padding=1, the outlier at index 2 should censor indices 1,2,3
    # This should leave two short segments that get removed
    assert c["n_kept"] <= 2  # Very few frames should remain


def test_all_frames_contiguous():
    """Test when all frames form one contiguous segment."""
    fd = np.zeros(10)
    dvars = np.zeros(10)

    cfg = {
        "fd_thresh_mm": 1.0,  # High threshold
        "dvars_thresh": 2.0,  # High threshold
        "min_contig_vols": 5,
        "pad_vols": 0,
    }

    c = build_censor(fd, dvars, cfg)

    # All frames should be kept
    assert c["n_kept"] == 10
    assert c["n_censored"] == 0
    assert len(c["kept_segments"]) == 1
    assert c["kept_segments"][0] == (0, 10)
