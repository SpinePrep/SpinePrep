"""Test-retest reliability of per-vertebral-level cord tSNR.

VALIDATION / BENCHMARK module — NOT a pipeline step. Consumes S9 derivatives
(``*_desc-tsnr_per_level.tsv``) and computes ICC(2,1) across sessions, the
standard test-retest reliability coefficient (Shrout & Fleiss 1979, two-way
random effects, single measurement, absolute agreement).

This is the first of the publication-validation benchmarks (see
.claude/specs/v1-publication-roadmap.md). It deliberately lives outside the
preprocessing pipeline: reliability is a property we MEASURE to validate the
tool, not a derivative the tool emits (the ROI/connectivity/reliability step was
removed from the pipeline 2026-06-11 as analyst-owned — this module is the
benchmark side, which is legitimate and standard, cf. the fMRIPrep paper).

Usage:  poetry run python validation/reliability_tsnr.py [scope ...]
"""

from __future__ import annotations

import glob
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# scope -> repeated-measures datasets with >=2 sessions on disk
TEST_RETEST_SCOPES = {
    "dorsalhorn": "dorsalhorn pain (heat task, ses-01 vs ses-02)",
    "handgrasp": "handgrasp motor (ses-01 vs ses-02)",
}


def _load_per_level(scope: str) -> pd.DataFrame:
    rows = []
    pat = f"work/done/{scope}/S9/derivatives/spineprep/**/*desc-tsnr_per_level.tsv"
    for f in glob.glob(pat, recursive=True):
        m = re.search(r"(sub-[A-Za-z0-9]+)_(ses-[0-9]+)?", f)
        if not m:
            continue
        sub, ses = m.group(1), (m.group(2) or "ses-01")
        try:
            df = pd.read_csv(f, sep="\t")
        except Exception:
            continue
        for _, r in df.iterrows():
            rows.append({"sub": sub, "ses": ses,
                         "level": int(r["level"]), "tsnr": float(r["mean_tsnr"])})
    return pd.DataFrame(rows)


def icc_2_1(M: np.ndarray) -> tuple[float, int]:
    """ICC(2,1): two-way random, single rater, absolute agreement.

    M: rows = targets (subjects), cols = raters (sessions). NaN rows dropped.
    """
    M = M[~np.isnan(M).any(axis=1)]
    n, k = M.shape
    if n < 3:
        return float("nan"), n
    grand = M.mean()
    ms_rows = k * ((M.mean(1) - grand) ** 2).sum() / (n - 1)
    ms_cols = n * ((M.mean(0) - grand) ** 2).sum() / (k - 1)
    ss_total = ((M - grand) ** 2).sum()
    ms_err = (ss_total - (n - 1) * ms_rows - (k - 1) * ms_cols) / ((n - 1) * (k - 1))
    denom = ms_rows + (k - 1) * ms_err + k * (ms_cols - ms_err) / n
    return (float((ms_rows - ms_err) / denom) if denom > 0 else float("nan")), n


def _level_name(lvl: int) -> str:
    return f"C{lvl}" if lvl <= 8 else f"T{lvl - 8}"


def run(scopes: list[str], out_tsv: Path | None = None) -> pd.DataFrame:
    results = []
    for scope in scopes:
        label = TEST_RETEST_SCOPES.get(scope, scope)
        d = _load_per_level(scope)
        if d.empty:
            print(f"  {label}: no per-level tSNR found")
            continue
        g = (d.groupby(["sub", "ses", "level"])["tsnr"].mean().reset_index())
        sess = sorted(g["ses"].unique())[:2]
        print(f"\n{label} — sessions {sess}")
        iccs = []
        for lvl in sorted(g["level"].unique()):
            piv = g[g["level"] == lvl].pivot_table(index="sub", columns="ses",
                                                   values="tsnr")
            if not set(sess).issubset(piv.columns):
                continue
            icc, n = icc_2_1(piv[sess].to_numpy())
            if not np.isnan(icc):
                print(f"   {_level_name(lvl):>3}: ICC={icc:5.2f}  (n={n})")
                iccs.append(icc)
                results.append({"scope": scope, "level": _level_name(lvl),
                                "icc_2_1": round(icc, 3), "n": n})
        if iccs:
            print(f"   >>> mean across levels: ICC={np.mean(iccs):.2f}")
    df = pd.DataFrame(results)
    if out_tsv is not None and not df.empty:
        out_tsv.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out_tsv, sep="\t", index=False)
        print(f"\nwrote {out_tsv}")
    return df


if __name__ == "__main__":
    scopes = sys.argv[1:] or list(TEST_RETEST_SCOPES)
    print("Test-retest reliability of per-level cord tSNR — ICC(2,1)")
    run(scopes, out_tsv=Path("validation/results/reliability_tsnr.tsv"))
