"""Unit tests for crop detector functionality."""

from pathlib import Path

import numpy as np

from workflow.lib.crop import detect_crop


def _fake_tsv(p: Path, series):
    """Create a fake TSV file with global signal data."""
    with open(p, "w") as f:
        f.write("global_signal\n")
        for val in series:
            f.write(f"{val}\n")


def test_detector_trims_head_tail_with_bounds(tmp_path):
    """Test that detector trims head and tail volumes with proper bounds."""
    n = 60
    s = np.ones(n)
    s[:4] = 10.0  # head artifact
    s[-3:] = 12.0  # tail artifact
    tsv = tmp_path / "conf.tsv"
    _fake_tsv(tsv, s)

    out = detect_crop(
        confounds_tsv=str(tsv),
        bold_path="",
        cord_mask=None,
        opts={"z_thresh": 2.5, "max_trim_start": 10, "max_trim_end": 10},
    )

    assert out["from"] == 4 and out["to"] == n - 3 and out["nvols"] == n
