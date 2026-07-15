"""Regression tests for the S8 physio/BOLD alignment fix.

S3 removes the first N volumes, so the BOLD reaching S8 starts N TRs after the
first physio trigger. Before the fix the crop began at the trigger while
`n_volumes` was the post-drop count, so the physio led the BOLD by N x TR and
RETROICOR modelled the wrong cardiac phase. See .claude/specs/s3-algorithm-audit.md.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import numpy as np

from spineprep.steps.s8.process import _physio_to_pnm_input

FS = 400.0          # Siemens PMU
TR = 1.66           # GVS
N_VOL = 359         # post-drop volume count
N_DROP = 4


def _physio(n_samples: int, trigger_at: int) -> dict:
    trig = np.zeros(n_samples)
    trig[trigger_at] = 1.0
    # ramp so we can identify which samples were cropped
    return {
        "sampling_frequency_hz": FS,
        "cardiac": np.arange(n_samples, dtype=float),
        "respiratory": np.arange(n_samples, dtype=float),
        "trigger": trig,
    }


def test_crop_starts_n_dummy_trs_after_first_trigger(tmp_path):
    trigger_at = 1000
    p = _physio(400_000, trigger_at)
    _, info = _physio_to_pnm_input(p, tmp_path, tr_s=TR, n_volumes=N_VOL,
                                   n_dummy_dropped=N_DROP)
    expected_offset = int(round(N_DROP * TR * FS))   # 4 * 1.66 * 400 = 2656
    assert info["dummy_offset_samples"] == expected_offset
    assert info["crop_samples"][0] == trigger_at + expected_offset
    assert info["n_dummy_dropped"] == N_DROP


def test_window_length_still_matches_the_bold(tmp_path):
    p = _physio(400_000, 1000)
    _, info = _physio_to_pnm_input(p, tmp_path, tr_s=TR, n_volumes=N_VOL,
                                   n_dummy_dropped=N_DROP)
    start, end = info["crop_samples"]
    assert end - start == int(round(TR * N_VOL * FS))


def test_sample_zero_is_bold_volume_zero(tmp_path):
    """The written file's first sample must be the physio at BOLD volume 0."""
    trigger_at = 1000
    p = _physio(400_000, trigger_at)
    out, _ = _physio_to_pnm_input(p, tmp_path, tr_s=TR, n_volumes=N_VOL,
                                  n_dummy_dropped=N_DROP)
    data = np.loadtxt(out)
    # cardiac was a ramp equal to sample index, so value == absolute index
    assert data[0, 0] == float(trigger_at + int(round(N_DROP * TR * FS)))


def test_no_offset_when_nothing_was_dropped(tmp_path):
    """n_dummy_dropped=0 reproduces the previous behaviour exactly."""
    trigger_at = 1000
    p = _physio(400_000, trigger_at)
    _, info = _physio_to_pnm_input(p, tmp_path, tr_s=TR, n_volumes=N_VOL,
                                   n_dummy_dropped=0)
    assert info["dummy_offset_samples"] == 0
    assert info["crop_samples"][0] == trigger_at
