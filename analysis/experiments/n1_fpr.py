#!/usr/bin/env python3
"""N1 -- the empirical false-positive rate of cord fMRI inference.

A resting run contains no task. Fit a task GLM to it and every 'significant'
voxel is a false positive, with no modelling assumption needed to know that.
This is the Eklund 2016 design, in the cord.

126 resting runs reach S9 (ds004386 n=96, ds005075 n=30). Each run is fitted
with D synthetic task designs drawn from the paradigm space the cord literature
actually uses (blocks of 10-30 s, and event-related with jitter), at random
phase. That gives D independent nulls per run instead of one, so a per-run rate
is measurable rather than a single coin flip.

Three separate questions, kept separate because they have different answers:

1. FWE RATE at the thresholds the field publishes. Nominal 5% for the corrected
   ones. Measured as the fraction of (run, design) pairs with at least one
   surviving voxel or cluster.
2. IS THE PARAMETRIC NULL CORRECT? Compare the empirical t distribution under no
   task against the theoretical t_dof. An inflation factor here is the mechanism
   for any excess in (1), and it transfers to every published cord t-statistic.
3. ARE THE RESIDUALS WHITE? The standard model assumes the noise it did not
   model is exchangeable. Cord noise is cardiac pulsation aliased past the
   Nyquist limit of a ~2.3 s TR. Measured as residual lag-1 autocorrelation,
   before and after AR(1) prewhitening.

THE TRAP, stated up front. A resting run is not a pure null: it contains real
cardiac and respiratory structure, and a task regressor may legitimately
correlate with it. That is the finding, not an error, but the two readings must
be separated. Hence the physio arm -- where RETROICOR columns exist, the same
designs are refitted with them included. If the excess drops, physiological
structure is the driver; if it does not, the fault is in the inference itself.

Efficiency: for a single task column the fit is exact after projecting out the
nuisance space, so all D designs are evaluated in one matmul per run rather than
D regressions.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, "/mnt/ssd1/SpinePrep")

import numpy as np
import pandas as pd
from scipy import ndimage, stats as sps

from analysis import driver
from analysis.glm import lean_confounds, spm_hrf
from analysis.glm_spec import conditions_for, repetition_time_s

COHORT = Path("/mnt/ssd1/spineprep_cohort_s2")
OUT = Path("/mnt/ssd1/SpinePrep/analysis/results")
N_DESIGN = 200
SEED = 20260727

# Paradigms taken from the cord task literature: blocked motor/pain designs run
# 10-30 s on with matched rest; event-related pain uses brief stimuli with
# jittered inter-stimulus intervals.
BLOCK_ON = (10.0, 15.0, 20.0, 30.0)
EVENT_DUR = (2.0, 4.0)
EVENT_ISI = (8.0, 20.0)


def make_designs(n_vol: int, tr: float, n: int, rng) -> np.ndarray:
    """(n_vol, n) HRF-convolved synthetic task regressors, mean-centred."""
    dt = 0.1
    dur = n_vol * tr
    grid = np.arange(0, dur, dt)
    hk = spm_hrf(dt)
    out = np.empty((n_vol, n))
    tgt = np.arange(n_vol) * tr
    for j in range(n):
        stick = np.zeros_like(grid)
        if j % 2 == 0:                                    # blocked
            on = float(rng.choice(BLOCK_ON))
            phase = rng.uniform(0, 2 * on)
            t = phase
            while t < dur:
                stick[(grid >= t) & (grid < t + on)] = 1.0
                t += 2 * on
        else:                                             # event-related
            t = rng.uniform(0, 10)
            while t < dur:
                d = rng.uniform(*EVENT_DUR)
                stick[(grid >= t) & (grid < t + d)] = 1.0
                t += d + rng.uniform(*EVENT_ISI)
        conv = np.convolve(stick, hk)[: len(grid)]
        out[:, j] = np.interp(tgt, grid, conv)
    out -= out.mean(axis=0, keepdims=True)
    sd = out.std(axis=0)
    sd[sd < 1e-12] = 1.0
    return out / sd


def project_out(Xn: np.ndarray):
    """Orthonormal basis of the nuisance space, for exact residualisation."""
    q, _ = np.linalg.qr(Xn)
    return q


def fit_designs(Y: np.ndarray, D: np.ndarray, Q: np.ndarray):
    """t map for every design at once.

    Y (T,V) and D (T,nD) are residualised against the nuisance basis Q, then
    each design is a single-regressor fit. Returns (t (V,nD), dof, resid_ar1).
    """
    T = Y.shape[0]
    Yr = Y - Q @ (Q.T @ Y)
    Dr = D - Q @ (Q.T @ D)
    dn = (Dr * Dr).sum(axis=0)                       # (nD,)
    live = dn > 1e-9
    dn = np.where(live, dn, 1.0)
    b = (Dr.T @ Yr) / dn[:, None]                    # (nD,V)
    dof = T - Q.shape[1] - 1
    if dof <= 0:
        return None, None, None
    # residual SS without forming the (T,V,nD) product: for a single regressor
    # SS_resid = SS(Yr) - b^2 * SS(Dr)
    ssy = (Yr * Yr).sum(axis=0)                      # (V,)
    ssr = ssy[None, :] - (b ** 2) * dn[:, None]
    ssr = np.maximum(ssr, 1e-20)
    se = np.sqrt(ssr / dof / dn[:, None])
    t = (b / se).T                                   # (V,nD)
    # whiteness on the nuisance-only residual, which is design-independent
    R = Yr
    num = (R[1:] * R[:-1]).sum(axis=0)
    den = (R * R).sum(axis=0)
    ar1 = num / np.maximum(den, 1e-20)
    return t, dof, ar1


def ar1_prewhiten(Y: np.ndarray, Xn: np.ndarray, D: np.ndarray, rho: float):
    """Cochrane-Orcutt style AR(1) filter applied to data and both designs."""
    def f(A):
        return A[1:] - rho * A[:-1]
    return f(Y), f(Xn), f(D)


def cluster_survives(tvec, idx, shape, tcrit, kmin):
    """Does any 26-connected cluster of supra-threshold voxels reach kmin?"""
    vol = np.zeros(shape, dtype=bool)
    vol[tuple(idx.T)] = tvec > tcrit
    if not vol.any():
        return False
    lab, n = ndimage.label(vol, structure=np.ones((3, 3, 3)))
    if n == 0:
        return False
    return int(np.bincount(lab.ravel())[1:].max()) >= kmin


def main():
    rng_master = np.random.default_rng(SEED)
    rows = []
    tpool = []                       # subsample of t values, for question 2
    horn_rows = []                   # per (run, design) horn CV effect, for the group test

    runs = [r for r in driver.iter_runs(COHORT)
            if not conditions_for(r["dataset"], r["run_id"])]
    print(f"resting runs: {len(runs)}", flush=True)

    import nibabel as nib
    for k, run in enumerate(runs):
        parcels, _ = driver.build_parcels(run)
        if "cord" not in parcels:
            continue
        cord = parcels["cord"]["cord"]
        idx = np.argwhere(cord)
        try:
            data = np.asarray(nib.load(str(run["bold"])).dataobj, dtype=np.float32)
        except Exception:
            continue
        if data.ndim != 4:
            continue
        n_vol = data.shape[3]
        tr = repetition_time_s(run["bold"])
        Y = data[cord].T.astype(np.float64)
        if Y.shape[0] != n_vol:
            continue
        Y = Y - Y.mean(axis=0, keepdims=True)
        keep = Y.std(axis=0) > 1e-9
        if keep.sum() < 50:
            continue
        Y, idx = Y[:, keep], idx[keep]
        V = Y.shape[1]

        Xn, names = lean_confounds(Path(run["confounds"]), n_vol)
        Xn = np.column_stack([Xn, np.ones(n_vol)]) if Xn.size else np.ones((n_vol, 1))
        # physio arm, where the confounds table carries RETROICOR columns
        Xp = None
        try:
            df = pd.read_csv(run["confounds"], sep="\t").iloc[:n_vol]
            rc = [c for c in df.columns if c.lower().startswith("retroicor")]
            if rc:
                A = np.nan_to_num(df[rc].to_numpy(float))
                A = A[:, A.std(0) > 1e-9]
                if A.size:
                    Xp = np.column_stack([Xn, A])
        except Exception:
            pass

        rng = np.random.default_rng(SEED + k)
        D = make_designs(n_vol, tr, N_DESIGN, rng)

        for arm, Xnu in (("lean", Xn), ("physio", Xp)):
            if Xnu is None:
                continue
            if np.linalg.matrix_rank(Xnu) < Xnu.shape[1]:
                Xnu = Xnu[:, np.linalg.qr(Xnu)[1].diagonal().__abs__() > 1e-8]
            Q = project_out(Xnu)
            t, dof, ar1 = fit_designs(Y, D, Q)
            if t is None:
                continue

            # thresholds the cord literature publishes
            t001 = sps.t.isf(0.001, dof)
            t01 = sps.t.isf(0.01, dof)
            tbonf = sps.t.isf(0.05 / V, dof)
            p = sps.t.sf(t, dof)                                    # (V,nD) one-sided

            any001 = (t > t001).any(axis=0)
            anybonf = (t > tbonf).any(axis=0)
            # Benjamini-Hochberg per design
            ps = np.sort(p, axis=0)
            thr = 0.05 * np.arange(1, V + 1)[:, None] / V
            anyfdr = (ps <= thr).any(axis=0)
            clus = np.array([cluster_survives(t[:, j], idx, cord.shape, t01, 10)
                             for j in range(t.shape[1])])

            rows.append(dict(
                dataset=run["dataset"], subject=run["subject"], run_id=run["run_id"],
                arm=arm, n_vox=V, n_vol=n_vol, tr=tr, dof=dof, n_nuis=Q.shape[1],
                fp_p001=float(any001.mean()), fp_bonf=float(anybonf.mean()),
                fp_fdr=float(anyfdr.mean()), fp_cluster=float(clus.mean()),
                max_t=float(t.max()), t_sd=float(t.std()),
                t_q999=float(np.quantile(t, 0.999)), t_crit_001=float(t001),
                ar1_resid=float(np.median(ar1)),
            ))
            if arm == "lean":
                tpool.append(rng.choice(t.ravel(), size=min(20000, t.size),
                                        replace=False))
                # AR(1) prewhitened re-fit, same designs
                rho = float(np.median(ar1))
                if abs(rho) > 0.02:
                    Yw, Xw, Dw = ar1_prewhiten(Y, Xnu, D, rho)
                    Qw = project_out(Xw)
                    tw, dofw, ar1w = fit_designs(Yw, Dw, Qw)
                    if tw is not None:
                        tb = sps.t.isf(0.05 / V, dofw)
                        rows[-1].update(
                            rho=rho,
                            fp_bonf_white=float((tw > tb).any(axis=0).mean()),
                            ar1_resid_white=float(np.median(ar1w)),
                            t_sd_white=float(tw.std()))

                # group-level arm: the estimator our own analysis uses --
                # a-priori horn, top-10%, odd/even cross-validated
                horn = (parcels.get("gmhorn") or {}).get("gm-ventral-L")
                if horn is not None:
                    fi = horn[tuple(idx.T)]
                    if fi.sum() >= 10:
                        odd = np.arange(0, n_vol, 2)
                        even = np.arange(1, n_vol, 2)
                        vals = np.full(N_DESIGN, np.nan)
                        try:
                            Qo = project_out(Xnu[odd])
                            Qe = project_out(Xnu[even])
                            Yh = Y[:, fi]
                            bo = _betas(Yh[odd], D[odd], Qo)
                            be = _betas(Yh[even], D[even], Qe)
                            nk = max(1, int(0.1 * fi.sum()))
                            for j in range(N_DESIGN):
                                sel = np.argsort(bo[j])[-nk:]
                                vals[j] = be[j][sel].mean()
                        except Exception:
                            pass
                        horn_rows.append(dict(dataset=run["dataset"],
                                              subject=run["subject"],
                                              run_id=run["run_id"],
                                              **{f"d{j}": vals[j] for j in range(N_DESIGN)}))
        if (k + 1) % 10 == 0:
            print(f"  {k+1}/{len(runs)} runs", flush=True)

    OUT.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "n1_fpr_per_run.csv", index=False)
    hd = pd.DataFrame(horn_rows)
    hd.to_csv(OUT / "n1_fpr_group_horn.csv", index=False)
    np.save(OUT / "n1_tpool.npy", np.concatenate(tpool) if tpool else np.array([]))
    report(df, hd, np.concatenate(tpool) if tpool else np.array([]))


def _betas(Y, D, Q):
    """(nD, V) betas for every design, nuisance projected out."""
    Yr = Y - Q @ (Q.T @ Y)
    Dr = D - Q @ (Q.T @ D)
    dn = np.maximum((Dr * Dr).sum(axis=0), 1e-12)
    return (Dr.T @ Yr) / dn[:, None]


def report(df, hd, tpool):
    L = df[df.arm == "lean"]
    print("\n" + "=" * 74)
    print("N1  EMPIRICAL FALSE-POSITIVE RATE OF CORD fMRI INFERENCE")
    print("=" * 74)
    print(f"runs {len(L)}   designs/run {N_DESIGN}   "
          f"median cord voxels {L.n_vox.median():.0f}   median dof {L.dof.median():.0f}")

    print("\n--- Q1  fraction of null fits declaring at least one active voxel ---")
    print("  The unit of inference is the RUN, not the fit: the 200 designs within")
    print("  a run share its noise. Tests and intervals are therefore across runs.")
    print(f"  {'threshold':38} {'measured':>9} {'95% CI':>16} {'nominal':>8} {'vs 5%':>9}")
    for col, lab, nom in (
            ("fp_p001", "voxelwise p<0.001 UNCORRECTED", "see note"),
            ("fp_cluster", "p<0.01 + cluster >=10 voxels", "5%"),
            ("fp_fdr", "FDR q<0.05 (any voxel)", "5%"),
            ("fp_bonf", "Bonferroni FWE p<0.05", "5%")):
        v = L[col].to_numpy(float)
        m, se = v.mean(), v.std(ddof=1) / np.sqrt(len(v))
        ci = f"[{(m-1.96*se)*100:.1f}, {(m+1.96*se)*100:.1f}]"
        pv = sps.ttest_1samp(v, 0.05).pvalue if col != "fp_p001" else np.nan
        ps = "n/a" if np.isnan(pv) else (f"p={pv:.3f}" if pv >= 1e-3 else f"p={pv:.1e}")
        print(f"  {lab:38} {m*100:8.1f}% {ci:>16} {nom:>8} {ps:>9}")
    print("  note: uncorrected 0.001 has no nominal per-map rate; reported for")
    print("        comparison with the corrected rows only.")

    print("\n  per dataset (Bonferroni FWE, nominal 5%):")
    for ds, g in L.groupby("dataset"):
        print(f"    {ds[:44]:46} {g.fp_bonf.mean()*100:6.1f}%   n={len(g)}")

    print("\n--- Q2  is the parametric null correct? ---")
    if tpool.size:
        dof = float(L.dof.median())
        emp = np.quantile(tpool, [0.95, 0.99, 0.999])
        th = sps.t.isf([0.05, 0.01, 0.001], dof)
        print(f"  {'quantile':10} {'empirical t':>12} {'theoretical t':>14} {'inflation':>10}")
        for q, e, t_ in zip(("95%", "99%", "99.9%"), emp, th):
            print(f"  {q:10} {e:12.3f} {t_:14.3f} {e/t_:9.2f}x")
        print(f"  empirical SD of t = {tpool.std():.3f}  (theory "
              f"{np.sqrt(dof/(dof-2)):.3f})")
        print(f"  true tail mass at the nominal 0.001 threshold: "
              f"{float((tpool > sps.t.isf(0.001, dof)).mean()):.5f}")

    print("\n--- Q3  are the residuals white? ---")
    print(f"  residual lag-1 autocorrelation, median over voxels: "
          f"{L.ar1_resid.median():+.3f}  (white = 0)")
    if "ar1_resid_white" in L and L.ar1_resid_white.notna().any():
        w = L.dropna(subset=["ar1_resid_white"])
        print(f"  after AR(1) prewhitening:                          "
              f"{w.ar1_resid_white.median():+.3f}")
        print(f"  FWE rate before prewhitening {w.fp_bonf.mean()*100:.1f}%  ->  "
              f"after {w.fp_bonf_white.mean()*100:.1f}%")

    print("\n--- the trap: does modelled physiology explain it? ---")
    P = df[df.arm == "physio"]
    if len(P):
        m = L.set_index("run_id").fp_bonf
        both = P.assign(lean=P.run_id.map(m)).dropna(subset=["lean"])
        print(f"  runs with RETROICOR available: {len(both)}")
        print(f"  FWE lean {both.lean.mean()*100:.1f}%  ->  "
              f"with physio regressors {both.fp_bonf.mean()*100:.1f}%")
    else:
        print("  no resting run in the cohort carries RETROICOR columns;")
        print("  this reading cannot be separated on resting data alone.")

    print("\n--- Q4  GROUP level, our own estimator (a-priori horn, top-10%, CV) ---")
    if len(hd):
        dcols = [c for c in hd.columns if c.startswith("d") and c[1:].isdigit()]
        for ds, g in hd.groupby("dataset"):
            sub = g.groupby("subject")[dcols].mean()
            if len(sub) < 5:
                continue
            t, p = sps.ttest_1samp(sub.to_numpy(), 0.0, axis=0, nan_policy="omit")
            p = np.asarray(p, dtype=float)
            d = np.nanmean(sub.to_numpy(), 0) / np.nanstd(sub.to_numpy(), 0, ddof=1)
            print(f"    {ds[:44]:46} N={len(sub):3}  "
                  f"designs p<0.05: {np.nanmean(p < 0.05)*100:5.1f}%  "
                  f"(nominal 5%)   max|d| {np.nanmax(np.abs(d)):.2f}")

        print("\n--- Q5  THE NULL EFFECT-SIZE FLOOR (the most useful output) ---")
        print("  Group Cohen's d obtained from resting data with a random design,")
        print("  using the identical estimator our real analysis uses. Any published")
        print("  cord d below this band is not distinguishable from no signal.")
        alld = []
        for ds, g in hd.groupby("dataset"):
            sub = g.groupby("subject")[dcols].mean().to_numpy()
            if len(sub) < 5:
                continue
            dd = np.nanmean(sub, 0) / np.nanstd(sub, 0, ddof=1)
            alld.append(dd)
            q = np.nanpercentile(np.abs(dd), [50, 90, 95, 99])
            print(f"    {ds[:40]:42} N={len(sub):3}  |d| median {q[0]:.2f}  "
                  f"p90 {q[1]:.2f}  p95 {q[2]:.2f}  p99 {q[3]:.2f}")
        if alld:
            a = np.abs(np.concatenate(alld))
            f95 = float(np.nanpercentile(a, 95))
            print(f"    {'POOLED NULL FLOOR':42}        |d| median "
                  f"{np.nanmedian(a):.2f}  p90 {np.nanpercentile(a,90):.2f}  "
                  f"p95 {f95:.2f}  p99 {np.nanpercentile(a,99):.2f}")
            print(f"\n  Our own F2 top-10% effect sizes against this floor (p95 = {f95:.2f}):")
            for ds, dv in (("ds004616 handgrasp", 0.90), ("ds005884 motor", 0.41),
                           ("ds004926 pain", 0.11), ("ds005883 pain", 0.44)):
                print(f"    {ds:24} d={dv:+.2f}   "
                      f"{'ABOVE the null floor' if dv > f95 else 'INSIDE the null band'}")
            print("  Caveat: the floor is estimated on resting runs from two datasets,")
            print("  so it carries their N and noise, not each task dataset's.")
    print("\nDONE_MARKER")


if __name__ == "__main__":
    main()
