"""Runtime instrumentation and the benchmark analysis.

Timing was added 2026-07-21. Before it, the only timing field in the pipeline
was S9's `smoothing_runtime_s`, which read 0.0 on all 450 cohort runs because
smoothing is disabled -- so there was effectively no timing data, and none could
be recovered from file mtimes (S2/S3/S7 write all nine dataset files in one
burst, showing a 0.0-minute span).

The tests below pin the properties that make a timing number trustworthy:
tool time is captured automatically, resumed and failed runs are excluded, and
latency is never pooled with throughput.
"""
import json
import time

import pytest

from spineprep.lib.timing import (
    add_tool_time,
    resumed_timing,
    time_step,
    timed_step,
)


# --- the timing primitive -------------------------------------------------


def test_wall_and_tool_are_recorded():
    with time_step() as t:
        time.sleep(0.02)
        add_tool_time(0.01)
    assert t["wall_s"] >= 0.02
    assert t["tool_s"] == pytest.approx(0.01, abs=1e-6)
    assert t["n_tool_calls"] == 1


def test_overhead_is_wall_minus_tool():
    with time_step() as t:
        time.sleep(0.05)
        add_tool_time(0.01)
    assert t["overhead_s"] == pytest.approx(t["wall_s"] - t["tool_s"], abs=0.01)


def test_concurrent_tool_time_is_flagged_not_clamped():
    """tool_s > wall_s means subprocesses ran in parallel, so "overhead" has no
    meaning. It must read None rather than a clamped 0 that an analysis would
    happily average -- the coercion that made S9 report an unmeasured FWHM as 0.
    """
    with time_step() as t:
        add_tool_time(10.0)          # far more than the block's wall time
    assert t["concurrent_tool_calls"] is True
    assert t["overhead_s"] is None


def test_accumulator_does_not_leak_between_runs():
    with time_step() as a:
        add_tool_time(1.0)
    with time_step() as b:
        pass
    assert a["tool_s"] == 1.0
    assert b["tool_s"] == 0.0


def test_decorator_injects_timing_into_the_run_record():
    @timed_step
    def fake():
        add_tool_time(0.02)
        return {"status": "PASS"}
    rec = fake()
    assert "timing" in rec and rec["timing"]["tool_s"] == pytest.approx(0.02, abs=1e-6)
    assert rec["timing"]["resumed"] is False


def test_decorator_times_early_failure_returns():
    """Steps have many early `return {...}` exits; all must be timed."""
    @timed_step
    def fails_early():
        return {"status": "FAIL", "reason": "missing input"}
    rec = fails_early()
    assert "timing" in rec


def test_decorator_reads_worker_count_from_env(monkeypatch):
    monkeypatch.setenv("SPINEPREP_N_WORKERS", "12")

    @timed_step
    def fake():
        return {}
    assert fake()["timing"]["n_workers"] == 12


def test_decorator_is_harmless_on_non_dict_returns():
    @timed_step
    def odd():
        return "not a dict"
    assert odd() == "not a dict"


def test_resumed_timing_is_marked():
    t = resumed_timing()
    assert t["resumed"] is True and t["wall_s"] == 0.0


def test_resumed_and_live_records_share_a_key_set():
    """Analysis reads both; divergent keys would silently drop columns."""
    with time_step() as live:
        pass
    assert set(live) == set(resumed_timing())


# --- run_command captures tool time automatically -------------------------


def test_run_command_accumulates_tool_time():
    from spineprep.lib.run import run_command
    with time_step() as t:
        run_command(["sleep", "0.15"])
    assert t["n_tool_calls"] == 1
    assert 0.1 < t["tool_s"] < 1.0


def test_failed_tool_call_still_counts_its_time():
    """A run that died late still consumed the time; counting only successes
    would understate it."""
    from spineprep.lib.run import run_command
    with time_step() as t:
        ok, _ = run_command(["false"])
    assert ok is False
    assert t["n_tool_calls"] == 1


# --- the analysis ---------------------------------------------------------


def _qc(tmp_path, step_full, dataset, runs):
    d = tmp_path / "logs" / step_full / dataset
    d.mkdir(parents=True, exist_ok=True)
    (d / "qc.json").write_text(json.dumps({"runs": runs}))


def _rec(run_id, wall, workers, status="PASS", resumed=False):
    return {
        "run_id": run_id, "status": status, "metrics": {"n_volumes": 230},
        "timing": {"wall_s": wall, "tool_s": wall * 0.9,
                   "overhead_s": wall * 0.1, "n_tool_calls": 5,
                   "n_workers": workers, "gpu_slots": None,
                   "load_avg_start": 1.0, "benchmark_mode": None,
                   "concurrent_tool_calls": False, "resumed": resumed},
    }


def test_analysis_excludes_resumed_runs(tmp_path):
    from benchmark.analyze import collect
    _qc(tmp_path, "S6_func_to_anat_registration", "ds", [
        _rec("a", 100.0, 1), _rec("b", 0.0, 1, resumed=True)])
    rows, excl = collect(tmp_path)
    assert len(rows) == 1 and excl["resumed"] == 1


def test_analysis_excludes_failed_runs(tmp_path):
    """A run that died in its first minute is not a measure of step duration."""
    from benchmark.analyze import collect
    _qc(tmp_path, "S6_func_to_anat_registration", "ds", [
        _rec("a", 100.0, 1), _rec("b", 2.0, 1, status="FAIL")])
    rows, excl = collect(tmp_path)
    assert len(rows) == 1 and excl["failed_run"] == 1


