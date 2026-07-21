"""Estimators behind the endpoints, validated against published values.

The governing rule, and the reason many of these tests assert `is None`:
an estimator must return None rather than a number when the input cannot
support the statistic. A plausible-looking value computed from nothing survives
into a figure and is indistinguishable from a real one -- the exact failure
class this project spent the week removing from the pipeline.
"""
import math

import numpy as np
import pytest

from analysis.estimators import (
    between_subject_variance_fraction,
    cohens_d,
    detection_fraction,
    dice,
    gini,
    icc,
    laterality_index,
    median_iqr,
    one_sample_t,
    pearson_r,
    spearman_brown,
    split_half,
    tsnr,
)

# Shrout & Fleiss (1979) Table 1. Published: ICC(1,1)=.17, (2,1)=.29, (3,1)=.71
SF = np.array([[9, 2, 5, 8], [6, 1, 3, 2], [8, 4, 6, 8],
               [7, 1, 2, 6], [10, 5, 6, 9], [6, 2, 4, 7]], float)


# --- ICC: validated, not assumed -----------------------------------------


@pytest.mark.parametrize("form,published", [("1,1", 0.17), ("2,1", 0.29), ("3,1", 0.71)])
def test_icc_matches_shrout_and_fleiss(form, published):
    assert icc(SF, form=form)["icc"] == pytest.approx(published, abs=0.005)


def test_icc_forms_are_ordered_as_theory_requires():
    """3,1 treats occasions as fixed and so cannot be below 2,1."""
    v = {f: icc(SF, form=f)["icc"] for f in ("1,1", "2,1", "3,1")}
    assert v["3,1"] > v["2,1"] > v["1,1"]


def test_icc_reports_a_confidence_interval_bracketing_the_estimate():
    r = icc(SF, form="2,1")
    assert r["ci_lo"] is not None and r["ci_hi"] is not None
    assert r["ci_lo"] < r["icc"] < r["ci_hi"]


def test_icc_interval_is_wide_at_small_n():
    """n=6 gives an interval spanning most of the range -- which is why the
    point estimate alone is not reportable for our 11-18 subject datasets."""
    r = icc(SF, form="2,1")
    assert (r["ci_hi"] - r["ci_lo"]) > 0.5


def test_icc_of_identical_repeats_is_one():
    m = np.array([[1., 1.], [2., 2.], [3., 3.], [4., 4.]])
    assert icc(m, form="2,1")["icc"] == pytest.approx(1.0, abs=1e-9)


def test_icc_returns_none_with_too_few_subjects_or_repeats():
    assert icc(np.array([[1., 2.]]), form="2,1")["icc"] is None
    assert icc(np.array([[1.], [2.], [3.]]), form="2,1")["icc"] is None


def test_icc_drops_rows_with_missing_values():
    m = np.vstack([SF, [np.nan, 1, 2, 3]])
    assert icc(m, form="2,1")["n"] == SF.shape[0]


def test_icc_rejects_an_unknown_form():
    with pytest.raises(ValueError):
        icc(SF, form="4,1")


# --- split-half -----------------------------------------------------------


def test_spearman_brown_lengthens_a_half_correlation():
    assert spearman_brown(0.5) == pytest.approx(2 / 3)
    assert spearman_brown(0.0) == 0.0
    assert spearman_brown(1.0) == pytest.approx(1.0)


def test_spearman_brown_is_undefined_at_minus_one():
    assert spearman_brown(-1.0) is None
    assert spearman_brown(None) is None


def test_split_half_recovers_a_strong_signal():
    t = np.arange(200)
    sig = np.sin(t / 5.0)
    assert split_half(sig, "oddeven") > 0.9


def test_split_half_of_noise_is_near_zero():
    rng = np.random.default_rng(0)
    r = split_half(rng.standard_normal(400), "oddeven")
    assert abs(r) < 0.2


def test_oddeven_split_resists_drift_better_than_halves():
    """A first/second-half split confounds reliability with scanner drift."""
    t = np.arange(300)
    drifting = np.sin(t / 4.0) + t * 0.05      # strong linear drift
    assert split_half(drifting, "oddeven") > split_half(drifting, "halves")


def test_split_half_returns_none_on_short_or_flat_input():
    assert split_half([1, 2, 3]) is None
    assert split_half([5.0] * 50) is None


# --- variance decomposition ----------------------------------------------


def test_between_subject_fraction_is_high_when_subjects_differ():
    m = np.array([[1., 1.1], [5., 5.1], [9., 9.1]])
    assert between_subject_variance_fraction(m) > 0.95


