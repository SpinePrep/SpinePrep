#!/usr/bin/env python3
"""R1 -- an external criterion for the cord response, trial by trial.

Every effect analysis in this project tests a response against ZERO. F1 is the
strongest finding precisely because it has a physical referee, a measured field.
The effect side has never had one. This supplies it.

The question is not "is the response non-zero" but "does it TRACK something
measured outside the BOLD data, trial by trial, within a subject". A within-subject
correlation across trials is immune to both problems documented so far: it needs
no spatial summary choice (F2) and no localisation (N5).

CORRECTION TO THE PLAN. The Round 2 notes proposed delivered temperature as the
effect side's equivalent of a measured field. That is wrong for this cohort:
ds004926's `temperature` column is constant at 48.00 C across all 1600 trials, so
there is no delivered dose to respond to. The criteria that actually vary are:

  ds004616  GRIP FORCE, from the physio right_grip / left_grip channels at 100 Hz.
            A physical measurement, continuously varying, independent of the
            subject's report. The strongest referee available here.
  ds004926  `rating`, 50-96, SD 12.2 over 19 distinct values, 20 trials per run.
  ds005883  `PR` (pain intensity) and `UpR` (unpleasantness), 0-10 VAS, 15 trials
            per run. PR is range-restricted (mean 6.77, SD 1.30) which will
            attenuate its correlation; UpR varies more (SD 2.21).

Ratings are subject-generated, so they are a weaker referee than grip force:
arousal, attention, respiration and movement all covary with reported intensity.
That is exactly why the controls below are not optional.

DESIGN
- Single-trial betas by LSA: one regressor per event, all conditions modelled
  individually, plus the same lean nuisance set used everywhere else. Runs whose
  single-trial design is rank-deficient are skipped, not fitted unstably.
- Primary ROI summary is the a-priori horn MEAN, which involves NO voxel
  selection and therefore no circularity at all. A leave-one-trial-out top-10% is
  reported second: voxels ranked on every OTHER trial, read out on the held-out
  one.
- Coupling is Spearman across trials within a run, averaged over runs per subject
  as Fisher z, then tested across subjects.

THREE CONTROLS, because a positive result has three boring explanations.
1. CONTRALATERAL HORN and WHOLE CORD. If coupling is equally strong there, it is
   not a specific dorsal/ventral horn response.
2. MOTION AND DVARS AS COMPETING PREDICTORS. Trial-wise FD and DVARS are
   correlated against the same criterion. If motion tracks the criterion, motion
   can produce the BOLD coupling.
3. PARTIAL COUPLING. The criterion-BOLD correlation is recomputed after
   regressing trial-wise FD and DVARS out of both. Surviving that is the result;
   not surviving it means the coupling was motion.

A null is publishable and matters: it would say the cord response is not
resolvable trial by trial, which sits naturally beside the ICC ~0.05 reliability
and the peak ICC ~0 from N5.
"""
from __future__ import annotations

import csv
import gzip
import json
import sys
from pathlib import Path

sys.path.insert(0, "/mnt/ssd1/SpinePrep")

import numpy as np
import pandas as pd
import yaml
from scipy import stats as sps

from analysis import driver
from analysis.glm import lean_confounds, spm_hrf
from analysis.glm_spec import conditions_for, corrected_events, repetition_time_s

COHORT = Path("/mnt/ssd1/spineprep_cohort_s2")
OUT = Path("/mnt/ssd1/SpinePrep/analysis/results")

# dataset -> (horn tier, fixed side or None, target conditions, rating columns)
CFG = {
    "openneuro_ds004616_spinalcord_handgrasp_task": ("ventral", None, ("left", "right"), ()),
    "openneuro_ds004926_dorsalhorn_pain": ("dorsal", "L", ("heat",), ("rating",)),
    "openneuro_ds005883_cospine_pain": ("dorsal", "R", ("pain",), ("PR", "UpR")),
}
GRIP = {"L": "left_grip", "R": "right_grip"}


