"""Unit tests for censor logic in confounds.py"""

import numpy as np

from workflow.lib.confounds import append_censor_columns, build_censor


def test_basic_thresholds():
    """Test basic threshold-based censoring."""
    fd = np.array([0.0, 0.2, 0.6, 0.3, 0.8])
    dvars = np.array([0.1, 0.2, 0.2, 2.0, 0.1])
    cfg = {
        "fd_thresh_mm": 0.5,
        "dvars_thresh": 1.5,
        "min_contig_vols": 3,
        "pad_vols": 1,
    }

    c = build_censor(fd, dvars, cfg)

    # Check basic properties
    assert c["censor"].shape == fd.shape
    assert c["n_censored"] + c["n_kept"] == len(fd)
    assert c["n_censored"] == int(c["censor"].sum())
    assert c["n_kept"] == int((1 - c["censor"]).sum())

    # Frame 2 should be censored (FD > 0.5)
    assert c["censor"][2] == 1
    # Frame 3 should be censored (DVARS > 1.5)
    assert c["censor"][3] == 1


def test_padding():
    """Test padding around censored frames."""
    fd = np.array([0.0, 0.2, 0.6, 0.3, 0.8])
    dvars = np.array([0.1, 0.2, 0.2, 0.2, 0.1])
    cfg = {
        "fd_thresh_mm": 0.5,
        "dvars_thresh": 1.5,
        "min_contig_vols": 1,  # No contiguity filtering
        "pad_vols": 1,
    }

    c = build_censor(fd, dvars, cfg)

    # Frame 2 should be censored (FD > 0.5)
    # Frame 4 should be censored (FD > 0.5)
    # With padding=1, frames 1,3 should also be censored
    assert c["censor"][1] == 1  # Padded before frame 2
    assert c["censor"][2] == 1  # Direct censoring
    assert c["censor"][3] == 1  # Padded after frame 2
    assert c["censor"][4] == 1  # Direct censoring


def test_contiguity_filtering():
    """Test minimum contiguity filtering."""
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


def test_no_censoring():
    """Test when no frames should be censored."""
    fd = np.array([0.1, 0.2, 0.3, 0.4])
    dvars = np.array([0.5, 0.6, 0.7, 0.8])
    cfg = {
        "fd_thresh_mm": 1.0,  # High threshold
        "dvars_thresh": 2.0,  # High threshold
        "min_contig_vols": 1,
        "pad_vols": 0,
    }

    c = build_censor(fd, dvars, cfg)

    # No frames should be censored
    assert c["n_censored"] == 0
    assert c["n_kept"] == len(fd)
    assert np.all(c["censor"] == 0)


def test_all_censored():
    """Test when all frames should be censored."""
    fd = np.array([1.0, 1.0, 1.0, 1.0])
    dvars = np.array([2.0, 2.0, 2.0, 2.0])
    cfg = {
        "fd_thresh_mm": 0.5,
        "dvars_thresh": 1.0,
        "min_contig_vols": 1,
        "pad_vols": 0,
    }

    c = build_censor(fd, dvars, cfg)

    # All frames should be censored
    assert c["n_censored"] == len(fd)
    assert c["n_kept"] == 0
    assert np.all(c["censor"] == 1)


def test_append_censor_columns():
    """Test appending censor columns to DataFrame."""
    import pandas as pd

    df = pd.DataFrame(
        {"framewise_displacement": [0.0, 0.5, 0.8], "dvars": [0.1, 0.2, 0.3]}
    )

    censor_dict = {"censor": np.array([0, 1, 1]), "n_censored": 2, "n_kept": 1}

    df_out = append_censor_columns(df, censor_dict)

    # Check canonical column order
    expected_cols = ["framewise_displacement", "dvars", "frame_censor"]
    assert list(df_out.columns[:3]) == expected_cols
    assert "frame_censor" in df_out.columns
    assert df_out["frame_censor"].tolist() == [0, 1, 1]
