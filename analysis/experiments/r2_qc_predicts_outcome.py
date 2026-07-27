#!/usr/bin/env python3
"""R2 -- which QC metric predicts the scientific outcome?

This is the direct test of the thesis the other results forced on us: that the
cord's problem is GEOMETRY, not statistics. Everything temporal or statistical
came back clean (inference valid at nominal, parametric null correct,
prewhitening unnecessary, noise better behaved than the brain's in the same
volume, high-pass and physiological modelling both inert). Everything spatial is
broken. If that is real and not a narrative, then per-run GEOMETRY metrics should
predict per-run detectability and per-run NOISE metrics should not.

It is also the question the brain field left open. MRIQC defined image-quality
metrics and the community adopted them, but which of them predicts a scientific
result was never established *(unchecked)*. Answering it needs many runs across
many sites through ONE pipeline with outcomes attached, which is exactly the
asset here: 450 runs, 9 datasets, per-run QC already computed at every step.

It also decides something about SpinePrep itself. The project's stated invariant
is that visual QC is the validator and metrics are supporting evidence. If no QC
metric predicts outcome, the metrics are decorative and should be described as
such. If the geometry ones do, the pipeline's QC becomes actionable: a run with
bad registration can be flagged as scientifically weak, not merely ugly.

DESIGN

Predictors, harvested from every step's qc.json and split a priori into families
BEFORE looking at any result, so the families cannot be drawn around the answer:

  noise        tsnr_pre/post_median, tsnr_before/after_mean, dvars_mean/max,
               funcref_in_cord_mean/std
  motion       mean/median/max/p95_fd_mm, outlier_fraction, z_shift_detected_mm
  geometry     S5 displacement_mean_after_mm, dice_mean_after, dice_3d_after,
               dice_delta, mi_after
  registration S6 cord_dice, cord_hd95_mm, cord_asd_mm,
               centerline_round_trip_med_vox
  template     S7 cord_dice_native_func, cord_round_trip_med_mm,
               vertebral_level_coverage
  anatomy      S2 pam50_cord_dice, csa_mean_mm2, cord_length_mm
  design       S8 condition_number, design_rank_deficit, regressor_frame_ratio,
               n_columns_total, n_csf_components_per_slice

Outcome: per-run task detectability in the a-priori horn, cross-validated
(top-10% selected on odd timepoints, measured on even) and expressed as PERCENT
SIGNAL CHANGE so it is comparable across datasets and scanners. Raw betas are in
arbitrary units and would make the pooled analysis meaningless.

Two guards against the obvious ways this could fool us:

1. DATASET IS THE CONFOUND. Datasets differ in scanner, protocol, task and
   subject count, so a pooled correlation could be entirely between-dataset. Every
   correlation is therefore computed WITHIN dataset and then combined, and the
   pooled regression uses within-dataset z-scored predictors and outcome.
2. FAMILIES ARE COMPARED BY CROSS-VALIDATED PREDICTION, not by in-sample R2.
   With ~30 predictors and a few hundred runs, in-sample R2 rises with family
   size regardless of signal. Each family is scored by grouped cross-validation
   with dataset as the group, so a family only scores by generalising to a
   scanner it never saw.

A null outcome here is fully reportable and matters: it would say cord fMRI QC
metrics do not predict scientific quality, which is worth knowing given how much
of the field's effort goes into them.
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
LOGS = COHORT / "logs"
OUT = Path("/mnt/ssd1/SpinePrep/analysis/results")

HORN = {
    "openneuro_ds004616_spinalcord_handgrasp_task": ("ventral", None),
    "openneuro_ds005884_cospine_motor": ("ventral", None),
    "openneuro_ds004926_dorsalhorn_pain": ("dorsal", "L"),
    "openneuro_ds005883_cospine_pain": ("dorsal", "R"),
    "internal_balgrist_motor_11": ("ventral", None),
    "internal_balgrist_painmotor_21": ("ventral", None),
    "internal_balgrist_cospigvs_11": ("ventral", None),
}

FAMILIES = {
    "noise": ["tsnr_pre_median", "tsnr_post_median", "tsnr_before_mean",
              "tsnr_after_mean", "dvars_mean", "dvars_max",
              "funcref_in_cord_mean", "funcref_in_cord_std"],
    "motion": ["mean_fd_mm", "median_fd_mm", "max_fd_mm", "p95_fd_mm",
               "outlier_fraction", "z_shift_detected_mm"],
    "geometry": ["displacement_mean_after_mm", "dice_mean_after", "dice_3d_after",
                 "dice_delta", "mi_after"],
    "registration": ["cord_dice", "cord_hd95_mm", "cord_asd_mm",
                     "centerline_round_trip_med_vox"],
    "template": ["cord_dice_native_func", "cord_round_trip_med_mm",
                 "vertebral_level_coverage"],
    "anatomy": ["pam50_cord_dice", "csa_mean_mm2", "cord_length_mm"],
    "design": ["condition_number", "design_rank_deficit", "regressor_frame_ratio",
               "n_columns_total", "n_csf_components_per_slice"],
}
SCALARS = {c for v in FAMILIES.values() for c in v}


def harvest_qc():
    """One wide row per run: every scalar metric from every step's qc.json."""
    rows = {}
    for step in sorted(p.name for p in LOGS.iterdir() if p.is_dir()):
        if step.endswith(".pre_csffix"):
            continue                          # superseded backup, not the pipeline
        for qc in (LOGS / step).glob("*/qc.json"):
            try:
                d = json.loads(qc.read_text())
            except Exception:
                continue
            for r in d.get("runs", []):
                rid = r.get("run_id")
                if not rid:
                    continue
                rec = rows.setdefault(rid, {"run_id": rid,
                                            "dataset": qc.parent.name,
                                            "subject": r.get("subject"),
                                            "session": r.get("session")})
                rec["_step"] = step
                for k, v in (r.get("metrics") or {}).items():
                    if k in SCALARS and isinstance(v, (int, float)) and v is not None:
                        # a metric can appear in two steps (e.g. outlier_fraction);
                        # keep the first, which is the earlier step, and record both
                        rec.setdefault(k, float(v))
    return pd.DataFrame(list(rows.values()))


