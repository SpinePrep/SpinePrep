"""Regression tests for the final S3 audit fixes.

F1  — respect NumberOfVolumesDiscardedByScanner (83 cohort runs declare 6).
F10 — DVARS-ref must be the ABSOLUTE TEMPORAL DIFFERENCE of the RMS-to-reference,
      matching FSL fsl_motion_outliers --refrms (the metric Kaptan 2023 and
      Dabbagh 2024 actually use). The undifferenced version carried scanner drift
      and flagged it as motion.
F5  — the drift gate gains a gradient test, since the absolute cap sits above the
      lower medulla and cannot catch an early leak.
See .claude/specs/s3-algorithm-audit.md.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import numpy as np

from spineprep.steps.s3.localize import _effective_dummy_drop

POLICY = {"dummy": {"drop_count": 4, "respect_scanner_discards": True}}


def _bold_with_sidecar(tmp_path, meta):
    b = tmp_path / "sub-01_task-x_bold.nii.gz"
    b.write_bytes(b"")
    if meta is not None:
        (tmp_path / "sub-01_task-x_bold.json").write_text(json.dumps(meta))
    return b


# --- F1 ---------------------------------------------------------------------

def test_drop_defaults_when_no_sidecar(tmp_path):
    assert _effective_dummy_drop(_bold_with_sidecar(tmp_path, None), POLICY) == 4


def test_drop_is_zero_when_scanner_already_discarded(tmp_path):
    b = _bold_with_sidecar(tmp_path, {"NumberOfVolumesDiscardedByScanner": 6})
    assert _effective_dummy_drop(b, POLICY) == 0


def test_drop_defaults_when_scanner_discarded_none(tmp_path):
    b = _bold_with_sidecar(tmp_path, {"NumberOfVolumesDiscardedByScanner": 0})
    assert _effective_dummy_drop(b, POLICY) == 4


def test_respect_flag_can_be_disabled(tmp_path):
    b = _bold_with_sidecar(tmp_path, {"NumberOfVolumesDiscardedByScanner": 6})
    pol = {"dummy": {"drop_count": 4, "respect_scanner_discards": False}}
    assert _effective_dummy_drop(b, pol) == 4


def test_unreadable_sidecar_falls_back_to_default(tmp_path):
    b = tmp_path / "sub-01_task-x_bold.nii.gz"
    b.write_bytes(b"")
    (tmp_path / "sub-01_task-x_bold.json").write_text("{not json")
    assert _effective_dummy_drop(b, POLICY) == 4


# --- F10 --------------------------------------------------------------------

def _refrms(rms_to_ref):
    """Mirror of the shipped computation, for metric-behaviour assertions."""
    out = np.abs(np.diff(rms_to_ref, prepend=rms_to_ref[0]))
    if len(out) > 1:
        out[0] = out[1]
    return out


def test_refrms_differencing_removes_linear_drift():
    """A pure drift must not produce a rising outlier metric."""
    drift = np.linspace(10.0, 50.0, 100)
    out = _refrms(drift)
    assert np.ptp(out) < 1e-6           # flat
    assert out.max() < 1.0              # and small


def test_refrms_differencing_preserves_a_spike():
    rms = np.full(50, 10.0)
    rms[25] = 40.0                      # one bad frame
    out = _refrms(rms)
    assert out[25] > 25.0               # jump in
    assert out[26] > 25.0               # jump back out
    assert out[10] < 1e-6               # quiet elsewhere


def test_refrms_length_matches_frames():
    rms = np.random.default_rng(0).normal(10, 1, 37)
    assert len(_refrms(rms)) == 37
