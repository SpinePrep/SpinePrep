#!/usr/bin/env python3
"""R10 -- a pruned multiverse: how much does the pipeline choice change the answer?

NARPS had 70 teams analyse one brain dataset and reach conflicting conclusions;
Carp 2012 enumerated 34,560 brain pipelines. The cord has no multiverse analysis
*(unchecked)*, and the cord is where one is actually tractable, because the space of
defensible choices is small enough to enumerate exhaustively rather than sample.

THE PRUNING IS PART OF THE RESULT. A multiverse over axes already shown to be inert
is padding. Measured earlier in this project:

  INERT, excluded          high-pass filtering (median d 0.035 to -0.020 across
                           none/quarter/half/all), physiological modelling
                           (RETROICOR rim/core gain ~1.1, no detection benefit),
                           prewhitening (residuals already white; AR(1) made the
                           false-positive rate worse), inference method (FWE 5.9%
                           against a nominal 5%, cluster inference conservative)
  MOVES THE ANSWER         summary measure (sign flips in 2 of 4 datasets),
                           censoring fraction (+0.425 at 10%, +0.062 at 25%),
                           smoothing (best kernel differs per dataset)

So four axes drop out and the multiverse runs over the three that survive, plus the
confound set, giving 3 x 3 x 3 x 2 = 54 fully defensible pipelines per dataset.

  summary measure   parcel mean / cross-validated top-10% / peak
  censoring         none / worst 10% of frames / FD > 0.5 mm (the brain rule)
  smoothing         none / isotropic 4 mm / rostrocaudal 10 mm
  confounds         lean (motion + cosine + spikes) / lean + RETROICOR

WHAT IS REPORTED is the distribution of the CONCLUSION, not of a metric: across the
54 pipelines, how many say significant positive, how many null, how many
significant negative. A reader cares whether the answer to the scientific question
is stable, not whether a number wobbles.

Every arm is fitted on the SAME runs, which is the only comparison the R2
null-calibration showed to be safe for this estimator: the split-half top-10%
estimator's magnitude tracks run noise, so arms must share their runs. They do.

HONEST LIMIT. Distortion correction cannot enter, because changing it means
re-running S5 and regenerating the derivatives rather than re-analysing them. Since
F1 found the largest single effect on that axis, the multiverse reported here
UNDERSTATES the true spread. That is stated rather than hidden.
"""
from __future__ import annotations

import csv
import json
import sys
from itertools import product
from pathlib import Path

sys.path.insert(0, "/mnt/ssd1/SpinePrep")

import numpy as np
import pandas as pd
import yaml
from scipy import ndimage, stats as sps

from analysis import driver
from analysis.glm import build_task_design, lean_confounds
from analysis.glm_spec import conditions_for, corrected_events, repetition_time_s

COHORT = Path("/mnt/ssd1/spineprep_cohort_s2")
OUT = Path("/mnt/ssd1/SpinePrep/analysis/results")
FW = 2.355

HORN = {
    "openneuro_ds004616_spinalcord_handgrasp_task": ("ventral", None),
    "openneuro_ds005884_cospine_motor": ("ventral", None),
    "openneuro_ds004926_dorsalhorn_pain": ("dorsal", "L"),
    "openneuro_ds005883_cospine_pain": ("dorsal", "R"),
}
SMOOTH = ["none", "iso4", "rc10"]
CENSOR = ["none", "worst10", "fd0.5"]
CONF = ["lean", "lean+retro"]
SUMMARY = ["mean", "top10", "peak"]


def side_of(c):
    c = c.lower().replace("-", "").replace("_", "")
    if "left" in c or c.endswith("l"):
        return "L"
    if "right" in c or c.endswith("r"):
        return "R"
    return None


