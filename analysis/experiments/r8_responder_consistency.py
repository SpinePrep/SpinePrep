#!/usr/bin/env python3
"""R8 -- is a responder still a responder on the repeat?

The reliability results so far are all about CONTINUOUS quantities: effect ICC
~0.05, peak location ICC ~0. Clinically the question is usually coarser and binary
-- did this person's cord respond -- and a measure can be useless for ranking
people while still being usable for classifying them. That is a different question
from ICC and it has not been asked in the cord *(unchecked)*.

DESIGN
- Per run, two binary flags, deliberately different in how much they assume:
    horn_mean > 0     the a-priori horn's unselected mean response is positive.
                      No voxel selection, so nothing to be circular about.
    cv_top10 > 0      the cross-validated top-10% response is positive. Uses
                      selection, but the SIGN is safe: R2's null calibration
                      showed the estimator's MAGNITUDE tracks run noise while its
                      mean stays unbiased, so a sign test is unaffected.
- Agreement across each subject's repeats, as raw percent agreement and as Cohen's
  kappa. Kappa is the one that matters: with a base rate far from 50% two raters
  who agree by accident look impressive on percent agreement alone.
- Chance agreement is computed from the OBSERVED marginal responder rate, not
  assumed to be 50%.

WHAT WOULD BE INFORMATIVE EITHER WAY. Kappa near zero means the binary call is as
unreliable as the continuous measure, and the coarsening buys nothing. Kappa in the
moderate band would be genuinely useful: it would mean cord task fMRI can support a
yes/no statement about an individual even though it cannot support a magnitude, and
that is the form most clinical questions take.
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
        Yc = Y - Y.mean(axis=0, keepdims=True)
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

        bfull, b1, b2 = fit(np.arange(n_vol)), fit(odd), fit(even)
        if bfull is None or b1 is None or b2 is None:
            continue
        ht, fixed = HORN[ds]
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
                dataset=ds, subject=run["subject"],
                session=str(run.get("session") or "none"),
                run_id=run["run_id"], condition=cn,
                horn_mean=float(bfull[ci][fi].mean()),
                cv_top10=float(v2[np.argsort(v1)[-k:]].mean())))
        if (k_run + 1) % 40 == 0:
            print(f"  {k_run+1}/{len(runs)}", flush=True)

    df = pd.DataFrame(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT / "r8_responder.csv", index=False)
    report(df)


def kappa_from_pairs(pairs):
    """Cohen's kappa over (rater1, rater2) binary pairs, chance from the margins."""
    a = np.asarray(pairs, dtype=int)
    if len(a) < 5:
        return np.nan, np.nan, np.nan, len(a)
    po = float((a[:, 0] == a[:, 1]).mean())
    p1, p2 = a[:, 0].mean(), a[:, 1].mean()
    pe = p1 * p2 + (1 - p1) * (1 - p2)
    k = (po - pe) / (1 - pe) if (1 - pe) > 1e-9 else np.nan
    # exact binomial test of observed agreement against chance agreement
    p = sps.binomtest(int((a[:, 0] == a[:, 1]).sum()), len(a), pe,
                      alternative="greater").pvalue
    return po, pe, k, len(a), p


def report(df):
    print("\n" + "=" * 88)
    print("R8  IS A RESPONDER STILL A RESPONDER ON THE REPEAT?")
    print("=" * 88)
    if not len(df):
        print("no runs resolved")
        return
    lab = lambda d: d.split("_")[1][:12] if d.split("_")[0] == "openneuro" \
        else "_".join(d.split("_")[1:3])[:14]
    print(f"runs {df.run_id.nunique()}   subjects {df.subject.nunique()}")
    print("\nkappa bands (Landis & Koch): <0 none, 0-0.20 slight, 0.21-0.40 fair,")
    print("0.41-0.60 moderate, 0.61-0.80 substantial.\n")
    for flag in ("horn_mean", "cv_top10"):
        print(f"--- responder = {flag} > 0 ---")
        print(f"  {'dataset':16} {'condition':11} {'resp rate':>10} {'agree':>7} "
              f"{'chance':>7} {'kappa':>7} {'p':>8} {'pairs':>6}")
        allp = []
        for (ds, cn), g in df.groupby(["dataset", "condition"]):
            pairs = []
            for sub, gs in g.groupby("subject"):
                v = gs.groupby("run_id")[flag].mean()
                if len(v) < 2:
                    continue
                b = (v.to_numpy() > 0).astype(int)
                for i, j in combinations(range(len(b)), 2):
                    pairs.append((b[i], b[j]))
            if len(pairs) < 5:
                continue
            allp.extend(pairs)
            po, pe, k, n, p = kappa_from_pairs(pairs)
            rate = float((g[flag] > 0).mean())
            star = "  <--" if (np.isfinite(p) and p < 0.05) else ""
            print(f"  {lab(ds):16} {cn[:11]:11} {rate:10.2f} {po:7.2f} {pe:7.2f} "
                  f"{k:+7.3f} {p:8.4f} {n:6}{star}")
        if len(allp) >= 10:
            po, pe, k, n, p = kappa_from_pairs(allp)
            print(f"  {'POOLED':16} {'':11} {'':10} {po:7.2f} {pe:7.2f} "
                  f"{k:+7.3f} {p:8.4f} {n:6}")
        print()
    print("""  READING. A kappa near zero means coarsening the measure to yes/no buys
  nothing: the binary call is as unreliable as the magnitude, and a clinical
  statement about an individual is not supportable either way. A moderate kappa
  would be the one genuinely useful individual-level result available from this
  data, because it is the form most clinical questions actually take.

  Note the responder rate: where it sits far from 0.50, percent agreement looks
  high for free, which is exactly why kappa and the chance column are shown next
  to it rather than the agreement alone.""")
    print("\nDONE_MARKER")


if __name__ == "__main__":
    main()
