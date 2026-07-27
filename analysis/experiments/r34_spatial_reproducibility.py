#!/usr/bin/env python3
"""R3 + R4 -- is ANY spatial feature of the cord response reproducible?

N5 established that the peak carries no subject-specific information: ICC(2,1) on
the rostrocaudal peak is +0.16, +0.03, +0.05 and -0.04 across four datasets, and
between-run SD within one session equals or exceeds between-subject SD. Because
within-subject repeats pass through the same registration, that convicts
measurement noise rather than normalisation.

That leaves an obvious and unanswered question. The peak is one number, the
argmax. Does the PATTERN carry information the argmax throws away? Two tests:

R3  FINGERPRINTING (Finn 2015, borrowed). Can a run be matched to the correct
    subject purely from its cord response pattern? Identification accuracy against
    a 1/n_subjects chance baseline is a sharper instrument than a correlation,
    because it asks whether the information is sufficient rather than non-zero.

R4  THE ROSTROCAUDAL PROFILE. If point localisation fails but the profile along
    the cord reproduces, the field gets a usable rule -- report profiles over
    levels, not peak coordinates. This is also the only honest route to the
    centre-of-mass claim that F3's guardrail forbids asserting: measure it.

THE COMMON-SPACE PROBLEM, and why the earlier attempt failed. Cord parcels live in
each subject's NATIVE grid, so a cross-subject voxel intersection is empty -- that
is what killed the leave-one-subject-out design. The fix is to stop using voxels.
Each run is summarised as a vector over ANATOMICAL CELLS defined by the warped
PAM50 atlas: 6 grey-matter horn parcels (dorsal/ventral/intermediate x L/R) x
spinal level. Every subject has the same cells by construction, and no voxel
correspondence is needed. R4 uses the same cells collapsed across parcels.

THREE CONTROLS, because pattern similarity is inflated by anything stable within a
subject that has nothing to do with the task.
1. The identical identification run on the MEAN-SIGNAL map and the TSNR map. Those
   contain no task information at all. If they identify subjects as well as the
   response pattern does, the response pattern is riding on anatomy and
   vasculature, not on the task.
2. The response pattern after the tSNR and mean-signal patterns are regressed out
   of it, which removes the shared component rather than merely reporting it.
3. Identification restricted to the SAME condition, so a subject is never matched
   to itself through a shared task rather than a shared physiology.
"""
from __future__ import annotations

import csv
import json
import sys
from itertools import combinations
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
GM = ("dorsal", "ventral", "intermediate")
SIDES = ("L", "R")
MIN_CELL_VOX = 3

DATASETS = ["openneuro_ds004616_spinalcord_handgrasp_task",
            "openneuro_ds005884_cospine_motor",
            "openneuro_ds004926_dorsalhorn_pain",
            "openneuro_ds005883_cospine_pain",
            "internal_balgrist_motor_11",
            "internal_balgrist_painmotor_21"]


def cell_features(vals, parcels, midx, levels):
    """Mean of `vals` in each (GM parcel x spinal level) cell, plus the profile.

    Returns (cells dict, profile dict). Cells are keyed identically for every
    subject, so the vectors are comparable across subjects without any voxel
    correspondence.
    """
    cells, prof = {}, {}
    lv = levels[tuple(midx.T)] if levels is not None else None
    uniq = sorted(set(int(x) for x in np.unique(lv) if x > 0)) if lv is not None else []
    for tier, name in ((GM, "gmhorn"),):
        for p in tier:
            for s in SIDES:
                m = (parcels.get(name) or {}).get(f"gm-{p}-{s}")
                if m is None:
                    continue
                fi = m[tuple(midx.T)]
                if lv is None:
                    if fi.sum() >= MIN_CELL_VOX:
                        cells[f"{p}-{s}"] = float(vals[fi].mean())
                    continue
                for L in uniq:
                    sel = fi & (lv == L)
                    if sel.sum() >= MIN_CELL_VOX:
                        cells[f"{p}-{s}-L{L}"] = float(vals[sel].mean())
    if lv is not None:
        for L in uniq:
            sel = lv == L
            if sel.sum() >= MIN_CELL_VOX:
                prof[f"L{L}"] = float(vals[sel].mean())
    return cells, prof


