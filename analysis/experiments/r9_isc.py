#!/usr/bin/env python3
"""R9 -- model-free detection by inter-subject correlation.

Every detection result in this project comes from a GLM: an assumed HRF, an assumed
event shape, an assumed nuisance model. Hasson's inter-subject correlation assumes
none of those. Where two subjects receive the identical stimulus at the identical
times, any shared timecourse must be stimulus-driven, because nothing else is
synchronised between two people in a scanner on different days.

That makes it a genuine independent check on the nulls. If ISC finds shared
stimulus-driven signal in the cord where the GLM finds nothing, the nulls were an
estimator or model-assumption problem. If ISC is also flat, the model assumptions
were not the limitation.

WHERE IT IS VALID, checked rather than assumed. Onset sequences were compared across
runs: ds004616 has 17 runs sharing one sequence, balgrist_motor all 46, and
balgrist_cospigvs all 43. ds004926 and ds005883 have subject-specific jitter -- 60
and 39 distinct sequences respectively -- so ISC is undefined there and they are
excluded rather than fudged.

DESIGN
- Runs are grouped by their exact onset signature; only groups of 8 or more enter.
- Common space is the same anatomical-cell scheme as R3/R4 (GM horn x spinal level),
  since voxel grids are native per subject. Cell timecourses are compared, not
  voxels.
- Timecourses are cosine-detrended, so shared scanner drift cannot masquerade as
  shared stimulus response. Motion is regressed out too here, unlike R5: motion is
  not a candidate explanation for BETWEEN-subject synchrony, but a large shared
  motion artefact would still be noise.
- Only pairs from DIFFERENT subjects contribute, so within-subject similarity
  cannot inflate it.
- NULL: one member of each pair is circularly shifted by a random amount. That
  preserves each timecourse's own autocorrelation and amplitude exactly and destroys
  only the temporal alignment, which is the thing ISC tests. 200 shifts.
"""
from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path

sys.path.insert(0, "/mnt/ssd1/SpinePrep")

import numpy as np
import pandas as pd
import yaml
from scipy import stats as sps

from analysis import driver
from analysis.glm import lean_confounds
from analysis.glm_spec import conditions_for, corrected_events, repetition_time_s

COHORT = Path("/mnt/ssd1/spineprep_cohort_s2")
OUT = Path("/mnt/ssd1/SpinePrep/analysis/results")
GM = ("dorsal", "ventral", "intermediate")
SIDES = ("L", "R")
MIN_GROUP = 8
N_SHIFT = 200

DATASETS = ["openneuro_ds004616_spinalcord_handgrasp_task",
            "internal_balgrist_motor_11",
            "internal_balgrist_cospigvs_11"]
HORN = {"openneuro_ds004616_spinalcord_handgrasp_task": "ventral",
        "internal_balgrist_motor_11": "ventral",
        "internal_balgrist_cospigvs_11": "ventral"}


def cell_series(Y, parcels, midx, levels, horn_tier):
    """{cell: timecourse} over GM parcel x spinal level, plus two summary ROIs."""
    out = {}
    lv = levels[tuple(midx.T)] if levels is not None else None
    uniq = sorted(set(int(x) for x in np.unique(lv) if x > 0)) if lv is not None else []
    for p in GM:
        for s in SIDES:
            m = (parcels.get("gmhorn") or {}).get(f"gm-{p}-{s}")
            if m is None:
                continue
            fi = m[tuple(midx.T)]
            if fi.sum() >= 3:
                out[f"{p}-{s}"] = Y[:, fi].mean(axis=1)
            if lv is None:
                continue
            for L in uniq:
                sel = fi & (lv == L)
                if sel.sum() >= 3:
                    out[f"{p}-{s}-L{L}"] = Y[:, sel].mean(axis=1)
    out["whole_cord"] = Y.mean(axis=1)
    for s in SIDES:
        m = (parcels.get("gmhorn") or {}).get(f"gm-{horn_tier}-{s}")
        if m is not None:
            fi = m[tuple(midx.T)]
            if fi.sum() >= 3:
                out[f"APRIORI-{s}"] = Y[:, fi].mean(axis=1)
    return out


def isc_and_null(series, subjects, rng):
    """Mean between-subject correlation, and the circular-shift null."""
    n = len(series)
    obs, null = [], []
    for i, j in combinations(range(n), 2):
        if subjects[i] == subjects[j]:
            continue
        a, b = series[i], series[j]
        L = min(len(a), len(b))
        a, b = a[:L], b[:L]
        if np.std(a) < 1e-9 or np.std(b) < 1e-9:
            continue
        obs.append(float(np.corrcoef(a, b)[0, 1]))
    if len(obs) < 10:
        return np.nan, np.nan, np.nan, 0
    for _ in range(N_SHIFT):
        acc = []
        for i, j in combinations(range(n), 2):
            if subjects[i] == subjects[j]:
                continue
            a, b = series[i], series[j]
            L = min(len(a), len(b))
            a, b = a[:L], np.roll(b[:L], int(rng.integers(1, L)))
            if np.std(a) < 1e-9 or np.std(b) < 1e-9:
                continue
            acc.append(float(np.corrcoef(a, b)[0, 1]))
        if acc:
            null.append(float(np.mean(acc)))
    if not null:
        return float(np.mean(obs)), np.nan, np.nan, len(obs)
    null = np.asarray(null)
    o = float(np.mean(obs))
    p = float((null >= o).mean())
    return o, float(null.mean()), p, len(obs)


