#!/usr/bin/env python3
"""Regenerate S6 reportlets (composite + per-slice Dice) for the promoted reg
cohort, applying the BUG-4 (affine-derived S/I/A/P markers) + FEAT-3
(caudal/rostral labels) fixes. Reads work/done/reg/S6 work dirs, writes into the
matching derivatives figures dir (same filenames the qc.json already lists)."""
import sys, glob, json
from pathlib import Path
ROOT = Path("/mnt/ssd1/SpinePrep"); sys.path.insert(0, str(ROOT / "src"))
from spineprep.steps.s6.reportlets import render_s6_composite, render_s6_dice_per_slice

s6 = (ROOT / "work" / "done" / "reg" / "S6").resolve()
thr = {"pass_dice_min": 0.85, "fail_dice_below": 0.65}

# map run_id -> (dice, hd95) from qc.json
metr = {}
for q in glob.glob(str(s6 / "logs" / "S6_func_to_anat_registration" / "*" / "qc.json")):
    for r in json.load(open(q)).get("runs", []):
        m = r.get("metrics", {}) or {}
        metr[r.get("run_id", "")] = (m.get("cord_dice"), m.get("cord_hd95_mm"))

runs = sorted({Path(p).parent for p in glob.glob(
    str(s6 / "work" / "S6_func_to_anat_registration" / "*" / "funccrop_mask.nii.gz"))})
print(f"{len(runs)} S6 runs")
for d in runs:
    name = d.name
    # figures dir: find the run's derivatives func dir via the bold_on_anat target
    cands = glob.glob(str(s6 / "derivatives" / "spineprep" / "**" /
                          f"{name}_desc-S6_cord_dice_per_slice.png"), recursive=True)
    if not cands:
        print(f"  SKIP {name}: no derivatives figures dir"); continue
    figdir = Path(cands[0]).parent
    dice, hd95 = metr.get(name, (None, None))
    try:
        render_s6_composite(
            bold_mean_path=d / "bold_mean.nii.gz",
            anat_dseg_in_bold_path=d / "anat_dseg_in_bold.nii.gz",
            cord_mask_path=d / "funccrop_mask.nii.gz",
            output_path=figdir / f"{name}_desc-S6_bold_on_anat.png",
            anat_in_bold_path=d / "anat_in_bold.nii.gz",
            funcref_path=d / "funcref.nii.gz",
            dice=dice, hd95=hd95,
        )
        render_s6_dice_per_slice(
            d / "funccrop_mask.nii.gz", d / "anat_dseg_in_bold.nii.gz",
            figdir / f"{name}_desc-S6_cord_dice_per_slice.png", thr,
        )
        print(f"  OK {name}")
    except Exception as e:
        print(f"  ERR {name}: {e}")