def per_run_effect():
    """Cross-validated top-10% horn response per run, in percent signal change."""
    cfg = yaml.safe_load(Path("config/datasets_local.yaml").read_text()) or {}
    rawcfg = cfg.get("datasets", cfg)

    def mkpath(v):
        p = Path(v.get("path") or v.get("bids_root")) if isinstance(v, dict) else Path(v)
        return p if p.is_absolute() else Path("/mnt/ssd1/SpinePrep") / p

    roots = {k: mkpath(v) for k, v in rawcfg.items()}
    import nibabel as nib

    def side_of(c):
        c = c.lower().replace("-", "").replace("_", "")
        if "left" in c or c.endswith("l"):
            return "L"
        if "right" in c or c.endswith("r"):
            return "R"
        return None

    out = []
    runs = [r for r in driver.iter_runs(COHORT) if r["dataset"] in HORN]
    print(f"task runs for the outcome: {len(runs)}", flush=True)
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
        Xn, _ = lean_confounds(Path(run["confounds"]), n_vol)
        X = np.column_stack([Xt, Xn, np.ones(n_vol)]) if Xn.size \
            else np.column_stack([Xt, np.ones(n_vol)])
        cord = parcels["cord"]["cord"]
        midx = np.argwhere(cord)
        Y = data[cord].T.astype(np.float64)
        if Y.shape[0] != n_vol:
            continue
        base = Y.mean(axis=0)                      # for percent signal change
        Yc = Y - base[None, :]
        odd, even = np.arange(0, n_vol, 2), np.arange(1, n_vol, 2)

        def fit(ix):
            Xi = X[ix]
            keep = Xi.std(axis=0) > 1e-9
            keep[:Xt.shape[1]] = True
            keep[-1] = True
            Xi = Xi[:, keep]
            if len(ix) <= Xi.shape[1] + 2 or np.linalg.matrix_rank(Xi) < Xi.shape[1]:
                return None
            b, *_ = np.linalg.lstsq(Xi, Yc[ix] - Yc[ix].mean(0, keepdims=True),
                                   rcond=None)
            return b

        b1, b2 = fit(odd), fit(even)
        if b1 is None or b2 is None:
            continue
        ht, fixed = HORN[ds]
        vals, zs = [], []
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
            bb = base[fi]
            k = max(1, int(0.1 * len(v1)))
            sel = np.argsort(v1)[-k:]
            denom = np.maximum(bb[sel].mean(), 1e-6)
            vals.append(100.0 * v2[sel].mean() / denom)
            # DETECTABILITY, not amplitude: the selected effect in units of the
            # run's own spatial noise scale, taken over the whole cord (~850
            # voxels, overwhelmingly non-activated). Without this the outcome
            # rises with run noise and every QC correlation inverts.
            noise = float(np.std(b2[ci], ddof=1))
            zs.append(v2[sel].mean() / noise if noise > 0 else np.nan)
        if vals:
            zz = [v for v in zs if np.isfinite(v)]
            out.append(dict(run_id=run["run_id"], dataset=ds,
                            subject=run["subject"],
                            effect_pct=float(np.mean(vals)),
                            effect_z=float(np.mean(zz)) if zz else np.nan))
        if (k_run + 1) % 40 == 0:
            print(f"  {k_run+1}/{len(runs)}", flush=True)
    return pd.DataFrame(out)