def side_of(c):
    c = c.lower().replace("-", "").replace("_", "")
    if "left" in c or c.endswith("l"):
        return "L"
    if "right" in c or c.endswith("r"):
        return "R"
    return None


def corrected_events_keep(dataset_key, rows, start_time_s, run_id):
    """glm_spec.corrected_events, but carrying each event's SOURCE row.

    The canonical function returns only onset/duration/trial_type, which drops
    the per-trial rating columns this analysis needs. Rather than re-deriving the
    corrections, this mirrors them and then ASSERTS that the timing it produces is
    identical to the canonical function's, so the two cannot drift apart
    unnoticed. If the assertion ever fails, the canonical version has changed and
    this must be updated rather than worked around.
    """
    from analysis.glm_spec import SPEC
    s = SPEC.get(dataset_key)
    if not s:
        return []
    keep = set(conditions_for(dataset_key, run_id))
    shift = float(s.get("onset_shift_s") or 0.0)
    dur_override = s.get("duration_override_s")
    out = []
    for r in rows:
        cond = (r.get("trial_type") or "").strip()
        if s.get("condition_from_filename"):
            cond = next(iter(keep), "task")
        elif cond not in keep:
            continue
        try:
            onset = float(r["onset"]) - float(start_time_s) + shift
            dur = float(dur_override if dur_override is not None
                        else (r.get("duration") or 0.0))
        except (TypeError, ValueError, KeyError):
            continue
        if onset + dur <= 0:
            continue
        out.append({"onset": round(onset, 4), "duration": round(dur, 4),
                    "trial_type": cond, "_raw": r})
    ref = corrected_events(dataset_key, rows, start_time_s, run_id)
    assert len(ref) == len(out), f"event count drift in {dataset_key}/{run_id}"
    for a, b in zip(ref, out):
        assert a["onset"] == b["onset"] and a["duration"] == b["duration"], \
            f"event timing drift in {dataset_key}/{run_id}"
    return out


def trial_designs(events, n_vol, tr):
    """(n_vol, n_trials) HRF-convolved single-trial regressors, in event order."""
    dt = 0.1
    grid = np.arange(0, n_vol * tr, dt)
    hk = spm_hrf(dt)
    tgt = np.arange(n_vol) * tr
    cols = []
    for e in events:
        o, d = float(e["onset"]), max(float(e["duration"]), dt)
        stick = np.zeros_like(grid)
        stick[(grid >= o) & (grid < o + d)] = 1.0
        conv = np.convolve(stick, hk)[: len(grid)]
        cols.append(np.interp(tgt, grid, conv))
    if not cols:
        return np.empty((n_vol, 0))
    return np.column_stack(cols)


def grip_per_trial(run_id, root, events, side_by_trial):
    """Mean force in each trial's window, from the hand matching that trial."""
    ph = next(iter(Path(root).rglob(f"{run_id}_physio.tsv.gz")), None)
    if ph is None:
        return None
    js = Path(str(ph).replace(".tsv.gz", ".json"))
    if not js.exists():
        return None
    try:
        meta = json.loads(js.read_text())
        cols = meta.get("Columns") or []
        fs = float(meta.get("SamplingFrequency") or 0)
        t0 = float(meta.get("StartTime") or 0.0)
        if fs <= 0 or not cols:
            return None
        a = np.loadtxt(gzip.open(ph))
    except Exception:
        return None
    if a.ndim != 2:
        return None
    out = []
    for e, sd in zip(events, side_by_trial):
        ch = GRIP.get(sd)
        if ch is None or ch not in cols:
            out.append(np.nan)
            continue
        v = a[:, cols.index(ch)]
        o, d = float(e["onset"]), float(e["duration"])
        i0 = int(round((o - t0) * fs))
        i1 = int(round((o + d - t0) * fs))
        i0, i1 = max(0, i0), min(len(v), max(i0 + 1, i1))
        out.append(float(np.abs(v[i0:i1]).mean()) if i1 > i0 else np.nan)
    return np.asarray(out, dtype=float)


def fisher(r):
    r = np.clip(r, -0.999999, 0.999999)
    return np.arctanh(r)


