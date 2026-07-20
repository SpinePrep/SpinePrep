"""S10's paper-facing text must match what the pipeline actually does.

Regressions for the 2026-07-19 audit. Two classes of defect:

1. The per-subject report and participants.tsv recommended EXCLUDING subjects
   on "mean FD > 0.5 mm (Kaptan 2023)". Wrong three ways: Kaptan 2023 computes
   no FD (it censors on DVARS/refRMS at 2 SD); 0.5 mm is Power 2012's BRAIN
   value; and it sits at this cohort's own FD median, flagging 265/467 runs.

2. The methods boilerplate is published as "reuse verbatim" but described FD
   censoring that was off, SyN as the S5 default (now `none`), the S6 recipe as
   "Kaptan 2023" (the code retracts this), CSF as a top-20% mean (it is 5-PC
   aCompCor), and smoothing + PAM50 4D output (both disabled).
"""
import tempfile
from pathlib import Path

import pytest

from spineprep.steps.s10.process import _build_methods_manifest
from spineprep.steps.s10.reports import _recommendation


# --- 1. FD must not drive an exclusion recommendation --------------------


def test_high_fd_alone_does_not_trigger_review():
    """A clean run with high FD must still read 'include'."""
    rec, reason = _recommendation(mean_fd=3.0, median_tsnr=20.0, n_failed=0,
                                  fd_thr=0.5, tsnr_thr=5.0)
    assert rec == "include"
    assert "FD" not in reason


def test_recommendation_never_cites_kaptan_for_fd():
    rec, reason = _recommendation(mean_fd=9.9, median_tsnr=20.0, n_failed=0,
                                  fd_thr=0.5, tsnr_thr=5.0)
    assert "Kaptan" not in reason


def test_low_tsnr_still_triggers_review():
    """The legitimate criteria must keep working."""
    rec, reason = _recommendation(mean_fd=0.1, median_tsnr=2.0, n_failed=0,
                                  fd_thr=0.5, tsnr_thr=5.0)
    assert rec == "review"
    assert "tSNR" in reason


def test_failed_runs_still_trigger_review():
    rec, reason = _recommendation(mean_fd=0.1, median_tsnr=20.0, n_failed=1,
                                  fd_thr=0.5, tsnr_thr=5.0)
    assert rec == "review"
    assert "failed" in reason


def test_failed_runs_plus_low_tsnr_escalates_to_exclude():
    rec, _ = _recommendation(mean_fd=0.1, median_tsnr=2.0, n_failed=2,
                             fd_thr=0.5, tsnr_thr=5.0)
    assert rec == "exclude"


# --- 2. The methods boilerplate must track live policy -------------------


@pytest.fixture(scope="module")
def methods_md():
    tmp = Path(tempfile.mkdtemp())
    return _build_methods_manifest(Path("."), {}, {},
                                   tmp / "m.md", tmp / "m.tex", tmp / "m.html")


@pytest.mark.parametrize("claim", [
    "FD > 0.5",                 # FD censoring is off
    "Kaptan 2023 recipe",       # S6 recipe is SpinePrep's own
    "top-20%-variance",         # CSF is 5-PC aCompCor, not a top-20% mean
    "PAM50-space smoothed BOLD",  # neither smoothing nor PAM50 4D is on
])
def test_boilerplate_drops_retracted_claims(methods_md, claim):
    assert claim not in methods_md, f"boilerplate still claims: {claim}"


@pytest.mark.parametrize("placeholder", ["{fd_thr}", "{sigma_str}", "{s5_fallback}",
                                         "{s9_desc}", "{outlier_desc}"])
def test_boilerplate_has_no_unrendered_placeholders(methods_md, placeholder):
    assert placeholder not in methods_md


def test_boilerplate_states_the_real_s5_default(methods_md):
    assert "fallback is `none`" in methods_md


def test_boilerplate_states_smoothing_is_off(methods_md):
    assert "No spatial smoothing is applied" in methods_md


def test_boilerplate_attributes_s6_recipe_to_spineprep(methods_md):
    assert "SpinePrep's" in methods_md and "own" in methods_md


def test_boilerplate_says_fd_does_not_censor(methods_md):
    assert "FD does not censor" in methods_md or "does not censor" in methods_md


def test_every_cited_bib_key_is_defined(methods_md):
    """A dangling @key renders as a broken citation in the paper."""
    import re
    from spineprep.steps.s10 import process as s10p
    src = Path(s10p.__file__).read_text()
    cited = set(re.findall(r"\[@([A-Za-z0-9_]+)\]", methods_md))
    assert cited, "no citations found -- test would be vacuous"
    missing = [k for k in sorted(cited) if f"@article{{{k}," not in src
               and f"@misc{{{k}," not in src and f"@software{{{k}," not in src]
    assert not missing, f"cited but undefined in the bibliography: {missing}"
