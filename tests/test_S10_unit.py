"""Unit tests for S10 QC-aggregation pure helpers.

S10 is the read-only "release" step: it walks per-step qc.json files,
builds a subject x step status matrix, computes pass rates, and writes a
reproducibility receipt + methods boilerplate + references bib. These
tests pin the deterministic, side-effect-free helpers — the parts a
reviewer must trust to reproduce the numbers.
"""
from __future__ import annotations

import re
import shutil

import pytest

from spineprep.steps.s10 import process as s11


# ---------------------------------------------------------------------------
# ALL_STEPS — guards the S2B regression
# ---------------------------------------------------------------------------


def test_all_steps_includes_s2b_denoise():
    """P0 regression: the S2B MP-PCA denoise step must appear in ALL_STEPS,
    otherwise its policy SHA + provenance never reach the release receipt."""
    assert ("S2B", "S2B_func_denoise") in s11.ALL_STEPS
    # And it must sit between S2 and S3 (chain order matters for the matrix).
    shorts = [s for s, _ in s11.ALL_STEPS]
    assert shorts.index("S2") < shorts.index("S2B") < shorts.index("S3")


# ---------------------------------------------------------------------------
# _parse_version_lines
# ---------------------------------------------------------------------------


def test_parse_version_bare_semver():
    """A bare semver-ish line is returned verbatim."""
    assert s11._parse_version_lines("7.1") == "7.1"
    assert s11._parse_version_lines("6.0.5") == "6.0.5"


def test_parse_version_strips_prefix_line():
    """A 'version: X' prefix is stripped and the tail returned."""
    assert s11._parse_version_lines("version: 6.0") == "6.0"
    assert s11._parse_version_lines("FSL version: 6.0.7") == "6.0.7"


def test_parse_version_skips_junk_returns_first_match():
    """Junk lines are skipped; the first version-shaped line wins."""
    text = "loading modules...\nsome banner\n7.1.0\ntrailing noise"
    assert s11._parse_version_lines(text) == "7.1.0"
    # Pure junk -> None.
    assert s11._parse_version_lines("no version here\njust words") is None
    assert s11._parse_version_lines("") is None


# ---------------------------------------------------------------------------
# _norm_subject
# ---------------------------------------------------------------------------


def test_norm_subject_drops_prefix():
    assert s11._norm_subject("sub-01") == "01"
    assert s11._norm_subject("sub-pilot02") == "pilot02"
    # Already-bare label passes through unchanged.
    assert s11._norm_subject("03") == "03"


def test_norm_subject_drops_synthetic_ids():
    """The synthetic per-dataset 'all' row (and friends) must normalise to
    None so it never pollutes participant tables (audit B2/B3)."""
    assert s11._norm_subject("all") is None
    assert s11._norm_subject("sub-all") is None
    assert s11._norm_subject(None) is None
    assert s11._norm_subject("") is None
    assert s11._norm_subject("*") is None


# ---------------------------------------------------------------------------
# _hash_policy_yaml
# ---------------------------------------------------------------------------


def _repo_root() -> "object":
    # tests/ lives at <repo>/tests; the repo root holds the policy/ dir.
    from pathlib import Path
    return Path(__file__).resolve().parents[1]


def test_hash_policy_yaml_is_stable_64hex():
    """SHA256 of an existing policy file is a 64-char hex string and is
    identical across two calls (determinism is the whole point of S10)."""
    root = _repo_root()
    h1 = s11._hash_policy_yaml(root, "S2B_func_denoise")
    assert h1 is not None
    assert re.fullmatch(r"[0-9a-f]{64}", h1), h1
    h2 = s11._hash_policy_yaml(root, "S2B_func_denoise")
    assert h1 == h2


def test_hash_policy_yaml_glob_fallback_for_s8():
    """S8's file is named S8_confounds.yaml but its step full-name is
    S8_confounds_and_physio_regressors; the glob fallback must still find
    it via the S8_* pattern."""
    root = _repo_root()
    h = s11._hash_policy_yaml(root, "S8_confounds_and_physio_regressors")
    assert h is not None
    assert re.fullmatch(r"[0-9a-f]{64}", h)


