#!/usr/bin/env python3
"""Estimators behind the SpinePrep endpoints.

ANALYSIS module -- not part of the preprocessing toolbox.

Every function here returns ``None`` rather than a number when the input cannot
support the statistic: too few subjects, zero variance, an empty parcel. That is
deliberate and it is the same rule the pipeline audit enforced all week -- a
plausible-looking number computed from nothing is worse than a visible gap,
because it survives into a figure and nobody can tell it apart from a real
value. Callers must handle ``None``; ``record()`` will happily store it, and a
missing value is honest.

Validation
----------
ICC is checked against the worked example in Shrout & Fleiss (1979), Table 1,
whose ICC(1,1)=0.17, ICC(2,1)=0.29 and ICC(3,1)=0.71 are published. The
confidence interval follows McGraw & Wong (1996). Nothing here was accepted on
the basis that the formula "looked right".
"""
from __future__ import annotations

import math
from typing import Optional, Sequence

import numpy as np


# ---------------------------------------------------------------------------
# Reliability
# ---------------------------------------------------------------------------


def pearson_r(a: Sequence[float], b: Sequence[float]) -> Optional[float]:
    """Pearson correlation, or None when it is undefined."""
    x = np.asarray(a, dtype=float)
    y = np.asarray(b, dtype=float)
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    if x.size < 3 or x.std() == 0 or y.std() == 0:
        return None
    return float(np.corrcoef(x, y)[0, 1])


def spearman_brown(r: Optional[float]) -> Optional[float]:
    """Correct a split-half correlation to full-run length: 2r/(1+r).

    Each half is only half as long as the run, and reliability grows with
    length, so an uncorrected split-half systematically UNDERSTATES full-run
    reliability. Reporting the raw value alone would understate the pipeline.
    Undefined at r = -1.
    """
    if r is None or not math.isfinite(r) or r <= -1.0:
        return None
    return float(2.0 * r / (1.0 + r))


def split_half(series: Sequence[float], method: str = "oddeven") -> Optional[float]:
    """Split-half correlation of a timeseries.

    ``oddeven`` (default) interleaves samples, which is robust to slow drift:
    a first/second-half split confounds reliability with scanner drift and any
    habituation over the run, both of which are real in cord fMRI. ``halves``
    is offered for comparison, not as the default.
    """
    v = np.asarray(series, dtype=float)
    v = v[np.isfinite(v)]
    if v.size < 6:
        return None
    if method == "oddeven":
        a, b = v[0::2], v[1::2]
    elif method == "halves":
        h = v.size // 2
        a, b = v[:h], v[h:2 * h]
    else:
        raise ValueError(f"unknown split method {method!r}")
    n = min(a.size, b.size)
    return pearson_r(a[:n], b[:n])


