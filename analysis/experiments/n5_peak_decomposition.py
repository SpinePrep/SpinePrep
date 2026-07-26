#!/usr/bin/env python3
"""N5 -- decompose the peak-location scatter, and audit how F3 measured it.

F3 currently reports across-subject peak scatter of 1-4 mm in plane and 14-19 mm
rostrocaudally, normalised against random placement. It is descriptive, which
invites "so what", and it is open to "your registration is simply bad".

FIRST, AN AUDIT OF OUR OWN NUMBER. The original code (tier2_all.py T2.3) recorded
each peak as `native_voxel_index * voxel_size`. That is a position in the
subject's OWN CROPPED GRID, not in any shared anatomical frame. Each subject's
crop is placed by S3 around that subject's cord, so two subjects whose peaks sit
at the identical anatomical level can differ by however much their crop origins
differ. Any such difference is added to the reported scatter and is not biology.
This script measures that offset directly, so the size of the artifact is known
rather than assumed.

SECOND, THE DECOMPOSITION. Peak position is re-expressed in coordinates that
cannot carry a crop offset:
  z_rel   mm from the a-priori horn's own rostrocaudal centroid, in the same run
  x_rel   mm from the cord centroid of the peak's own axial slice
  y_rel   the same, anterior-posterior
  z_frac  position as a fraction of the horn's rostrocaudal extent, which also
          removes any difference in how many levels the horn spans
Every term is computed inside one run, so the shared frame is anatomy and no
inverse warp is needed. The warped level map supplies an independent check:
which spinal level the peak falls in.

Then the variance is split across the three repeat axes the cohort actually has:

  between RUNS, same session, same subject   -> measurement noise alone
  between SESSIONS, same subject             -> + repositioning and registration
  between SUBJECTS                           -> + true inter-individual anatomy

  sigma2_between_subject = sigma2_noise + sigma2_session + sigma2_biology

by method of moments on the nested means. This is the finding that matters: if
measurement noise dominates, the cord peak is not a poorly reproducible
biological location, it is an UNMEASURABLE quantity in a single run, and the fix
is more data per subject rather than a warning about published level claims. If
biology dominates, group-level vertebral-level claims are the thing that fails.
Those two readings call for opposite actions, which is why the split is worth
more than the raw scatter.

ds004616 ses-02 follows an acute intermittent hypoxia protocol and its two
sessions are NOT repeats (glm_spec documents this), so it contributes to the
run axis only. ds004386's two runs are auto versus manual z-shim, also not
repeats, and it has no task, so it does not enter at all.
"""
from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
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
# sessions that are NOT repeat measurements
NOT_REPEAT_SESSIONS = {"openneuro_ds004616_spinalcord_handgrasp_task"}


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
            img = nib.load(str(run["bold"]))
            data = np.asarray(img.dataobj, dtype=np.float32)
        except Exception:
            continue
        if data.ndim != 4:
            continue
        zooms = [float(z) for z in img.header.get_zooms()[:3]]
        n_vol = data.shape[3]
        tr = repetition_time_s(run["bold"])
        Xt, names = build_task_design(
            corrected_events(ds, erows, stt, run["run_id"]), n_vol, tr, conds)
        if Xt.shape[1] == 0:
            continue
        Xn, _ = lean_confounds(Path(run["confounds"]), n_vol)
        X = np.column_stack([Xt, Xn, np.ones(n_vol)]) if Xn.size \
            else np.column_stack([Xt, np.ones(n_vol)])
        if np.linalg.matrix_rank(X) < X.shape[1]:
            X = np.column_stack([Xt, np.ones(n_vol)])
        cord = parcels["cord"]["cord"]
        midx = np.argwhere(cord)
        Y = data[cord].T.astype(np.float64)
        if Y.shape[0] != n_vol:
            continue
        Y = Y - Y.mean(axis=0, keepdims=True)
        b, *_ = np.linalg.lstsq(X, Y, rcond=None)

        levels = None
        lp = Path(run["spinallevels"])
        if lp.exists():
            try:
                levels = np.asarray(nib.load(str(lp)).dataobj)
            except Exception:
                levels = None

        ht, fixed = HORN[ds]
        for ci, cn in enumerate(names):
            sd_ = side_of(cn) or fixed
            if sd_ is None:
                continue
            h = parcels["gmhorn"].get(f"gm-{ht}-{sd_}")
            if h is None:
                continue
            fi = h[tuple(midx.T)]
            if fi.sum() < 10:
                continue
            hidx = midx[fi]
            pk = hidx[int(np.argmax(b[ci][fi]))]

            # --- the frame F3 used: raw native index * voxel size
            raw = [float(pk[i] * zooms[i]) for i in range(3)]
            # --- crop-free anatomical coordinates
            hz = hidx[:, 2].astype(float)
            z_cent = hz.mean()
            z_span = (hz.max() - hz.min() + 1)
            z_rel = float((pk[2] - z_cent) * zooms[2])
            z_frac = float((pk[2] - hz.min()) / max(1.0, z_span - 1)) if z_span > 1 else np.nan
            # cord centroid of the peak's own axial slice
            sl = midx[midx[:, 2] == pk[2]]
            if len(sl) == 0:
                continue
            x_rel = float((pk[0] - sl[:, 0].mean()) * zooms[0])
            y_rel = float((pk[1] - sl[:, 1].mean()) * zooms[1])
            lev = float(levels[tuple(pk)]) if levels is not None else np.nan

            rows.append(dict(
                dataset=ds, subject=run["subject"],
                session=str(run.get("session") or "none"),
                run_id=run["run_id"], condition=cn,
                raw_x=raw[0], raw_y=raw[1], raw_z=raw[2],
                horn_centroid_z_mm=float(z_cent * zooms[2]),
                horn_span_mm=float(z_span * zooms[2]),
                x_rel=x_rel, y_rel=y_rel, z_rel=z_rel, z_frac=z_frac,
                level=lev, n_horn=int(fi.sum()),
            ))
        if (k_run + 1) % 20 == 0:
            print(f"  {k_run+1}/{len(runs)}", flush=True)

    OUT.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "n5_peak_decomposition.csv", index=False)
    report(df)


