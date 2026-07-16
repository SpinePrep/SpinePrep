#!/usr/bin/env python3
"""Recompute S4 FD/metrics/status from persisted params -- no motion re-run.

Why this is safe
----------------
S4's `params_total` (the summed motion estimate) is used in exactly two places:
`compute_framewise_displacement` and the trace reportlet. It NEVER touches the
image data. The corrected series (`desc-mocoref_bold`) comes from Stage 1's
scipy shift (in voxels, self-consistent) and SCT's own warp application, both of
which are correct. So the 2026-07-16 FD defects -- mixed units and slice-signed
averaging -- corrupted a reported NUMBER, not the data. Everything needed to
recompute is on disk per run:

    work/S4_func_motion_correction/<run_id>/moco_params_coarse.tsv   (stage 1, voxels)
    work/S4_func_motion_correction/<run_id>/moco_params_x.nii.gz     (stage 2, mm)
    work/S4_func_motion_correction/<run_id>/moco_params_y.nii.gz
    runs/S3_func_init_and_crop/<run_id>/funccrop_bold.nii.gz         (geometry)

This pass recomputes FD with `moco.compose_cord_fd`, rewrites the FD-derived
metrics and the run status in qc.json, and leaves tSNR/DVARS untouched (they are
image-based and already cord-restricted).

Usage
-----
    python3 scripts/s4_recompute_fd.py --dry-run     # report only
    python3 scripts/s4_recompute_fd.py               # rewrite qc.json
    python3 scripts/s4_recompute_fd.py --fd-threshold 1.2
"""
from __future__ import annotations

import argparse
import json
import shutil
import statistics as st
import sys
from pathlib import Path

import nibabel as nib
import numpy as np
import pandas as pd
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from spineprep.lib.moco import compose_cord_fd  # noqa: E402

OUT = Path("/mnt/ssd1/spineprep_cohort_s2")
W = OUT / "work" / "S4_func_motion_correction"
S3 = OUT / "runs" / "S3_func_init_and_crop"
QC = OUT / "logs" / "S4_func_motion_correction"


def recompute_run(run_id: str):
    wd = W / run_id
    coarse = wd / "moco_params_coarse.tsv"
    mxp, myp = wd / "moco_params_x.nii.gz", wd / "moco_params_y.nii.gz"
    bold = S3 / run_id / "funccrop_bold.nii.gz"
    if not coarse.exists() or not bold.exists():
        return None
    img = nib.load(bold)
    zx, zy = img.header.get_zooms()[:2]
    ax = nib.orientations.aff2axcodes(img.affine)
    p1 = pd.read_csv(coarse, sep="\t")
    tx = p1.get("tx_coarse", pd.Series(np.zeros(len(p1)))).values
    ty = p1.get("ty_coarse", pd.Series(np.zeros(len(p1)))).values
    sx = sy = None
    if mxp.exists() and myp.exists():
        a = nib.load(mxp).get_fdata()
        b = nib.load(myp).get_fdata()
        if a.ndim == 4 and a.shape[-1] == len(tx):
            sx, sy = a, b
    fd, info = compose_cord_fd(tx, ty, sx, sy, float(zx), float(zy), axcodes=ax)
    return fd, info


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--fd-threshold", type=float, default=None,
                    help="override fd_threshold_mm (default: policy value)")
    args = ap.parse_args()

    pol = yaml.safe_load((REPO / "policy" / "S4_func_motion_correction.yaml").read_text())
    qt = pol["qc_thresholds"]
    fd_thr = args.fd_threshold if args.fd_threshold is not None else qt["fd_threshold_mm"]
    fail_frac = qt.get("max_high_motion_fraction")  # None = motion never FAILs
    warn_frac = qt.get("warn_high_motion_fraction")
    warn_fd = qt["warn_fd_mm"]
    min_tsnr = qt["min_tsnr"]

    old_fracs, new_fracs, deltas = [], [], []
    status_change = {"PASS->PASS": 0, "FAIL->PASS": 0, "PASS->FAIL": 0, "other": 0}
    n_done = 0

    for qcp in sorted(QC.glob("*/qc.json")):
        j = json.loads(qcp.read_text())
        changed = False
        for r in j.get("runs", []):
            rid = r.get("run_id")
            m = r.get("metrics") or {}
            if not rid or not m:
                continue
            res = recompute_run(rid)
            if res is None:
                continue
            fd, info = res
            old_frac = m.get("high_motion_fraction")
            old_status = r.get("status")

            n_hi = int(np.sum(fd > fd_thr))
            frac = n_hi / len(fd)
            m["max_fd_mm"] = float(np.max(fd))
            m["mean_fd_mm"] = float(np.mean(fd))
            m["high_motion_frame_count"] = n_hi
            m["high_motion_fraction"] = float(frac)
            m["fd_composition"] = info

            reasons = []
            status = "PASS"
            if fail_frac is not None and frac > fail_frac:
                status = "FAIL"
                reasons.append(
                    f"{frac:.0%} of frames exceed FD>{fd_thr}mm "
                    f"(> {fail_frac:.0%} usable-data floor)")
            elif warn_frac is not None and frac > warn_frac:
                status = "WARN"
                reasons.append(f"high censored fraction {frac:.0%}")
            if m["max_fd_mm"] > warn_fd:
                if status == "PASS":
                    status = "WARN"
                reasons.append(
                    f"motion/artifact spike: max FD {m['max_fd_mm']:.2f}mm "
                    f"(censored downstream, not a rejection)")
            if qt.get("warn_tsnr_degraded", True) and m.get("tsnr_improvement_pct", 0) < 0:
                if status == "PASS": status = "WARN"
                reasons.append(
                    f"motion correction reduced cord tSNR by "
                    f"{abs(m['tsnr_improvement_pct']):.1f}%")
            if m.get("tsnr_after_mean", 99) < min_tsnr:
                status = "FAIL"
                reasons.append(f"tSNR {m['tsnr_after_mean']:.2f} < {min_tsnr}")

            key = f"{old_status}->{status}"
            status_change[key] = status_change.get(key, 0) + 1
            if old_frac is not None:
                old_fracs.append(old_frac)
                new_fracs.append(frac)
                deltas.append(frac - old_frac)
            r["status"] = status
            r["failure_reasons"] = reasons
            changed = True
            n_done += 1

        if changed and not args.dry_run:
            bak = qcp.with_suffix(".json.pre_fdfix")
            if not bak.exists():
                shutil.copy2(qcp, bak)
            from collections import Counter
            c = Counter(x.get("status") for x in j.get("runs", []))
            n = len(j.get("runs", []))
            j["status"] = ("PASS" if c.get("PASS", 0) == n
                           else "WARN" if c.get("PASS", 0) > 0 else "FAIL")
            qcp.write_text(json.dumps(j, indent=2))

    print(f"runs recomputed: {n_done}")
    if old_fracs:
        print(f"\nhigh_motion_fraction  OLD median {st.median(old_fracs):.3f} "
              f"-> NEW median {st.median(new_fracs):.3f}")
        print(f"  runs >0.50 (FAIL):  OLD {sum(f>0.50 for f in old_fracs)}  "
              f"-> NEW {sum(f>0.50 for f in new_fracs)}")
        print(f"  runs >0.30 (WARN):  OLD {sum(f>0.30 for f in old_fracs)}  "
              f"-> NEW {sum(f>0.30 for f in new_fracs)}")
    print("\nstatus transitions:")
    for k, v in sorted(status_change.items(), key=lambda x: -x[1]):
        if v:
            print(f"  {k:<14} {v}")
    if args.dry_run:
        print("\n(dry run - nothing written)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