def main():
    cfg = yaml.safe_load(Path("config/datasets_local.yaml").read_text()) or {}
    rawcfg = cfg.get("datasets", cfg)

    def mkpath(v):
        p = Path(v.get("path") or v.get("bids_root")) if isinstance(v, dict) else Path(v)
        return p if p.is_absolute() else Path("/mnt/ssd1/SpinePrep") / p

    roots = {k: mkpath(v) for k, v in rawcfg.items()}
    import nibabel as nib

    rows, runrows = [], []
    runs = [r for r in driver.iter_runs(COHORT) if r["dataset"] in CFG]
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
        events = corrected_events_keep(ds, erows, stt, run["run_id"])
        if not events:
            continue
        Xtr = trial_designs(events, n_vol, tr)
        if Xtr.shape[1] < 5:
            continue
        Xn, _ = lean_confounds(Path(run["confounds"]), n_vol)
        X = np.column_stack([Xtr, Xn, np.ones(n_vol)]) if Xn.size \
            else np.column_stack([Xtr, np.ones(n_vol)])
        keep = X.std(axis=0) > 1e-9
        keep[:Xtr.shape[1]] = True
        keep[-1] = True
        X = X[:, keep]
        if n_vol <= X.shape[1] + 5 or np.linalg.matrix_rank(X) < X.shape[1]:
            continue                       # unstable single-trial design, skip
        cord = parcels["cord"]["cord"]
        midx = np.argwhere(cord)
        Y = data[cord].T.astype(np.float64)
        if Y.shape[0] != n_vol:
            continue
        Y = Y - Y.mean(axis=0, keepdims=True)
        B, *_ = np.linalg.lstsq(X, Y, rcond=None)
        B = B[: Xtr.shape[1]]                        # (n_trials, n_vox)

        # trial-wise motion, from the confounds table
        try:
            cdf = pd.read_csv(run["confounds"], sep="\t").iloc[:n_vol]
            fdv = np.nan_to_num(cdf["framewise_displacement"].to_numpy(float)) \
                if "framewise_displacement" in cdf else np.zeros(n_vol)
            dvv = np.nan_to_num(cdf["dvars"].to_numpy(float)) \
                if "dvars" in cdf else np.zeros(n_vol)
        except Exception:
            fdv = dvv = np.zeros(n_vol)
        fd_t, dv_t = [], []
        for e in events:
            a = int(np.floor(float(e["onset"]) / tr))
            b = int(np.ceil((float(e["onset"]) + float(e["duration"])) / tr))
            a, b = max(0, a), min(n_vol, max(a + 1, b))
            fd_t.append(float(fdv[a:b].mean()))
            dv_t.append(float(dvv[a:b].mean()))
        fd_t, dv_t = np.asarray(fd_t), np.asarray(dv_t)

        ht, fixed = CFG[ds][0], CFG[ds][1]
        targets = CFG[ds][2]
        rcols = CFG[ds][3]
        sides = [side_of(str(e["trial_type"])) or fixed for e in events]

        # criteria per trial, and run-level criteria kept separately.
        # ds004926's `rating` turned out to be CONSTANT across all 20 trials of a
        # run: it is a run-level report, not a trial-wise one (verified: within-run
        # SD is exactly 0 in all 76 runs, between-run SD 12.17 over 19 distinct
        # values). A trial-wise correlation is undefined there, so those runs would
        # have vanished silently -- which is why the run-level arm below exists
        # rather than the dataset simply being dropped.
        crit, crit_run = {}, {}
        for rc in rcols:
            vals = []
            for e in events:
                v = (e.get("_raw") or {}).get(rc)
                try:
                    vals.append(float(v))
                except Exception:
                    vals.append(np.nan)
            a = np.asarray(vals, float)
            if np.isfinite(a).sum() >= 6:
                if np.nanstd(a) > 0:
                    crit[rc] = a
                else:
                    crit_run[rc] = float(np.nanmean(a))
        if not rcols:
            g = grip_per_trial(run["run_id"], root, events, sides)
            if g is not None and np.isfinite(g).sum() >= 6 and np.nanstd(g) > 0:
                crit["grip_force"] = g
        # NOT `if not crit` -- ds004926 has only a RUN-level criterion, and
        # guarding on the trial-wise one alone silently dropped all 80 of its runs.
        if not crit and not crit_run:
            continue

        # ROI masks
        opp = {"L": "R", "R": "L"}
        rois = {}
        for e_side in set(s for s in sides if s):
            h = parcels["gmhorn"].get(f"gm-{ht}-{e_side}")
            hc = parcels["gmhorn"].get(f"gm-{ht}-{opp[e_side]}")
            if h is not None:
                rois[("ipsi_horn", e_side)] = h[tuple(midx.T)]
            if hc is not None:
                rois[("contra_horn", e_side)] = hc[tuple(midx.T)]
        rois[("whole_cord", None)] = np.ones(len(midx), bool)

        istarget = np.array([str(e["trial_type"]) in targets for e in events])

        # run-level amplitudes, for criteria that are constant within a run.
        # The horn MEAN is used, never a selected top-10%: R2 showed the split-half
        # selection estimator's magnitude grows as run noise rises, so comparing
        # selected magnitudes ACROSS runs is exactly the unsafe operation. The
        # unselected mean has no such dependence.
        if crit_run:
            base_all = data[cord].reshape(-1, n_vol).mean(axis=1)
            try:
                cdf2 = pd.read_csv(run["confounds"], sep="\t").iloc[:n_vol]
                fdm = float(np.nanmean(cdf2["framewise_displacement"])) \
                    if "framewise_displacement" in cdf2 else np.nan
            except Exception:
                fdm = np.nan
            sdv = data[cord].reshape(-1, n_vol).std(axis=1)
            tsnr_run = float(np.median(base_all[sdv > 0] / sdv[sdv > 0])) \
                if (sdv > 0).any() else np.nan
            for (roi, rside), fi in rois.items():
                if fi.sum() < 8:
                    continue
                sel = istarget.copy()
                if rside is not None:
                    sel &= np.array([s2 == rside for s2 in sides])
                if sel.sum() < 4:
                    continue
                bb = np.maximum(base_all[fi].mean(), 1e-6)
                amp = 100.0 * float(B[np.ix_(np.where(sel)[0], np.where(fi)[0])]
                                    .mean()) / bb
                for cname, cval in crit_run.items():
                    runrows.append(dict(
                        dataset=ds, subject=run["subject"],
                        session=str(run.get("session") or "none"),
                        run_id=run["run_id"], criterion=cname, roi=roi,
                        side=rside or "-", crit=cval, amp=amp,
                        tsnr=tsnr_run, fd=fdm, n_trials=int(sel.sum())))
        for cname, cvals in crit.items():
            for (roi, rside), fi in rois.items():
                if fi.sum() < 8:
                    continue
                sel = istarget.copy()
                if rside is not None:
                    sel &= np.array([s == rside for s in sides])
                if sel.sum() < 6:
                    continue
                bmean = B[:, fi].mean(axis=1)
                # leave-one-trial-out top-10%: rank on the other trials only
                btop = np.full(len(bmean), np.nan)
                idxs = np.where(sel)[0]
                k = max(1, int(0.1 * fi.sum()))
                for i in idxs:
                    other = idxs[idxs != i]
                    if len(other) < 3:
                        continue
                    rank = B[np.ix_(other, np.where(fi)[0])].mean(axis=0)
                    btop[i] = B[i, np.where(fi)[0][np.argsort(rank)[-k:]]].mean()
                c = cvals[sel]
                ok = np.isfinite(c)
                if ok.sum() < 6:
                    continue

                def sp(x):
                    xx = x[sel][ok]
                    m = np.isfinite(xx)
                    if m.sum() < 6 or np.std(xx[m]) == 0:
                        return np.nan
                    return sps.spearmanr(xx[m], c[ok][m]).statistic

                # partial: strip trial-wise FD and DVARS from BOTH sides
                def partial(x):
                    xx, cc = x[sel][ok], c[ok]
                    Z = np.column_stack([fd_t[sel][ok], dv_t[sel][ok],
                                         np.ones(ok.sum())])
                    m = np.isfinite(xx) & np.isfinite(cc) & np.isfinite(Z).all(1)
                    if m.sum() < 8:
                        return np.nan
                    q, _ = np.linalg.qr(Z[m])
                    rx = xx[m] - q @ (q.T @ xx[m])
                    rc_ = cc[m] - q @ (q.T @ cc[m])
                    if np.std(rx) == 0 or np.std(rc_) == 0:
                        return np.nan
                    return sps.spearmanr(rx, rc_).statistic

                rows.append(dict(
                    dataset=ds, subject=run["subject"], run_id=run["run_id"],
                    criterion=cname, roi=roi, side=rside or "-",
                    n_trials=int(ok.sum()), n_vox=int(fi.sum()),
                    rho_mean=sp(bmean), rho_top10=sp(btop),
                    rho_mean_partial=partial(bmean),
                    rho_fd=sps.spearmanr(fd_t[sel][ok], c[ok]).statistic
                    if np.std(fd_t[sel][ok]) > 0 else np.nan,
                    rho_dvars=sps.spearmanr(dv_t[sel][ok], c[ok]).statistic
                    if np.std(dv_t[sel][ok]) > 0 else np.nan,
                ))
        if (k_run + 1) % 20 == 0:
            print(f"  {k_run+1}/{len(runs)}", flush=True)

    OUT.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "r1_dose_response.csv", index=False)
    rdf = pd.DataFrame(runrows)
    rdf.to_csv(OUT / "r1_dose_response_runlevel.csv", index=False)
    report(df)
    report_runlevel(rdf)