def nested_var(g, col):
    """Method-of-moments split of between-subject variance by repeat axis.

    Returns (sd_run, sd_session, sd_subject_total, sd_bio) in the column's units.
    sd_run     : SD of runs within one session of one subject, pooled
    sd_session : SD of session means within a subject, pooled (only where a
                 subject has >1 usable session)
    sd_subject : SD of subject means, the quantity F3 reports
    sd_bio     : sqrt(max(0, var_subject - var_session - var_run/mean_runs))
    """
    g = g.dropna(subset=[col])
    if not len(g):
        return (np.nan,) * 4
    # within session, between run
    wr = []
    nper = []
    for (s, ses), gg in g.groupby(["subject", "session"]):
        v = gg.groupby("run_id")[col].mean().to_numpy(float)
        nper.append(len(v))
        if len(v) > 1:
            wr.append(v.var(ddof=1))
    var_run = float(np.mean(wr)) if wr else np.nan
    # within subject, between session
    ws = []
    for s, gg in g.groupby("subject"):
        v = gg.groupby("session")[col].mean().to_numpy(float)
        if len(v) > 1:
            ws.append(v.var(ddof=1))
    var_ses = float(np.mean(ws)) if ws else np.nan
    subj = g.groupby("subject")[col].mean().to_numpy(float)
    var_subj = float(subj.var(ddof=1)) if len(subj) > 2 else np.nan
    k = float(np.mean(nper)) if nper else 1.0
    bio = var_subj
    if np.isfinite(var_run):
        bio -= var_run / max(1.0, k)
    if np.isfinite(var_ses):
        bio -= var_ses
    sq = lambda v: np.sqrt(v) if np.isfinite(v) and v > 0 else np.nan
    return sq(var_run), sq(var_ses), sq(var_subj), sq(max(0.0, bio) if np.isfinite(bio) else np.nan)


