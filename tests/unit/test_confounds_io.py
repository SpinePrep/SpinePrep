"""Unit tests for confounds IO functionality."""

import json

import pandas as pd

from workflow.lib.confounds import write_confounds_tsv_json


def test_write_tsv_json_schema(tmp_path):
    """Test writing confounds TSV and JSON with proper schema."""
    df = pd.DataFrame({"framewise_displacement": [0, 0.5, 0.7], "dvars": [0, 1.2, 0.8]})

    tsv = tmp_path / "conf.tsv"
    js = tmp_path / "conf.json"

    write_confounds_tsv_json(
        df,
        str(tsv),
        str(js),
        {"FDMethod": "power_fd", "DVARSMethod": "std_dvars", "SamplingFrequency": 1.0},
    )

    # Check TSV has required columns
    df2 = pd.read_csv(tsv, sep="\t")
    assert set(["framewise_displacement", "dvars"]).issubset(df2.columns)

    # Check JSON has required metadata
    meta = json.loads(js.read_text())
    for k in ("FDMethod", "DVARSMethod", "SamplingFrequency"):
        assert k in meta