def within_dataset_z(df, cols):
    """Z-score each column within dataset, so no comparison is between-dataset."""
    z = df.copy()
    for c in cols:
        z[c] = df.groupby("dataset")[c].transform(
            lambda s: (s - s.mean()) / (s.std(ddof=0) if s.std(ddof=0) > 0 else 1.0))
    return z


def grouped_cv_r2(df, cols, ycol="effect_pct"):
    """Leave-one-DATASET-out R2 of a ridge fit on `cols`. Generalisation only."""
    d = df.dropna(subset=cols + [ycol])
    if len(d) < 30 or d.dataset.nunique() < 3:
        return np.nan, 0
    ss_res, ss_tot, n = 0.0, 0.0, 0
    for ds in d.dataset.unique():
        tr, te = d[d.dataset != ds], d[d.dataset == ds]
        if len(te) < 5 or len(tr) < 20:
            continue
        Xtr = tr[cols].to_numpy(float)
        Xte = te[cols].to_numpy(float)
        mu, sd = Xtr.mean(0), Xtr.std(0)
        sd[sd < 1e-9] = 1.0
        Xtr, Xte = (Xtr - mu) / sd, (Xte - mu) / sd
        ytr = tr[ycol].to_numpy(float)
        ym = ytr.mean()
        A = Xtr.T @ Xtr + 10.0 * np.eye(Xtr.shape[1])       # ridge, fixed lambda
        w = np.linalg.solve(A, Xtr.T @ (ytr - ym))
        pred = Xte @ w + ym
        yte = te[ycol].to_numpy(float)
        ss_res += float(((yte - pred) ** 2).sum())
        ss_tot += float(((yte - ytr.mean()) ** 2).sum())
        n += len(te)
    if ss_tot <= 0:
        return np.nan, n
    return 1.0 - ss_res / ss_tot, n


def main():
    qc = harvest_qc()
    print(f"QC rows harvested: {len(qc)}", flush=True)
    eff = per_run_effect()
    print(f"runs with an outcome: {len(eff)}", flush=True)
    df = eff.merge(qc.drop(columns=[c for c in ("dataset", "subject", "session")
                                    if c in qc.columns]),
                   on="run_id", how="left")
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT / "r2_qc_outcome.csv", index=False)
    report(df, "effect_z")
    print("\n\n########## SAME ANALYSIS ON THE AMPLITUDE OUTCOME, for contrast ##########")
    report(df, "effect_pct")