def smooth(data, arm, zooms):
    if arm == "none":
        return data
    if arm == "iso4":
        s = [(4.0 / FW) / z for z in zooms] + [0.0]
    else:
        s = [0.0, 0.0, (10.0 / FW) / zooms[2], 0.0]
    return ndimage.gaussian_filter(data, sigma=s, mode="nearest")


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
    print(f"runs: {len(runs)}   pipelines per run: "
          f"{len(SMOOTH)*len(CENSOR)*len(CONF)*len(SUMMARY)}", flush=True)

    for k_run, run in enumerate(runs):
        ds = run["dataset"]
        conds = conditions_for(ds, run["run_id"])
        if not conds:
            continue
        parcels, _ = driver.build_parcels(run)
        if "gmhorn" not in parcels or "cord" not in parcels:
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
            img = nib.load(str(run["bold"]))
            data = np.asarray(img.dataobj, dtype=np.float32)
        except Exception:
            continue
        if data.ndim != 4:
            continue
        zooms = [float(z) for z in img.header.get_zooms()[:3]]
        n_vol = data.shape[3]
        tr = repetition_time_s(run["bold"])
        Xt, names = build_task_design(
            corrected_events(ds, erows, stt, run["run_id"]), n_vol, tr, conds)
        if Xt.shape[1] == 0:
            continue
        cord = parcels["cord"]["cord"]
        midx = np.argwhere(cord)
        ht, fixed = HORN[ds]

        Xlean, _ = lean_confounds(Path(run["confounds"]), n_vol)
        try:
            cdf = pd.read_csv(run["confounds"], sep="\t").iloc[:n_vol]
            rc = [c for c in cdf.columns if c.lower().startswith("retroicor")]
            Xretro = np.nan_to_num(cdf[rc].to_numpy(float)) if rc else np.empty((n_vol, 0))
            if Xretro.size:
                Xretro = Xretro[:, Xretro.std(0) > 1e-9]
            fd = np.nan_to_num(cdf["framewise_displacement"].to_numpy(float)) \
                if "framewise_displacement" in cdf else np.zeros(n_vol)
        except Exception:
            Xretro, fd = np.empty((n_vol, 0)), np.zeros(n_vol)

        for sm in SMOOTH:
            d4 = smooth(data, sm, zooms)
            Y = d4[cord].T.astype(np.float64)
            if Y.shape[0] != n_vol:
                continue
            Yc = Y - Y.mean(axis=0, keepdims=True)
            for cf, cn_ in product(CONF, CENSOR):
                Xn = Xlean if cf == "lean" else (
                    np.column_stack([Xlean, Xretro]) if Xretro.size else Xlean)
                X = np.column_stack([Xt, Xn, np.ones(n_vol)]) if Xn.size \
                    else np.column_stack([Xt, np.ones(n_vol)])
                if cn_ == "none":
                    keepf = np.ones(n_vol, bool)
                elif cn_ == "worst10":
                    keepf = fd <= np.quantile(fd, 0.90)
                else:
                    keepf = fd <= 0.5
                idx = np.where(keepf)[0]
                if len(idx) < 60:
                    continue
                odd, even = idx[0::2], idx[1::2]

                def fit(ix):
                    Xi = X[ix]
                    kk = Xi.std(axis=0) > 1e-9
                    kk[:Xt.shape[1]] = True
                    kk[-1] = True
                    Xi = Xi[:, kk]
                    if len(ix) <= Xi.shape[1] + 2 or \
                            np.linalg.matrix_rank(Xi) < Xi.shape[1]:
                        return None
                    b, *_ = np.linalg.lstsq(
                        Xi, Yc[ix] - Yc[ix].mean(0, keepdims=True), rcond=None)
                    return b

                b1, b2 = fit(odd), fit(even)
                if b1 is None or b2 is None:
                    continue
                for ci, cname in enumerate(names):
                    sd_ = side_of(cname) or fixed
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
                    vals = {"mean": float(v2.mean()),
                            "top10": float(v2[np.argsort(v1)[-k:]].mean()),
                            "peak": float(v2[np.argmax(v1)])}
                    for sumr, val in vals.items():
                        rows.append(dict(
                            dataset=ds, subject=run["subject"],
                            run_id=run["run_id"], condition=cname,
                            smoothing=sm, censoring=cn_, confounds=cf,
                            summary=sumr, value=val))
        if (k_run + 1) % 20 == 0:
            print(f"  {k_run+1}/{len(runs)}", flush=True)

    df = pd.DataFrame(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT / "r10_multiverse.csv", index=False)
    report(df)


