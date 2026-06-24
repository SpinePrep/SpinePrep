"""Normative cord-fMRI QC database (T3; pillar N2 + V6).

Aggregates the per-run QC metrics the pipeline already emits — every scope's
S10 ``metrics_index.tsv`` (MRIQC long-format) plus the per-vertebral-level tSNR
TSVs — into a single cohort-wide NORMATIVE reference: for each headline metric,
the distribution (n, mean, sd, median, IQR, p5, p95) across the full validation
cohort, and tSNR resolved per vertebral level.

No field equivalent exists; this is "MRIQC's normative IQM database, for cord."
A benchmark/resource module, not a pipeline step. Numbers refresh after the
locked-σ full re-run (the machinery is the deliverable here).

Usage: poetry run python validation/normative_qc_db.py
"""

from __future__ import annotations

import glob
import re
from pathlib import Path

import numpy as np
import pandas as pd

# Headline metrics to publish as the normative reference (the step-local truth
# metrics + key quality indicators). Others stay in the full metrics_index.
HEADLINE = {
    ("S4", "mean_fd_mm"), ("S4", "max_fd_mm"), ("S4", "tsnr_improvement_pct"),
    ("S5", "dice_mean_after"), ("S5", "displacement_mean_after_mm"),
    ("S6", "cord_dice"), ("S6", "cord_asd_mm"),
    ("S7", "cord_dice_native_func"),
    ("S8", "condition_number"),
    ("S9", "tsnr_post_median"), ("S9", "tsnr_ratio_median"),
    ("S9", "fwhm_z_measured_mm"),
    ("S2", "pam50_cord_dice"), ("S2", "csa_mean_mm2"),
}
SCOPES = ["cospain", "cosmotor", "rest", "handgrasp", "dorsalhorn",
          "brainspine", "exp"]


def _level_name(lvl: int) -> str:
    return f"C{lvl}" if lvl <= 8 else f"T{lvl - 8}"


def _load_all_metrics() -> pd.DataFrame:
    frames = []
    for s in SCOPES:
        for f in glob.glob(f"work/done/{s}/S10/release/metrics_index.tsv"):
            try:
                df = pd.read_csv(f, sep="\t")
                df["scope"] = s
                frames.append(df)
            except Exception:
                continue
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _summary(vals: np.ndarray) -> dict:
    vals = vals[np.isfinite(vals)]
    return {
        "n": int(vals.size),
        "mean": round(float(np.mean(vals)), 4) if vals.size else None,
        "sd": round(float(np.std(vals, ddof=1)), 4) if vals.size > 1 else None,
        "median": round(float(np.median(vals)), 4) if vals.size else None,
        "iqr": round(float(np.subtract(*np.percentile(vals, [75, 25]))), 4) if vals.size else None,
        "p5": round(float(np.percentile(vals, 5)), 4) if vals.size else None,
        "p95": round(float(np.percentile(vals, 95)), 4) if vals.size else None,
    }


def build_metric_norms(df: pd.DataFrame, out_tsv: Path) -> pd.DataFrame:
    """Cohort-wide distribution per (step, metric), restricted to runs the
    pipeline accepted (PASS/WARN)."""
    rows = []
    ok = df[df["status"].isin(["PASS", "WARN"])]
    for (step, metric), g in ok.groupby(["step", "metric"]):
        if (step, metric) not in HEADLINE:
            continue
        rows.append({"step": step, "metric": metric,
                     **_summary(g["value"].to_numpy(dtype=float))})
    out = pd.DataFrame(rows).sort_values(["step", "metric"])
    out_tsv.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_tsv, sep="\t", index=False)
    return out


def build_tsnr_norms(out_tsv: Path) -> pd.DataFrame:
    """Per-vertebral-level tSNR distribution across the whole cohort (Kaptan 2023
    convention) from the S9 per-level TSVs."""
    rows = []
    for s in SCOPES:
        for f in glob.glob(f"work/done/{s}/S9/derivatives/spinalfmriprep/**/"
                           f"*desc-tsnr_per_level.tsv", recursive=True):
            try:
                df = pd.read_csv(f, sep="\t")
                for _, r in df.iterrows():
                    rows.append({"level": int(r["level"]),
                                 "mean_tsnr": float(r["mean_tsnr"])})
            except Exception:
                continue
    d = pd.DataFrame(rows)
    out = []
    for lvl, g in d.groupby("level"):
        out.append({"level": _level_name(int(lvl)),
                    **_summary(g["mean_tsnr"].to_numpy())})
    res = pd.DataFrame(out)
    out_tsv.parent.mkdir(parents=True, exist_ok=True)
    res.to_csv(out_tsv, sep="\t", index=False)
    return res


def main():
    df = _load_all_metrics()
    if df.empty:
        print("No metrics_index.tsv found.")
        return
    n_runs = df["run_id"].nunique()
    n_ds = df["dataset_key"].nunique()
    print(f"Normative QC DB — {n_runs} runs across {n_ds} datasets\n")
    mnorm = build_metric_norms(
        df, Path("validation/results/normative_qc_metrics.tsv"))
    print("Headline metric norms (cohort-wide, PASS/WARN runs):")
    print(mnorm.to_string(index=False))
    print()
    tnorm = build_tsnr_norms(
        Path("validation/results/normative_tsnr_per_level.tsv"))
    print("Per-vertebral-level cord tSNR norms:")
    print(tnorm.to_string(index=False))


if __name__ == "__main__":
    main()