def grp(g, col):
    """Subject-level Fisher-z mean, then a one-sample test against zero."""
    s = g.groupby("subject")[col].apply(lambda v: np.nanmean(fisher(v.to_numpy(float))))
    s = s[np.isfinite(s)]
    if len(s) < 5 or s.std(ddof=1) == 0:
        return np.nan, np.nan, len(s)
    t, p = sps.ttest_1samp(s, 0.0)
    return float(np.tanh(s.mean())), float(p), len(s)


def report(df):
    print("\n" + "=" * 88)
    print("R1  DOES THE CORD RESPONSE TRACK AN EXTERNAL CRITERION, TRIAL BY TRIAL?")
    print("=" * 88)
    if not len(df):
        print("no runs resolved")
        return
    print(f"runs {df.run_id.nunique()}   subjects {df.subject.nunique()}   "
          f"criteria {sorted(df.criterion.unique())}")
    print("\nrho is the group mean Spearman (Fisher-z averaged within subject,")
    print("then across subjects). p tests the subject means against zero.\n")
    for (ds, cname), g in df.groupby(["dataset", "criterion"]):
        print(f"  {ds.split('_')[1]} / {cname}   "
              f"median {g.n_trials.median():.0f} trials per run")
        print(f"    {'ROI':13} {'side':5} {'vox':>5} {'rho(mean)':>10} {'p':>9} "
              f"{'rho(top10)':>11} {'rho partial':>12} {'N':>4}")
        for (roi, side), gg in g.groupby(["roi", "side"]):
            r1, p1, n = grp(gg, "rho_mean")
            r2, _, _ = grp(gg, "rho_top10")
            r3, p3, _ = grp(gg, "rho_mean_partial")
            star = " <--" if (np.isfinite(p1) and p1 < 0.05) else ""
            print(f"    {roi:13} {side:5} {gg.n_vox.median():5.0f} {r1:+10.3f} "
                  f"{p1:9.4f} {r2:+11.3f} {r3:+12.3f} {n:4}{star}")
        rf, pf, _ = grp(g, "rho_fd")
        rd, pd_, _ = grp(g, "rho_dvars")
        print(f"    COMPETING PREDICTORS: criterion vs trial-wise FD "
              f"rho {rf:+.3f} (p={pf:.3f});  vs DVARS rho {rd:+.3f} (p={pd_:.3f})")
        print()
    print("  HOW TO READ THIS")
    print("  - ipsi_horn coupling that survives the partial, while contra_horn and")
    print("    whole_cord do not, is a specific and real cord response.")
    print("  - coupling of similar size in every ROI is a global or motion effect.")
    print("  - if the criterion itself correlates with FD or DVARS, motion is a")
    print("    live alternative and only the partial column can be trusted.")
    print("  - grip force is the strongest referee: it is a physical measurement,")
    print("    not a subject report.")
    print("\nDONE_MARKER")


