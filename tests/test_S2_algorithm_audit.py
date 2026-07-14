"""Regression tests for the S2 algorithm-audit fixes (2026-07-13).

Covers:
- F4: TotalSpineSeg labeling sanity check (catches disc mislabel signatures).
- F1: per-level PAM50 cord Dice degrades gracefully to None on missing inputs.
See .claude/specs/s2-algorithm-audit.md.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from spineprep.steps.s2.segment import _check_labeling_sanity
from spineprep.steps.s2.register import compute_pam50_cord_dice_per_level


# --- F4: labeling sanity ----------------------------------------------------

def test_sanity_ok_on_contiguous_monotonic_discs():
    # C2/C3=3 .. C7/T1=8, S-I index increasing with disc number (RPI).
    r = _check_labeling_sanity([(3, 10), (4, 20), (5, 30), (6, 40), (7, 50), (8, 60)])
    assert r["ok"] is True and r["internal_gaps"] == 0 and r["n_discs"] == 6


def test_sanity_flags_internal_gap():
    r = _check_labeling_sanity([(3, 10), (4, 20), (6, 40)])  # missing 5
    assert r["ok"] is False and r["internal_gaps"] == 1
    assert any("missing" in reason for reason in r["reasons"])


def test_sanity_ok_on_monotonic_DECREASING_si():
    # S-I index decreasing with disc number is fine — direction depends on
    # image orientation; only a reversal is a mislabel. (Regression: the first
    # version assumed increasing and false-flagged every real subject.)
    r = _check_labeling_sanity([(3, 417), (4, 370), (5, 324), (6, 278), (7, 232)])
    assert r["ok"] is True


def test_sanity_flags_non_monotonic_si_ordering():
    # disc 4 sits ABOVE disc 3 in S-I (index 5 < 10) — a mislabel signature.
    r = _check_labeling_sanity([(3, 10), (4, 5), (5, 30), (6, 40)])
    assert r["ok"] is False
    assert any("non-monotonic" in reason for reason in r["reasons"])


def test_sanity_flags_too_few_discs():
    r = _check_labeling_sanity([(3, 10), (4, 20)])
    assert r["ok"] is False and any("too few" in reason for reason in r["reasons"])


def test_sanity_empty_is_too_few_not_crash():
    r = _check_labeling_sanity([])
    assert r["ok"] is False and r["n_discs"] == 0


# --- F1: per-level Dice graceful failure ------------------------------------

def test_per_level_dice_returns_none_on_missing_warp(tmp_path):
    # Non-existent warp / seg must return None, never raise.
    out = compute_pam50_cord_dice_per_level(
        native_cord_seg=tmp_path / "nope_cord.nii.gz",
        warp_template2anat=tmp_path / "nope_warp.nii.gz",
        work_dir=tmp_path / "wd",
    )
    assert out is None
