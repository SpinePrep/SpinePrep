#!/usr/bin/env python3
"""N4 -- cord-shaped smoothing: the constructive answer to our own thesis.

The thesis says an individual grey-matter horn is median 4.5 mm2 (2-5 x 2-3 mm),
so a 4-6 mm isotropic FWHM kernel is WIDER THAN A HORN. The measured consequences
are in hand: no universal optimum across datasets, and Kaptan 2023 reports a
smoothing-induced sign change severe enough that they advise caution at 2 mm.

Every cord fMRI paper that smooths, smooths isotropically. That is the brain's
default, and the brain abandoned it for focal structures: HCP smooths on the
surface rather than through it, and spatially adaptive models replaced fixed
kernels. The cord has a geometry at least as exploitable as a cortical surface --
it is a tube about 8 mm across containing horns 2-3 mm across -- and nobody
exploits it.

So the question is not "what kernel width" but "what kernel SHAPE".

SEVEN ARMS.
  none                      no smoothing, the reference
  iso 2 / 4 / 6 mm          the field's current practice
  rc 6 / 10 / 14 mm         ROSTROCAUDAL ONLY. The cord is a tube; smooth along
                            it, never across the 2-3 mm horn. Averaging along z
                            pools voxels that share a horn instead of mixing
                            dorsal with ventral and left with right.
  rc-centreline             the same, but each axial slice is first shifted so
                            the cord centroids align, so the kernel follows the
                            cord's actual path instead of the image z axis. This
                            is the approximation to along-cord geodesic smoothing
                            that a straight axis-aligned kernel gets wrong
                            wherever the cord is not vertical.
  inplane 2 / 4 mm          in-plane only, the deliberate opposite of rc: the
                            arm that SHOULD be worst if the mechanism is right.
                            Included so the prediction can fail.
  masked iso 4              normalised convolution inside the cord mask, so no
                            signal is ever averaged across the cord/CSF boundary
  masked rc 10              both fixes at once

FWHM is converted to sigma per axis using each run's own voxel size, so an arm
means the same physical width on every dataset regardless of its grid.

The endpoint is the estimator F2 and G1 already use: group Cohen's d from the
a-priori horn, top-10% selected on ODD timepoints and measured on EVEN, so no
arm can win by circular selection. tSNR is reported alongside because a kernel
that raises tSNR while lowering d is removing signal, and only reporting both
makes that visible.

The prediction is directional and falsifiable: rostrocaudal beats isotropic at
matched physical width, and in-plane is worst. If in-plane wins, the focality
mechanism is wrong.
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
from scipy import ndimage, stats as sps

from analysis import driver
from analysis.glm import build_task_design, lean_confounds
from analysis.glm_spec import conditions_for, corrected_events, repetition_time_s

COHORT = Path("/mnt/ssd1/spineprep_cohort_s2")
OUT = Path("/mnt/ssd1/SpinePrep/analysis/results")
FW = 2.355                                    # FWHM -> sigma

HORN = {
    "openneuro_ds004616_spinalcord_handgrasp_task": ("ventral", None),
    "openneuro_ds005884_cospine_motor": ("ventral", None),
    "openneuro_ds004926_dorsalhorn_pain": ("dorsal", "L"),
    "openneuro_ds005883_cospine_pain": ("dorsal", "R"),
}

ARMS = [
    ("none", None),
    ("iso2", ("iso", 2.0)), ("iso4", ("iso", 4.0)), ("iso6", ("iso", 6.0)),
    ("rc6", ("rc", 6.0)), ("rc10", ("rc", 10.0)), ("rc14", ("rc", 14.0)),
    ("rc10_centreline", ("rcc", 10.0)),
    ("inplane2", ("ip", 2.0)), ("inplane4", ("ip", 4.0)),
    ("masked_iso4", ("miso", 4.0)),
    ("masked_rc10", ("mrc", 10.0)),
]


def side_of(c):
    c = c.lower().replace("-", "").replace("_", "")
    if "left" in c or c.endswith("l"):
        return "L"
    if "right" in c or c.endswith("r"):
        return "R"
    return None


def sigmas(kind, fwhm, zooms):
    """Per-axis sigma in voxels for a physical FWHM in mm."""
    s = [0.0, 0.0, 0.0]
    if kind in ("iso", "miso"):
        s = [(fwhm / FW) / z for z in zooms]
    elif kind in ("rc", "rcc", "mrc"):
        s = [0.0, 0.0, (fwhm / FW) / zooms[2]]
    elif kind == "ip":
        s = [(fwhm / FW) / zooms[0], (fwhm / FW) / zooms[1], 0.0]
    return s


def centreline_shifts(cord):
    """Per-slice (dx, dy) that brings each axial cord centroid onto the mean one."""
    nz = cord.shape[2]
    cx = np.full(nz, np.nan)
    cy = np.full(nz, np.nan)
    for z in range(nz):
        m = cord[:, :, z]
        if m.sum() < 1:
            continue
        ii, jj = np.nonzero(m)
        cx[z], cy[z] = ii.mean(), jj.mean()
    ok = np.isfinite(cx)
    if ok.sum() < 3:
        return None
    # fill gaps by nearest valid slice so every slice has a shift
    zs = np.arange(nz)
    cx = np.interp(zs, zs[ok], cx[ok])
    cy = np.interp(zs, zs[ok], cy[ok])
    return np.rint(cx - cx.mean()).astype(int), np.rint(cy - cy.mean()).astype(int)


def apply_shifts(vol4, dx, dy, sign=1):
    out = np.empty_like(vol4)
    for z in range(vol4.shape[2]):
        out[:, :, z] = np.roll(np.roll(vol4[:, :, z], -sign * dx[z], axis=0),
                               -sign * dy[z], axis=1)
    return out


def smooth(data, arm, zooms, cord):
    """Apply one arm to a 4D array. Returns a new array, never in place."""
    if arm is None:
        return data
    kind, fwhm = arm
    s = sigmas(kind, fwhm, zooms) + [0.0]
    if max(s) <= 0:
        return data
    if kind in ("miso", "mrc"):
        # normalised convolution: smooth signal and mask, then divide, so the
        # cord/CSF boundary never contributes
        m = cord.astype(np.float32)[..., None]
        num = ndimage.gaussian_filter(data * m, sigma=s, mode="nearest")
        den = ndimage.gaussian_filter(np.repeat(m, data.shape[3], axis=3),
                                      sigma=s, mode="nearest")
        out = np.where(den > 1e-3, num / np.maximum(den, 1e-6), data)
        return out.astype(np.float32)
    if kind == "rcc":
        sh = centreline_shifts(cord)
        if sh is None:
            return ndimage.gaussian_filter(data, sigma=s, mode="nearest")
        dx, dy = sh
        al = apply_shifts(data, dx, dy, sign=1)
        al = ndimage.gaussian_filter(al, sigma=s, mode="nearest")
        return apply_shifts(al, dx, dy, sign=-1)
    return ndimage.gaussian_filter(data, sigma=s, mode="nearest")


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
        ht, fixed = HORN[ds]
        odd, even = np.arange(0, n_vol, 2), np.arange(1, n_vol, 2)

        for name, arm in ARMS:
            try:
                d4 = smooth(data, arm, zooms, cord)
            except Exception:
                continue
            Y = d4[cord].T.astype(np.float64)
            if Y.shape[0] != n_vol:
                continue
            mu, sd = Y.mean(0), Y.std(0)
            tsnr = float(np.median(mu[sd > 0] / sd[sd > 0])) if (sd > 0).any() else np.nan
            Yc = Y - Y.mean(0, keepdims=True)

            def fit(ix):
                """Fit on a timepoint subset, pruning columns that degenerate on it.

                The lean confound set carries one-hot spike columns. A spike on an
                even-indexed frame is identically zero on the odd half, so the
                design silently loses rank on every split and a plain rank guard
                rejects the run. Dropping the columns that are constant WITHIN the
                subset keeps the task regressors, which are always first, and keeps
                every arm on the same design.
                """
                Xi = X[ix]
                keep = Xi.std(axis=0) > 1e-9
                keep[:Xt.shape[1]] = True                  # task columns always
                keep[-1] = True                            # intercept
                Xi = Xi[:, keep]
                if len(ix) <= Xi.shape[1] + 2 or np.linalg.matrix_rank(Xi) < Xi.shape[1]:
                    return None
                b, *_ = np.linalg.lstsq(Xi, Yc[ix] - Yc[ix].mean(0, keepdims=True),
                                       rcond=None)
                return b

            b1, b2 = fit(odd), fit(even)
            if b1 is None or b2 is None:
                continue
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
                    dataset=ds, subject=run["subject"], run_id=run["run_id"],
                    condition=cn, arm=name, n_horn=int(fi.sum()), tsnr=tsnr,
                    cv_top10=float(v2[np.argsort(v1)[-k:]].mean()),
                    cv_mean=float(v2.mean()),
                ))
        if (k_run + 1) % 20 == 0:
            print(f"  {k_run+1}/{len(runs)}", flush=True)

    OUT.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "n4_smoothing_shape.csv", index=False)
    report(df)


def gd(g, col):
    s = g.groupby("subject")[col].mean().to_numpy(float)
    s = s[np.isfinite(s)]
    if len(s) < 5 or s.std(ddof=1) == 0:
        return np.nan, np.nan, len(s)
    return s.mean() / s.std(ddof=1), sps.ttest_1samp(s, 0).pvalue, len(s)


def report(df):
    print("\n" + "=" * 92)
    print("N4  KERNEL SHAPE, not kernel width -- group Cohen's d (odd/even CV top-10%)")
    print("=" * 92)
    if not len(df):
        print("no runs resolved")
        return
    short = lambda d: d.split("_")[1] if d.split("_")[0] == "openneuro" else d.split("_")[2]
    dss = sorted(df.dataset.unique())
    print(f"runs {df.run_id.nunique()}   datasets {len(dss)}\n")
    print(f"  {'arm':17} " + " ".join(f"{short(d)[:9]:>10}" for d in dss)
          + f" {'median d':>9} {'tSNR':>7}")
    med = {}
    for name, _ in ARMS:
        cells, ds_d = [], []
        for d in dss:
            g = df[(df.dataset == d) & (df.arm == name)]
            dv, p, n = gd(g, "cv_top10") if len(g) else (np.nan, np.nan, 0)
            cells.append(f"{dv:+.2f}" if np.isfinite(dv) else "-")
            if np.isfinite(dv):
                ds_d.append(dv)
        ts = df[df.arm == name].tsnr.median()
        med[name] = np.median(ds_d) if ds_d else np.nan
        print(f"  {name:17} " + " ".join(c.rjust(10) for c in cells)
              + f" {med[name]:+9.3f} {ts:7.1f}")

    print("\n  --- the directional prediction ---")
    base = med.get("none", np.nan)
    print(f"  no smoothing                          median d {base:+.3f}")
    for grp, lab in ((("iso2", "iso4", "iso6"), "best ISOTROPIC"),
                     (("rc6", "rc10", "rc14", "rc10_centreline"), "best ROSTROCAUDAL"),
                     (("inplane2", "inplane4"), "best IN-PLANE"),
                     (("masked_iso4", "masked_rc10"), "best MASK-CONSTRAINED")):
        vals = {k: med[k] for k in grp if np.isfinite(med.get(k, np.nan))}
        if vals:
            b = max(vals, key=vals.get)
            print(f"  {lab:37} median d {vals[b]:+.3f}   ({b})")
    rc = max([med.get(k, -9) for k in ("rc6", "rc10", "rc14", "rc10_centreline")])
    iso = max([med.get(k, -9) for k in ("iso2", "iso4", "iso6")])
    ip = max([med.get(k, -9) for k in ("inplane2", "inplane4")])
    print(f"\n  prediction was rostrocaudal > isotropic > in-plane.")
    print(f"  measured: rc {rc:+.3f}  iso {iso:+.3f}  in-plane {ip:+.3f}  -> "
          f"{'CONFIRMED' if (rc > iso > ip) else 'NOT confirmed'}")

    print("\n  --- paired test against the two references, subject level ---")
    piv = df.pivot_table(index=["dataset", "subject", "condition"],
                         columns="arm", values="cv_top10")
    for ref in ("none", "iso4"):
        if ref not in piv:
            continue
        print(f"    vs {ref}:")
        for name, _ in ARMS:
            if name == ref or name not in piv:
                continue
            j = piv[[name, ref]].dropna()
            if len(j) < 10:
                continue
            st = sps.wilcoxon(j[name], j[ref])
            delta = float((j[name] - j[ref]).median())
            flag = "  <-- better" if (delta > 0 and st.pvalue < 0.05) else ""
            print(f"      {name:17} median delta {delta:+.4f}  p={st.pvalue:.4f}"
                  f"  n={len(j)}{flag}")

    print("\n  A kernel that raises tSNR while lowering d is removing signal.")
    print("  Both columns are above so that trade is visible rather than implied.")
    print("\nDONE_MARKER")


if __name__ == "__main__":
    main()
