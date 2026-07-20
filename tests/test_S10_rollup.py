"""S10's release verdict must reflect the data, not just the HTML.

Regression for the 2026-07-19 audit: S10's status came from exactly two things
-- whether the per-subject HTML rendered, and whether S10 itself threw. Upstream
run failures never entered the verdict. The real release proved it: qc.json said
"status": "PASS" while its own run_inventory.tsv held 18 FAILed and 410 WARN
runs out of 469. A release gate that certifies formatting rather than data is
not a QC gate.

`missing_step_qc_count` was separately the literal 0 -- published as if measured
while nothing computed it, and its two policy thresholds were never read.
"""
import pytest

from spineprep.steps.s10.orchestrate import (
    _count_missing_step_qc,
    _rollup_run_status,
    _run_key,
)

_STEPS = ("S3", "S4", "S5", "S6", "S7", "S8", "S9")


def _rec(ds, sub, run, step, status):
    return {"dataset_key": ds, "subject": sub, "session": None,
            "run_id": run, "step": step, "status": status}


def _full_run(ds, sub, run, status="PASS", upto=None):
    return [_rec(ds, sub, run, s, status) for s in (upto or _STEPS)]


def test_rollup_counts_each_run_once():
    recs = _full_run("ds1", "01", "r1") + _full_run("ds1", "01", "r2")
    assert _rollup_run_status(recs) == {"PASS": 2, "WARN": 0, "FAIL": 0}


def test_rollup_takes_the_worst_status_across_steps():
    recs = _full_run("ds1", "01", "r1")
    recs.append(_rec("ds1", "01", "r1", "S6", "FAIL"))
    assert _rollup_run_status(recs)["FAIL"] == 1


def test_rollup_warn_beats_pass_but_loses_to_fail():
    recs = _full_run("ds1", "01", "r1")
    recs.append(_rec("ds1", "01", "r1", "S5", "WARN"))
    assert _rollup_run_status(recs) == {"PASS": 0, "WARN": 1, "FAIL": 0}


def test_rollup_does_not_merge_same_subject_across_datasets():
    """sub-01 exists in six datasets in the real cohort."""
    recs = _full_run("ds1", "01", "r1") + _full_run("ds2", "01", "r1")
    assert sum(_rollup_run_status(recs).values()) == 2


def test_run_key_includes_dataset():
    a = _run_key({"dataset_key": "ds1", "subject": "01", "run_id": "r1"})
    b = _run_key({"dataset_key": "ds2", "subject": "01", "run_id": "r1"})
    assert a != b


def test_rollup_ignores_non_participant_steps():
    """S1 is dataset-level and S2 anatomy-level; neither is per-run."""
    recs = _full_run("ds1", "01", "r1")
    recs.append(_rec("ds1", "01", "r1", "S1", "FAIL"))
    recs.append(_rec("ds1", "01", "r1", "S10", "FAIL"))
    assert _rollup_run_status(recs)["FAIL"] == 0


# --- missing step QC ------------------------------------------------------


def test_no_missing_qc_for_a_complete_run():
    assert _count_missing_step_qc(_full_run("ds1", "01", "r1")) == 0


def test_a_gap_below_the_high_water_mark_is_missing():
    """S3, S4, then S6 -- S5 silently produced nothing."""
    recs = [_rec("ds1", "01", "r1", s, "PASS") for s in ("S3", "S4", "S6")]
    assert _count_missing_step_qc(recs) == 1


def test_steps_after_a_stop_are_not_counted_missing():
    """A run that FAILed at S5 legitimately has no S6-S9 records."""
    recs = [_rec("ds1", "01", "r1", s, "PASS") for s in ("S3", "S4", "S5")]
    assert _count_missing_step_qc(recs) == 0


def test_missing_qc_is_measured_not_hardcoded():
    """It used to be the literal 0 in the metrics dict."""
    recs = [_rec("ds1", "01", "r1", s, "PASS") for s in ("S3", "S7")]
    assert _count_missing_step_qc(recs) > 0


def test_policy_declares_the_rollup_thresholds():
    import yaml
    from pathlib import Path
    thr = yaml.safe_load(
        Path("policy/S10_qc_aggregation_and_release.yaml").read_text())["qc_thresholds"]
    assert thr["pass_max_run_fail_fraction"] < thr["warn_max_run_fail_fraction"]


def test_dashboard_does_not_merge_subjects_across_datasets():
    """The collision that hid 117 subjects: sub-01 in two datasets is two rows."""
    from spineprep.steps.s10 import process as s10p
    recs = []
    for ds, st in (("ds_A", "FAIL"), ("ds_B", "PASS")):
        recs.append({"step": "S4", "dataset_key": ds, "subject": "01",
                     "session": None, "run_id": "01_run-01", "status": st,
                     "failure_message": None, "metrics": {}})
    matrix = s10p._build_group_dashboard_data(recs, policy={})["matrix"]
    assert len(matrix.index) == 2, "two datasets' sub-01 must not merge"
    assert matrix.loc["ds_A / 01", "S4"] == "FAIL"
    assert matrix.loc["ds_B / 01", "S4"] == "PASS", \
        "a bad sub-01 in one dataset must not paint another dataset's sub-01"