def test_hash_policy_yaml_missing_returns_none(tmp_path):
    """No policy/ dir and no matching file -> None (S1 has no policy)."""
    assert s11._hash_policy_yaml(tmp_path, "S1_input_verify") is None
    # policy dir exists but no S99_* file matches.
    (tmp_path / "policy").mkdir()
    assert s11._hash_policy_yaml(tmp_path, "S99_does_not_exist") is None


# ---------------------------------------------------------------------------
# _build_references_bib
# ---------------------------------------------------------------------------


def test_build_references_bib_contains_key_entries(tmp_path):
    """The auto-bibliography must carry the denoising (Veraart) and the
    cord-fMRI (Kaptan) references the methods boilerplate cites."""
    out = tmp_path / "CITATION.bib"
    s11._build_references_bib(out)
    text = out.read_text()
    assert "@article{veraart2016," in text
    assert "@article{kaptan2023," in text
    # Spot-check a couple more so a truncated write is caught.
    assert "@article{deleener2018," in text
    assert "@article{eippert2017," in text
    # DOI of the denoising reference is load-bearing for reuse.
    assert "10.1016/j.neuroimage.2016.08.016" in text


# ---------------------------------------------------------------------------
# Status-matrix aggregation (_build_group_dashboard_data)
# ---------------------------------------------------------------------------


def _rec(step, subject, status, ds="ds_A", run_id=None, metrics=None):
    """Minimal flat run record as produced by _flat_run_records."""
    return {
        "step": step,
        "dataset_key": ds,
        "subject": subject,
        "session": None,
        "run_id": run_id or f"{subject}_run-01",
        "status": status,
        "failure_message": None,
        "metrics": metrics or {},
        "reportlets": {},
    }


def test_group_dashboard_matrix_fail_dominates():
    """In a subject x step cell aggregated across runs, FAIL beats WARN
    beats PASS."""
    records = [
        _rec("S4", "01", "PASS", run_id="01_run-01"),
        _rec("S4", "01", "FAIL", run_id="01_run-02"),
        _rec("S4", "02", "PASS", run_id="02_run-01"),
        _rec("S4", "02", "WARN", run_id="02_run-02"),
        _rec("S4", "03", "PASS", run_id="03_run-01"),
    ]
    data = s11._build_group_dashboard_data(records, policy={})
    matrix = data["matrix"]
    # sub-01 has a FAIL run -> cell is FAIL.
    assert matrix.loc["01", "S4"] == "FAIL"
    # sub-02 has WARN but no FAIL -> cell is WARN.
    assert matrix.loc["02", "S4"] == "WARN"
    # sub-03 is all PASS.
    assert matrix.loc["03", "S4"] == "PASS"


def test_group_dashboard_pass_rate_fraction():
    """Per-step pass-rate is the fraction of records whose status == PASS
    (3 PASS out of 5 records -> 0.6)."""
    records = [
        _rec("S4", "01", "PASS", run_id="01_run-01"),
        _rec("S4", "01", "FAIL", run_id="01_run-02"),
        _rec("S4", "02", "PASS", run_id="02_run-01"),
        _rec("S4", "02", "WARN", run_id="02_run-02"),
        _rec("S4", "03", "PASS", run_id="03_run-01"),
    ]
    data = s11._build_group_dashboard_data(records, policy={})
    assert data["pass_rates"]["S4"] == pytest.approx(3 / 5)


def test_group_dashboard_empty_records():
    """No records -> the 'empty' sentinel, not a crash."""
    assert s11._build_group_dashboard_data([], policy={}) == {"empty": True}


# ---------------------------------------------------------------------------
# Version detectors that shell out — light touch only
# ---------------------------------------------------------------------------


def test_detect_mrtrix_version_str_or_none():
    """dwidenoise is present in this env; the detector must return a
    version-shaped string (and never raise)."""
    v = s11._detect_mrtrix_version()
    assert v is None or isinstance(v, str)
    if shutil.which("dwidenoise") and v is not None:
        assert re.match(r"\d+\.\d+", v), v


def test_detect_fsl_version_str_or_none():
    """fslversion is present in this env; detector returns str-or-None and
    never raises."""
    v = s11._detect_fsl_version()
    assert v is None or isinstance(v, str)
    # When present it must not be the env-var banner that B10 fixed.
    if v is not None:
        assert not v.upper().startswith("FSLDIR")