def icc(matrix, form: str = "2,1", ci: float = 0.95) -> dict:
    """Intraclass correlation for a subjects x measurements matrix.

    Returns ``{"icc": float|None, "ci_lo": .., "ci_hi": .., "n": .., "k": ..}``.

    ``form`` follows Shrout & Fleiss (1979):
      "1,1" one-way random -- measurements are not the same across subjects
      "2,1" two-way random, ABSOLUTE agreement -- the test-retest default, and
            what we use: session is a random factor and we care that values
            agree, not merely that they correlate
      "3,1" two-way mixed, consistency -- treats the measurement occasions as
            fixed, which is wrong for test-retest and inflates the estimate

    We report 2,1 because 3,1 would ignore systematic session differences --
    exactly the thing a reliability claim must not hide.
    """
    m = np.asarray(matrix, dtype=float)
    if m.ndim != 2:
        raise ValueError("icc expects a 2D subjects x measurements array")
    m = m[np.isfinite(m).all(axis=1)]
    n, k = m.shape
    out = {"icc": None, "ci_lo": None, "ci_hi": None, "n": int(n), "k": int(k)}
    if n < 2 or k < 2:
        return out

    grand = m.mean()
    row_m = m.mean(axis=1)
    col_m = m.mean(axis=0)

    ss_r = k * ((row_m - grand) ** 2).sum()            # between subjects
    ss_c = n * ((col_m - grand) ** 2).sum()            # between measurements
    ss_t = ((m - grand) ** 2).sum()
    ss_e = ss_t - ss_r - ss_c

    df_r, df_c, df_e = n - 1, k - 1, (n - 1) * (k - 1)
    if df_e <= 0:
        return out
    ms_r, ms_c, ms_e = ss_r / df_r, ss_c / df_c, ss_e / df_e
    ms_w = (ss_c + ss_e) / (df_c + df_e)               # within-subject, for 1,1

    if form == "1,1":
        denom = ms_r + (k - 1) * ms_w
        val = (ms_r - ms_w) / denom if denom else None
    elif form == "2,1":
        denom = ms_r + (k - 1) * ms_e + k * (ms_c - ms_e) / n
        val = (ms_r - ms_e) / denom if denom else None
    elif form == "3,1":
        denom = ms_r + (k - 1) * ms_e
        val = (ms_r - ms_e) / denom if denom else None
    else:
        raise ValueError(f"unknown ICC form {form!r}")
    if val is None or not math.isfinite(val):
        return out
    out["icc"] = float(val)

    # Confidence interval (McGraw & Wong 1996). Requires scipy's F quantiles;
    # if scipy is absent we return the point estimate with no interval rather
    # than inventing one.
    try:
        from scipy import stats
    except Exception:
        return out
    alpha = 1.0 - ci
    try:
        if form == "3,1":
            f_obs = ms_r / ms_e
            fl = f_obs / stats.f.ppf(1 - alpha / 2, df_r, df_e)
            fu = f_obs * stats.f.ppf(1 - alpha / 2, df_e, df_r)
            out["ci_lo"] = float((fl - 1) / (fl + k - 1))
            out["ci_hi"] = float((fu - 1) / (fu + k - 1))
        elif form == "2,1":
            fj = stats.f.ppf(1 - alpha / 2, df_c, df_e)
            vn = (k * out["icc"] * ms_c + n * (1 + (k - 1) * out["icc"]) * ms_e) ** 2
            vd = (df_c * (k * out["icc"] * ms_c) ** 2
                  + (n * (1 + (k - 1) * out["icc"]) - k * out["icc"]) ** 2 * ms_e ** 2 * df_e)
            v = vn / vd if vd else None
            if v:
                f_lo = stats.f.ppf(1 - alpha / 2, df_r, v)
                f_hi = stats.f.ppf(1 - alpha / 2, v, df_r)
                lo = (n * (ms_r - f_lo * ms_e)
                      / (f_lo * (k * ms_c + (k * n - k - n) * ms_e) + n * ms_r))
                hi = ((n * (f_hi * ms_r - ms_e))
                      / (k * ms_c + (k * n - k - n) * ms_e + n * f_hi * ms_r))
                out["ci_lo"], out["ci_hi"] = float(lo), float(hi)
        elif form == "1,1":
            f_obs = ms_r / ms_w
            fl = f_obs / stats.f.ppf(1 - alpha / 2, df_r, n * (k - 1))
            fu = f_obs * stats.f.ppf(1 - alpha / 2, n * (k - 1), df_r)
            out["ci_lo"] = float((fl - 1) / (fl + k - 1))
            out["ci_hi"] = float((fu - 1) / (fu + k - 1))
    except Exception:
        pass
    for b in ("ci_lo", "ci_hi"):
        if out[b] is not None and not math.isfinite(out[b]):
            out[b] = None
    return out


def between_subject_variance_fraction(matrix) -> Optional[float]:
    """Share of total variance that is between-subject.

    This is ICC's numerator, and the reason a clean group effect can coexist
    with poor reliability: a task designed to drive everyone the same way
    suppresses between-subject variance by construction (Hedge, Powell &
    Sumner 2018). Reporting it alongside ICC makes that visible instead of
    leaving a low ICC looking like a pipeline failure.
    """
    m = np.asarray(matrix, dtype=float)
    m = m[np.isfinite(m).all(axis=1)]
    if m.shape[0] < 2 or m.shape[1] < 2:
        return None
    grand = m.mean()
    ss_between = m.shape[1] * ((m.mean(axis=1) - grand) ** 2).sum()
    ss_total = ((m - grand) ** 2).sum()
    if ss_total <= 0:
        return None
    return float(ss_between / ss_total)


