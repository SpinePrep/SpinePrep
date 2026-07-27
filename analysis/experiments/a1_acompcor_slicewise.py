#!/usr/bin/env python3
"""A1 -- the retracted aCompCor analysis, done correctly.

WHAT WAS WRONG. The original analysis applied SpinePrep's slice-wise CSF design
FLAT: all 125-155 `csf_sliceNN_pcMM` columns were handed to every voxel in the cord,
when S8's own specification says the design is built for a SLICEWISE GLM. A voxel in
slice 12 was regressed against the CSF components of slices 3 through 32. Both the
task and connectivity arms were retracted for that reason.

Verified before rebuilding: the CSF slice indices (4-32) line up with the cord's z
extent in the bold grid (5-32), so `csf_slice{z}_pc*` maps directly onto bold slice z
and the correct application is unambiguous.

WHY IT IS WORTH REDOING. It holds the one genuinely novel inference still available.
Kaptan 2023 read reduced connectivity after CSF regression as evidence of INCREASED
validity; Hemmerling 2026 could not rule out real signal loss. Neither could separate
the two, because each had only one endpoint. A paired design with BOTH endpoints on
the same runs can:

  task detection UP + connectivity DOWN  -> the denoising removed noise. Kaptan right.
  task detection DOWN + connectivity DOWN -> it removed signal. Hemmerling's worry real.
  both unchanged                          -> the family is inert, like the others.

R7 adds a second motive: this one family is 78% of the confound budget and 105
recoverable degrees of freedom, so whether it earns its cost is now a quantified
question rather than a stylistic one.

THREE ARMS, identical in everything else:
  none           task + motion + cosine + spikes
  csf_flat       + ALL CSF columns to every voxel  (reproduces the retracted error,
                 kept so the size of that error is visible rather than asserted)
  csf_slicewise  + only the voxel's OWN slice components  (correct)

Endpoints, both on the same runs so the comparison is method-vs-method, the only
form the R2 null-calibration showed to be safe for this estimator:
  TASK          group Cohen's d, odd/even cross-validated top-10% in the a-priori horn
  CONNECTIVITY  ventral-left to ventral-right correlation, the Kaptan V-V measure
  COST          residual degrees of freedom actually spent per voxel
"""
from __future__ import annotations

import csv
import json
import re
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
ARMS = ["none", "csf_flat", "csf_slicewise"]

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


def csf_by_slice(cdf, n_vol):
    """{slice index: (T, k) matrix of that slice's CSF components}."""
    out = {}
    for c in cdf.columns:
        m = re.match(r"csf_slice(\d+)_pc\d+", c)
        if m:
            out.setdefault(int(m.group(1)), []).append(c)
    res = {}
    for z, cols in out.items():
        A = np.nan_to_num(cdf[sorted(cols)].to_numpy(float))[:n_vol]
        A = A[:, A.std(axis=0) > 1e-9]
        if A.size:
            res[z] = A
    return res


def fit_block(X, Y, ix, n_task):
    """Least squares on a timepoint subset, pruning columns degenerate on it."""
    Xi = X[ix]
    keep = Xi.std(axis=0) > 1e-9
    keep[:n_task] = True
    keep[-1] = True
    Xi = Xi[:, keep]
    if len(ix) <= Xi.shape[1] + 2 or np.linalg.matrix_rank(Xi) < Xi.shape[1]:
        return None, 0
    Yi = Y[ix] - Y[ix].mean(axis=0, keepdims=True)
    b, *_ = np.linalg.lstsq(Xi, Yi, rcond=None)
    return b, len(ix) - Xi.shape[1]


