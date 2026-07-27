#!/usr/bin/env python3
"""A4 + A8 + A6 -- three supporting analyses, each closing a specific loose end.

A4  THE GLOBAL SIGNAL ON RAW DATA, AND IN BOTH ORGANS.
    R5 measured the whole-cord global signal on preproc-v1 and found 1-2% of
    variance, which cannot produce the paired-organ anomaly (ds005884's cord mean
    reaching d = +0.72 over 657 of ~848 voxels). But the two do not share an input:
    the anomaly appeared in RAW EPI with cosine drift only. This measures the global
    signal where the anomaly lives, and because the CoSpine acquisitions carry brain
    and cord in one volume it also gives the first cord-versus-brain global signal
    comparison in the same shot.

A8  RESIDUAL NON-RIGID MOTION AFTER SLICEWISE RIGID CORRECTION.
    The cord stretches and compresses with breathing and swallowing; the brain does
    not. S4 corrects 2D slicewise rigid motion, which by construction cannot remove
    deformation ALONG the cord. Measured directly: per timepoint, the intensity
    weighted cord centroid of every axial slice. Subtracting each timepoint's mean
    over slices removes the rigid translation that S4 does model; what remains is
    centreline DEFORMATION, which nothing in the pipeline models. A cord-specific
    failure mode with no brain analogue, and a candidate mechanism for the S2
    heterogeneity (tSNR gain ranged +0% to +121% with no consistent transfer).

A6  VARIANCE DECOMPOSITION OF THE QC METRICS.
    Tests the project's own invariant that heterogeneity is signal rather than noise.
    Splits each metric's variance into dataset, subject and run components. If dataset
    dominates subject, multi-site cord fMRI needs harmonisation before pooling, which
    would be the first such statement in the field. R2 already showed these metrics do
    not predict scientific outcome, so this asks a different question: what do they
    measure?
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
from analysis.glm import build_task_design
from analysis.glm_spec import conditions_for, corrected_events, repetition_time_s

COHORT = Path("/mnt/ssd1/spineprep_cohort_s2")
S3 = COHORT / "runs" / "S3_func_init_and_crop"
OUT = Path("/mnt/ssd1/SpinePrep/analysis/results")
PAIRED = ["openneuro_ds005884_cospine_motor", "openneuro_ds005883_cospine_pain",
          "openneuro_ds005075_brain_spine_rest"]


def cosine_basis(n_vol, tr, cutoff_s=100.0):
    k = int(np.floor(2 * n_vol * tr / cutoff_s))
    if k < 1:
        return np.empty((n_vol, 0))
    t = (np.arange(n_vol) + 0.5) / n_vol
    return np.column_stack([np.cos(np.pi * (j + 1) * t) for j in range(k)])


def brain_mask(mean3d, cord, margin=6):
    from scipy import ndimage
    zc = np.where(cord.sum(axis=(0, 1)) > 0)[0]
    z0 = (zc.max() + margin) if len(zc) else mean3d.shape[2] // 2
    if z0 >= mean3d.shape[2] - 4:
        return None
    m = np.zeros_like(cord, dtype=bool)
    sub = mean3d[:, :, z0:]
    m[:, :, z0:] = sub > 0.5 * np.percentile(sub, 99)
    if m.sum() < 200:
        return None
    lab, n = ndimage.label(m, structure=np.ones((3, 3, 3)))
    if n == 0:
        return None
    big = 1 + int(np.argmax(np.bincount(lab.ravel())[1:]))
    m = ndimage.binary_erosion(lab == big, structure=np.ones((3, 3, 3)))
    return m if m.sum() >= 200 else None


# ---------------------------------------------------------------- A4
def a4():
    import nibabel as nib
    cfg = yaml.safe_load(Path("config/datasets_local.yaml").read_text()) or {}
    rawcfg = cfg.get("datasets", cfg)

    def mkpath(v):
        p = Path(v.get("path") or v.get("bids_root")) if isinstance(v, dict) else Path(v)
        return p if p.is_absolute() else Path("/mnt/ssd1/SpinePrep") / p

    roots = {k: mkpath(v) for k, v in rawcfg.items()}
    rows = []
    runs = [r for r in driver.iter_runs(COHORT) if r["dataset"] in PAIRED]
    print(f"A4: paired brain+cord runs {len(runs)}", flush=True)
    for k, run in enumerate(runs):
        seg = S3 / run["run_id"] / "init" / "localize" / "func_ref_fast_seg.nii.gz"
        if not seg.exists():
            continue
        root = roots.get(run["dataset"])
        raw = next(iter(Path(root).rglob(f"{run['run_id']}_bold.nii.gz")), None) \
            if root else None
        if raw is None:
            continue
        try:
            cord = np.asarray(nib.load(str(seg)).dataobj) > 0.5
            img = nib.load(str(raw))
            data = np.asarray(img.dataobj, dtype=np.float32)
        except Exception:
            continue
        if data.ndim != 4 or data.shape[:3] != cord.shape:
            continue
        n_vol = data.shape[3]
        tr = repetition_time_s(raw)
        mean3d = data.mean(axis=3)
        br = brain_mask(mean3d, cord)
        if br is None:
            continue
        C = np.column_stack([cosine_basis(n_vol, tr), np.ones(n_vol)])
        q, _ = np.linalg.qr(C)
        # task design where one exists, to ask whether the raw global signal is
        # task-locked -- the question the anomaly raises
        conds = conditions_for(run["dataset"], run["run_id"])
        Xt = np.empty((n_vol, 0))
        if conds:
            ev = next(iter(Path(root).rglob(f"{run['run_id']}_events.tsv")), None)
            if ev is not None:
                erows = list(csv.DictReader(open(ev), delimiter="\t"))
                scj = Path(str(raw).replace(".nii.gz", ".json"))
                stt = 0.0
                if scj.exists():
                    try:
                        stt = float(json.loads(scj.read_text()).get("StartTime") or 0.0)
                    except Exception:
                        pass
                Xt, _ = build_task_design(
                    corrected_events(run["dataset"], erows, stt, run["run_id"]),
                    n_vol, tr, conds)
        rec = dict(dataset=run["dataset"], subject=run["subject"],
                   run_id=run["run_id"], n_cord=int(cord.sum()),
                   n_brain=int(br.sum()))
        for lab, m in (("cord", cord), ("brain", br)):
            Y = data[m].T.astype(np.float64)
            if Y.shape[0] != n_vol:
                continue
            Y = Y - Y.mean(axis=0, keepdims=True)
            Yd = Y - q @ (q.T @ Y)
            gs = Yd.mean(axis=1)
            if np.std(gs) < 1e-9:
                continue
            gsz = (gs - gs.mean()) / np.std(gs)
            num = (Yd * gsz[:, None]).sum(axis=0) / n_vol
            r2 = (num ** 2) / np.maximum(Yd.var(axis=0), 1e-20)
            rec[f"{lab}_gs_r2_median"] = float(np.median(r2))
            rec[f"{lab}_gs_r2_p90"] = float(np.percentile(r2, 90))
            if Xt.shape[1]:
                xz = (Xt - Xt.mean(0)) / np.maximum(Xt.std(0), 1e-12)
                rec[f"{lab}_gs_task_r"] = float(np.max(np.abs(
                    [np.corrcoef(gsz, xz[:, i])[0, 1] for i in range(Xt.shape[1])])))
        rows.append(rec)
        if (k + 1) % 20 == 0:
            print(f"  {k+1}/{len(runs)}", flush=True)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- A8
def a8():
    import nibabel as nib
    rows = []
    runs = list(driver.iter_runs(COHORT))
    print(f"A8: runs {len(runs)}", flush=True)
    for k, run in enumerate(runs):
        try:
            img = nib.load(str(run["bold"]))
            data = np.asarray(img.dataobj, dtype=np.float32)
            cord = np.asarray(nib.load(str(run["cord"])).dataobj) > 0.5
        except Exception:
            continue
        if data.ndim != 4 or data.shape[:3] != cord.shape:
            continue
        n_vol = data.shape[3]
        zooms = [float(z) for z in img.header.get_zooms()[:3]]
        zs = [z for z in range(cord.shape[2]) if cord[:, :, z].sum() >= 3]
        if len(zs) < 5:
            continue
        # intensity-weighted cord centroid per slice per timepoint
        cx = np.full((n_vol, len(zs)), np.nan)
        cy = np.full((n_vol, len(zs)), np.nan)
        for i, z in enumerate(zs):
            m = cord[:, :, z]
            ii, jj = np.nonzero(m)
            w = data[ii, jj, z, :].astype(np.float64)          # (nvox, T)
            sw = w.sum(axis=0)
            good = sw > 1e-6
            if good.sum() < 10:
                continue
            cx[good, i] = (ii[:, None] * w).sum(axis=0)[good] / sw[good]
            cy[good, i] = (jj[:, None] * w).sum(axis=0)[good] / sw[good]
        ok = np.isfinite(cx).all(axis=1) & np.isfinite(cy).all(axis=1)
        if ok.sum() < 20:
            continue
        cx, cy = cx[ok] * zooms[0], cy[ok] * zooms[1]
        # RIGID component: each timepoint's mean shift across slices -- what S4 models
        rig_x, rig_y = cx.mean(axis=1), cy.mean(axis=1)
        # NON-RIGID: what remains once that shift is removed, i.e. change in the
        # SHAPE of the centreline, which slicewise rigid correction cannot touch
        nr_x = cx - rig_x[:, None]
        nr_y = cy - rig_y[:, None]
        rows.append(dict(
            dataset=run["dataset"], subject=run["subject"], run_id=run["run_id"],
            n_slices=len(zs), n_vol=int(ok.sum()),
            rigid_sd_mm=float(np.sqrt(np.var(rig_x) + np.var(rig_y))),
            nonrigid_sd_mm=float(np.sqrt(
                np.mean(np.var(nr_x, axis=0) + np.var(nr_y, axis=0)))),
        ))
        if (k + 1) % 50 == 0:
            print(f"  {k+1}/{len(runs)}", flush=True)
    df = pd.DataFrame(rows)
    if len(df):
        df["ratio"] = df.nonrigid_sd_mm / df.rigid_sd_mm.replace(0, np.nan)
    return df


# ---------------------------------------------------------------- A6
def a6():
    from analysis.experiments.r2_qc_predicts_outcome import harvest_qc, FAMILIES
    qc = harvest_qc()
    cols = [c for v in FAMILIES.values() for c in v
            if c in qc.columns and qc[c].notna().sum() > 100]
    return qc, cols


def nested_shares(df, col):
    """Method-of-moments split into dataset / subject / run variance shares."""
    d = df.dropna(subset=[col, "dataset", "subject"])
    if len(d) < 40 or d.dataset.nunique() < 3:
        return None
    # within-subject (between-run) variance, pooled
    wr = [g[col].var(ddof=1) for _, g in d.groupby(["dataset", "subject"])
          if len(g) > 1 and np.isfinite(g[col].var(ddof=1))]
    var_run = float(np.mean(wr)) if wr else 0.0
    # between-subject within dataset
    ws = []
    for _, g in d.groupby("dataset"):
        sm = g.groupby("subject")[col].mean()
        if len(sm) > 1:
            ws.append(sm.var(ddof=1))
    var_subj = max(0.0, float(np.mean(ws)) - var_run) if ws else 0.0
    dm = d.groupby("dataset")[col].mean()
    var_ds = max(0.0, float(dm.var(ddof=1))) if len(dm) > 1 else 0.0
    tot = var_ds + var_subj + var_run
    if tot <= 0:
        return None
    return var_ds / tot, var_subj / tot, var_run / tot, tot


def report(A4, A8, QC, cols):
    print("\n" + "=" * 88)
    print("A4  THE GLOBAL SIGNAL ON RAW DATA, CORD vs BRAIN, SAME VOLUME")
    print("=" * 88)
    if not len(A4):
        print("  no runs resolved")
    else:
        print(f"  {len(A4)} runs. Raw EPI, cosine-detrended only -- the same input the")
        print("  paired-organ anomaly appeared in. R5's 1-2% was on preproc-v1.")
        print(f"  {'dataset':30} {'cord R2':>9} {'brain R2':>10} {'ratio':>7} "
              f"{'cord p90':>9} {'brain p90':>10} {'n':>4}")
        for ds, g in A4.groupby("dataset"):
            g = g.dropna(subset=["cord_gs_r2_median", "brain_gs_r2_median"])
            if not len(g):
                continue
            print(f"  {ds[:30]:30} {g.cord_gs_r2_median.median():9.3f} "
                  f"{g.brain_gs_r2_median.median():10.3f} "
                  f"{(g.cord_gs_r2_median/g.brain_gs_r2_median.replace(0,np.nan)).median():7.2f} "
                  f"{g.cord_gs_r2_p90.median():9.3f} "
                  f"{g.brain_gs_r2_p90.median():10.3f} {len(g):4}")
        g = A4.dropna(subset=["cord_gs_r2_median", "brain_gs_r2_median"])
        if len(g) >= 10:
            st = sps.wilcoxon(g.cord_gs_r2_median, g.brain_gs_r2_median)
            print(f"\n  paired cord vs brain: Wilcoxon p={st.pvalue:.2e} (n={len(g)})")
        if "cord_gs_task_r" in A4:
            t = A4.dropna(subset=["cord_gs_task_r"])
            if len(t) >= 5:
                print(f"  raw cord global signal vs task design, max |r| per run: "
                      f"median {t.cord_gs_task_r.median():.3f}, "
                      f"p90 {t.cord_gs_task_r.quantile(.9):.3f} (n={len(t)})")
                print("  If this is small, the RAW global signal is not task-locked")
                print("  either, and the ds005884 anomaly needs another explanation.")

    print("\n" + "=" * 88)
    print("A8  RESIDUAL NON-RIGID CORD DEFORMATION AFTER SLICEWISE RIGID CORRECTION")
    print("=" * 88)
    if not len(A8):
        print("  no runs resolved")
    else:
        print("  rigid_sd    = SD over time of the centreline's MEAN position (what S4 models)")
        print("  nonrigid_sd = SD over time of the centreline's SHAPE once that is removed")
        print(f"  {'dataset':34} {'rigid mm':>9} {'nonrigid mm':>12} {'ratio':>7} {'n':>4}")
        for ds, g in A8.groupby("dataset"):
            print(f"  {ds[:34]:34} {g.rigid_sd_mm.median():9.3f} "
                  f"{g.nonrigid_sd_mm.median():12.3f} {g.ratio.median():7.2f} {len(g):4}")
        print(f"  {'ALL':34} {A8.rigid_sd_mm.median():9.3f} "
              f"{A8.nonrigid_sd_mm.median():12.3f} {A8.ratio.median():7.2f} {len(A8):4}")
        print(f"\n  runs where non-rigid EXCEEDS rigid: "
              f"{int((A8.ratio > 1).sum())}/{len(A8)} "
              f"({100*float((A8.ratio > 1).mean()):.0f}%)")
        print("  A ratio above 1 means the deformation the pipeline cannot correct is")
        print("  larger than the translation it does correct.")

    print("\n" + "=" * 88)
    print("A6  VARIANCE DECOMPOSITION OF THE QC METRICS")
    print("=" * 88)
    print("  Shares of each metric's variance. If DATASET dominates SUBJECT, these")
    print("  metrics measure the site and protocol rather than the person, and")
    print("  multi-site cord fMRI needs harmonisation before pooling.")
    print(f"  {'metric':32} {'dataset':>9} {'subject':>9} {'run':>9}")
    tab = []
    for c in cols:
        r = nested_shares(QC, c)
        if r is None:
            continue
        tab.append((c, *r))
    tab.sort(key=lambda x: -x[1])
    for c, a, b, d_, _ in tab:
        print(f"  {c:32} {a*100:8.0f}% {b*100:8.0f}% {d_*100:8.0f}%")
    if tab:
        A = np.mean([t[1] for t in tab]); B = np.mean([t[2] for t in tab])
        D = np.mean([t[3] for t in tab])
        print(f"  {'MEAN over metrics':32} {A*100:8.0f}% {B*100:8.0f}% {D*100:8.0f}%")
        print(f"\n  dataset dominates subject in "
              f"{sum(1 for t in tab if t[1] > t[2])}/{len(tab)} metrics")
    print("\nDONE_MARKER")


if __name__ == "__main__":
    A4 = a4()
    A8 = a8()
    QC, cols = a6()
    OUT.mkdir(parents=True, exist_ok=True)
    if len(A4):
        A4.to_csv(OUT / "a4_raw_global_signal.csv", index=False)
    if len(A8):
        A8.to_csv(OUT / "a8_nonrigid.csv", index=False)
    report(A4, A8, QC, cols)