# ---------------------------------------------------------------------------
# Effect
# ---------------------------------------------------------------------------


def cohens_d(values: Sequence[float]) -> Optional[float]:
    """One-sample Cohen's d: mean / sd.

    Used rather than the raw beta because betas are not comparable across
    datasets with different TRs, scaling and run lengths, and this analysis
    compares seven paradigms.
    """
    v = np.asarray(values, dtype=float)
    v = v[np.isfinite(v)]
    if v.size < 2:
        return None
    sd = v.std(ddof=1)
    if sd == 0:
        return None
    return float(v.mean() / sd)


def one_sample_t(values: Sequence[float]) -> Optional[float]:
    v = np.asarray(values, dtype=float)
    v = v[np.isfinite(v)]
    if v.size < 2:
        return None
    sd = v.std(ddof=1)
    if sd == 0:
        return None
    return float(v.mean() / (sd / math.sqrt(v.size)))


def detection_fraction(values: Sequence[float], threshold: float) -> Optional[float]:
    """Fraction of subjects whose effect exceeds ``threshold``.

    The threshold is a reporting choice, not a claim, so it must be recorded
    next to the value wherever this is published.
    """
    v = np.asarray(values, dtype=float)
    v = v[np.isfinite(v)]
    if v.size == 0:
        return None
    return float((v > threshold).mean())


def gini(values: Sequence[float]) -> Optional[float]:
    """Gini coefficient of a non-negative effect map: 0 uniform, 1 concentrated.

    Our focality measure. Negative values are clipped to zero first, because
    Gini is undefined on signed data and a deactivation is not "negative
    concentration" -- focality here asks how tightly the POSITIVE effect is
    packed. Report the clipping wherever this is used.
    """
    v = np.asarray(values, dtype=float)
    v = v[np.isfinite(v)]
    if v.size < 2:
        return None
    v = np.clip(v, 0, None)
    total = v.sum()
    if total <= 0:
        return None
    v = np.sort(v)
    n = v.size
    idx = np.arange(1, n + 1)
    return float((2.0 * (idx * v).sum()) / (n * total) - (n + 1.0) / n)


def dice(a, b, threshold: float = 0.0) -> Optional[float]:
    """Dice overlap of two suprathreshold maps.

    Spatial reliability of an effect, which is a different question from
    whether its magnitude reproduces -- an effect can shift location while
    keeping its size, and vice versa.
    """
    x = np.asarray(a, dtype=float) > threshold
    y = np.asarray(b, dtype=float) > threshold
    if x.shape != y.shape:
        raise ValueError(f"shape mismatch {x.shape} vs {y.shape}")
    denom = x.sum() + y.sum()
    if denom == 0:
        return None
    return float(2.0 * (x & y).sum() / denom)


def laterality_index(ipsi: float, contra: float) -> Optional[float]:
    """(ipsi - contra) / (ipsi + contra), in [-1, 1].

    Only meaningful for lateralised paradigms. Returns None when the
    denominator vanishes or either side is negative, where the ratio stops
    being interpretable as a share.
    """
    if ipsi is None or contra is None:
        return None
    if not (math.isfinite(ipsi) and math.isfinite(contra)):
        return None
    if ipsi < 0 or contra < 0:
        return None
    denom = ipsi + contra
    if denom <= 0:
        return None
    return float((ipsi - contra) / denom)


# ---------------------------------------------------------------------------
# Quality
# ---------------------------------------------------------------------------


def tsnr(series_2d) -> Optional[np.ndarray]:
    """Voxelwise tSNR = mean / sd over time. Input is (voxels, time)."""
    m = np.asarray(series_2d, dtype=float)
    if m.ndim != 2 or m.shape[1] < 3:
        return None
    sd = m.std(axis=1, ddof=1)
    mu = m.mean(axis=1)
    out = np.full(m.shape[0], np.nan)
    ok = sd > 0
    out[ok] = mu[ok] / sd[ok]
    return out


def median_iqr(values) -> tuple[Optional[float], Optional[float]]:
    v = np.asarray(values, dtype=float)
    v = v[np.isfinite(v)]
    if v.size == 0:
        return None, None
    q1, q3 = np.percentile(v, [25, 75])
    return float(np.median(v)), float(q3 - q1)
