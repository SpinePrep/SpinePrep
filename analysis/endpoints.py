#!/usr/bin/env python3
"""Endpoint registry and canonical naming for the SpinePrep analysis.

ANALYSIS module -- not part of the preprocessing toolbox.

Why a registry rather than conventions
--------------------------------------
Naming drift is what makes a multi-dataset analysis unreproducible: the same
quantity acquires three spellings, a unit is dropped from one column, and two
tables stop joining. So metric names are not a convention here, they are data.
Every value this analysis produces must be emitted through ``record()``, which
rejects a metric name that is not registered and a tier/parcel that does not
exist. A typo fails loudly instead of creating a silent fourth spelling.

Naming rules, applied without exception
---------------------------------------
* ``snake_case`` throughout, matching the existing S9 metrics
  (``tsnr_post_median``) and the validation tables (``icc_2_1``).
* A unit suffix wherever a value has one: ``_mm``, ``_s``, ``_pct``, ``_frac``.
  Unitless statistics (correlations, ICC, Dice, d) carry none.
* A statistic suffix where a summary is taken: ``_median``, ``_mean``, ``_iqr``.
* Interval bounds are ``<metric>_ci_lo`` / ``<metric>_ci_hi``, never "lower"
  or "l95".
* Counts start with ``n_``.

Output shape
------------
One tidy long-format table, one row per
(dataset, subject, session, run, tier, parcel, metric). Long format because a
wide table cannot hold four spatial tiers with different parcel counts without
either exploding into hundreds of columns or silently dropping tiers.

Reporting stance, taken from the literature review
--------------------------------------------------
We publish DISTRIBUTIONS, not thresholds. MRIQC's own team states in Nature
Protocols (10.1038/s41596-026-01352-y) that there are no formal guidelines for
what makes a scan usable and that image-quality metrics may not generalise
across sites. So every endpoint here is reported with its spread, and nothing
in this module defines a pass/fail cut.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Spatial tiers (decision Q1-D: nested hierarchy, noise reported per tier)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Tier:
    name: str
    description: str
    typical_n_voxels: str      # measured on the cohort at EPI resolution
    reliability_caveat: str


TIERS: dict[str, Tier] = {
    "cord": Tier(
        "cord", "Whole cord mask in native functional space",
        "~462", "None -- the best-powered tier."),
    "spinallevel": Tier(
        "spinallevel", "PAM50 spinal (nerve-root) level",
        "~50",
        "Coverage varies 4-10 levels per run, so levels are unevenly sampled "
        "across the cohort; n per level must accompany every value."),
    "vertlevel": Tier(
        "vertlevel", "PAM50 vertebral level -- a DIFFERENT parcellation from "
        "spinal level, and not interchangeable with it",
        "~55",
        "Same coverage imbalance as spinal levels."),
    "hemicord": Tier(
        "hemicord", "Left / right half of the cord, split at the midline",
        "~230", "None beyond the cord tier."),
    "gmhorn": Tier(
        "gmhorn", "PAM50 grey-matter parcels: dorsal horn, ventral horn and "
        "intermediate zone, left and right",
        "8-17",
        "MEASURED at 8-9 voxels for dorsal horn against a 462-voxel cord. "
        "Any statistic here is dominated by sampling noise; report interval "
        "estimates and never present this tier as equivalent to tier 1."),
}


# ---------------------------------------------------------------------------
# Endpoint registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Metric:
    name: str
    description: str
    units: Optional[str]
    family: str                      # quality | reliability | effect
    needs_task: bool                 # requires an events model
    needs_repeats: Optional[str]     # None | "split" | "run" | "session"
    higher_is_better: Optional[bool]
    citation: str = ""
    caveat: str = ""
    # Tiers this metric is DEFINED on. None means all tiers. Enforced in
    # record(), because a caveat in a docstring is documentation and this
    # module's premise is that naming and applicability are data, not prose.
    valid_tiers: Optional[tuple] = None


def _m(*a, **k) -> Metric:
    return Metric(*a, **k)


METRICS: dict[str, Metric] = {m.name: m for m in [

    # --- context (always emitted; interpretation depends on it) -----------
    _m("n_voxels", "Voxels in the parcel for this run", "count", "quality",
       False, None, None,
       caveat="Emitted for EVERY parcel because tier-4 statistics are "
              "meaningless without it."),
    _m("n_volumes", "Timepoints in the run", "count", "quality",
       False, None, None),

    # --- quality -----------------------------------------------------------
    _m("tsnr_median", "Median temporal SNR across parcel voxels", None,
       "quality", False, None, True,
       citation="Eippert 2017; Kaptan 2023 report in-cord tSNR at 3T"),
    _m("tsnr_iqr", "Interquartile range of voxelwise tSNR in the parcel", None,
       "quality", False, None, None),
    _m("fd_mean_mm", "Mean framewise displacement over the run", "mm",
       "quality", False, None, False,
       citation="2-term cord form: Ricchi/Kinany/Van De Ville 2024",
       caveat="Descriptive only. No cord-calibrated FD threshold exists; the "
              "commonly quoted 0.5 mm is brain-derived (Power 2012) and sits "
              "at this cohort's own median."),
    _m("dvars_median", "Median DVARS over the run", None, "quality",
       False, None, False),

    # --- reliability (Q2-A: split-half is the backbone) --------------------
    _m("splithalf_r", "Pearson r between parcel timeseries of the two halves",
       None, "reliability", False, "split", True,
       caveat="Uncorrected. Report splithalf_r_sb alongside it."),
    _m("splithalf_r_sb",
       "Spearman-Brown corrected split-half reliability, 2r/(1+r)", None,
       "reliability", False, "split", True,
       citation="Spearman-Brown prophecy formula",
       caveat="The standard correction: an uncorrected split-half underestimates "
              "full-run reliability because each half is only half as long."),
    _m("icc_2_1", "ICC(2,1): absolute-agreement, two-way random effects", None,
       "reliability", False, "session", True,
       citation="Shrout & Fleiss 1979",
       caveat="Only ds004926 supports true between-session test-retest. "
              "ds004616's two sessions bracket an intervention."),
    _m("icc_2_1_ci_lo", "Lower bound, 95% CI on ICC(2,1)", None, "reliability",
       False, "session", None),
    _m("icc_2_1_ci_hi", "Upper bound, 95% CI on ICC(2,1)", None, "reliability",
       False, "session", None,
       caveat="Mandatory. With 11-18 subjects in three datasets the point "
              "estimate alone is not interpretable."),
    _m("betweensubj_var_frac",
       "Fraction of total variance attributable to between-subject differences",
       "frac", "reliability", False, "run", None,
       citation="Hedge, Powell & Sumner 2018 (the reliability paradox)",
       caveat="Task designs optimised for group effects SUPPRESS this, which "
              "is ICC's numerator. A clean group effect with low ICC is "
              "expected, not a pipeline failure."),

    # --- effect (Q3-C; task datasets only) ---------------------------------
    _m("effect_d", "Cohen's d of the contrast within the parcel", None,
       "effect", True, None, True,
       caveat="Comparable across datasets and TRs; the raw beta is not."),
    _m("effect_t", "t statistic of the contrast within the parcel", None,
       "effect", True, None, True),
    _m("detect_frac",
       "Fraction of subjects with a suprathreshold effect in this parcel",
       "frac", "effect", True, None, True,
       caveat="Threshold is a reporting choice, not a claim; report the "
              "threshold used alongside the value."),
    _m("focality_gini",
       "Gini coefficient of the effect across cord voxels: 0 = uniform, "
       "1 = concentrated in one voxel", None, "effect", True, None, None,
       caveat="Focality is a property of how an effect distributes ACROSS the "
              "cord, so it is undefined within a sub-parcel.",
       valid_tiers=("cord",)),
    _m("effect_dice",
       "Dice overlap of suprathreshold maps between two repeats", None,
       "effect", True, "split", True,
       caveat="Spatial reliability of the effect, distinct from the "
              "reliability of its magnitude."),
    _m("laterality_index",
       "(ipsi - contra) / (ipsi + contra) on suprathreshold voxel COUNTS per "
       "hemicord (Hemmerling 2023), not the mean beta", None, "effect", True,
       None, None,
       citation="Hemmerling 2023; Weber 2016",
       caveat="Activation asymmetry, not a mean. Only meaningful for lateralised "
              "paradigms (handgrasp, CoSpine motor); undefined for bilateral or "
              "pain tasks.",
       valid_tiers=("hemicord", "gmhorn")),

    # --- biological validity (C3; derived, group- or subject-level) ---------
    _m("laterality_ipsi_frac",
       "Fraction of subjects whose sided conditions are ipsilateral-dominant "
       "(LI > 0)", "frac", "effect", True, None, True,
       citation="Hemmerling 2023; Weber 2016",
       caveat="Single-subject level: laterality is strong and reliable per "
              "subject, unlike the dorsal/ventral dissociation.",
       valid_tiers=("hemicord",)),
    _m("horn_dissociation_d",
       "One-sample Cohen's d across subjects of (expected-horn minus other-horn) "
       "effect", None, "effect", True, None, True,
       citation="Dabbagh 2024 (single-subject horn ICC 0.03-0.24)",
       caveat="GROUP LEVEL ONLY. Single-subject horn localisation is unreliable "
              "at EPI resolution; never claim a per-subject dorsal/ventral result.",
       valid_tiers=("gmhorn",)),
    _m("horn_expected_frac",
       "Fraction of subjects with the expected horn stronger than the other",
       "frac", "effect", True, None, True,
       caveat="Group-level companion to horn_dissociation_d; descriptive.",
       valid_tiers=("gmhorn",)),
]}


FAMILIES = ("quality", "reliability", "effect")


class EndpointError(ValueError):
    """Raised on an unregistered metric, tier, or malformed record."""


def validate_metric(name: str) -> Metric:
    if name not in METRICS:
        close = [k for k in METRICS if k.split("_")[0] == name.split("_")[0]]
        raise EndpointError(
            f"unregistered metric {name!r}"
            + (f"; did you mean one of {close}?" if close else "")
            + ". Add it to METRICS rather than emitting an ad-hoc name.")
    return METRICS[name]


def validate_tier(tier: str) -> Tier:
    if tier not in TIERS:
        raise EndpointError(
            f"unknown tier {tier!r}; expected one of {sorted(TIERS)}")
    return TIERS[tier]


def record(rows: list[dict], *, dataset: str, subject: str,
           session: Optional[str], run_id: Optional[str],
           tier: str, parcel: str, metric: str, value: Any,
           n: Optional[int] = None, **extra) -> list[dict]:
    """Append one validated endpoint row. The only sanctioned way to emit.

    ``n`` is the sample size behind the value (subjects for a group statistic,
    voxels for a parcel summary). It is not optional in spirit: a tier-4 value
    without its n is uninterpretable, which is the whole reason the registry
    exists.
    """
    validate_tier(tier)
    m = validate_metric(metric)
    if m.family not in FAMILIES:
        raise EndpointError(f"{metric} has invalid family {m.family!r}")
    if m.valid_tiers is not None and tier not in m.valid_tiers:
        raise EndpointError(
            f"{metric!r} is not defined on tier {tier!r}; valid tiers are "
            f"{list(m.valid_tiers)}. {m.caveat}")
    rows.append({
        "dataset": dataset, "subject": subject, "session": session,
        "run_id": run_id, "tier": tier, "parcel": parcel,
        "metric": metric, "value": value, "n": n,
        "family": m.family, "units": m.units or "",
        **extra,
    })
    return rows


CANONICAL_COLUMNS = ["dataset", "subject", "session", "run_id", "tier",
                     "parcel", "metric", "value", "n", "family", "units"]


def parcel_name(tier: str, index: Any, side: Optional[str] = None) -> str:
    """Canonical parcel label. One spelling per parcel, everywhere.

    Deliberately explicit rather than clever: ``C5`` alone is ambiguous between
    a spinal and a vertebral level, and the two are different parcellations, so
    the tier prefix is part of the name.
    """
    if tier == "cord":
        return "cord"
    if tier == "spinallevel":
        return f"spinal-{index}"
    if tier == "vertlevel":
        return f"vert-{index}"
    if tier == "hemicord":
        if side not in ("L", "R"):
            raise EndpointError("hemicord parcel needs side 'L' or 'R'")
        return f"hemicord-{side}"
    if tier == "gmhorn":
        if index not in ("dorsal", "ventral", "intermediate"):
            raise EndpointError(
                f"gmhorn parcel must be dorsal|ventral|intermediate, got {index!r}")
        if side not in ("L", "R"):
            raise EndpointError("gmhorn parcel needs side 'L' or 'R'")
        return f"gm-{index}-{side}"
    raise EndpointError(f"unknown tier {tier!r}")


def applicable_metrics(*, has_task: bool, repeat_axis: Optional[str]) -> list[str]:
    """Which endpoints a dataset can support, given what it actually has.

    ``repeat_axis`` is None, "split", "run" or "session". Split-half is
    available everywhere (it needs one run), which is why it is the backbone.
    """
    order = {None: 0, "split": 1, "run": 2, "session": 3}
    have = order.get(repeat_axis, 0)
    out = []
    for name, m in METRICS.items():
        if m.needs_task and not has_task:
            continue
        if m.needs_repeats is not None and order[m.needs_repeats] > have:
            continue
        out.append(name)
    return sorted(out)