def vec(dicts, keys):
    return np.array([[d.get(k, np.nan) for k in keys] for d in dicts], dtype=float)


def ident_accuracy(V, subjects):
    """Leave-one-out nearest-neighbour identification accuracy, Spearman distance.

    A run is 'identified' when its most similar OTHER run belongs to the same
    subject. Chance is reported from the actual repeat structure by permutation,
    not assumed to be 1/n, because subjects contribute unequal numbers of runs.
    """
    n = len(V)
    ok = np.isfinite(V).sum(axis=0) >= max(4, int(0.8 * n))
    V = V[:, ok]
    keep = np.isfinite(V).all(axis=1)
    V, subjects = V[keep], np.asarray(subjects)[keep]
    if len(V) < 8 or V.shape[1] < 4 or len(set(subjects)) < 4:
        return np.nan, np.nan, 0, 0
    R = np.asarray([[sps.spearmanr(V[i], V[j]).statistic if i != j else -np.inf
                     for j in range(len(V))] for i in range(len(V))])
    R = np.nan_to_num(R, nan=-np.inf)
    hit = np.array([subjects[int(np.argmax(R[i]))] == subjects[i]
                    for i in range(len(V))])
    acc = float(hit.mean())
    rng = np.random.default_rng(7)
    null = []
    for _ in range(2000):
        ps = rng.permutation(subjects)
        null.append(float(np.mean([ps[int(np.argmax(R[i]))] == ps[i]
                                   for i in range(len(V))])))
    null = np.asarray(null)
    p = float((null >= acc).mean())
    return acc, float(null.mean()), p, len(V)


def within_between(V, subjects):
    """Mean within-subject and between-subject pattern correlation."""
    n = len(V)
    w, b = [], []
    for i, j in combinations(range(n), 2):
        m = np.isfinite(V[i]) & np.isfinite(V[j])
        if m.sum() < 4:
            continue
        r = sps.spearmanr(V[i][m], V[j][m]).statistic
        if not np.isfinite(r):
            continue
        (w if subjects[i] == subjects[j] else b).append(r)
    if len(w) < 5 or len(b) < 20:
        return np.nan, np.nan, np.nan, len(w), len(b)
    u = sps.mannwhitneyu(w, b, alternative="greater")
    return float(np.mean(w)), float(np.mean(b)), float(u.pvalue), len(w), len(b)


def residualise_vec(V, C):
    """Remove the columns of C (per-run nuisance patterns) from each row of V."""
    out = V.copy()
    for i in range(len(V)):
        m = np.isfinite(V[i]) & np.isfinite(C[i])
        if m.sum() < 5:
            continue
        x = np.column_stack([C[i][m], np.ones(m.sum())])
        q, _ = np.linalg.qr(x)
        out[i][m] = V[i][m] - q @ (q.T @ V[i][m])
    return out


