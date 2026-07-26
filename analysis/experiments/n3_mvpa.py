#!/usr/bin/env python3
"""N3 -- multivariate detection as the correct summary measure.

F2 shows that summarising an a-priori cord horn by its MEAN destroys the task
effect and inverts its sign in half the datasets, while a cross-validated top-10%
recovers it. Both are univariate summaries of a spatial pattern, and both need
the analyst to have guessed the right ROI.

The brain field's answer to focal signal in a small region is not a better
average, it is to stop averaging: cross-validated multivariate classification
never collapses the pattern, so the dilution mechanism cannot bite it.

If the focality thesis is right this predicts something specific and falsifiable:
multivariate detection should recover task information in the datasets that are
NULL under unbiased univariate testing, and it should do so from the WHOLE CORD
without being told which horn to look in. If it does, the field's cord nulls are
a summary-measure artifact rather than an absence of signal. If it does not, the
signal genuinely is not there and F5's non-replication stands as biology.

DESIGN
- Input is the locked preprocessing (preproc-v1), the same derivatives every
  other analysis uses.
- Nuisance (motion, cosine, spikes) is regressed out first, identically for every
  arm, so no arm gets a cleaner input than another.
- One sample per task block: the mean pattern over [onset+4 s, onset+duration+4 s]
  for the HRF delay. Baseline samples are drawn from windows at least 10 s clear
  of any event, matched in count.
- Cross-validation is LEAVE-ONE-BLOCK-OUT over contiguous blocks, never random
  k-fold over timepoints: neighbouring frames are correlated and random folds
  would leak the answer across the split.
- Classifier is shrinkage LDA, appropriate when voxels outnumber samples.
- Three ROIs: the a-priori horn, the ipsilateral hemicord, and the whole cord.
  The whole-cord arm is the real question -- it needs no anatomical guess.
- The univariate comparators are computed ON THE SAME FOLDS, so the contrast is
  estimator versus estimator and not fold versus fold.

TWO NULLS, because an AUC above 0.5 proves nothing on its own.
1. Block-label permutation within run (N_PERM shuffles), which preserves the
   spatial covariance and the temporal structure and destroys only the labels.
2. Resting runs with synthetic block designs, the N1 null, which additionally
   destroys any task-correlated physiology.
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
from sklearn.decomposition import PCA
from sklearn.discriminant_analysis import LinearDiscriminantAnalysis as LDA
from sklearn.metrics import roc_auc_score

from analysis import driver
from analysis.glm import lean_confounds
from analysis.glm_spec import conditions_for, corrected_events, repetition_time_s

COHORT = Path("/mnt/ssd1/spineprep_cohort_s2")
OUT = Path("/mnt/ssd1/SpinePrep/analysis/results")
N_PERM = 50
SEED = 20260727
HRF_DELAY_S = 4.0
CLEAR_S = 10.0

HORN = {
    "openneuro_ds004616_spinalcord_handgrasp_task": ("ventral", None),
    "openneuro_ds005884_cospine_motor": ("ventral", None),
    "internal_balgrist_motor_11": ("ventral", None),
    "internal_balgrist_painmotor_21": ("ventral", None),
    "internal_balgrist_cospigvs_11": ("ventral", None),
    "openneuro_ds004926_dorsalhorn_pain": ("dorsal", "L"),
    "openneuro_ds005883_cospine_pain": ("dorsal", "R"),
}


def side_of(c):
    c = c.lower().replace("-", "").replace("_", "")
    if "left" in c or c.endswith("l"):
        return "L"
    if "right" in c or c.endswith("r"):
        return "R"
    return None


def residualise(Y, Xn):
    """Project the nuisance space out of the data, once, for every arm."""
    if Xn is None or Xn.size == 0:
        Xn = np.ones((Y.shape[0], 1))
    else:
        Xn = np.column_stack([Xn, np.ones(Y.shape[0])])
    q, _ = np.linalg.qr(Xn)
    return Y - q @ (q.T @ Y)


def samples(Y, tr, blocks, n_vol):
    """(X, y, group) -- one row per block plus matched baseline rows."""
    d = HRF_DELAY_S
    onoff = np.zeros(n_vol, bool)
    for o, dur in blocks:
        a = int(np.floor((o + d) / tr))
        b = int(np.ceil((o + dur + d) / tr))
        onoff[max(0, a):min(n_vol, max(a + 1, b))] = True
    # frames clear of every event by CLEAR_S on both sides
    clear = np.ones(n_vol, bool)
    for o, dur in blocks:
        a = int(np.floor((o - CLEAR_S) / tr))
        b = int(np.ceil((o + dur + d + CLEAR_S) / tr))
        clear[max(0, a):min(n_vol, max(a + 1, b))] = False
    X, y, g = [], [], []
    for i, (o, dur) in enumerate(blocks):
        a = int(np.floor((o + d) / tr))
        b = int(np.ceil((o + dur + d) / tr))
        a, b = max(0, a), min(n_vol, max(a + 1, b))
        if b <= a:
            continue
        X.append(Y[a:b].mean(axis=0)); y.append(1); g.append(i)
    if not X:
        return None
    # baseline windows of the same mean length, spread over the clear frames
    w = max(1, int(round(np.mean([len(range(*_ab(o, dur, tr, n_vol)))
                                  for o, dur in blocks]))))
    ci = np.where(clear)[0]
    runs_ = np.split(ci, np.where(np.diff(ci) != 1)[0] + 1) if len(ci) else []
    wins = [r[i:i + w] for r in runs_ for i in range(0, len(r) - w + 1, w)
            if len(r[i:i + w]) == w]
    if not wins:
        return None
    step = max(1, len(wins) // max(1, len(X)))
    chosen = wins[::step][:len(X)]
    for j, wi in enumerate(chosen):
        X.append(Y[wi].mean(axis=0)); y.append(0); g.append(j)
    return np.asarray(X), np.asarray(y), np.asarray(g)


def _ab(o, dur, tr, n_vol):
    a = int(np.floor((o + HRF_DELAY_S) / tr))
    b = int(np.ceil((o + dur + HRF_DELAY_S) / tr))
    return max(0, a), min(n_vol, max(a + 1, b))


def cv_auc(X, y, g, rng=None, permute=False):
    """Leave-one-block-out AUC, plus the univariate comparators on the same folds."""
    y = y.copy()
    if permute and rng is not None:
        # shuffle the label of each block PAIR, preserving the design structure
        for gi in np.unique(g):
            m = g == gi
            if m.sum() == 2:
                y[m] = rng.permutation(y[m])
        if len(np.unique(y)) < 2:
            return None
    groups = np.unique(g)
    if len(groups) < 4:
        return None
    scores, truth, uni, unitop = [], [], [], []
    for gi in groups:
        te = g == gi
        trn = ~te
        if len(np.unique(y[trn])) < 2 or te.sum() == 0:
            continue
        Xtr, Xte = X[trn], X[te]
        mu, sd = Xtr.mean(0), Xtr.std(0)
        sd[sd < 1e-9] = 1.0
        Xtr, Xte = (Xtr - mu) / sd, (Xte - mu) / sd
        # univariate comparators BEFORE any dimensionality reduction, so they see
        # the same voxels the ROI actually contains
        con = Xtr[y[trn] == 1].mean(0) - Xtr[y[trn] == 0].mean(0)
        uni.append(np.atleast_1d(Xte.mean(axis=1)))
        k = max(1, int(0.1 * len(con)))
        top = np.argsort(con)[-k:]
        unitop.append(np.atleast_1d(Xte[:, top].mean(axis=1)))
        # PCA on the TRAINING half only. A whole-cord ROI is ~850 voxels against
        # ~30 samples, where a full covariance estimate is both unstable and the
        # dominant cost. Components are fitted on train and applied to test, so
        # no test information reaches the reduction.
        ncomp = int(min(Xtr.shape[1], max(2, Xtr.shape[0] - 2), 40))
        if Xtr.shape[1] > ncomp:
            try:
                pca = PCA(n_components=ncomp, svd_solver="randomized",
                          random_state=0).fit(Xtr)
                Xtr, Xte = pca.transform(Xtr), pca.transform(Xte)
            except Exception:
                pass
        try:
            clf = LDA(solver="lsqr", shrinkage="auto").fit(Xtr, y[trn])
            s = clf.decision_function(Xte)
        except Exception:
            uni.pop(); unitop.pop()
            continue
        scores.append(np.atleast_1d(s)); truth.append(y[te])
    if len(truth) < 4:
        return None
    tr_ = np.concatenate(truth)
    if len(np.unique(tr_)) < 2:
        return None
    def auc(v):
        try:
            return float(roc_auc_score(tr_, np.concatenate(v)))
        except Exception:
            return np.nan
    return dict(auc_mvpa=auc(scores), auc_uni_mean=auc(uni), auc_uni_top10=auc(unitop))


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
    print(f"task runs: {len(runs)}", flush=True)

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
        events = corrected_events(ds, erows, stt, run["run_id"])
        cord = parcels["cord"]["cord"]
        midx = np.argwhere(cord)
        Xn, _ = lean_confounds(Path(run["confounds"]), n_vol)
        Yc = data[cord].T.astype(np.float64)
        if Yc.shape[0] != n_vol:
            continue
        Yc = residualise(Yc - Yc.mean(0, keepdims=True), Xn)

        ht, fixed = HORN[ds]
        rng = np.random.default_rng(SEED + k_run)
        for cond in conds:
            blocks = [(float(e["onset"]), float(e["duration"]))
                      for e in events if e["trial_type"] == cond]
            if len(blocks) < 4:
                continue
            sd_ = side_of(cond) or fixed
            rois = {"cord": np.ones(len(midx), bool)}
            if sd_:
                h = parcels["gmhorn"].get(f"gm-{ht}-{sd_}")
                if h is not None:
                    fi = h[tuple(midx.T)]
                    if fi.sum() >= 8:
                        rois["horn"] = fi
                hemi = (parcels.get("hemicord") or {}).get(f"hemicord-{sd_}")
                if hemi is not None:
                    fi = hemi[tuple(midx.T)]
                    if fi.sum() >= 20:
                        rois["hemicord"] = fi
            for roi, fi in rois.items():
                s = samples(Yc[:, fi], tr, blocks, n_vol)
                if s is None:
                    continue
                X, y, g = s
                if X.shape[1] < 5:
                    continue
                real = cv_auc(X, y, g)
                if real is None:
                    continue
                perm = []
                for _ in range(N_PERM):
                    p = cv_auc(X, y, g, rng=rng, permute=True)
                    if p:
                        perm.append(p["auc_mvpa"])
                perm = np.asarray([v for v in perm if np.isfinite(v)])
                rows.append(dict(
                    dataset=ds, subject=run["subject"], run_id=run["run_id"],
                    condition=cond, roi=roi, n_vox=int(fi.sum()),
                    n_blocks=len(blocks), **real,
                    perm_mean=float(perm.mean()) if perm.size else np.nan,
                    perm_p=float((perm >= real["auc_mvpa"]).mean()) if perm.size else np.nan,
                ))
        if (k_run + 1) % 20 == 0:
            print(f"  {k_run+1}/{len(runs)}", flush=True)

    OUT.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "n3_mvpa.csv", index=False)
    report(df)


def gstat(g, col, null=0.5):
    s = g.groupby("subject")[col].mean().to_numpy(float)
    s = s[np.isfinite(s)]
    if len(s) < 5 or s.std(ddof=1) == 0:
        return np.nan, np.nan, len(s), np.nan
    t, p = sps.ttest_1samp(s, null)
    return (s.mean() - null) / s.std(ddof=1), p, len(s), s.mean()


def report(df):
    print("\n" + "=" * 84)
    print("N3  MULTIVARIATE DETECTION vs UNIVARIATE SUMMARIES, identical folds")
    print("=" * 84)
    if not len(df):
        print("no runs resolved")
        return
    print(f"runs {df.run_id.nunique()}   datasets {df.dataset.nunique()}   "
          f"permutations/arm {N_PERM}")
    print("\nAUC is leave-one-block-out. d and p test the SUBJECT means against 0.5.")
    print("perm_p is the within-run block-label permutation null, averaged.\n")
    for ds, gds in df.groupby("dataset"):
        print(f"  {ds}")
        print(f"    {'ROI':10} {'vox':>5} {'AUC mvpa':>9} {'d':>7} {'p':>9} "
              f"{'permAUC':>8} {'AUC uni-mean':>13} {'AUC uni-top10':>14} {'N':>4}")
        for roi in ("horn", "hemicord", "cord"):
            g = gds[gds.roi == roi]
            if not len(g):
                continue
            d, p, n, m = gstat(g, "auc_mvpa")
            _, _, _, mm = gstat(g, "auc_uni_mean")
            _, _, _, mt = gstat(g, "auc_uni_top10")
            print(f"    {roi:10} {g.n_vox.median():5.0f} {m:9.3f} {d:+7.2f} "
                  f"{p:9.4f} {g.perm_mean.mean():8.3f} {mm:13.3f} {mt:14.3f} {n:4}")
        print()
    print("  POOLED across datasets, subject means:")
    print(f"    {'ROI':10} {'AUC mvpa':>9} {'d':>7} {'p':>10} {'uni-mean':>10} "
          f"{'uni-top10':>10}")
    for roi in ("horn", "hemicord", "cord"):
        g = df[df.roi == roi]
        if not len(g):
            continue
        s = g.groupby(["dataset", "subject"])[
            ["auc_mvpa", "auc_uni_mean", "auc_uni_top10"]].mean()
        v = s.auc_mvpa.to_numpy()
        t, p = sps.ttest_1samp(v, 0.5)
        print(f"    {roi:10} {v.mean():9.3f} {(v.mean()-0.5)/v.std(ddof=1):+7.2f} "
              f"{p:10.2e} {s.auc_uni_mean.mean():10.3f} "
              f"{s.auc_uni_top10.mean():10.3f}")
    print("\n  READING. The whole-cord row is the one that matters: it needs no")
    print("  anatomical guess. If it detects where the a-priori horn univariate")
    print("  test is null, the field's cord nulls are a summary-measure artifact.")
    print("  If the permutation AUC is not ~0.5, the fold structure leaks and")
    print("  nothing here is interpretable.")
    print("\nDONE_MARKER")


if __name__ == "__main__":
    main()
