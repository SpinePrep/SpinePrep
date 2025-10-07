"""Unit tests for confounds column handling in confounds.py"""

import pandas as pd
import pytest

from workflow.lib.confounds import append_censor_columns


def test_tsv_has_canonical_columns():
    """Test that TSV has canonical columns in correct order."""
    df = pd.DataFrame(
        {"framewise_displacement": [0.0, 0.5, 0.7], "dvars": [0.0, 1.2, 0.8]}
    )

    censor_dict = {"censor": [0, 1, 1], "n_censored": 2, "n_kept": 1}

    df_out = append_censor_columns(df, censor_dict)

    # Check canonical column order
    expected_cols = ["framewise_displacement", "dvars", "frame_censor"]
    assert list(df_out.columns[:3]) == expected_cols

    # Check that all expected columns are present
    for col in expected_cols:
        assert col in df_out.columns

    # Check values
    assert df_out["frame_censor"].tolist() == [0, 1, 1]


def test_extra_columns_preserved():
    """Test that extra columns are preserved after canonical columns."""
    df = pd.DataFrame(
        {
            "framewise_displacement": [0.0, 0.5],
            "dvars": [0.0, 1.2],
            "extra_col1": [1, 2],
            "extra_col2": [3, 4],
        }
    )

    censor_dict = {"censor": [0, 1], "n_censored": 1, "n_kept": 1}

    df_out = append_censor_columns(df, censor_dict)

    # Check canonical columns come first
    expected_canonical = ["framewise_displacement", "dvars", "frame_censor"]
    assert list(df_out.columns[:3]) == expected_canonical

    # Check extra columns are preserved
    assert "extra_col1" in df_out.columns
    assert "extra_col2" in df_out.columns

    # Check values are preserved
    assert df_out["extra_col1"].tolist() == [1, 2]
    assert df_out["extra_col2"].tolist() == [3, 4]


def test_empty_dataframe():
    """Test handling of empty DataFrame."""
    df = pd.DataFrame()

    censor_dict = {"censor": [], "n_censored": 0, "n_kept": 0}

    df_out = append_censor_columns(df, censor_dict)

    # Should have frame_censor column
    assert "frame_censor" in df_out.columns
    assert len(df_out) == 0


def test_mismatched_lengths():
    """Test handling of mismatched censor and DataFrame lengths."""
    df = pd.DataFrame({"framewise_displacement": [0.0, 0.5], "dvars": [0.0, 1.2]})

    # Censor array too short
    censor_dict = {
        "censor": [0],  # Only 1 element, but DataFrame has 2 rows
        "n_censored": 0,
        "n_kept": 1,
    }

    # This should raise an error or handle gracefully
    with pytest.raises((ValueError, IndexError)):
        append_censor_columns(df, censor_dict)