def main():
    cfg = yaml.safe_load(Path("config/datasets_local.yaml").read_text()) or {}
    rawcfg = cfg.get("datasets", cfg)

    def mkpath(v):
        p = Path(v.get("path") or v.get("bids_root")) if isinstance(v, dict) else Path(v)
        return p if p.is_absolute() else Path("/mnt/ssd1/SpinePrep") / p

    roots = {k: mkpath(v) for k, v in rawcfg.items()}
    import nibabel as nib

    recs = []
    runs = [r for r in driver.iter_runs(COHORT) if r["dataset"] in DATASETS]
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
        Xn, _ = lean_confounds(Path(run["confounds"]), n_vol)
        X = np.column_stack([Xt, Xn, np.ones(n_vol)]) if Xn.size \
            else np.column_stack([Xt, np.ones(n_vol)])
        keep = X.std(axis=0) > 1e-9
        keep[:Xt.shape[1]] = True
        keep[-1] = True
        X = X[:, keep]
        if np.linalg.matrix_rank(X) < X.shape[1]:
            continue
        cord = parcels["cord"]["cord"]
        midx = np.argwhere(cord)
        Y = data[cord].T.astype(np.float64)
        if Y.shape[0] != n_vol:
            continue
        mu = Y.mean(axis=0)
        sd = Y.std(axis=0)
        tsnr = np.where(sd > 0, mu / np.maximum(sd, 1e-9), 0.0)
        B, *_ = np.linalg.lstsq(X, Y - mu[None, :], rcond=None)

        levels = None
        lp = Path(run["spinallevels"])
        if lp.exists():
            try:
                levels = np.asarray(nib.load(str(lp)).dataobj)
            except Exception:
                levels = None

        c_mu, p_mu = cell_features(mu, parcels, midx, levels)
        c_ts, p_ts = cell_features(tsnr, parcels, midx, levels)
        for ci, cn in enumerate(names):
            c_b, p_b = cell_features(B[ci], parcels, midx, levels)
            if len(c_b) < 6:
                continue
            recs.append(dict(dataset=ds, subject=run["subject"],
                             session=str(run.get("session") or "none"),
                             run_id=run["run_id"], condition=cn,
                             beta=c_b, prof=p_b, mean=c_mu, tsnr=c_ts,
                             prof_mean=p_mu, prof_tsnr=p_ts))
        if (k_run + 1) % 25 == 0:
            print(f"  {k_run+1}/{len(runs)}", flush=True)

    print(f"records: {len(recs)}", flush=True)
    import pickle
    with open(OUT / "r34_recs.pkl", "wb") as fh:
        pickle.dump(recs, fh)
    OUT.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([{k: v for k, v in r.items()
                   if k in ("dataset", "subject", "session", "run_id", "condition")}
                  for r in recs]).to_csv(OUT / "r34_records.csv", index=False)
    report(recs)