def main():
    cfg = yaml.safe_load(Path("config/datasets_local.yaml").read_text()) or {}
    rawcfg = cfg.get("datasets", cfg)

    def mkpath(v):
        p = Path(v.get("path") or v.get("bids_root")) if isinstance(v, dict) else Path(v)
        return p if p.is_absolute() else Path("/mnt/ssd1/SpinePrep") / p

    roots = {k: mkpath(v) for k, v in rawcfg.items()}
    import nibabel as nib

    rows, conn = [], []
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
            cdf = pd.read_csv(run["confounds"], sep="\t")
        except Exception:
            continue
        if data.ndim != 4:
            continue
        n_vol = data.shape[3]
        cdf = cdf.iloc[:n_vol]
        tr = repetition_time_s(run["bold"])
        Xt, names = build_task_design(
            corrected_events(ds, erows, stt, run["run_id"]), n_vol, tr, conds)
        if Xt.shape[1] == 0:
            continue
        Xlean, _ = lean_confounds(Path(run["confounds"]), n_vol)
        csf = csf_by_slice(cdf, n_vol)
        csf_all = np.column_stack(list(csf.values())) if csf else np.empty((n_vol, 0))
        cord = parcels["cord"]["cord"]
        midx = np.argwhere(cord)
        Y = data[cord].T.astype(np.float64)
        if Y.shape[0] != n_vol:
            continue
        Y = Y - Y.mean(axis=0, keepdims=True)
        zidx = midx[:, 2]
        odd, even = np.arange(0, n_vol, 2), np.arange(1, n_vol, 2)
        nT = Xt.shape[1]
        ht, fixed = HORN[ds]

        for arm in ARMS:
            B = {"odd": np.full((nT, Y.shape[1]), np.nan),
                 "even": np.full((nT, Y.shape[1]), np.nan)}
            resid = np.zeros_like(Y)
            dofs = []
            if arm == "csf_slicewise":
                groups = [(z, zidx == z) for z in np.unique(zidx)]
            else:
                groups = [(None, np.ones(len(zidx), bool))]
            for z, sel in groups:
                if not sel.any():
                    continue
                extra = (csf.get(int(z), np.empty((n_vol, 0)))
                         if arm == "csf_slicewise"
                         else (csf_all if arm == "csf_flat" else np.empty((n_vol, 0))))
                blocks = [Xt] + ([Xlean] if Xlean.size else []) \
                    + ([extra] if extra.size else []) + [np.ones((n_vol, 1))]
                X = np.column_stack(blocks)
                for lab, ix in (("odd", odd), ("even", even)):
                    b, dof = fit_block(X, Y[:, sel], ix, nT)
                    if b is not None:
                        B[lab][:, sel] = b[:nT]
                bfull, dof = fit_block(X, Y[:, sel], np.arange(n_vol), nT)
                if bfull is not None:
                    dofs.append(dof)
                    # residual timeseries with the task KEPT, for connectivity:
                    # remove only the nuisance part
                    Xi = X
                    kn = Xi.std(axis=0) > 1e-9
                    kn[:nT] = True
                    kn[-1] = True
                    Xi = Xi[:, kn]
                    Xn_only = np.column_stack([Xi[:, nT:]])
                    q, _ = np.linalg.qr(Xn_only)
                    resid[:, sel] = Y[:, sel] - q @ (q.T @ Y[:, sel])
            if not dofs:
                continue
            # TASK endpoint
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
                v1, v2 = B["odd"][ci][fi], B["even"][ci][fi]
                ok = np.isfinite(v1) & np.isfinite(v2)
                if ok.sum() < 8:
                    continue
                v1, v2 = v1[ok], v2[ok]
                kk = max(1, int(0.1 * len(v1)))
                rows.append(dict(
                    dataset=ds, subject=run["subject"], run_id=run["run_id"],
                    condition=cn, arm=arm, dof=float(np.median(dofs)),
                    n_csf_used=(0 if arm == "none" else
                                (csf_all.shape[1] if arm == "csf_flat"
                                 else float(np.median([csf.get(int(z), np.empty((n_vol, 0))).shape[1]
                                                       for z in np.unique(zidx)])))),
                    cv_top10=float(v2[np.argsort(v1)[-kk:]].mean())))
            # CONNECTIVITY endpoint: ventral L to ventral R
            vl = (parcels.get("gmhorn") or {}).get("gm-ventral-L")
            vr = (parcels.get("gmhorn") or {}).get("gm-ventral-R")
            if vl is not None and vr is not None:
                fl, fr = vl[tuple(midx.T)], vr[tuple(midx.T)]
                if fl.sum() >= 5 and fr.sum() >= 5:
                    a, b_ = resid[:, fl].mean(axis=1), resid[:, fr].mean(axis=1)
                    if np.std(a) > 1e-9 and np.std(b_) > 1e-9:
                        conn.append(dict(
                            dataset=ds, subject=run["subject"],
                            session=str(run.get("session") or "none"),
                            run_id=run["run_id"], arm=arm,
                            vv=float(np.corrcoef(a, b_)[0, 1])))
        if (k_run + 1) % 20 == 0:
            print(f"  {k_run+1}/{len(runs)}", flush=True)

    T = pd.DataFrame(rows)
    C = pd.DataFrame(conn)
    OUT.mkdir(parents=True, exist_ok=True)
    T.to_csv(OUT / "a1_acompcor_task.csv", index=False)
    C.to_csv(OUT / "a1_acompcor_conn.csv", index=False)
    report(T, C)


def gd(g, col):
    s = g.groupby("subject")[col].mean().to_numpy(float)
    s = s[np.isfinite(s)]
    if len(s) < 5 or s.std(ddof=1) == 0:
        return np.nan, np.nan, len(s)
    return s.mean() / s.std(ddof=1), sps.ttest_1samp(s, 0).pvalue, len(s)


