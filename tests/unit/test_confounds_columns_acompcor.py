"""Unit tests for aCompCor column generation in confounds."""

import numpy as np
import pandas as pd

from workflow.lib.confounds import append_acompcor


def test_tsv_has_acompcor_columns():
    """Test that aCompCor columns are added to confounds DataFrame."""
    df = pd.DataFrame(
        {
            "framewise_displacement": [0] * 10,
            "dvars": [0] * 10,
            "frame_censor": [0] * 10,
        }
    )

    # Mock aCompCor data
    pcs = {
        "cord": {
            "pcs": np.random.randn(10, 2),
            "explained_variance": np.array([0.1, 0.05]),
        }
    }

    df2, meta = append_acompcor(df, pcs)

    # Check that aCompCor columns are present
    assert "acomp_cord_pc01" in df2.columns
    assert "acomp_cord_pc02" in df2.columns

    # Check metadata
    assert "aCompCor" in meta
    assert "cord" in meta["aCompCor"]
    assert meta["aCompCor"]["cord"]["n_components"] == 2


def test_multiple_tissues():
    """Test aCompCor with multiple tissues."""
    df = pd.DataFrame(
        {
            "framewise_displacement": [0] * 10,
            "dvars": [0] * 10,
            "frame_censor": [0] * 10,
        }
    )

    pcs = {
        "cord": {
            "pcs": np.random.randn(10, 2),
            "explained_variance": np.array([0.1, 0.05]),
        },
        "wm": {
            "pcs": np.random.randn(10, 3),
            "explained_variance": np.array([0.2, 0.1, 0.05]),
        },
    }

    df2, meta = append_acompcor(df, pcs)

    # Check cord columns
    assert "acomp_cord_pc01" in df2.columns
    assert "acomp_cord_pc02" in df2.columns

    # Check WM columns
    assert "acomp_wm_pc01" in df2.columns
    assert "acomp_wm_pc02" in df2.columns
    assert "acomp_wm_pc03" in df2.columns

    # Check metadata
    assert "cord" in meta["aCompCor"]
    assert "wm" in meta["aCompCor"]
    assert meta["aCompCor"]["cord"]["n_components"] == 2
    assert meta["aCompCor"]["wm"]["n_components"] == 3


def test_canonical_column_order():
    """Test that aCompCor columns are placed in canonical order."""
    df = pd.DataFrame(
        {
            "framewise_displacement": [0] * 10,
            "dvars": [0] * 10,
            "frame_censor": [0] * 10,
        }
    )

    pcs = {
        "cord": {
            "pcs": np.random.randn(10, 2),
            "explained_variance": np.array([0.1, 0.05]),
        }
    }

    df2, _ = append_acompcor(df, pcs)

    # Get column positions
    cols = list(df2.columns)
    fd_pos = cols.index("framewise_displacement")
    dvars_pos = cols.index("dvars")
    censor_pos = cols.index("frame_censor")
    acomp_pos = cols.index("acomp_cord_pc01")

    # aCompCor should come after frame_censor
    assert acomp_pos > censor_pos
    # Basic order should be maintained
    assert fd_pos < dvars_pos < censor_pos


def test_empty_pcs_handling():
    """Test handling of empty PC data."""
    df = pd.DataFrame(
        {
            "framewise_displacement": [0] * 10,
            "dvars": [0] * 10,
            "frame_censor": [0] * 10,
        }
    )

    # Empty PCs dict
    pcs = {}

    df2, meta = append_acompcor(df, pcs)

    # Should return original DataFrame with no aCompCor columns
    assert df2.equals(df)
    assert "aCompCor" in meta
    assert meta["aCompCor"] == {}


def test_pcs_with_zero_variance():
    """Test handling of PCs with zero explained variance."""
    df = pd.DataFrame(
        {
            "framewise_displacement": [0] * 10,
            "dvars": [0] * 10,
            "frame_censor": [0] * 10,
        }
    )

    pcs = {
        "cord": {"pcs": np.zeros((10, 2)), "explained_variance": np.array([0.0, 0.0])}
    }

    df2, meta = append_acompcor(df, pcs)

    # Should still add columns even with zero variance
    assert "acomp_cord_pc01" in df2.columns
    assert "acomp_cord_pc02" in df2.columns
    assert meta["aCompCor"]["cord"]["n_components"] == 2