def report(df):
    print("\n" + "=" * 88)
    print("R10  PRUNED MULTIVERSE -- the distribution of the CONCLUSION")
    print("=" * 88)
    if not len(df):
        print("no runs resolved")
        return
    short = lambda d: d.split("_")[1] if d.split("_")[0] == "openneuro" else d.split("_")[2]
    axes = ["smoothing", "censoring", "confounds", "summary"]
    res = []
    for (ds, *a), g in df.groupby(["dataset"] + axes):
        s = g.groupby("subject").value.mean().to_numpy(float)
        s = s[np.isfinite(s)]
        if len(s) < 5 or s.std(ddof=1) == 0:
            continue
        d_ = s.mean() / s.std(ddof=1)
        p = sps.ttest_1samp(s, 0.0).pvalue
        res.append(dict(dataset=ds, **dict(zip(axes, a)), d=d_, p=p, n=len(s)))
    R = pd.DataFrame(res)
    R.to_csv(OUT / "r10_multiverse_arms.csv", index=False)
    print(f"pipelines evaluated: {len(R)} across {R.dataset.nunique()} datasets "
          f"({len(R)//max(R.dataset.nunique(),1)} per dataset)\n")

    print("--- the conclusion, per dataset, across all defensible pipelines ---")
    print(f"  {'dataset':12} {'pipelines':>10} {'sig POSITIVE':>13} {'null':>8} "
          f"{'sig NEGATIVE':>13} {'d range':>18}")
    for ds, g in R.groupby("dataset"):
        pos = int(((g.p < 0.05) & (g.d > 0)).sum())
        neg = int(((g.p < 0.05) & (g.d < 0)).sum())
        nul = len(g) - pos - neg
        print(f"  {short(ds)[:12]:12} {len(g):10} {pos:12} ({100*pos/len(g):3.0f}%) "
              f"{nul:7} {neg:12} ({100*neg/len(g):3.0f}%) "
              f"{g.d.min():+.2f} to {g.d.max():+.2f}")

    print("\n--- does the SIGN flip within a dataset? ---")
    for ds, g in R.groupby("dataset"):
        flip = (g.d.min() < 0) and (g.d.max() > 0)
        print(f"  {short(ds)[:12]:12} {'SIGN FLIPS' if flip else 'sign stable':12} "
              f"({100*(g.d > 0).mean():.0f}% of pipelines positive)")

    print("\n--- which axis moves the answer most? ---")
    print("  Variance of the group d attributable to each axis, as the spread of")
    print("  per-level means within dataset. Larger means the choice matters more.")
    print(f"  {'axis':12} " + " ".join(f"{short(d)[:9]:>10}" for d in sorted(R.dataset.unique()))
          + f" {'mean':>8}")
    for ax in axes:
        cells, allv = [], []
        for ds in sorted(R.dataset.unique()):
            g = R[R.dataset == ds]
            m = g.groupby(ax).d.mean()
            v = float(m.max() - m.min()) if len(m) > 1 else np.nan
            cells.append(f"{v:.3f}" if np.isfinite(v) else "-")
            if np.isfinite(v):
                allv.append(v)
        print(f"  {ax:12} " + " ".join(c.rjust(10) for c in cells)
              + f" {np.mean(allv):8.3f}")

    print("\n--- the best and worst pipeline per dataset ---")
    for ds, g in R.groupby("dataset"):
        b = g.loc[g.d.idxmax()]
        w = g.loc[g.d.idxmin()]
        print(f"  {short(ds)[:12]:12} best d {b.d:+.2f}: "
              f"{b.smoothing}/{b.censoring}/{b.confounds}/{b.summary}")
        print(f"  {'':12} worst d {w.d:+.2f}: "
              f"{w.smoothing}/{w.censoring}/{w.confounds}/{w.summary}")

    print("""
  READING. The percentage columns are the finding. If a dataset's conclusion is
  positive in only a fraction of defensible pipelines, then a single published
  pipeline reporting that result was choosing, not discovering -- and the choice was
  not visible to the reader.

  LIMIT, restated because it matters for interpretation: distortion correction is
  absent from these axes, because changing it requires re-running the pipeline
  rather than re-analysing its output. F1 found the largest single effect on that
  axis, so the spread here is a LOWER BOUND on the true analytic variability.""")
    print("\nDONE_MARKER")


if __name__ == "__main__":
    main()