# ---------------------------------------------------------------------------
# reports.py — subject/group report model (redesign 2026-06-23)
# ---------------------------------------------------------------------------

from spineprep.steps.s10 import reports as s10r


def test_recommendation_include_when_clean():
    rec, reason = s10r._recommendation(mean_fd=0.2, median_tsnr=12.0,
                                       n_failed=0, fd_thr=0.5, tsnr_thr=5.0)
    assert rec == "include"
    assert "no failed steps" in reason


def test_recommendation_ignores_high_fd():
    """Updated 2026-07-19: this test previously asserted that high FD triggers
    review, which was the defect. FD had been gated at 0.5 mm and cited to
    Kaptan 2023 -- a paper that computes no FD at all -- and 0.5 mm sits at this
    cohort's own FD median, so it flagged 265/467 runs. FD is now descriptive
    only, matching S4's 2026-07-16 removal of the equivalent gate."""
    rec, reason = s10r._recommendation(mean_fd=0.9, median_tsnr=12.0,
                                       n_failed=0, fd_thr=0.5, tsnr_thr=5.0)
    assert rec == "include"
    assert "FD" not in reason


def test_recommendation_review_on_low_tsnr():
    rec, _ = s10r._recommendation(mean_fd=0.2, median_tsnr=3.0,
                                  n_failed=0, fd_thr=0.5, tsnr_thr=5.0)
    assert rec == "review"


def test_recommendation_exclude_on_fail_plus_metric():
    # a failed run AND a bad metric escalates to exclude. Uses low tSNR as the
    # second criterion; high FD no longer counts as one (see above).
    rec, _ = s10r._recommendation(mean_fd=0.2, median_tsnr=2.0,
                                  n_failed=1, fd_thr=0.5, tsnr_thr=5.0)
    assert rec == "exclude"


def test_worst_status_precedence():
    assert s10r._worst(["PASS", "WARN", "FAIL"]) == "FAIL"
    assert s10r._worst(["PASS", "WARN"]) == "WARN"
    assert s10r._worst(["PASS", "PASS"]) == "PASS"
    assert s10r._worst([]) == "NA"


def test_pick_orders_and_dedupes(tmp_path):
    figs = {"motion_traces": tmp_path / "a.png",
            "tsnr_comparison": tmp_path / "b.png",
            "dvars_plot": tmp_path / "c.png"}
    picked = s10r._pick(figs, ["motion", "tsnr"])
    assert [k for k, _ in picked] == ["motion_traces", "tsnr_comparison"]


def test_step_figs_resolves_by_convention(tmp_path):
    figdir = tmp_path / "sub-01" / "figures"
    figdir.mkdir(parents=True)
    (figdir / "sub-01_task-rest_desc-S4_motion_traces.png").write_bytes(b"x")
    (figdir / "sub-01_task-rest_desc-S4_tsnr_comparison.png").write_bytes(b"x")
    (figdir / "sub-01_task-rest_desc-S5_distortion_effectiveness.png").write_bytes(b"x")
    figs = s10r._step_figs([figdir], "sub-01_task-rest", "S4")
    assert set(figs.keys()) == {"motion_traces", "tsnr_comparison"}


def test_attrition_reconciles_with_fail_drops(tmp_path):
    # 3 runs enter S3; one FAILs at S4 -> S5 has 2; matches the audit invariant.
    recs = []
    def add(step, rid, status):
        recs.append({"dataset_key": "ds", "subject": "01", "session": None,
                     "run_id": rid, "step": step, "status": status, "metrics": {}})
    for rid in ("r1", "r2", "r3"):
        add("S3", rid, "PASS")
    add("S4", "r1", "PASS"); add("S4", "r2", "PASS"); add("S4", "r3", "FAIL")
    add("S5", "r1", "PASS"); add("S5", "r2", "PASS")
    wf = s10r._attrition_waterfall_png(recs, "ds", tmp_path / "att.png")
    assert wf["counts"]["S3"] == 3
    assert wf["counts"]["S5"] == 2
    drop = wf["counts"]["S4"] - wf["counts"]["S5"]
    assert drop == wf["fails"]["S4"] == 1