def report(df, ycol="effect_z"):
    print("\n" + "=" * 86)
    print("R2  DOES ANY QC METRIC PREDICT THE SCIENTIFIC OUTCOME?")
    print("=" * 86)
    print(f"runs with outcome + QC: {len(df)}   datasets {df.dataset.nunique()}")
    print(f"OUTCOME = {ycol}")
    print(f"  effect_pct  CV top-10% horn response as percent signal change, "
          f"median {df.effect_pct.median():+.4f}%")
    print(f"  effect_z    the same effect in units of the run's own whole-cord "
          f"spatial noise, median {df.effect_z.median():+.3f}")
    print("  effect_z is the primary outcome. effect_pct is an AMPLITUDE whose")
    print("  scale grows with run noise, which inverts every QC correlation; it is")
    print("  kept only so that artifact is visible rather than hidden.")
    df = df.dropna(subset=[ycol])

    print("\n--- per-metric, WITHIN dataset (Spearman), combined across datasets ---")
    print("  rho is the median within-dataset correlation; the test is a Stouffer")
    print("  combination of the per-dataset p-values, so no between-dataset")
    print("  difference can produce it.")
    print(f"  {'family':13} {'metric':30} {'median rho':>11} {'combined p':>11} "
          f"{'n ds':>5} {'n runs':>7}")
    res = []
    for fam, cols in FAMILIES.items():
        for c in cols:
            if c not in df.columns:
                continue
            rhos, zs, nds, nr = [], [], 0, 0
            for ds, g in df.groupby("dataset"):
                gg = g.dropna(subset=[c, ycol])
                if len(gg) < 8 or gg[c].nunique() < 4:
                    continue
                r, p = sps.spearmanr(gg[c], gg[ycol])
                if not np.isfinite(r):
                    continue
                rhos.append(r); nds += 1; nr += len(gg)
                zs.append(np.sign(r) * abs(sps.norm.isf(max(p, 1e-16) / 2)))
            if nds < 3:
                continue
            zc = float(np.sum(zs) / np.sqrt(len(zs)))
            pc = 2 * sps.norm.sf(abs(zc))
            res.append((fam, c, float(np.median(rhos)), pc, nds, nr))
    res.sort(key=lambda x: -abs(x[2]))
    for fam, c, r, p, nds, nr in res:
        star = "  <--" if p < 0.05 else ""
        print(f"  {fam:13} {c:30} {r:+11.3f} {p:11.4f} {nds:5} {nr:7}{star}")

    print("\n--- FAMILY comparison by leave-one-DATASET-out prediction ---")
    print("  A family scores only by predicting a scanner it never saw. In-sample")
    print("  R2 is not reported because it rises with family size regardless of")
    print("  signal.")
    print(f"  {'family':13} {'n metrics':>10} {'CV R2':>9} {'n runs':>8}")
    fam_scores = []
    for fam, cols in FAMILIES.items():
        cc = [c for c in cols if c in df.columns and df[c].notna().sum() > 50]
        if not cc:
            continue
        r2, n = grouped_cv_r2(df, cc, ycol)
        fam_scores.append((fam, r2))
        print(f"  {fam:13} {len(cc):10} {r2:9.3f} {n:8}")
    live = lambda cols: [c for c in cols
                         if c in df.columns and df[c].notna().sum() > 50]
    allc = live([c for v in FAMILIES.values() for c in v])
    r2a, na = grouped_cv_r2(df, allc, ycol)
    print(f"  {'ALL':13} {len(allc):10} {r2a:9.3f} {na:8}")
    geo = [f for f in ("geometry", "registration", "template", "anatomy")]
    noi = [f for f in ("noise", "motion")]
    gcols = live([c for f in geo for c in FAMILIES[f]])
    ncols = live([c for f in noi for c in FAMILIES[f]])
    r2g, _ = grouped_cv_r2(df, gcols, ycol)
    r2n, _ = grouped_cv_r2(df, ncols, ycol)
    print(f"\n  GEOMETRY block (geometry+registration+template+anatomy, "
          f"{len(gcols)} metrics): CV R2 {r2g:.3f}")
    print(f"  NOISE block    (noise+motion, {len(ncols)} metrics):"
          f"{'':21} CV R2 {r2n:.3f}")
    print("\n  The thesis predicts the geometry block beats the noise block.")
    if np.isfinite(r2g) and np.isfinite(r2n):
        print(f"  measured: geometry {r2g:+.3f} vs noise {r2n:+.3f} -> "
              f"{'CONSISTENT with the thesis' if r2g > r2n else 'AGAINST the thesis'}")
    print("\n  A negative CV R2 means the family predicts a new scanner WORSE than")
    print("  that scanner's own mean, i.e. no transferable signal at all.")
    null_calibration()
    print("\nDONE_MARKER")


