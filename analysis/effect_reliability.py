#!/usr/bin/env python3
"""Reliability of the cord-fMRI EFFECT ESTIMATE vs anatomical scale.

ANALYSIS module -- not part of the preprocessing toolbox.

This replaces the flagship-reliability metric. The previous endpoints measured
the wrong quantities for "reliability": split-half of the parcel-mean TIMESERIES
(temporal signal reproducibility) and ICC of tSNR (image-quality stability).
Neither is what the field means by reliability, and on ds004926 the tSNR-ICC
(0.75) contradicts the published effect-ICC (poor; Dabbagh 2024, the same data).

Reliability that matters = does a subject's TASK EFFECT reproduce. Measured two
ways, both on the parcel-mean task beta (the effect a study would use):

  test-retest ICC(2,1)  between sessions, across subjects, per parcel.
                        The gold standard. Available only where true session
                        repeats exist (ds004926 = Dabbagh N=40, 2 days).

  split-half reliability  within a run: fit the GLM on odd vs even timepoints,
                        correlate the two effect estimates across subjects,
                        Spearman-Brown corrected. The SAME construct as
                        test-retest (does a subject's effect reproduce), but
                        available for every task dataset -> the cross-cohort
                        generalization of the scale dependence.

Both are aggregated to the four nested tiers (cord, hemicord, spinal level, GM
horn) to give the reliability-vs-scale curve on the correct quantity.
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Optional

import numpy as np
import yaml

from analysis import driver
from analysis import estimators as ES
from analysis.glm import build_task_design
from analysis.glm_spec import conditions_for, corrected_events, repetition_time_s

RESULTS = Path(__file__).resolve().parent / "results"


def _roots() -> dict:
    cfg = yaml.safe_load(Path("config/datasets_local.yaml").read_text()) or {}
    raw = cfg.get("datasets", cfg)
    out = {}
    for k, v in raw.items():
        p = Path(v.get("path") or v.get("bids_root")) if isinstance(v, dict) else Path(v)
        out[k] = p if p.is_absolute() else Path("/mnt/ssd1/SpinePrep") / p
    return out


def _events_and_start(run, roots):
    root = roots.get(run["dataset"])
    rows = None
    if root is not None:
        ev = next(iter(Path(root).rglob(f"{run['run_id']}_events.tsv")), None)
        if ev is not None:
            with open(ev) as fh:
                rows = list(csv.DictReader(fh, delimiter="\t"))
    start = 0.0
    sc = Path(str(run["bold"]).replace(".nii.gz", ".json"))
    if sc.exists():
        try:
            start = float(json.loads(sc.read_text()).get("StartTime") or 0.0)
        except Exception:
            start = 0.0
    return rows, start


def _fit_effect(data, cord_mask, events, start, dataset, run_id, tr,
                time_idx: Optional[np.ndarray] = None) -> Optional[np.ndarray]:
    """Per-cord-voxel task-effect estimate (mean beta across task conditions).

    time_idx selects a subset of timepoints (odd/even) for split-half; None uses
    the whole run. Returns a (n_cord_vox,) effect vector or None if unusable.
    """
    n_vol = data.shape[3]
    conds = conditions_for(dataset, run_id)
    ev = corrected_events(dataset, events, start, run_id)
    Xtask, task_names = build_task_design(ev, n_vol, tr, conds)
    if Xtask.shape[1] == 0:
        return None
    # task + intercept only: the effect estimate is deliberately the raw task
    # beta, matching the effect a study reports; confound modelling is a separate
    # axis (confound_benchmark) and would differ between the two split halves.
    X = np.column_stack([Xtask, np.ones(n_vol)])
    Y = data[cord_mask].T
    if Y.shape[0] != n_vol:
        return None
    if time_idx is not None:
        X = X[time_idx]
        Y = Y[time_idx]
    Y = Y - Y.mean(axis=0, keepdims=True)
    if np.linalg.matrix_rank(X) < X.shape[1]:
        return None
    beta, *_ = np.linalg.lstsq(X, Y, rcond=None)
    n_task = len(task_names)
    # subject-level effect = mean beta across task conditions, per voxel
    return beta[:n_task].mean(axis=0)


def _parcel_effects(effect_vec, midx, parcels) -> dict:
    """{tier: {parcel: parcel-mean effect}} for one run/half."""
    out = {}
    for tier, pmap in parcels.items():
        d = {}
        for pn, pm in pmap.items():
            flat = pm[tuple(midx.T)]
            if flat.any():
                d[pn] = float(effect_vec[flat].mean())
        if d:
            out[tier] = d
    return out


def run(out_dir: Path, limit: Optional[int] = None) -> dict:
    import nibabel as nib
    roots = _roots()
    # accumulate per (dataset, tier, parcel):
    #   half[subject] -> ([h1 vals], [h2 vals])   for split-half
    #   sess[subject][session] -> [full effect]   for test-retest
    half = defaultdict(lambda: defaultdict(lambda: ([], [])))
    sess = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    manifest = {"runs": 0, "fit": 0}

    for i, r in enumerate(driver.iter_runs(out_dir)):
        if limit is not None and i >= limit:
            break
        if not conditions_for(r["dataset"], r["run_id"]):
            continue                              # rest run, no task effect
        parcels, _ = driver.build_parcels(r)
        if "cord" not in parcels:
            continue
        ev, start = _events_and_start(r, roots)
        if ev is None:
            continue
        try:
            tr = repetition_time_s(r["bold"])
            data = np.asarray(nib.load(str(r["bold"])).dataobj, dtype=np.float32)
        except Exception:
            continue
        if data.ndim != 4:
            continue
        manifest["runs"] += 1
        cord = parcels["cord"]["cord"]
        midx = np.argwhere(cord)
        n_vol = data.shape[3]
        odd = np.arange(0, n_vol, 2)
        even = np.arange(1, n_vol, 2)
        eff_full = _fit_effect(data, cord, ev, start, r["dataset"], r["run_id"], tr)
        eff_h1 = _fit_effect(data, cord, ev, start, r["dataset"], r["run_id"], tr, odd)
        eff_h2 = _fit_effect(data, cord, ev, start, r["dataset"], r["run_id"], tr, even)
        if eff_full is None:
            continue
        manifest["fit"] += 1
        sub, ses = r["subject"], r["session"]
        if eff_h1 is not None and eff_h2 is not None:
            pe1 = _parcel_effects(eff_h1, midx, parcels)
            pe2 = _parcel_effects(eff_h2, midx, parcels)
            for tier in pe1:
                for pn in pe1[tier]:
                    if pn in pe2.get(tier, {}):
                        h = half[(r["dataset"], tier, pn)][sub]
                        h[0].append(pe1[tier][pn]); h[1].append(pe2[tier][pn])
        pef = _parcel_effects(eff_full, midx, parcels)
        for tier in pef:
            for pn, v in pef[tier].items():
                sess[(r["dataset"], tier, pn)][sub][ses].append(v)

    rows = []
    # ---- split-half reliability of the effect (all task datasets) ----
    # ICC(2,1) of the two half-run effects across subjects, then Spearman-Brown
    # to the full run length -> directly comparable to the test-retest ICC below
    # (same estimator, same construct; the halves are exchangeable so ICC(2,1)
    # is appropriate). Split-half shares session/state, so it is an OPTIMISTIC
    # upper bound on test-retest -- the gap is shown on ds004926 where both exist.
    for (ds, tier, pn), subs in half.items():
        mat = []
        for sub, (h1, h2) in subs.items():
            if h1 and h2:
                mat.append([float(np.mean(h1)), float(np.mean(h2))])
        if len(mat) >= 6:
            res = ES.icc(np.array(mat, float), form="2,1")
            if res["icc"] is not None:
                # Spearman-Brown up-corrects a half-length reliability to full
                # length, but it is only defined for a POSITIVE reliability:
                # 2r/(1+r) diverges as r -> -1 and returns values outside
                # [-1,1] for any r < 0. A negative ICC means "no reliable
                # signal", so keep it raw; SB-correct only the positive case.
                icc = res["icc"]
                sb = (2 * icc / (1 + icc)) if icc > 0 else icc
                sb = max(-1.0, min(1.0, sb))
                rows.append({"dataset": ds, "tier": tier, "parcel": pn,
                             "metric": "effect_splithalf_icc_sb",
                             "value": sb, "n": len(mat)})
    # ---- test-retest ICC of the effect (session datasets) ----
    for (ds, tier, pn), subs in sess.items():
        if driver.REPEAT_AXIS.get(ds) != "session":
            continue
        mat = []
        for sub, per in subs.items():
            if len(per) >= 2:
                mat.append([float(np.mean(per[s])) for s in sorted(per)][:2])
        if len(mat) >= 6:
            res = ES.icc(np.array(mat, float), form="2,1")
            if res["icc"] is not None:
                rows.append({"dataset": ds, "tier": tier, "parcel": pn,
                             "metric": "effect_icc_2_1", "value": res["icc"],
                             "n": res["n"]})

    RESULTS.mkdir(parents=True, exist_ok=True)
    outp = RESULTS / "effect_reliability.csv"
    if rows:
        keys = ["dataset", "tier", "parcel", "metric", "value", "n"]
        with open(outp, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=keys)
            w.writeheader(); w.writerows(rows)
    manifest["out_rows"] = len(rows)
    (RESULTS / "effect_reliability_manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest, indent=2))
    return manifest


if __name__ == "__main__":
    import sys
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/mnt/ssd1/spineprep_cohort_s2")
    lim = int(sys.argv[2]) if len(sys.argv) > 2 else None
    run(out, lim)