def report_runlevel(rdf):
    print("\n" + "=" * 88)
    print("R1b  RUN-LEVEL CRITERION (ds004926 rating is constant within a run)")
    print("=" * 88)
    if not len(rdf):
        print("no run-level criterion resolved")
        print("\nDONE_MARKER_RUNLEVEL")
        return
    for (ds, cname), g in rdf.groupby(["dataset", "criterion"]):
        print(f"\n  {ds.split('_')[1]} / {cname}   {g.run_id.nunique()} runs, "
              f"{g.subject.nunique()} subjects")
        print(f"    {'ROI':13} {'side':5} {'rho':>7} {'p':>8} "
              f"{'rho|tSNR,FD':>12} {'p':>8} {'n runs':>7}")
        for (roi, side), gg in g.groupby(["roi", "side"]):
            d = gg.dropna(subset=["crit", "amp"])
            if len(d) < 8 or d.crit.nunique() < 4:
                continue
            r, p = sps.spearmanr(d.crit, d.amp)
            # partial out tSNR and mean FD, both of which move amplitude
            dd = d.dropna(subset=["tsnr", "fd"])
            rp = pp = np.nan
            if len(dd) >= 12:
                Z = np.column_stack([sps.rankdata(dd.tsnr), sps.rankdata(dd.fd),
                                     np.ones(len(dd))])
                q, _ = np.linalg.qr(Z)
                ra = sps.rankdata(dd.amp) - q @ (q.T @ sps.rankdata(dd.amp))
                rc = sps.rankdata(dd.crit) - q @ (q.T @ sps.rankdata(dd.crit))
                if np.std(ra) > 0 and np.std(rc) > 0:
                    rp, pp = sps.pearsonr(ra, rc)
            star = "  <--" if (np.isfinite(pp) and pp < 0.05) else ""
            print(f"    {roi:13} {side:5} {r:+7.3f} {p:8.4f} {rp:+12.3f} "
                  f"{pp:8.4f} {len(d):7}{star}")

        # within-subject paired design: two sessions per subject removes every
        # between-subject confound, at the cost of needing the rating to change
        print("    WITHIN-SUBJECT paired change across sessions "
              "(removes all between-subject confounds):")
        for (roi, side), gg in g.groupby(["roi", "side"]):
            dl = []
            for sub, gs in gg.groupby("subject"):
                m = gs.groupby("session")[["crit", "amp"]].mean()
                if len(m) == 2 and m.crit.nunique() == 2:
                    a, b = m.iloc[0], m.iloc[1]
                    dl.append((b.crit - a.crit, b.amp - a.amp))
            if len(dl) < 6:
                print(f"      {roi:13} {side:5} only {len(dl)} subjects with a "
                      f"rating CHANGE between sessions -- not testable")
                continue
            A = np.array(dl)
            r, p = sps.spearmanr(A[:, 0], A[:, 1])
            print(f"      {roi:13} {side:5} rho(d_rating, d_response) {r:+.3f} "
                  f"p={p:.4f}  n={len(dl)} subjects")
    print("""
  READING. The run-level arm is weaker than a trial-wise one by construction: it
  compares different runs, so anything that differs between runs can carry the
  correlation. That is why tSNR and mean FD are partialled out, and why the
  within-subject paired change is reported -- it is the only version in which no
  between-subject variable can contribute.""")
    print("\nDONE_MARKER_RUNLEVEL")


if __name__ == "__main__":
    main()
