#!/usr/bin/env python3
"""Regenerate the new S4 reportlet set (trace panel + slicewise heatmap +
tSNR/per-slice) for the promoted reg cohort, from existing S4 outputs.
Reads work/done/reg/S4; writes into that workfolder's derivatives figures dir
and mirrors flat copies into work/review/s4_reportlets/ for quick inspection.
"""
import sys, glob, shutil
from pathlib import Path
import numpy as np, pandas as pd, nibabel as nib, yaml

ROOT = Path("/mnt/ssd1/SpinalfMRIprep")
sys.path.insert(0, str(ROOT / "src"))
from spinalfmriprep.lib import moco, viz_s4

s4 = (ROOT / "work" / "done" / "reg" / "S4").resolve()
pol = yaml.safe_load((ROOT / "policy" / "S4_func_motion_correction.yaml").read_text())
fd_thr = float(pol.get("qc_thresholds", {}).get("fd_threshold_mm", 0.5))
dpi = int(pol.get("qc", {}).get("motion_traces", {}).get("dpi", 100))
cmap = pol.get("qc", {}).get("tsnr_comparison", {}).get("colormap", "viridis")

review = ROOT / "work" / "review" / "s4_reportlets"
review.mkdir(parents=True, exist_ok=True)

run_dirs = sorted({Path(p).parent for p in glob.glob(str(s4 / "work" / "S4_func_motion_correction" / "*" / "moco_params_coarse.tsv"))})
print(f"{len(run_dirs)} reg S4 runs\n")

for d in run_dirs:
    name = d.name
    try:
        # params_total = Stage-1 bulk + Stage-2 slicewise mean (both mm)
        p1 = pd.read_csv(d / "moco_params_coarse.tsv", sep="\t")
        params = pd.DataFrame({"tx": p1["tx_coarse"].to_numpy(), "ty": p1["ty_coarse"].to_numpy()})
        mx = nib.load(d / "moco_params_x.nii.gz").get_fdata()
        my = nib.load(d / "moco_params_y.nii.gz").get_fdata()
        params["tx"] += mx.mean(axis=(0, 1, 2))
        params["ty"] += my.mean(axis=(0, 1, 2))
        fd = moco.compute_framewise_displacement(params)

        # after BOLD (mocoref) for DVARS + mask
        cands = glob.glob(str(s4 / "derivatives" / "spinalfmriprep" / "**" / f"{name}_desc-mocoref_bold.nii.gz"), recursive=True)
        after = nib.load(cands[0]).get_fdata()
        mask = np.mean(after, axis=-1) > 0
        dvars = moco.compute_dvars(after, mask)
        _q1, _q3 = np.percentile(dvars, [25, 75])
        dvars_thr = float(_q3 + 1.5 * (_q3 - _q1))  # Tukey fence, matches S8

        tb = nib.load(d / "tsnr_before.nii.gz").get_fdata()
        ta = nib.load(d / "tsnr_after.nii.gz").get_fdata()
        zooms = nib.load(d / "tsnr_after.nii.gz").header.get_zooms()[:3]
        mb, ma = tb[mask].mean(), ta[mask].mean()
        impr = float((ma - mb) / mb * 100) if mb > 0 else 0.0
        cz = np.where(mask.any(axis=(0, 1)))[0]
        czx = (int(cz.min()), int(cz.max())) if cz.size else None

        # figures dir for this run (mirror the derivatives layout from the bold path)
        fig_dir = Path(cands[0]).parent.parent / "figures"
        fig_dir.mkdir(parents=True, exist_ok=True)

        f1 = fig_dir / f"{name}_desc-S4_motion_traces.png"
        f2 = fig_dir / f"{name}_desc-S4_slicewise_heatmap.png"
        f3 = fig_dir / f"{name}_desc-S4_tsnr_comparison.png"
        viz_s4.render_motion_traces(params, fd, dvars, fd_thr, dvars_thr, f1, dpi=dpi)
        viz_s4.render_slicewise_heatmap(mx, my, f2, cord_z_extent=czx, dpi=dpi)
        viz_s4.render_tsnr_comparison(tb, ta, mask, zooms, f3, improvement_pct=impr, colormap=cmap, dpi=dpi)
        for f in (f1, f2, f3):
            shutil.copy(f, review / f.name)
        print(f"  OK {name:46} maxFD={fd.max():.2f} dVARSmax={dvars.max():.1f} tSNRΔ={impr:+.1f}%")
    except Exception as e:
        print(f"  ERR {name}: {e}")

print(f"\nFigures mirrored to: {review}")