def report(T, C):
    short = lambda d: d.split("_")[1] if d.split("_")[0] == "openneuro" else d.split("_")[2]
    print("\n" + "=" * 88)
    print("A1  aCompCor DONE CORRECTLY -- slice-wise, against flat and against none")
    print("=" * 88)
    if not len(T):
        print("no runs resolved")
        return
    print(f"runs {T.run_id.nunique()}   datasets {T.dataset.nunique()}")
    print("\n--- COST: what each arm actually spends ---")
    print(f"  {'arm':16} {'CSF cols per voxel':>19} {'residual dof':>13}")
    for arm in ARMS:
        g = T[T.arm == arm]
        if not len(g):
            continue
        print(f"  {arm:16} {g.n_csf_used.median():19.0f} {g.dof.median():13.0f}")

    print("\n--- TASK endpoint: group Cohen's d (odd/even CV top-10%) ---")
    dss = sorted(T.dataset.unique())
    print(f"  {'arm':16} " + " ".join(f"{short(d)[:9]:>10}" for d in dss) + f" {'median':>8}")
    med = {}
    for arm in ARMS:
        cells, vals = [], []
        for d in dss:
            g = T[(T.dataset == d) & (T.arm == arm)]
            dv, p, n = gd(g, "cv_top10") if len(g) else (np.nan, np.nan, 0)
            cells.append(f"{dv:+.2f}" if np.isfinite(dv) else "-")
            if np.isfinite(dv):
                vals.append(dv)
        med[arm] = np.median(vals) if vals else np.nan
        print(f"  {arm:16} " + " ".join(c.rjust(10) for c in cells)
              + f" {med[arm]:+8.3f}")
    piv = T.pivot_table(index=["dataset", "subject", "condition"],
                        columns="arm", values="cv_top10")
    print("\n  paired subject-level tests:")
    for a, b in (("csf_slicewise", "none"), ("csf_flat", "none"),
                 ("csf_slicewise", "csf_flat")):
        if a in piv and b in piv:
            j = piv[[a, b]].dropna()
            if len(j) >= 10:
                st = sps.wilcoxon(j[a], j[b])
                print(f"    {a:14} vs {b:14} median delta "
                      f"{float((j[a]-j[b]).median()):+.4f}  p={st.pvalue:.4f}  n={len(j)}")

    print("\n--- CONNECTIVITY endpoint: ventral-left to ventral-right (Kaptan V-V) ---")
    if len(C):
        print(f"  {'arm':16} " + " ".join(f"{short(d)[:9]:>10}" for d in
                                          sorted(C.dataset.unique())) + f" {'all':>8}")
        for arm in ARMS:
            cells = []
            for d in sorted(C.dataset.unique()):
                g = C[(C.dataset == d) & (C.arm == arm)]
                cells.append(f"{g.vv.median():+.3f}" if len(g) >= 5 else "-")
            g = C[C.arm == arm]
            print(f"  {arm:16} " + " ".join(c.rjust(10) for c in cells)
                  + f" {g.vv.median():+8.3f}")
        cp = C.pivot_table(index=["dataset", "subject", "run_id"],
                           columns="arm", values="vv")
        print("\n  paired tests:")
        for a, b in (("csf_slicewise", "none"), ("csf_flat", "none"),
                     ("csf_slicewise", "csf_flat")):
            if a in cp and b in cp:
                j = cp[[a, b]].dropna()
                if len(j) >= 10:
                    st = sps.wilcoxon(j[a], j[b])
                    print(f"    {a:14} vs {b:14} median delta "
                          f"{float((j[a]-j[b]).median()):+.4f}  p={st.pvalue:.2e}  "
                          f"n={len(j)}")

    print("\n--- THE DISSOCIATION, which is the whole point ---")
    dt = med.get("csf_slicewise", np.nan) - med.get("none", np.nan)
    dc = np.nan
    if len(C):
        cp = C.pivot_table(index=["dataset", "subject", "run_id"],
                           columns="arm", values="vv")
        if "csf_slicewise" in cp and "none" in cp:
            j = cp[["csf_slicewise", "none"]].dropna()
            dc = float((j.csf_slicewise - j.none).median())
    print(f"  slice-wise CSF changes TASK detection by      {dt:+.3f} in group d")
    print(f"  slice-wise CSF changes V-V CONNECTIVITY by    {dc:+.3f}")
    if np.isfinite(dt) and np.isfinite(dc):
        if dt > 0 and dc < 0:
            v = ("noise removal. Kaptan 2023's reading is supported: the drop in "
                 "connectivity is the confound leaving, not signal.")
        elif dt < 0 and dc < 0:
            v = ("signal loss. Hemmerling 2026's concern is supported: the "
                 "denoising takes real response with it.")
        elif abs(dt) < 0.05 and abs(dc) < 0.02:
            v = ("inert, like every other confound family tested here. It costs "
                 "degrees of freedom and buys nothing.")
        else:
            v = "mixed; neither published reading is supported cleanly."
        print(f"  -> {v}")
    print("""
  The csf_flat row exists to size the retracted error rather than assert it: it is
  the same 125-155 columns applied to every voxel, which is what the original
  analysis did. Any difference between csf_flat and csf_slicewise is the magnitude
  of that mistake.""")
    print("\nDONE_MARKER")


if __name__ == "__main__":
    main()