def report(df):
    short = lambda d: d.split("_")[1] if d.split("_")[0] == "openneuro" else d.split("_")[2]
    print("\n" + "=" * 88)
    print("N5  PEAK-LOCATION SCATTER: audit of the frame, then a variance split")
    print("=" * 88)
    if not len(df):
        print("no runs resolved")
        return
    print(f"runs {df.run_id.nunique()}   subjects {df.subject.nunique()}   "
          f"datasets {df.dataset.nunique()}")

    print("\n--- AUDIT  how much of F3's rostrocaudal scatter is the CROP ORIGIN? ---")
    print("  F3 measured peak position as native voxel index x voxel size. If two")
    print("  subjects' crops start at different anatomical points, that difference")
    print("  is inside the number. The horn centroid is the same anatomy in every")
    print("  subject, so its scatter in that frame is pure frame offset.")
    print(f"  {'dataset':12} {'N':>3} {'SD raw_z':>9} {'SD horn centroid z':>19} "
          f"{'SD z_rel':>9} {'inflation':>10}")
    for ds, g in df.groupby("dataset"):
        s = g.groupby("subject")[["raw_z", "horn_centroid_z_mm", "z_rel"]].mean()
        if len(s) < 5:
            continue
        a, b_, c = (s.raw_z.std(ddof=1), s.horn_centroid_z_mm.std(ddof=1),
                    s.z_rel.std(ddof=1))
        print(f"  {short(ds)[:12]:12} {len(s):3} {a:9.2f} {b_:19.2f} {c:9.2f} "
              f"{(a/c if c > 0 else np.nan):9.2f}x")
    print("  SD z_rel is the same peaks measured from each run's own horn centroid,")
    print("  which no crop offset can enter. The inflation column is the factor by")
    print("  which the published frame overstated the rostrocaudal scatter.")

    print("\n--- the crop-free scatter, all three axes (mm, across subject means) ---")
    print(f"  {'dataset':12} {'N':>3} {'SD x_rel':>9} {'SD y_rel':>9} {'SD z_rel':>9} "
          f"{'horn span':>10} {'levels hit':>11}")
    for ds, g in df.groupby("dataset"):
        s = g.groupby("subject")[["x_rel", "y_rel", "z_rel"]].mean()
        if len(s) < 5:
            continue
        lv = g.level.dropna()
        print(f"  {short(ds)[:12]:12} {len(s):3} {s.x_rel.std(ddof=1):9.2f} "
              f"{s.y_rel.std(ddof=1):9.2f} {s.z_rel.std(ddof=1):9.2f} "
              f"{g.horn_span_mm.median():10.1f} "
              f"{(lv.nunique() if len(lv) else 0):11}")

    print("\n--- VARIANCE SPLIT  measurement noise vs repositioning vs biology ---")
    print("  sd_run     between runs in one session of one subject -- noise alone")
    print("  sd_session between sessions in one subject -- + repositioning/registration")
    print("  sd_subj    between subjects -- the number F3 reports")
    print("  sd_bio     what is left for real anatomy after removing the other two")
    for col in ("z_rel", "x_rel", "y_rel"):
        print(f"\n  {col}:")
        print(f"    {'dataset':12} {'sd_run':>8} {'sd_session':>11} {'sd_subj':>9} "
              f"{'sd_bio':>8} {'noise share':>12}")
        for ds, g in df.groupby("dataset"):
            if ds in NOT_REPEAT_SESSIONS:
                g = g.assign(session="none")
            r, s_, su, bio = nested_var(g, col)
            if not np.isfinite(su):
                continue
            share = (r ** 2 / su ** 2) if (np.isfinite(r) and su > 0) else np.nan
            f = lambda v: f"{v:8.2f}" if np.isfinite(v) else "       -"
            if np.isfinite(share) and share >= 1.0:
                verdict = "noise >= ALL between-subject variance"
            elif np.isfinite(share):
                verdict = f"noise = {share*100:.0f}% of between-subject variance"
            else:
                verdict = "no within-session repeats"
            print(f"    {short(ds)[:12]:12} {f(r)} {f(s_):>11} {f(su):>9} "
                  f"{f(bio):>8}   {verdict}")

    print("\n--- IS THERE ANY SUBJECT-SPECIFIC SIGNAL IN THE PEAK? ICC(2,1) ---")
    print("  Computed over each subject's repeats (runs, then sessions). ICC ~ 0")
    print("  means knowing the subject tells you nothing about where the peak is.")
    print(f"  {'dataset':12} {'axis':7} {'ICC':>7} {'n subj':>7} {'repeats/subj':>13}")
    for ds, g in df.groupby("dataset"):
        for col in ("z_rel", "x_rel", "y_rel"):
            v = g.dropna(subset=[col])
            grp = [x[col].to_numpy(float) for _, x in v.groupby("subject")
                   if len(x) > 1]
            if len(grp) < 5:
                continue
            k = min(len(a) for a in grp)
            M = np.array([a[:k] for a in grp])
            n, kk = M.shape
            gm = M.mean()
            ms_b = kk * ((M.mean(1) - gm) ** 2).sum() / (n - 1)
            ms_w = ((M - M.mean(1, keepdims=True)) ** 2).sum() / (n * (kk - 1))
            icc = (ms_b - ms_w) / (ms_b + (kk - 1) * ms_w) if (ms_b + (kk - 1) * ms_w) > 0 else np.nan
            print(f"  {short(ds)[:12]:12} {col:7} {icc:+7.3f} {n:7} {kk:13}")

    print("\n--- CEILING CHECK on the in-plane numbers ---")
    print("  The a-priori horn is a narrow COLUMN: a few voxels across, running the")
    print("  whole imaged cord. In-plane the peak has almost nowhere to go, so a")
    print("  small SD there is a property of the ROI, not evidence of localisation.")
    print(f"  median horn rostrocaudal span {df.horn_span_mm.median():.0f} mm, "
          f"median horn size {df.n_horn.median():.0f} voxels")
    print("\n  READING. Where sd_run reaches or exceeds sd_subj, the single-run peak")
    print("  carries no subject-specific information: it moves as much between two")
    print("  runs of one person minutes apart as it does between different people.")
    print("  That is a stronger and different claim than 'poorly reproducible")
    print("  biology' -- the peak is not a measurement of that person at all.")
    print("\nDONE_MARKER")


if __name__ == "__main__":
    main()
