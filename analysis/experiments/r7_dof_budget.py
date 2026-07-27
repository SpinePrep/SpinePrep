#!/usr/bin/env python3
"""R7 -- the degrees-of-freedom budget of the cord confound model.

Bright & Murphy 2015 established for the brain that a confound model is not free:
every regressor spends a degree of freedom, and past a point the denoising costs
more sensitivity than the noise it removes. The cord has no equivalent audit
*(unchecked)*, and SpinePrep's own confound design is unusually wide because it is
built slice-wise: the S8 metrics record 5 CSF components PER SLICE, which at 25-28
slices means 125-140 CSF columns alone.

That component count is already a known open bug in this project, with no precedent
in the literature it cites (Behzadi 6 total, Muschelli 3 for CSF, Ricchi 5 total,
Hemmerling median 9). This quantifies what it costs.

Everything here is read from the per-run S8 qc.json metrics that the pipeline
already writes, so there is no refitting and no new modelling assumption. The
sensitivity cost is ANALYTIC rather than empirical: for a fixed effect, the
t-statistic scales as sqrt(dof), so the relative efficiency of a wide design against
a lean one is sqrt(dof_wide / dof_lean). That is exact and needs no simulation. What
it deliberately does NOT claim is that the wide design is worse overall -- removing
real noise can more than repay the lost degrees of freedom. The empirical side of
that question was the confound-family benchmark, which found no family improved
sensitivity.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, "/mnt/ssd1/SpinePrep")

import numpy as np
import pandas as pd

COHORT = Path("/mnt/ssd1/spineprep_cohort_s2")
LOGS = COHORT / "logs"
OUT = Path("/mnt/ssd1/SpinePrep/analysis/results")

KEYS = ["n_volumes", "n_columns_total", "n_columns_motion", "n_columns_csf",
        "n_csf_components_per_slice", "n_csf_slices", "n_columns_retroicor",
        "n_columns_cosine", "n_columns_spinalcompcor", "n_columns_outliers",
        "condition_number", "condition_number_worst_slice", "design_rank",
        "design_rank_deficit", "regressor_frame_ratio",
        "n_columns_dropped_degenerate"]
# published CSF/aCompCor component counts, for the comparison
PRECEDENT = [("Behzadi 2007 (aCompCor, total)", 6),
             ("Muschelli 2014 (CSF only)", 3),
             ("Ricchi 2024 (cord, total)", 5),
             ("Hemmerling 2026 (cord, median)", 9),
             ("Barry (cord, adaptive)", 4)]


def main():
    rows = []
    for qc in (LOGS / "S8_confounds_and_physio_regressors").glob("*/qc.json"):
        try:
            d = json.loads(qc.read_text())
        except Exception:
            continue
        for r in d.get("runs", []):
            m = r.get("metrics") or {}
            if not r.get("run_id"):
                continue
            rec = dict(dataset=qc.parent.name, subject=r.get("subject"),
                       run_id=r["run_id"])
            for k in KEYS:
                v = m.get(k)
                rec[k] = float(v) if isinstance(v, (int, float)) else np.nan
            rows.append(rec)
    df = pd.DataFrame(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT / "r7_dof_budget.csv", index=False)
    report(df)


def report(df):
    print("=" * 86)
    print("R7  THE DEGREES-OF-FREEDOM BUDGET OF THE CORD CONFOUND MODEL")
    print("=" * 86)
    if not len(df):
        print("no S8 records found")
        return
    d = df.dropna(subset=["n_volumes", "n_columns_total"])
    print(f"runs {len(d)}   datasets {d.dataset.nunique()}")
    print(f"\n--- how much of each run is spent on confounds? ---")
    d = d.assign(spent=d.n_columns_total / d.n_volumes,
                 dof=d.n_volumes - d.n_columns_total)
    print(f"  {'quantity':40} {'median':>9} {'p10':>8} {'p90':>8} {'max':>8}")
    for col, lab in (("n_volumes", "frames per run"),
                     ("n_columns_total", "confound regressors"),
                     ("spent", "FRACTION of frames spent"),
                     ("dof", "residual degrees of freedom"),
                     ("condition_number", "design condition number"),
                     ("design_rank_deficit", "rank deficit"),
                     ("n_columns_dropped_degenerate", "columns dropped as degenerate")):
        v = d[col].dropna()
        if not len(v):
            continue
        print(f"  {lab:40} {v.median():9.3f} {v.quantile(.1):8.3f} "
              f"{v.quantile(.9):8.3f} {v.max():8.3f}")

    print("\n--- where do the regressors go? (median columns per family) ---")
    fam = [("n_columns_csf", "CSF (slice-wise aCompCor)"),
           ("n_columns_retroicor", "RETROICOR"),
           ("n_columns_cosine", "cosine drift"),
           ("n_columns_motion", "motion"),
           ("n_columns_outliers", "outlier / spike"),
           ("n_columns_spinalcompcor", "SpinalCompCor")]
    tot = d.n_columns_total.median()
    print(f"  {'family':32} {'median':>8} {'% of total':>11} {'p90':>8}")
    for col, lab in fam:
        v = d[col].dropna()
        if not len(v):
            continue
        print(f"  {lab:32} {v.median():8.0f} {100*v.median()/max(tot,1):10.1f}% "
              f"{v.quantile(.9):8.0f}")

    print("\n--- the CSF component count against its own literature ---")
    cps = d.n_csf_components_per_slice.dropna()
    nsl = d.n_csf_slices.dropna()
    csf = d.n_columns_csf.dropna()
    if len(cps):
        print(f"  SpinePrep: {cps.median():.0f} components per slice x "
              f"{nsl.median():.0f} slices = {csf.median():.0f} CSF columns")
    print(f"  {'precedent':36} {'components':>11} {'ratio to ours':>14}")
    for lab, n in PRECEDENT:
        print(f"  {lab:36} {n:11} {csf.median()/n:13.0f}x")
    print("  No published cord or brain aCompCor implementation uses a per-slice")
    print("  count. The comparison is to TOTAL components, which is what those")
    print("  papers report, so the ratio is the honest way to state the gap.")

    print("\n--- analytic sensitivity cost, vs a lean design ---")
    print("  For a fixed effect the t-statistic scales as sqrt(dof), so relative")
    print("  efficiency against a leaner model is sqrt(dof_wide / dof_lean). This is")
    print("  exact; it is not a claim that the wide model is worse overall, since")
    print("  removing real noise can repay the lost degrees of freedom.")
    print(f"  {'comparison':44} {'median dof':>11} {'rel. efficiency':>16}")
    nv = d.n_volumes.median()
    lean_cols = (d.n_columns_motion.median() + d.n_columns_cosine.median()
                 + d.n_columns_outliers.median())
    for lab, cols in (("full S8 design", d.n_columns_total.median()),
                      ("lean: motion + cosine + spikes", lean_cols),
                      ("if CSF were 5 components TOTAL, not per slice",
                       d.n_columns_total.median() - csf.median() + 5)):
        dof = nv - cols
        print(f"  {lab:44} {dof:11.0f} {np.sqrt(max(dof,1)/max(nv-lean_cols,1)):15.3f}")
    dof_full = nv - d.n_columns_total.median()
    dof_fix = nv - (d.n_columns_total.median() - csf.median() + 5)
    print(f"\n  Replacing the per-slice CSF count with 5 TOTAL components would "
          f"recover\n  {dof_fix - dof_full:.0f} degrees of freedom per run "
          f"({100*(np.sqrt(dof_fix/max(dof_full,1))-1):.0f}% more t per unit effect),")
    print("  and would bring the pipeline in line with the literature it cites.")

    print("\n--- runs where the budget is already broken ---")
    bad = d[d.n_columns_total >= d.n_volumes]
    tight = d[d.spent > 0.5]
    rd = d[d.design_rank_deficit > 0]
    print(f"  regressors >= frames (no residual dof at all): {len(bad)} runs "
          f"({100*len(bad)/len(d):.1f}%)")
    print(f"  more than HALF the frames spent on confounds:  {len(tight)} runs "
          f"({100*len(tight)/len(d):.1f}%)")
    print(f"  rank-deficient design:                         {len(rd)} runs "
          f"({100*len(rd)/len(d):.1f}%)")
    if len(d.dataset.unique()) > 1:
        print(f"\n  {'dataset':34} {'frames':>7} {'cols':>6} {'spent':>7} {'dof':>6}")
        for ds, g in d.groupby("dataset"):
            print(f"  {ds[:34]:34} {g.n_volumes.median():7.0f} "
                  f"{g.n_columns_total.median():6.0f} {g.spent.median():7.2f} "
                  f"{g.dof.median():6.0f}")
    print("\nDONE_MARKER")


if __name__ == "__main__":
    main()