def report(recs):
    print("\n" + "=" * 90)
    print("R3  FINGERPRINTING -- can a run be matched to its subject from the pattern?")
    print("=" * 90)
    if not recs:
        print("no records")
        return
    df = pd.DataFrame(recs)
    def lab(d):
        parts = d.split("_")
        return parts[1][:10] if parts[0] == "openneuro" else "_".join(parts[1:3])[:14]
    df["dslab"] = df.dataset.map(lab)
    print("Identification: nearest other run by Spearman correlation over anatomical")
    print("cells (GM horn x spinal level). Chance is measured by permuting the subject")
    print("labels 2000 times, so unequal runs-per-subject cannot inflate it.\n")
    print(f"  {'dataset':14} {'condition':10} {'feature':14} {'n runs':>7} "
          f"{'accuracy':>9} {'chance':>8} {'p':>8}")
    for (ds, cn), g in df.groupby(["dataset", "condition"]):
        if len(g) < 8 or g.subject.nunique() < 4:
            continue
        keys_b = sorted(set().union(*[set(d) for d in g.beta]))
        keys_o = sorted(set().union(*[set(d) for d in g["mean"]]))
        Vb = vec(list(g.beta), keys_b)
        Vm = vec(list(g["mean"]), keys_o)
        Vt = vec(list(g.tsnr), keys_o)
        subs = list(g.subject)
        rowsout = []
        for lab_, V in (("task beta", Vb), ("mean signal", Vm), ("tSNR", Vt)):
            a, ch, p, n = ident_accuracy(V, subs)
            rowsout.append((lab_, a, ch, p, n))
        # beta with the anatomy/vasculature patterns removed
        common = [k for k in keys_b if k in keys_o]
        if len(common) >= 6:
            Vb2 = vec(list(g.beta), common)
            Vt2 = vec(list(g.tsnr), common)
            Vm2 = vec(list(g["mean"]), common)
            Vr = residualise_vec(residualise_vec(Vb2, Vt2), Vm2)
            a, ch, p, n = ident_accuracy(Vr, subs)
            rowsout.append(("beta | tSNR,mean", a, ch, p, n))
        for lab_, a, ch, p, n in rowsout:
            if not n or not np.isfinite(a):
                continue          # no within-subject repeats: not testable, not "nan"
            star = "  <--" if (np.isfinite(p) and p < 0.05) else ""
            print(f"  {lab(ds)[:14]:14} {cn[:10]:10} {lab_:14} {n:7} "
                  f"{a:9.3f} {ch:8.3f} {p:8.4f}{star}")

    print("\n--- within- vs between-subject pattern correlation ---")
    print(f"  {'dataset':14} {'condition':10} {'feature':14} {'within':>8} """
          f"{'between':>8} {'p(W>B)':>9} {'nW':>5} {'nB':>6}")
    for (ds, cn), g in df.groupby(["dataset", "condition"]):
        if len(g) < 8 or g.subject.nunique() < 4:
            continue
        keys_b = sorted(set().union(*[set(d) for d in g.beta]))
        keys_o = sorted(set().union(*[set(d) for d in g.tsnr]))
        subs = list(g.subject)
        common = [k for k in keys_b if k in keys_o]
        feats = [("task beta", vec(list(g.beta), keys_b)),
                 ("tSNR", vec(list(g.tsnr), keys_o))]
        if len(common) >= 6:
            feats.append(("beta|tSNR,mean",
                          residualise_vec(residualise_vec(
                              vec(list(g.beta), common),
                              vec(list(g.tsnr), common)),
                              vec(list(g["mean"]), common))))
        for lab_, V in feats:
            w, b, p, nw, nb = within_between(V, subs)
            if not np.isfinite(w):
                continue
            star = "  <--" if p < 0.05 else ""
            print(f"  {lab(ds)[:14]:14} {cn[:10]:10} {lab_:14} {w:+8.3f} "
                  f"{b:+8.3f} {p:9.4f} {nw:5} {nb:6}{star}")

    print("\n" + "=" * 90)
    print("R4  THE ROSTROCAUDAL PROFILE -- does it reproduce where the peak does not?")
    print("=" * 90)
    print("Same machinery on the response profile over spinal levels alone.")
    print(f"  {'dataset':14} {'condition':10} {'feature':12} {'levels':>7} "
          f"{'within':>8} {'between':>8} {'p(W>B)':>9} {'ident acc':>10} {'chance':>8}")
    for (ds, cn), g in df.groupby(["dataset", "condition"]):
        if len(g) < 8 or g.subject.nunique() < 4:
            continue
        keys = sorted(set().union(*[set(d) for d in g.prof]),
                      key=lambda s: int(s[1:]))
        if len(keys) < 4:
            continue
        subs = list(g.subject)
        pk = [k for k in keys if k in set().union(*[set(d) for d in g.prof_tsnr])]
        pfeats = [("task profile", vec(list(g.prof), keys)),
                  ("tSNR profile", vec(list(g.prof_tsnr), keys))]
        if len(pk) >= 4:
            pfeats.append(("prof|tSNR prof",
                           residualise_vec(vec(list(g.prof), pk),
                                           vec(list(g.prof_tsnr), pk))))
        for lab_, V in pfeats:
            w, b, p, nw, nb = within_between(V, subs)
            a, ch, pa, n = ident_accuracy(V, subs)
            if not np.isfinite(w):
                continue
            star = "  <--" if p < 0.05 else ""
            print(f"  {lab(ds)[:14]:14} {cn[:10]:10} {lab_:14} {len(keys):7} "
                  f"{w:+8.3f} {b:+8.3f} {p:9.4f} {a:10.3f} {ch:8.3f}{star}")

    print("""
  HOW TO READ BOTH
  - Identification above chance for the task beta, WHILE the tSNR and mean-signal
    features stay at chance, is subject-specific task information that the peak
    threw away. That would sharpen N5 from "no information" to "no information in
    the argmax" and would restore a use for individual differences.
  - Identification above chance for tSNR and mean signal TOO means the pattern is
    carrying anatomy and vasculature. The 'beta | tSNR,mean' row is the version
    that matters in that case: it is the task pattern with those removed.
  - For R4, a profile that reproduces within subject while the peak does not
    (N5: peak ICC ~0) is the constructive result -- it names the spatial claim the
    data supports. If the profile is no better, then no spatial summary of the cord
    response is subject-specific, which is a stronger and bleaker statement than
    N5 alone.""")
    print("\nDONE_MARKER")


if __name__ == "__main__":
    main()