def main():
    cfg = yaml.safe_load(Path("config/datasets_local.yaml").read_text()) or {}
    rawcfg = cfg.get("datasets", cfg)

    def mkpath(v):
        p = Path(v.get("path") or v.get("bids_root")) if isinstance(v, dict) else Path(v)
        return p if p.is_absolute() else Path("/mnt/ssd1/SpinePrep") / p

    roots = {k: mkpath(v) for k, v in rawcfg.items()}
    import nibabel as nib

    store = defaultdict(list)          # (dataset, onset_signature) -> records
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
        try:
            sig = tuple(round(float(r["onset"]), 1) for r in erows)
        except Exception:
            continue
        try:
            data = np.asarray(nib.load(str(run["bold"])).dataobj, dtype=np.float32)
        except Exception:
            continue
        if data.ndim != 4:
            continue
        n_vol = data.shape[3]
        tr = repetition_time_s(run["bold"])
        cord = parcels["cord"]["cord"]
        midx = np.argwhere(cord)
        Y = data[cord].T.astype(np.float64)
        if Y.shape[0] != n_vol:
            continue
        Y = Y - Y.mean(axis=0, keepdims=True)
        Xn, _ = lean_confounds(Path(run["confounds"]), n_vol)
        Z = np.column_stack([Xn, np.ones(n_vol)]) if Xn.size else np.ones((n_vol, 1))
        Z = Z[:, Z.std(axis=0) > 1e-12] if Z.shape[1] > 1 else Z
        q, _ = np.linalg.qr(np.column_stack([Z, np.ones(n_vol)]))
        Y = Y - q @ (q.T @ Y)
        levels = None
        lp = Path(run["spinallevels"])
        if lp.exists():
            try:
                levels = np.asarray(nib.load(str(lp)).dataobj)
            except Exception:
                levels = None
        cs = cell_series(Y, parcels, midx, levels, HORN[ds])
        store[(ds, sig, n_vol, round(tr, 3))].append(
            dict(subject=run["subject"], run_id=run["run_id"], cells=cs))
        if (k_run + 1) % 25 == 0:
            print(f"  {k_run+1}/{len(runs)}", flush=True)

    rows = []
    rng = np.random.default_rng(11)
    for (ds, sig, n_vol, tr), recs in store.items():
        subs = [r["subject"] for r in recs]
        if len(recs) < MIN_GROUP or len(set(subs)) < 6:
            continue
        keys = set(recs[0]["cells"])
        for r in recs[1:]:
            keys &= set(r["cells"])
        for key in sorted(keys):
            series = [r["cells"][key] for r in recs]
            o, nu, p, npair = isc_and_null(series, subs, rng)
            if not np.isfinite(o):
                continue
            rows.append(dict(dataset=ds, n_runs=len(recs),
                             n_subjects=len(set(subs)), n_vol=n_vol, tr=tr,
                             cell=key, isc=o, isc_null=nu, p=p, n_pairs=npair))
    df = pd.DataFrame(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT / "r9_isc.csv", index=False)
    report(df)


def report(df):
    print("\n" + "=" * 88)
    print("R9  INTER-SUBJECT CORRELATION -- detection with no HRF and no design matrix")
    print("=" * 88)
    if not len(df):
        print("no shared-timing group large enough")
        print("\nDONE_MARKER")
        return
    lab = lambda d: d.split("_")[1][:12] if d.split("_")[0] == "openneuro" \
        else "_".join(d.split("_")[1:3])[:14]
    print("ISC is the mean correlation between DIFFERENT subjects' cell timecourses.")
    print("The null circularly shifts one member of each pair, preserving each")
    print("timecourse's autocorrelation and destroying only the alignment.\n")
    print(f"  {'dataset':16} {'ROI':16} {'runs':>5} {'subj':>5} {'ISC':>8} "
          f"{'null':>8} {'ISC-null':>9} {'p':>8} {'pairs':>6}")
    for ds, g in df.groupby("dataset"):
        prio = [c for c in g.cell.unique() if c.startswith("APRIORI")]
        for key in prio + ["whole_cord"]:
            gg = g[g.cell == key]
            if not len(gg):
                continue
            r = gg.iloc[0]
            star = "  <--" if r.p < 0.05 else ""
            print(f"  {lab(ds):16} {key:16} {r.n_runs:5.0f} {r.n_subjects:5.0f} "
                  f"{r.isc:+8.4f} {r.isc_null:+8.4f} {r.isc - r.isc_null:+9.4f} "
                  f"{r.p:8.4f} {r.n_pairs:6.0f}{star}")
    print("\n  --- all anatomical cells, strongest first per dataset ---")
    for ds, g in df.groupby("dataset"):
        gg = g.assign(delta=g.isc - g.isc_null).sort_values("delta", ascending=False)
        n_sig = int((gg.p < 0.05).sum())
        print(f"  {lab(ds)}: {n_sig}/{len(gg)} cells above their own shift null "
              f"at p<0.05")
        for _, r in gg.head(4).iterrows():
            print(f"      {r.cell:18} ISC {r.isc:+.4f}  null {r.isc_null:+.4f}  "
                  f"delta {r.delta:+.4f}  p={r.p:.4f}")
    print("""
  READING. ISC above its shift null means signal shared between different people at
  the same stimulus times, which cannot come from anything but the stimulus -- no
  HRF, event shape or nuisance model is assumed. If that appears where the GLM
  group tests were null, the model assumptions were the limitation. If ISC is flat
  too, they were not, and the cord response genuinely is at the edge of
  detectability in single sessions.

  The circular-shift null is essential here: cord timecourses share strong
  autocorrelation and residual physiological structure, and a naive test against
  zero would call that stimulus-driven synchrony.""")
    print("\nDONE_MARKER")


if __name__ == "__main__":
    main()
