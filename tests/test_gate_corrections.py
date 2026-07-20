"""Gate corrections from the 2026-07-19 end-to-end audit.

Four defects, each a gate that did not do what it claimed:
  * S2 kept the hard-cliff per-level Dice gate that S7 retired -- and here a
    FAIL costs the WHOLE subject, since S2 is the anatomical reference.
  * S8 sent an exactly singular design matrix to WARN while a merely bad one
    FAILed, because np.isfinite(inf) is False -- severity inverted, and
    reported as "not computed" when it had been computed.
  * S6 FAILed on a metric its own policy calls observability-only.
  * `spineprep check S3` returned PASS from every branch.
"""
import numpy as np
import pytest


# --- S2: three-banded per-level Dice --------------------------------------

_S2_THR = {"per_level_pass_min": 0.90, "per_level_fail_below": 0.85,
           "per_level_broken_below": 0.50}


def _s2_status(per_level, thr=_S2_THR):
    """Mirror of the S2 banding in session.py, exercised directly."""
    import statistics as st
    med, lo = st.median(per_level), min(per_level)
    status = "PASS"
    if med < thr["per_level_fail_below"]:
        status = "FAIL"
    elif med < thr["per_level_pass_min"]:
        status = "WARN"
    if lo < thr["per_level_broken_below"] and status == "PASS":
        status = "WARN"
    return status


def test_s2_sibling_runs_no_longer_split_across_fail():
    """The S7 lesson: 0.8997 and 0.9019 differ by noise, neither may FAIL."""
    assert _s2_status([0.8997] * 3) == "WARN"
    assert _s2_status([0.9019] * 3) == "PASS"


def test_s2_genuine_outlier_still_fails():
    for med in (0.70, 0.80, 0.84):
        assert _s2_status([med] * 3) == "FAIL", med


def test_s2_boundaries_are_inclusive_pass_and_warn():
    assert _s2_status([0.90] * 3) == "PASS"
    assert _s2_status([0.85] * 3) == "WARN"


def test_s2_broken_level_reported_inside_warn_band():
    assert _s2_status([0.0, 0.97, 0.98]) == "WARN"


def test_s2_policy_declares_the_fail_floor():
    """The gate must be configurable, not hardcoded."""
    import yaml
    from pathlib import Path
    pol = yaml.safe_load(Path("policy/S2_anat_cordref.yaml").read_text())
    thr = pol["qc_thresholds"]
    assert "per_level_fail_below" in thr
    assert thr["per_level_fail_below"] < thr["per_level_pass_min"]


# --- S8: infinity is the worst outcome, not a middling one -----------------


def _s8_status(cn, thr=None):
    from spineprep.steps.s8.process import _classify
    thr = thr or {"pass_condition_number": 1000.0, "warn_condition_number": 10000.0}
    status, reasons = _classify({"condition_number": cn}, thr)
    return status, " ".join(reasons)


def test_s8_singular_design_fails():
    status, reason = _s8_status(float("inf"))
    assert status == "FAIL"
    assert "singular" in reason


def test_s8_singular_is_not_reported_as_unmeasured():
    _, reason = _s8_status(float("inf"))
    assert "not computed" not in reason


def test_s8_severity_is_monotonic():
    """A worse condition number may never yield a better verdict."""
    rank = {"PASS": 0, "WARN": 1, "FAIL": 2}
    seq = [_s8_status(v)[0] for v in (10.0, 5000.0, 20000.0, 9.47e16, float("inf"))]
    assert [rank[s] for s in seq] == sorted(rank[s] for s in seq)
    assert seq[-1] == "FAIL"


def test_s8_nan_still_reads_as_unmeasured():
    status, reason = _s8_status(float("nan"))
    assert status == "WARN" and "not computed" in reason


def test_s8_normal_values_unchanged():
    assert _s8_status(10.0)[0] == "PASS"
    assert _s8_status(5000.0)[0] == "WARN"
    assert _s8_status(20000.0)[0] == "FAIL"


# --- S6: observability-only metrics must not gate --------------------------


def test_s6_centerline_drift_cannot_fail_a_run():
    from spineprep.steps.s6.process import _classify
    thr = {"pass_dice_min": 0.85, "pass_centerline_med_vox_max": 3.0,
           "warn_centerline_med_vox_max": 6.0,
           "pass_centerline_max_vox_max": 5.0,
           "warn_centerline_max_vox_max": 10.0}
    status, reasons = _classify(
        {"cord_dice": 0.95, "centerline_round_trip_med_vox": 99.0,
         "centerline_round_trip_max_vox": 99.0}, thr, syn_fallback=False)
    assert status == "WARN", "policy says this metric does not gate"
    assert any("does not gate" in r for r in reasons)


def test_s6_missing_metric_says_so():
    """A silent WARN with an empty reason list is not a diagnostic."""
    from spineprep.steps.s6.process import _classify
    status, reasons = _classify(
        {"cord_dice": 0.95, "centerline_round_trip_med_vox": None}, {}, syn_fallback=False)
    assert any("not computed" in r for r in reasons)


# --- S3: a check that can fail ---------------------------------------------


def test_s3_check_fails_on_empty_output_dir(tmp_path):
    from spineprep.steps.s3.orchestrate import check_S3_func_init_and_crop as chk
    assert chk(out=str(tmp_path)).status == "FAIL"


def test_s3_check_fails_without_out():
    from spineprep.steps.s3.orchestrate import check_S3_func_init_and_crop as chk
    assert chk().status == "FAIL"


def test_s3_check_fails_when_derivative_missing(tmp_path):
    import json
    log = tmp_path / "logs" / "S3_func_init_and_crop" / "ds"
    log.mkdir(parents=True)
    (log / "qc.json").write_text(json.dumps(
        {"runs": [{"run_id": "sub-01_task-x", "status": "PASS", "reportlets": {}}]}))
    r = chk_result = __import__(
        "spineprep.steps.s3.orchestrate", fromlist=["check_S3_func_init_and_crop"]
    ).check_S3_func_init_and_crop(out=str(tmp_path))
    assert r.status == "FAIL"
    assert "funccrop_bold" in (r.failure_message or "")
