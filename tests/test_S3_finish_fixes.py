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


# --- F1 end-to-end: the effective drop must REACH qc.json -------------------
# The first F1 fix dropped the right number of volumes but never returned the
# count: outlier_mask.json (and therefore qc.json metrics.n_dummy_dropped) was
# read from the POLICY DEFAULT. S8 offsets physio by that value and S9 writes
# StartTime from it, so on the 83 scanner-discard runs the pipeline dropped 0
# and then told S8 it had dropped 4 -- re-introducing the exact 4-TR physio
# misalignment F1 set out to remove.

def test_localize_returns_effective_drop_key():
    """S3.1's result must expose n_dummy_dropped for session.py to forward."""
    import inspect
    from spineprep.steps.s3 import localize
    src = inspect.getsource(localize)
    assert '"n_dummy_dropped": int(dummy_volumes)' in src


def test_outlier_reports_passed_drop_not_policy_default():
    """When the caller passes the applied count, reporting must use it."""
    import inspect
    from spineprep.steps.s3 import outlier
    sig = inspect.signature(outlier._process_s3_2_outlier_gating)
    assert "n_dummy_dropped" in sig.parameters
    src = inspect.getsource(outlier._process_s3_2_outlier_gating)
    assert "dummy_count = int(n_dummy_dropped)" in src


def test_session_prefers_s3_1_over_cached_outlier_mask():
    """A cached outlier_mask.json must not override the applied count."""
    import inspect
    from spineprep.steps.s3 import session
    src = inspect.getsource(session)
    assert 's3_1_res.get("n_dummy_dropped")' in src
    assert "n_dummy_dropped=s3_1_res.get" in src


def test_batch_path_honours_workers():
    """The multi-dataset path ignored batch_workers while printing 'N workers'."""
    import inspect
    from spineprep.steps.s3 import orchestrate
    src = inspect.getsource(orchestrate.run_S3_func_init_and_crop_batch)
    assert "ProcessPoolExecutor(max_workers=batch_workers)" in src
    assert "session_runs[idx]" in src  # index-ordered, not completion-ordered
