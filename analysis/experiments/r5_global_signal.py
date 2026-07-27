#!/usr/bin/env python3
"""R5 -- the whole-cord global signal: does it exist, and is it task-coupled?

The paired-organ experiment threw up an anomaly that was recorded rather than
explained: in ds005884 the cord's MEAN response rose as the ROI grew, reaching
d = +0.72 at 657 of a median 848 cord voxels. A focal response cannot do that. A
whole-cord fluctuation locked to the task can.

The brain has a large literature on exactly this quantity -- global signal
regression, its costs, and whether the global signal is artifact or neural (Power
2017, Murphy & Fox 2017, Liu 2017). The cord has no definition of a global signal
at all *(unchecked)*, so the pipeline has no global confound family and no paper
reports whether one is needed.

FOUR QUESTIONS.

1. HOW BIG IS IT? The fraction of each cord voxel's variance explained by the
   whole-cord mean timeseries. In the brain this runs tens of percent.
2. IS IT TASK-COUPLED? Correlation of the global signal with the HRF-convolved
   task design. This is the question that decides whether removing it is safe: a
   task-coupled global signal means global signal regression removes real
   response, which is precisely the brain field's unresolved argument.
3. IS IT PHYSIOLOGICAL? Correlation against the RETROICOR respiratory and cardiac
   regressors where they exist, and against framewise displacement and DVARS.
   A global signal that is mostly respiration is a confound; one that is not
   needs another explanation.
4. WHAT DOES REMOVING IT COST OR BUY? The focal horn effect with and without the
   global signal in the model. This comparison holds the runs fixed and varies
   only the model, which is the only form of comparison the R2 null-calibration
   showed to be safe for this estimator.

The global signal is computed on the DEMEANED, cosine-detrended cord timeseries
so that scanner drift cannot masquerade as a global neural signal. It deliberately
does NOT have motion regressed out first: motion is one of the candidate
explanations in question 3, and removing it first would hide the answer.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, "/mnt/ssd1/SpinePrep")

import numpy as np
import pandas as pd
import yaml
from scipy import stats as sps

from analysis import driver
from analysis.glm import build_task_design, lean_confounds
from analysis.glm_spec import conditions_for, corrected_events, repetition_time_s

COHORT = Path("/mnt/ssd1/spineprep_cohort_s2")
OUT = Path("/mnt/ssd1/SpinePrep/analysis/results")

HORN = {
    "openneuro_ds004616_spinalcord_handgrasp_task": ("ventral", None),
    "openneuro_ds005884_cospine_motor": ("ventral", None),
    "openneuro_ds004926_dorsalhorn_pain": ("dorsal", "L"),
    "openneuro_ds005883_cospine_pain": ("dorsal", "R"),
    "internal_balgrist_motor_11": ("ventral", None),
    "internal_balgrist_painmotor_21": ("ventral", None),
}


def side_of(c):
    c = c.lower().replace("-", "").replace("_", "")
    if "left" in c or c.endswith("l"):
        return "L"
    if "right" in c or c.endswith("r"):
        return "R"
    return None


def cosine_basis(n_vol, tr, cutoff_s=100.0):
    k = int(np.floor(2 * n_vol * tr / cutoff_s))
    if k < 1:
        return np.empty((n_vol, 0))
    t = (np.arange(n_vol) + 0.5) / n_vol
    return np.column_stack([np.cos(np.pi * (j + 1) * t) for j in range(k)])


def main():
    cfg = yaml.safe_load(Path("config/datasets_local.yaml").read_text()) or {}
    rawcfg = cfg.get("datasets", cfg)

    def mkpath(v):
        p = Path(v.get("path") or v.get("bids_root")) if isinstance(v, dict) else Path(v)
        return p if p.is_absolute() else Path("/mnt/ssd1/SpinePrep") / p

    roots = {k: mkpath(v) for k, v in rawcfg.items()}
    import nibabel as nib

    rows = []
    runs = [r for r in driver.iter_runs(COHORT) if r["dataset"] in HORN]
    print(f"runs: {len(runs)}", flush=True)

    for k_run, run in enumerate(runs):
        ds = run["dataset"]
        conds = conditions_for(ds, run["run_id"])
        if not conds:
            continue
        parcels, _ = driver.build_parcels(run)
        if "cord" not in parcels or "gmhorn" not in parcels:
            continue
        root = roots.get(ds)
        ev = next(iter(Path(root).rglob(f"{run['run_id']}_events.tsv")), None) if root else None
        if ev is None:
            continue
        erows = list(csv.DictReader(open(ev), delimiter="\t"))
        scj = Path(str(run["bold"]).replace(".nii.gz", ".json"))
        stt = 0.0
        if scj.exists():
            try:
                stt = float(json.loads(scj.read_text()).get("StartTime") or 0.0)
            except Exception:
                pass
        try:
            data = np.asarray(nib.load(str(run["bold"])).dataobj, dtype=np.float32)
        except Exception:
            continue
        if data.ndim != 4:
            continue
        n_vol = data.shape[3]
        tr = repetition_time_s(run["bold"])
        Xt, names = build_task_design(
            corrected_events(ds, erows, stt, run["run_id"]), n_vol, tr, conds)
        if Xt.shape[1] == 0:
            continue
        cord = parcels["cord"]["cord"]
        midx = np.argwhere(cord)
        Y = data[cord].T.astype(np.float64)
        if Y.shape[0] != n_vol:
            continue
        Y = Y - Y.mean(axis=0, keepdims=True)
        # detrend with the same cosine basis the pipeline uses, so drift cannot
        # appear as a global neural signal. Motion is deliberately NOT removed.
        C = np.column_stack([cosine_basis(n_vol, tr), np.ones(n_vol)])
        q, _ = np.linalg.qr(C)
        Yd = Y - q @ (q.T @ Y)
        gs = Yd.mean(axis=1)
        if np.std(gs) < 1e-9:
            continue
        gsz = (gs - gs.mean()) / np.std(gs)

        # Q1 variance explained by the global signal, per voxel
        num = (Yd * gsz[:, None]).sum(axis=0) / n_vol
        r2 = (num ** 2) / np.maximum(Yd.var(axis=0), 1e-20)

        # Q3 physiology and motion
        try:
            cdf = pd.read_csv(run["confounds"], sep="\t").iloc[:n_vol]
        except Exception:
            cdf = pd.DataFrame()
        def corr_with(cols):
            if not len(cdf):
                return np.nan
            cc = [c for c in cdf.columns if any(c.lower().startswith(p) for p in cols)]
            if not cc:
                return np.nan
            A = np.nan_to_num(cdf[cc].to_numpy(float))
            A = A[:, A.std(0) > 1e-9]
            if not A.size:
                return np.nan
            qa, _ = np.linalg.qr(np.column_stack([A, np.ones(n_vol)]))
            fit = qa @ (qa.T @ gsz)
            return float(np.var(fit) / np.var(gsz))       # R2 of that family on GS
        r2_retro = corr_with(("retroicor",))
        r2_motion = corr_with(("trans_", "rot_"))
        fd = np.nan_to_num(cdf["framewise_displacement"].to_numpy(float)) \
            if "framewise_displacement" in cdf else None
        dv = np.nan_to_num(cdf["dvars"].to_numpy(float)) if "dvars" in cdf else None

        # Q2 task coupling of the global signal
        Xtz = (Xt - Xt.mean(0)) / np.maximum(Xt.std(0), 1e-12)
        task_r = [float(np.corrcoef(gsz, Xtz[:, i])[0, 1]) for i in range(Xt.shape[1])]

        # Q4 what removing it costs the focal effect
        Xn, _ = lean_confounds(Path(run["confounds"]), n_vol)
        ht, fixed = HORN[ds]
        odd, even = np.arange(0, n_vol, 2), np.arange(1, n_vol, 2)
        for arm, extra in (("no_gsr", None), ("gsr", gsz[:, None])):
            blocks = [Xt, Xn] if Xn.size else [Xt]
            if extra is not None:
                blocks.append(extra)
            X = np.column_stack(blocks + [np.ones(n_vol)])
            keep = X.std(axis=0) > 1e-9
            keep[:Xt.shape[1]] = True
            keep[-1] = True
            X = X[:, keep]

            def fit(ix):
                Xi = X[ix]
                kk = Xi.std(axis=0) > 1e-9
                kk[:Xt.shape[1]] = True
                kk[-1] = True
                Xi = Xi[:, kk]
                if len(ix) <= Xi.shape[1] + 2 or np.linalg.matrix_rank(Xi) < Xi.shape[1]:
                    return None
                b, *_ = np.linalg.lstsq(Xi, Yd[ix] - Yd[ix].mean(0, keepdims=True),
                                       rcond=None)
                return b

            b1, b2 = fit(odd), fit(even)
            if b1 is None or b2 is None:
                continue
            for ci, cn in enumerate(names):
                sd_ = side_of(cn) or fixed
                if sd_ is None:
                    continue
                h = parcels["gmhorn"].get(f"gm-{ht}-{sd_}")
                if h is None:
                    continue
                fi = h[tuple(midx.T)]
                if fi.sum() < 8:
                    continue
                v1, v2 = b1[ci][fi], b2[ci][fi]
                k = max(1, int(0.1 * len(v1)))
                rows.append(dict(
                    dataset=ds, subject=run["subject"], run_id=run["run_id"],
                    condition=cn, arm=arm,
                    cv_top10=float(v2[np.argsort(v1)[-k:]].mean()),
                    gs_r2_median=float(np.median(r2)),
                    gs_r2_p90=float(np.percentile(r2, 90)),
                    gs_task_r=float(task_r[ci]) if ci < len(task_r) else np.nan,
                    gs_r2_retroicor=r2_retro, gs_r2_motion=r2_motion,
                    gs_fd_r=float(np.corrcoef(gsz, fd)[0, 1]) if fd is not None
                    and np.std(fd) > 0 else np.nan,
                    gs_dvars_r=float(np.corrcoef(gsz, dv)[0, 1]) if dv is not None
                    and np.std(dv) > 0 else np.nan,
                    n_cord=int(cord.sum()),
                ))
        if (k_run + 1) % 25 == 0:
            print(f"  {k_run+1}/{len(runs)}", flush=True)

    OUT.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "r5_global_signal.csv", index=False)
    report(df)


def gsub(g, col, null=0.0):
    s = g.groupby("subject")[col].mean().to_numpy(float)
    s = s[np.isfinite(s)]
    if len(s) < 5 or s.std(ddof=1) == 0:
        return np.nan, np.nan, len(s)
    t, p = sps.ttest_1samp(s, null)
    return float(s.mean()), float(p), len(s)


def report(df):
    print("\n" + "=" * 88)
    print("R5  THE WHOLE-CORD GLOBAL SIGNAL")
    print("=" * 88)
    if not len(df):
        print("no runs resolved")
        return
    short = lambda d: d.split("_")[1] if d.split("_")[0] == "openneuro" else d.split("_")[2]
    A = df[df.arm == "no_gsr"]
    print(f"runs {A.run_id.nunique()}   datasets {A.dataset.nunique()}")

    print("\n--- Q1  how much cord variance is global? ---")
    print(f"  {'dataset':12} {'median R2':>10} {'90th pct R2':>12} {'cord vox':>9} {'N':>4}")
    for ds, g in A.groupby("dataset"):
        m, _, n = gsub(g, "gs_r2_median")
        p90, _, _ = gsub(g, "gs_r2_p90")
        print(f"  {short(ds)[:12]:12} {m:10.3f} {p90:12.3f} "
              f"{g.n_cord.median():9.0f} {n:4}")

    print("\n--- Q2  is it TASK-COUPLED?  (this decides whether removing it is safe) ---")
    print(f"  {'dataset':12} {'r(GS, task)':>12} {'p':>9} {'N':>4}")
    for ds, g in A.groupby("dataset"):
        r, p, n = gsub(g, "gs_task_r")
        star = "  <-- task-coupled" if (np.isfinite(p) and p < 0.05) else ""
        print(f"  {short(ds)[:12]:12} {r:+12.3f} {p:9.4f} {n:4}{star}")

    print("\n--- Q3  is it physiological or motion? (R2 of each family ON the GS) ---")
    print(f"  {'dataset':12} {'RETROICOR':>10} {'motion':>8} {'r(GS,FD)':>10} "
          f"{'r(GS,DVARS)':>12}")
    for ds, g in A.groupby("dataset"):
        a, _, _ = gsub(g, "gs_r2_retroicor")
        b, _, _ = gsub(g, "gs_r2_motion")
        c, _, _ = gsub(g, "gs_fd_r")
        d_, _, _ = gsub(g, "gs_dvars_r")
        print(f"  {short(ds)[:12]:12} {a:10.3f} {b:8.3f} {c:+10.3f} {d_:+12.3f}")

    print("\n--- Q4  what does removing it cost the FOCAL effect? ---")
    print("  Same runs, same voxels, only the model differs -- the one comparison")
    print("  the R2 null-calibration showed is safe for this estimator.")
    print(f"  {'dataset':12} {'d no_gsr':>10} {'d gsr':>8} {'paired p':>10} {'N':>4}")
    piv = df.pivot_table(index=["dataset", "subject", "condition"],
                         columns="arm", values="cv_top10")
    for ds, g in df.groupby("dataset"):
        def gd(arm):
            s = g[g.arm == arm].groupby("subject").cv_top10.mean().to_numpy(float)
            s = s[np.isfinite(s)]
            return (s.mean() / s.std(ddof=1)) if len(s) >= 5 and s.std(ddof=1) > 0 else np.nan
        try:
            j = piv.loc[ds][["no_gsr", "gsr"]].dropna()
            p = sps.wilcoxon(j.no_gsr, j.gsr).pvalue if len(j) >= 10 else np.nan
            n = len(j)
        except Exception:
            p, n = np.nan, 0
        print(f"  {short(ds)[:12]:12} {gd('no_gsr'):+10.2f} {gd('gsr'):+8.2f} "
              f"{p:10.4f} {n:4}")
    print("""
  HOW TO READ THIS
  - A large Q1 with a NON-significant Q2 means the cord has a big global signal
    that is not task-locked: a confound the pipeline should model, and removing it
    is close to free.
  - A significant Q2 means the global signal carries task response. Removing it
    then destroys real signal, which is the brain field's unresolved global-signal
    argument arriving in the cord. Q4 measures that cost directly.
  - If RETROICOR explains most of the global signal, it is respiration and cardiac
    and the existing confound family already covers it. If it does not, the cord
    has an unexplained global component that nothing in the pipeline models.""")
    print("\nDONE_MARKER")


if __name__ == "__main__":
    main()