def test_between_subject_fraction_matches_theory_under_pure_noise():
    """The reliability paradox: a task that drives everyone identically
    suppresses the variance ICC depends on.

    Tested across seeds rather than on one draw. Under pure noise the expected
    fraction is df_between/df_total = (n-1)/(nk-1); for 20x2 that is 0.487. A
    single seed spans 0.20-0.76, so asserting on one would test the seed, not
    the estimator -- an earlier version of this test did exactly that and
    failed on an unlucky draw.
    """
    import statistics as st
    vals = [between_subject_variance_fraction(
                5.0 + np.random.default_rng(s).standard_normal((20, 2)) * 2.0)
            for s in range(200)]
    expected = (20 - 1) / (20 * 2 - 1)
    assert st.median(vals) == pytest.approx(expected, abs=0.05)


# --- effect ---------------------------------------------------------------


def test_cohens_d_and_t_agree_by_sqrt_n():
    v = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert one_sample_t(v) == pytest.approx(cohens_d(v) * math.sqrt(len(v)))


def test_cohens_d_is_none_without_variance():
    assert cohens_d([3.0] * 10) is None
    assert cohens_d([1.0]) is None


def test_detection_fraction_counts_subjects_over_threshold():
    assert detection_fraction([0.1, 0.5, 0.9, 1.5], 0.4) == pytest.approx(0.75)
    assert detection_fraction([], 0.0) is None


# --- focality -------------------------------------------------------------


def test_gini_is_zero_for_a_uniform_effect():
    assert gini([5, 5, 5, 5]) == pytest.approx(0.0, abs=1e-9)


def test_gini_is_maximal_for_a_point_effect():
    """Upper bound is (n-1)/n, not 1, for finite n."""
    assert gini([0, 0, 0, 100]) == pytest.approx(0.75)


def test_gini_increases_with_concentration():
    assert gini([1, 1, 1, 7]) > gini([2, 2, 3, 3])


def test_gini_clips_negatives_rather_than_failing():
    """Deactivation is not negative concentration; focality asks how tightly
    the positive effect packs."""
    assert gini([-5, 0, 0, 10]) == pytest.approx(gini([0, 0, 0, 10]))


def test_gini_returns_none_with_no_positive_signal():
    assert gini([0, 0, 0, 0]) is None
    assert gini([-1, -2]) is None


# --- spatial overlap ------------------------------------------------------


def test_dice_known_values():
    assert dice([1, 1, 0, 0], [1, 1, 0, 0]) == pytest.approx(1.0)
    assert dice([1, 1, 0, 0], [0, 0, 1, 1]) == pytest.approx(0.0)
    assert dice([1, 1, 0, 0], [1, 0, 0, 0]) == pytest.approx(2 / 3)


def test_dice_of_two_empty_maps_is_none_not_zero():
    """Zero would claim 'no overlap'; the truth is 'nothing to compare'."""
    assert dice([0, 0], [0, 0]) is None


def test_dice_rejects_shape_mismatch():
    with pytest.raises(ValueError):
        dice([1, 0, 1], [1, 0])


# --- laterality -----------------------------------------------------------


def test_laterality_index_known_values():
    assert laterality_index(8, 2) == pytest.approx(0.6)
    assert laterality_index(5, 5) == pytest.approx(0.0)
    assert laterality_index(0, 4) == pytest.approx(-1.0)


def test_laterality_is_none_when_uninterpretable():
    assert laterality_index(0, 0) is None
    assert laterality_index(-1, 3) is None
    assert laterality_index(None, 1) is None


# --- quality --------------------------------------------------------------


def test_tsnr_is_mean_over_sd():
    rng = np.random.default_rng(2)
    m = 100.0 + rng.standard_normal((50, 200)) * 5.0
    v = tsnr(m)
    assert v is not None
    assert np.nanmedian(v) == pytest.approx(20.0, rel=0.2)


def test_tsnr_marks_flat_voxels_as_nan_not_infinite():
    m = np.vstack([np.full(20, 7.0), np.arange(20, dtype=float)])
    v = tsnr(m)
    assert math.isnan(v[0]) and math.isfinite(v[1])


def test_median_iqr_handles_empty_input():
    assert median_iqr([]) == (None, None)
    med, iqr = median_iqr([1, 2, 3, 4])
    assert med == pytest.approx(2.5) and iqr == pytest.approx(1.5)


# --- the governing rule ---------------------------------------------------


def test_every_estimator_returns_none_rather_than_a_wrong_number():
    """Degenerate input must never yield a plausible-looking value."""
    assert pearson_r([1, 2], [1, 2]) is None          # too few points
    assert pearson_r([1, 1, 1], [1, 2, 3]) is None    # zero variance
    assert split_half([1, 2]) is None
    assert cohens_d([1]) is None
    assert gini([1]) is None