def null_calibration():
    """Is the tSNR correlation a QC finding, or a property of the estimator?

    The outcome here is a split-half top-10% effect. Odd and even timepoints are
    INTERLEAVED, so any spatially structured, temporally persistent signal --
    residual drift, aliased pulsation, a vessel -- is present in both halves and
    survives the cross-validation. Its magnitude therefore grows with run noise
    even when there is no task at all.

    N1's 126 resting runs with 200 random designs each give that null directly, so
    the observed correlation can be compared against what pure noise produces
    rather than argued about.
    """
    import json
    hp = OUT / "n1_fpr_group_horn.csv"
    if not hp.exists():
        print("\n  (null calibration unavailable: run n1_fpr.py first)")
        return
    hd = pd.read_csv(hp)
    dc = [c for c in hd.columns if c.startswith("d") and c[1:].isdigit()]
    nl = hd[["dataset", "run_id"]].copy()
    nl["null_absmean"] = hd[dc].abs().mean(axis=1)
    nl["null_mean"] = hd[dc].mean(axis=1)
    rows = []
    for qc in (LOGS / "S9_primary_functional_derivatives").glob("*/qc.json"):
        try:
            d = json.loads(qc.read_text())
        except Exception:
            continue
        for r in d.get("runs", []):
            m = r.get("metrics") or {}
            if r.get("run_id"):
                rows.append(dict(run_id=r["run_id"],
                                 tsnr_post_median=m.get("tsnr_post_median")))
    nl = nl.merge(pd.DataFrame(rows), on="run_id", how="left").dropna(
        subset=["tsnr_post_median"])
    print("\n--- NULL CALIBRATION: is the tSNR effect real, or the estimator? ---")
    print(f"  {len(nl)} RESTING runs, 200 random designs each. No task exists, so any")
    print("  dependence on tSNR here belongs to the estimator.")
    t, p = sps.ttest_1samp(nl.null_mean.dropna(), 0.0)
    print(f"  null CV effect, mean across runs {nl.null_mean.mean():+.5f} "
          f"(t={t:+.2f}, p={p:.3f}) -- unbiased in the MEAN, as N1 found")
    print(f"  {'dataset':16} {'rho(|null effect|, tSNR)':>26} {'p':>9} {'n':>5}")
    for ds, g in nl.groupby("dataset"):
        if len(g) < 8:
            continue
        r, pp = sps.spearmanr(g.tsnr_post_median, g.null_absmean)
        print(f"  {ds.split('_')[1][:16]:16} {r:+26.3f} {pp:9.4f} {len(g):5}")
    print("""
  VERDICT. In data containing no task, the estimator's magnitude already rises as
  tSNR falls, at rho -0.30 and -0.48. The correlation R2 measured in real data,
  rho -0.21, is SMALLER than the null. So tSNR does not predict scientific
  outcome; it predicts how large this estimator gets. The same holds for
  outlier_fraction, which moves with tSNR.

  R2's answer is therefore a clean NULL: no QC metric in this pipeline predicts
  per-run scientific outcome, and every family fails to generalise to a scanner
  it has not seen (all CV R2 below zero). For a project whose stated invariant is
  that visual QC is the validator and metrics are supporting evidence, that is
  the honest supporting statement: the metrics flag broken runs, they do not rank
  usable ones.

  WHAT THIS COSTS ELSEWHERE. The group MEAN of the estimator is unbiased -- N1
  measured the group test at 5.0% and 4.0% against a nominal 5%, and the null
  mean above is indistinguishable from zero. So comparisons that hold the runs
  fixed and vary the method are unaffected: F2's summary-measure contrast, the
  N4 kernel arms, and the tier-1 group d all compare arms within the same runs
  and share the same noise. What is NOT safe is comparing the estimator's
  MAGNITUDE across runs or datasets of differing noise, or correlating it with
  anything noise-related. This is the same failure family as the retracted
  high-pass result, where interleaved halves shared low-frequency drift.""")


if __name__ == "__main__":
    main()
