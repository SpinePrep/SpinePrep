"""The endpoint registry must enforce naming and applicability, not suggest it.

Naming drift is what makes a multi-dataset analysis unreproducible: one
quantity acquires three spellings and two tables stop joining. These tests
check the rules against the registry itself, so a new metric that breaks a
convention fails here rather than in a figure six weeks later.
"""
import re

import pytest

from analysis.endpoints import (
    CANONICAL_COLUMNS,
    EndpointError,
    FAMILIES,
    METRICS,
    TIERS,
    applicable_metrics,
    parcel_name,
    record,
    validate_metric,
    validate_tier,
)


# --- naming rules, checked against every registered metric ----------------


@pytest.mark.parametrize("name", sorted(METRICS))
def test_metric_names_are_snake_case(name):
    assert re.fullmatch(r"[a-z0-9_]+", name), f"{name} is not snake_case"


@pytest.mark.parametrize("name", sorted(METRICS))
def test_units_and_suffix_agree(name):
    m = METRICS[name]
    if m.units in ("mm", "s", "pct", "frac"):
        assert name.endswith(("_mm", "_s", "_pct", "_frac")), \
            f"{name} declares units {m.units} but has no unit suffix"
    if name.endswith(("_mm", "_pct")):
        assert m.units, f"{name} has a unit suffix but declares no units"


@pytest.mark.parametrize("name", sorted(METRICS))
def test_counts_use_the_n_prefix(name):
    if METRICS[name].units == "count":
        assert name.startswith("n_"), f"{name} is a count but lacks the n_ prefix"


@pytest.mark.parametrize("name", sorted(METRICS))
def test_every_metric_declares_a_valid_family_and_repeat_axis(name):
    m = METRICS[name]
    assert m.family in FAMILIES
    assert m.needs_repeats in (None, "split", "run", "session")


def test_confidence_bounds_are_paired_with_their_metric():
    """A _ci_lo with no _ci_hi, or no base metric, is a naming error."""
    for name in METRICS:
        if name.endswith("_ci_lo"):
            base = name[: -len("_ci_lo")]
            assert base in METRICS, f"{name} has no base metric {base}"
            assert base + "_ci_hi" in METRICS, f"{base} has a lower bound but no upper"


def test_no_two_metrics_describe_the_same_thing():
    descs = [m.description.lower().strip().rstrip(".") for m in METRICS.values()]
    assert len(descs) == len(set(descs)), "duplicate metric descriptions"


# --- record() enforcement -------------------------------------------------


def test_record_emits_the_canonical_columns():
    rows = record([], dataset="d", subject="01", session=None, run_id="r",
                  tier="cord", parcel="cord", metric="tsnr_median",
                  value=22.5, n=460)
    assert set(CANONICAL_COLUMNS).issubset(rows[0])


def test_unregistered_metric_is_rejected():
    with pytest.raises(EndpointError, match="unregistered"):
        record([], dataset="d", subject="01", session=None, run_id="r",
               tier="cord", parcel="cord", metric="tsnr_avg", value=1.0)


def test_typo_suggests_the_registered_spelling():
    """A near-miss should name the real metric, not just fail."""
    with pytest.raises(EndpointError, match="tsnr_"):
        record([], dataset="d", subject="01", session=None, run_id="r",
               tier="cord", parcel="cord", metric="tsnr_middle", value=1.0)


def test_unknown_tier_is_rejected():
    with pytest.raises(EndpointError, match="unknown tier"):
        record([], dataset="d", subject="01", session=None, run_id="r",
               tier="segment", parcel="x", metric="tsnr_median", value=1.0)


def test_focality_is_rejected_outside_the_cord_tier():
    """Focality describes how an effect spreads ACROSS the cord; inside a
    sub-parcel it has no meaning."""
    with pytest.raises(EndpointError, match="not defined on tier"):
        record([], dataset="d", subject="01", session=None, run_id="r",
               tier="gmhorn", parcel="gm-dorsal-L", metric="focality_gini",
               value=0.3)


def test_laterality_is_rejected_on_the_cord_tier():
    with pytest.raises(EndpointError, match="not defined on tier"):
        record([], dataset="d", subject="01", session=None, run_id="r",
               tier="cord", parcel="cord", metric="laterality_index", value=0.1)


def test_focality_is_accepted_on_the_cord_tier():
    rows = record([], dataset="d", subject="01", session=None, run_id="r",
                  tier="cord", parcel="cord", metric="focality_gini",
                  value=0.42, n=460)
    assert rows[0]["value"] == 0.42


# --- parcel naming --------------------------------------------------------


def test_parcel_names_disambiguate_spinal_from_vertebral():
    """C5 alone is ambiguous between two different parcellations."""
    assert parcel_name("spinallevel", 5) == "spinal-5"
    assert parcel_name("vertlevel", 5) == "vert-5"
    assert parcel_name("spinallevel", 5) != parcel_name("vertlevel", 5)


def test_sided_parcels_require_a_side():
    assert parcel_name("hemicord", None, "L") == "hemicord-L"
    assert parcel_name("gmhorn", "dorsal", "R") == "gm-dorsal-R"
    with pytest.raises(EndpointError):
        parcel_name("hemicord", None)
    with pytest.raises(EndpointError):
        parcel_name("gmhorn", "dorsal")


def test_gmhorn_rejects_an_unknown_subdivision():
    with pytest.raises(EndpointError):
        parcel_name("gmhorn", "lateral", "L")


# --- applicability mirrors what the cohort actually has -------------------


def test_task_metrics_are_withheld_from_resting_datasets():
    rest = applicable_metrics(has_task=False, repeat_axis="split")
    assert "effect_d" not in rest and "focality_gini" not in rest
    assert "tsnr_median" in rest and "splithalf_r_sb" in rest


def test_split_half_is_available_everywhere():
    """It needs one run, which is why it is the reliability backbone."""
    for axis in ("split", "run", "session"):
        assert "splithalf_r_sb" in applicable_metrics(has_task=False, repeat_axis=axis)


def test_icc_requires_session_level_repeats():
    """Only ds004926 has true between-session test-retest."""
    assert "icc_2_1" not in applicable_metrics(has_task=True, repeat_axis="run")
    assert "icc_2_1" in applicable_metrics(has_task=True, repeat_axis="session")


def test_applicability_is_monotone_in_repeat_richness():
    """More repeats can only ever add metrics, never remove them."""
    prev = set()
    for axis in (None, "split", "run", "session"):
        cur = set(applicable_metrics(has_task=True, repeat_axis=axis))
        assert prev.issubset(cur), f"metrics lost when moving to {axis}"
        prev = cur


def test_every_tier_documents_its_reliability_caveat():
    """Tier 4 is 8 voxels; a framework that hides that is misleading."""
    for name, t in TIERS.items():
        assert t.reliability_caveat, f"{name} has no caveat"
    assert "8-9" in TIERS["gmhorn"].reliability_caveat