def test_analysis_never_pools_latency_with_throughput(tmp_path):
    """The central rule: 1-worker and 12-worker numbers must stay apart."""
    from benchmark.analyze import collect, report
    _qc(tmp_path, "S6_func_to_anat_registration", "ds", [
        _rec("a", 100.0, 1), _rec("b", 400.0, 12)])
    rep = report(*collect(tmp_path))
    assert set(rep["conditions"]) == {"1", "12"}
    assert rep["conditions"]["1"]["per_step"]["S6"]["median_s"] == 100.0
    assert rep["conditions"]["12"]["per_step"]["S6"]["median_s"] == 400.0


def test_analysis_reports_missing_timing_rather_than_zero(tmp_path):
    """Pre-instrumentation output must read as absent, not as instant."""
    from benchmark.analyze import collect, render, report
    d = tmp_path / "logs" / "S6_func_to_anat_registration" / "ds"
    d.mkdir(parents=True)
    (d / "qc.json").write_text(json.dumps({"runs": [{"run_id": "a", "status": "PASS"}]}))
    rows, excl = collect(tmp_path)
    assert rows == [] and excl["no_timing_record"] == 1
    assert "No timing records found" in render(report(rows, excl))


def test_analysis_marks_volume_scaling_steps(tmp_path):
    """S4/S5/S8/S9 grow with run length; the rest are flat. A single
    seconds-per-volume normaliser across all steps would be wrong."""
    from benchmark.analyze import collect, report
    _qc(tmp_path, "S4_func_motion_correction", "ds", [_rec("a", 300.0, 1)])
    _qc(tmp_path, "S6_func_to_anat_registration", "ds", [_rec("a", 400.0, 1)])
    rep = report(*collect(tmp_path))
    steps = rep["conditions"]["1"]["per_step"]
    assert steps["S4"]["scales_with_volumes"] is True
    assert steps["S6"]["scales_with_volumes"] is False


def test_analysis_reports_per_dataset(tmp_path):
    """Heterogeneity is the signal for runtime as much as for quality."""
    from benchmark.analyze import collect, report
    _qc(tmp_path, "S6_func_to_anat_registration", "d1", [_rec("a", 100.0, 1)])
    _qc(tmp_path, "S6_func_to_anat_registration", "d2", [_rec("b", 300.0, 1)])
    rep = report(*collect(tmp_path))
    assert rep["per_dataset"]["d1"]["median_s"] == 100.0
    assert rep["per_dataset"]["d2"]["median_s"] == 300.0


# --- latency harness selection --------------------------------------------


def test_latency_picks_span_distinct_conditions(tmp_path):
    """Three picks of the same length and mode would be repeats, not coverage."""
    from benchmark.latency import pick_runs
    runs9 = [{"run_id": f"r{i}", "status": "PASS", "metrics": {"n_volumes": nv}}
             for i, nv in enumerate((115, 230, 359, 200))]
    _qc(tmp_path, "S9_primary_functional_derivatives", "ds", runs9)
    d = tmp_path / "logs" / "S5_func_distortion_correction" / "ds"
    d.mkdir(parents=True, exist_ok=True)
    (d / "qc.json").write_text(json.dumps({"runs": [
        {"run_id": "r0", "mode": "none"}, {"run_id": "r1", "mode": "topup"},
        {"run_id": "r2", "mode": "none"}, {"run_id": "r3", "mode": "topup"}]}))
    picks = pick_runs(tmp_path)
    assert len(picks) == 3
    assert {p["role"] for p in picks} == {"short", "long", "topup"}
    assert len({p["run_id"] for p in picks}) == 3, "picks must be distinct runs"
    assert any(p["mode"] == "topup" for p in picks)


def test_latency_handles_a_cohort_with_no_topup(tmp_path):
    from benchmark.latency import pick_runs
    _qc(tmp_path, "S9_primary_functional_derivatives", "ds", [
        {"run_id": "r0", "status": "PASS", "metrics": {"n_volumes": 115}},
        {"run_id": "r1", "status": "PASS", "metrics": {"n_volumes": 359}}])
    picks = pick_runs(tmp_path)
    assert [p["role"] for p in picks] == ["short", "long"]


def test_no_step_calls_subprocess_run_directly():
    """Direct subprocess.run bypasses tool-time accounting.

    Regression for the 2026-07-21 cohort run: S4 reported a 0% tool share
    despite spending nearly all its wall-clock inside sct_fmri_moco, because it
    called subprocess.run directly rather than through the timed wrapper. Five
    steps had the same gap. External tools must be invoked via
    lib.run.run_command or lib.timing.timed_subprocess_run.
    """
    import re
    from pathlib import Path
    # timing.py defines the wrapper; run.py IS the timed path and calls
    # add_tool_time itself. Anything else must either use a timed wrapper or
    # carry an explicit `# notimed:` marker giving the reason -- so exemptions
    # are auditable in the source rather than hidden in this test.
    exempt_files = {"timing.py", "run.py"}
    offenders = []
    for p in sorted(Path("src/spineprep").rglob("*.py")):
        if p.name in exempt_files:
            continue
        for i, line in enumerate(p.read_text().splitlines(), 1):
            if re.search(r"(?<!timed_)subprocess\.run\(", line) and "notimed:" not in line:
                offenders.append(f"{p}:{i}")
    assert not offenders, (
        "these call subprocess.run directly and so are invisible to the "
        "benchmark:\n  " + "\n  ".join(offenders))


def test_timed_subprocess_records_even_on_failure():
    from spineprep.lib.timing import time_step, timed_subprocess_run
    with time_step() as t:
        timed_subprocess_run(["false"], capture_output=True)
    assert t["n_tool_calls"] == 1
