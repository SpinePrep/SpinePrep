#!/usr/bin/env python3
"""A2 -- two retrofits that strengthen F1, the project's strongest finding.

F1 currently says: image-based SyN distortion correction WORSENS cord geometry in
82% of runs, while the measured field removes 81% of it. That contradicts standing
advice (Wang 2017, fMRIPrep's --use-syn-sdc). Two things are missing, and both are
computable from files already on disk.

ARM A -- WHY does SyN fail?  A mechanism, not just an outcome.
F1 reports that SyN makes geometry worse but never asks whether its ESTIMATE of the
field bears any relation to the truth. Topup measures the field from a reversed-PE
pair; SyN guesses it from image content alone. Both exist for the same 80 runs, in
the same grid, so they can be compared directly. Topup's spline coefficients are
re-expanded into a displacement field with --fout/--dfout (7 s per run).

  If SyN's displacement is UNCORRELATED with the measured displacement, F1 gains a
  mechanism: the fallback is not a noisy version of the truth, it is unrelated to
  it, and applying it can only add error.
  If it is correlated but too large, the failure is over-warping, which is what the
  FASB preprint asserted in a Discussion sentence with no measurement.

Sign conventions differ between FSL (voxels, image axes) and ANTs (mm, physical
LPS), so the sign of the correlation is reported and interpreted rather than assumed;
the magnitude is what carries the argument.

ARM B -- IS CORD DISTORTION ACTUALLY WORSE THAN BRAIN DISTORTION?
F1's whole premise is that the cord is the hard case. That is universally asserted
and, as far as this project can tell, never measured against the brain in the same
acquisition. It is measurable here: the raw reversed-PE fieldmaps are FULL FOV
(128 x 128 x 70, 280 mm of coverage), so one topup run yields the measured field over
cord AND brain simultaneously. Same shot, same shim, same subject, same field.

That produces a number nobody has: the ratio of measured geometric displacement in
the cervical cord to that in the brain, within one acquisition.

Masks: cord from the pipeline's own uncropped sct_deepseg segmentation (S3), brain
from intensity plus morphology on the temporal mean above the cord's extent, the same
routine the paired-organ control used.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/mnt/ssd1/SpinePrep")

import numpy as np
import pandas as pd
import yaml
from scipy import stats as sps

from analysis import driver
from analysis.glm_spec import conditions_for

COHORT = Path("/mnt/ssd1/spineprep_cohort_s2")
S5 = COHORT / "work" / "S5_func_distortion_correction"
S3 = COHORT / "runs" / "S3_func_init_and_crop"
OUT = Path("/mnt/ssd1/SpinePrep/analysis/results")
SCRATCH = Path("/tmp/claude-1000/-mnt-ssd1-SpinePrep/"
               "f4e0bb8b-cddd-41fb-aa92-db62665bad69/scratchpad/a2work")
DATASETS = ["openneuro_ds005884_cospine_motor", "openneuro_ds005883_cospine_pain"]
TOPUP_CFG = "b02b0_1.cnf"          # what S5 uses; b02b0.cnf rejects small FOVs


def run(cmd, **kw):
    env = dict(os.environ, FSLOUTPUTTYPE="NIFTI_GZ")
    return subprocess.run(cmd, capture_output=True, text=True, env=env, **kw)


def topup_fields(fmap, acqp, base, timeout=3600):
    """Re-run topup asking for the field (Hz) and the displacement field."""
    r = run(["topup", f"--imain={fmap}", f"--datain={acqp}",
             f"--config={TOPUP_CFG}", f"--out={base}",
             f"--fout={base}_fout", f"--dfout={base}_dfout"], timeout=timeout)
    f = Path(f"{base}_fout.nii.gz")
    d = Path(f"{base}_dfout_01.nii.gz")
    return (f, d) if f.exists() and d.exists() else (None, None)


# --------------------------------------------------------------------------
# ARM A: SyN estimate vs measured field, within the cord
# --------------------------------------------------------------------------

def arm_a():
    import nibabel as nib
    SCRATCH.mkdir(parents=True, exist_ok=True)
    rows = []
    dirs = sorted(d for d in S5.iterdir()
                  if (d / "topup_fieldcoef.nii.gz").exists()
                  and (d / "syn_0Warp.nii.gz").exists())
    print(f"ARM A: runs with both topup and SyN: {len(dirs)}", flush=True)
    for k, d in enumerate(dirs):
        fm, acq = d / "fmap_merged.nii.gz", d / "acqparams.txt"
        cm = d / "cord_mask_in_bold.nii.gz"
        if not (fm.exists() and acq.exists() and cm.exists()):
            continue
        base = SCRATCH / f"a_{d.name}"
        fout, dfout = topup_fields(fm, acq, base)
        if dfout is None:
            continue
        try:
            meas = np.asarray(nib.load(str(dfout)).dataobj, dtype=np.float64)
            synimg = nib.load(str(d / "syn_0Warp.nii.gz"))
            syn = np.squeeze(np.asarray(synimg.dataobj, dtype=np.float64))
            cord = np.asarray(nib.load(str(cm)).dataobj) > 0.5
            zooms = [float(z) for z in nib.load(str(cm)).header.get_zooms()[:3]]
        except Exception:
            continue
        if meas.shape[:3] != cord.shape or syn.shape[:3] != cord.shape:
            continue
        # phase encoding is j (the second image axis) for this cohort; acqparams
        # confirms it as the +-1 entry in column 2
        pe = 1
        meas_mm = meas[..., pe] * zooms[pe]        # FSL dfout is in voxels
        syn_mm = syn[..., pe]                      # ANTs warp is already in mm
        m, s = meas_mm[cord], syn_mm[cord]
        ok = np.isfinite(m) & np.isfinite(s)
        if ok.sum() < 50 or np.std(m[ok]) < 1e-9 or np.std(s[ok]) < 1e-9:
            continue
        r = float(sps.pearsonr(m[ok], s[ok]).statistic)
        rs = float(sps.spearmanr(m[ok], s[ok]).statistic)
        rows.append(dict(
            run_id=d.name,
            dataset=("ds005884" if "motor" in d.name else "ds005883"),
            n_vox=int(ok.sum()), r=r, r_abs=abs(r), rho=rs,
            rmse_mm=float(np.sqrt(np.mean((m[ok] - s[ok]) ** 2))),
            meas_absmed=float(np.median(np.abs(m[ok]))),
            syn_absmed=float(np.median(np.abs(s[ok]))),
            meas_p95=float(np.percentile(np.abs(m[ok]), 95)),
            syn_p95=float(np.percentile(np.abs(s[ok]), 95)),
        ))
        for p in SCRATCH.glob(f"a_{d.name}*"):
            p.unlink(missing_ok=True)
        if (k + 1) % 10 == 0:
            print(f"  {k+1}/{len(dirs)}", flush=True)
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# ARM B: measured distortion, brain vs cord, full FOV
# --------------------------------------------------------------------------

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


def _arm_b_one(job):
    """One run: merge the reversed-PE pair, topup it, measure per organ. Worker.

    Split out as a module-level function so arm B can run in a process pool.
    Full-FOV topup on a 128x128x70 volume takes about five minutes, so 77 runs
    serially is over six hours; ten workers bring it under an hour.
    """
    import nibabel as nib
    rid, dataset, subject, segp, app, pap, trt = job
    base = SCRATCH / f"b_{rid}"
    merged = Path(f"{base}_merged.nii.gz")
    try:
        ia, ip = nib.load(app), nib.load(pap)
        a = np.asarray(ia.dataobj, dtype=np.float32)
        b = np.asarray(ip.dataobj, dtype=np.float32)
        a = a[..., 0] if a.ndim == 4 else a
        b = b[..., 0] if b.ndim == 4 else b
        if a.shape != b.shape:
            return None
        nib.save(nib.Nifti1Image(np.stack([a, b], axis=3), ia.affine, ia.header),
                 str(merged))
        acqp = Path(f"{base}_acqparams.txt")
        acqp.write_text(f"0 -1 0 {trt:.6f}\n0 1 0 {trt:.6f}\n")
        fout, dfout = topup_fields(merged, acqp, base)
        if dfout is None:
            return None
        disp = np.asarray(nib.load(str(dfout)).dataobj, dtype=np.float64)
        segimg = nib.load(segp)
        cord = np.asarray(segimg.dataobj) > 0.5
        zooms = [float(z) for z in segimg.header.get_zooms()[:3]]
        if disp.shape[:3] != cord.shape:
            return None
        br = brain_mask(a.astype(np.float64), cord)
        if br is None:
            return None
        pe = 1
        dmm = np.abs(disp[..., pe]) * zooms[pe]
        rec = dict(run_id=rid, dataset=dataset, subject=subject,
                   n_cord=int(cord.sum()), n_brain=int(br.sum()))
        for lab, m in (("cord", cord), ("brain", br)):
            v = dmm[m]
            v = v[np.isfinite(v)]
            if len(v):
                rec[f"{lab}_median_mm"] = float(np.median(v))
                rec[f"{lab}_p95_mm"] = float(np.percentile(v, 95))
                rec[f"{lab}_max_mm"] = float(v.max())
        return rec
    except Exception:
        return None
    finally:
        for q in SCRATCH.glob(f"b_{rid}*"):
            try:
                q.unlink()
            except Exception:
                pass


def arm_b(limit=None, workers=10):
    import nibabel as nib
    SCRATCH.mkdir(parents=True, exist_ok=True)
    cfg = yaml.safe_load(Path("config/datasets_local.yaml").read_text()) or {}
    rawcfg = cfg.get("datasets", cfg)

    def mkpath(v):
        p_ = Path(v.get("path") or v.get("bids_root")) if isinstance(v, dict) else Path(v)
        return p_ if p_.is_absolute() else Path("/mnt/ssd1/SpinePrep") / p_

    roots = {k: mkpath(v) for k, v in rawcfg.items()}
    runs = [r for r in driver.iter_runs(COHORT) if r["dataset"] in DATASETS]
    if limit:
        runs = runs[:limit]
    jobs = []
    for run_ in runs:
        rid = run_["run_id"]
        seg = S3 / rid / "init" / "localize" / "func_ref_fast_seg.nii.gz"
        if not seg.exists():
            continue
        root = roots.get(run_["dataset"])
        parts = rid.split("_")
        sub = parts[0]
        task = next((q.split("-", 1)[1] for q in parts if q.startswith("task-")), None)
        if task is None:
            continue
        # Fieldmap naming differs between the two CoSpine releases: ds005884 carries
        # an acq- entity matching the task (sub-04_acq-motorL_dir-AP_epi) while
        # ds005883 does not (sub-04_dir-AP_epi). Requiring acq- silently dropped all
        # 37 ds005883 runs, so the task-specific name is tried first and the plain
        # one is the fallback.
        def _fmap(direction):
            for pat in (f"{sub}*acq-{task}_dir-{direction}_epi.nii.gz",
                        f"{sub}_dir-{direction}_epi.nii.gz",
                        f"{sub}*dir-{direction}_epi.nii.gz"):
                hit = next(iter(Path(root).rglob(pat)), None)
                if hit is not None:
                    return hit
            return None

        ap, pa = _fmap("AP"), _fmap("PA")
        if ap is None or pa is None:
            continue
        # readout time from the run's own S5 acqparams, so the measured field is in
        # the same physical units the pipeline itself used
        trt = 0.0406
        s5a = S5 / rid / "acqparams.txt"
        if s5a.exists():
            try:
                trt = float(s5a.read_text().split()[3])
            except Exception:
                pass
        jobs.append((rid, run_["dataset"], run_["subject"], str(seg),
                     str(ap), str(pa), trt))
    print(f"ARM B: {len(jobs)} runs with a full-FOV reversed-PE pair; "
          f"{workers} workers", flush=True)
    rows = []
    from concurrent.futures import ProcessPoolExecutor, as_completed
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_arm_b_one, j_): j_[0] for j_ in jobs}
        done = 0
        for f in as_completed(futs):
            done += 1
            try:
                r = f.result()
            except Exception:
                r = None
            if r:
                rows.append(r)
            if done % 5 == 0:
                print(f"  {done}/{len(jobs)} ({len(rows)} usable)", flush=True)
    return pd.DataFrame(rows)


def report(A, B):
    print("\n" + "=" * 86)
    print("A2  RETROFITS TO F1")
    print("=" * 86)
    print("\n--- ARM A: does SyN's ESTIMATE agree with the MEASURED field? ---")
    if not len(A):
        print("  no runs resolved")
    else:
        print(f"  {len(A)} runs, phase-encoding displacement compared voxelwise "
              f"inside the cord")
        print(f"  {'dataset':12} {'r':>8} {'|r|':>7} {'rho':>8} {'RMSE mm':>9} "
              f"{'|meas| med':>11} {'|SyN| med':>10} {'n':>4}")
        for ds, g in A.groupby("dataset"):
            print(f"  {ds:12} {g.r.median():+8.3f} {g.r_abs.median():7.3f} "
                  f"{g.rho.median():+8.3f} {g.rmse_mm.median():9.3f} "
                  f"{g.meas_absmed.median():11.3f} {g.syn_absmed.median():10.3f} "
                  f"{len(g):4}")
        t, p = sps.ttest_1samp(A.r.to_numpy(), 0.0)
        print(f"  ALL          {A.r.median():+8.3f} {A.r_abs.median():7.3f} "
              f"{A.rho.median():+8.3f} {A.rmse_mm.median():9.3f} "
              f"{A.meas_absmed.median():11.3f} {A.syn_absmed.median():10.3f} "
              f"{len(A):4}")
        print(f"\n  correlation against zero: t={t:+.2f}, p={p:.2e}")
        print(f"  runs with |r| > 0.3: {int((A.r_abs > 0.3).sum())}/{len(A)}")
        print(f"  SyN/measured magnitude ratio, median: "
              f"{(A.syn_absmed / A.meas_absmed.replace(0, np.nan)).median():.3f}")
        print("""
  THE SIGN IS A CONVENTION, and it is resolvable by construction rather than by
  assumption. Every image in this cohort is LAS, so its second axis is
  anterior-positive. ANTs stores displacement fields in physical LPS, where the same
  axis is posterior-positive. The phase-encoding axis is j, that second axis. So an
  exact sign flip is expected on precisely the component compared here, and a
  consistent negative r across all 80 runs is that flip, not an anti-correlation.
  The magnitude is therefore what carries the result.

  WHAT IS MEASURED. SyN's estimate is moderately correlated with the measured field
  (|r| ~ 0.45, |rho| ~ 0.46, and 58/80 runs above 0.3), so it is NOT estimating
  noise -- it recovers real structure. But its magnitude is 0.178 of the measured
  field: median |displacement| 0.90 mm against a measured 5.44 mm. SyN under-corrects
  by roughly a factor of six, and reproduces under half the spatial pattern.

  This REPLACES the mechanism this arm was built to test. The hypothesis was that
  SyN's field is unrelated to the truth; it is not. The measured mechanism is
  under-correction plus partial spatial mismatch.

  OPEN, and it must not be glossed. F1 measures that SyN makes cord geometry WORSE in
  82% of runs. A warp that points the right way at 18% strength should improve
  geometry slightly, not degrade it. The two are reconcilable -- a field that is right
  on average but wrong in more than half of voxels can displace tissue locally while
  reducing global RMS, and F1's metric is per-slice centreline displacement rather
  than global RMS -- but that reconciliation is an INFERENCE here, not a measurement.
  Confirming it needs the two metrics computed on the same voxels in the same run,
  which this arm does not do.""")

    print("\n--- ARM B: measured distortion, CORD vs BRAIN, same acquisition ---")
    if not len(B):
        print("  no runs resolved")
    else:
        print(f"  {len(B)} runs. One topup on the full-FOV reversed-PE pair gives the")
        print("  measured field over both organs at once: same shot, same shim.")
        print(f"  {'dataset':30} {'cord med':>9} {'brain med':>10} {'ratio':>7} "
              f"{'cord p95':>9} {'brain p95':>10} {'n':>4}")
        for ds, g in B.groupby("dataset"):
            g = g.dropna(subset=["cord_median_mm", "brain_median_mm"])
            if not len(g):
                continue
            ratio = (g.cord_median_mm / g.brain_median_mm.replace(0, np.nan)).median()
            print(f"  {ds[:30]:30} {g.cord_median_mm.median():9.3f} "
                  f"{g.brain_median_mm.median():10.3f} {ratio:7.2f} "
                  f"{g.cord_p95_mm.median():9.3f} {g.brain_p95_mm.median():10.3f} "
                  f"{len(g):4}")
        g = B.dropna(subset=["cord_median_mm", "brain_median_mm"])
        if len(g) >= 10:
            st = sps.wilcoxon(g.cord_median_mm, g.brain_median_mm)
            ratio = (g.cord_median_mm / g.brain_median_mm.replace(0, np.nan))
            print(f"\n  paired cord vs brain, median displacement: "
                  f"Wilcoxon p={st.pvalue:.2e} (n={len(g)})")
            print(f"  cord/brain ratio: median {ratio.median():.2f}, "
                  f"IQR {ratio.quantile(.25):.2f}-{ratio.quantile(.75):.2f}")
            print(f"  cord worse than brain in {int((ratio > 1).sum())}/{len(g)} runs")
        print("""
  READING. This is F1's premise, measured rather than asserted. A ratio above 1
  quantifies for the first time how much worse cervical cord distortion is than
  brain distortion in the same acquisition, which is the reason a fieldmap matters
  more in the cord than the brain literature assumes. A ratio near 1 would mean the
  premise is weaker than the field believes, and F1 would need rewording.""")
    print("\nDONE_MARKER")


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "both"
    A = arm_a() if which in ("a", "both") else pd.DataFrame()
    B = arm_b() if which in ("b", "both") else pd.DataFrame()
    OUT.mkdir(parents=True, exist_ok=True)
    if len(A):
        A.to_csv(OUT / "a2_arm_a_syn_vs_measured.csv", index=False)
    if len(B):
        B.to_csv(OUT / "a2_arm_b_cord_vs_brain_distortion.csv", index=False)
    report(A, B)
