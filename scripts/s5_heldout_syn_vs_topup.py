#!/usr/bin/env python3
"""Held-out validation: does fieldmap-less SyN recover the MEASURED field?

Why this exists
---------------
On the 469-run cohort, 83 runs (18%) have a reversed-PE pair and 386 (82%) fall
back to image-based SyN. So SpinePrep's distortion story rests on the fallback --
and the fallback is the least defensible mode:

  * it is unprecedented in cord fMRI (TOPUP itself appears essentially once,
    CoSpine/Wei 2025; most cord work does no retrospective SDC at all);
  * FASB (Vahdat/Landelle/De Leener/Doyon) considered nonlinear warping of cord
    EPI and argued AGAINST it -- "performing a nonlinear transformation
    generates non-optimal twisted warping fields";
  * and our own QC CANNOT falsify it. Cord Dice rewards exactly the alignment
    SyN optimizes, so a good Dice is not evidence SyN worked. For topup Dice IS
    evidence (topup never saw it).

The CoSpine datasets ship reversed-PE pairs, so they are a held-out set: we can
correct the SAME runs with topup (measured field = reference) and with SyN
(pretending no fieldmap), and ask whether SyN lands where the physics says.

The statistic
-------------
S5 already reports per-slice A-P displacement between the EPI cord centroid and
the ANAT cord centroid. Both modes score against the same anatomy, so:

    d_before(z)  uncorrected displacement            (identical in both runs)
    d_topup(z)   displacement after the measured-field correction  [reference]
    d_syn(z)     displacement after image-based SyN

    residual(z) = |d_syn(z)  - d_topup(z)|     how far SyN sits from the truth
    baseline(z) = |d_before(z) - d_topup(z)|   how far it had to travel

    gap_closed  = 1 - mean(residual) / mean(baseline)

      1.0  SyN reproduces the measured field exactly
      0.0  SyN is no closer to the truth than doing nothing
      <0   SyN moved the cord AWAY from where the field says it belongs

This is not circular: the reference is a physical field measurement SyN never
saw. Dice is deliberately NOT used.

Usage
-----
    python3 scripts/s5_heldout_syn_vs_topup.py run      # run both modes
    python3 scripts/s5_heldout_syn_vs_topup.py analyze  # compare
"""
from __future__ import annotations

import json
import os
import shutil
import statistics as st
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = Path("/mnt/ssd1/spineprep_cohort_s2")
POLICY = REPO / "policy" / "S5_func_distortion_correction.yaml"
SNAP = Path("/mnt/ssd1/spineprep_s5_heldout")
DATASETS = ["openneuro_ds005883_cospine_pain", "openneuro_ds005884_cospine_motor"]
WORKERS = os.environ.get("HELDOUT_WORKERS", "8")


def _set_prefer_mode(mode: str) -> None:
    """Force S5's mode. Restored from the .bak by `restore()`."""
    text = POLICY.read_text()
    out, done = [], False
    for line in text.splitlines(keepends=True):
        s = line.lstrip()
        if s.startswith("prefer_mode:") and not done:
            indent = line[: len(line) - len(s)]
            out.append(f'{indent}prefer_mode: "{mode}"  # forced by s5_heldout\n')
            done = True
        else:
            out.append(line)
    assert done, "prefer_mode: not found in policy"
    POLICY.write_text("".join(out))


def run_mode(mode: str) -> None:
    print(f"\n=== S5 held-out: forcing mode={mode} ===", flush=True)
    _set_prefer_mode(mode)
    env = dict(os.environ, PYTHONPATH=str(REPO / "src"))
    for ds in DATASETS:
        cmd = [
            sys.executable, "-m", "spineprep.cli", "run",
            "S5_func_distortion_correction",
            "--dataset-key", ds,
            "--out", str(OUT),
            "--datasets-local", "config/datasets_local.yaml",
            "--batch-workers", WORKERS,
        ]
        print(f"  {ds} ...", flush=True)
        subprocess.run(cmd, cwd=REPO, env=env)
        src = OUT / "logs" / "S5_func_distortion_correction" / ds / "qc.json"
        dst = SNAP / mode / ds / "qc.json"
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.exists():
            shutil.copy2(src, dst)
            print(f"    snapshot -> {dst}", flush=True)
        else:
            print(f"    WARNING: no qc.json at {src}", flush=True)


def restore() -> None:
    bak = POLICY.with_suffix(".yaml.heldout_bak")
    if bak.exists():
        shutil.copy2(bak, POLICY)
        print(f"restored {POLICY} from {bak}")


def analyze() -> int:
    rows = []
    for ds in DATASETS:
        try:
            a = json.loads((SNAP / "topup" / ds / "qc.json").read_text())
            b = json.loads((SNAP / "syn" / ds / "qc.json").read_text())
        except FileNotFoundError as e:
            print(f"missing snapshot: {e}")
            return 1
        syn_by_id = {r.get("run_id"): r for r in b.get("runs", [])}
        for rt in a.get("runs", []):
            rid = rt.get("run_id")
            rs = syn_by_id.get(rid)
            if not rs:
                continue
            mt, ms = rt.get("metrics") or {}, rs.get("metrics") or {}
            # Only runs where topup ACTUALLY ran are a valid reference.
            if rt.get("mode") != "topup" or ms.get("displacement_after_mm") is None:
                continue
            zt, zs = mt.get("per_slice_z"), ms.get("per_slice_z")
            dt, dsy = mt.get("displacement_after_mm"), ms.get("displacement_after_mm")
            db = mt.get("displacement_before_mm")
            if not all(isinstance(x, list) for x in (zt, zs, dt, dsy, db)):
                continue
            # align on common slices
            si = {z: i for i, z in enumerate(zs)}
            res, base = [], []
            for i, z in enumerate(zt):
                j = si.get(z)
                if j is None:
                    continue
                res.append(abs(dsy[j] - dt[i]))
                base.append(abs(db[i] - dt[i]))
            if not res or not base:
                continue
            mres, mbase = st.mean(res), st.mean(base)
            gap = (1 - mres / mbase) if mbase > 1e-6 else float("nan")
            rows.append({
                "ds": ds, "run": rid, "n_z": len(res),
                "residual_mm": mres, "baseline_mm": mbase, "gap_closed": gap,
                "disp_topup": mt.get("displacement_mean_after_mm"),
                "disp_syn": ms.get("displacement_mean_after_mm"),
            })

    if not rows:
        print("No comparable runs. Did both modes run?")
        return 1

    print(f"\n{'run':<44} {'base':>6} {'resid':>6} {'gap':>7}")
    print("-" * 68)
    for r in sorted(rows, key=lambda x: x["gap_closed"]):
        print(f"{r['run'][:44]:<44} {r['baseline_mm']:>6.2f} "
              f"{r['residual_mm']:>6.2f} {r['gap_closed']:>7.2f}")
    gaps = [r["gap_closed"] for r in rows]
    res = [r["residual_mm"] for r in rows]
    base = [r["baseline_mm"] for r in rows]
    gaps_s = sorted(gaps)
    print("-" * 68)
    print(f"n runs                : {len(rows)}")
    print(f"baseline |d_before-d_topup| : mean {st.mean(base):.2f} mm")
    print(f"residual |d_syn-d_topup|    : mean {st.mean(res):.2f} mm")
    print(f"gap_closed            : median {st.median(gaps):.2f}  "
          f"mean {st.mean(gaps):.2f}  min {gaps_s[0]:.2f}  max {gaps_s[-1]:.2f}")
    print(f"runs where SyN moved AWAY from the field (gap<0): "
          f"{sum(g < 0 for g in gaps)}/{len(gaps)}")
    print("\nReading: gap 1.0 = SyN reproduces the measured field; 0.0 = no better "
          "than doing nothing; <0 = SyN moved the cord away from the truth.")
    (SNAP / "heldout_results.json").write_text(json.dumps(rows, indent=2))
    print(f"\nrows -> {SNAP/'heldout_results.json'}")
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "analyze"
    if cmd == "run":
        bak = POLICY.with_suffix(".yaml.heldout_bak")
        if not bak.exists():
            shutil.copy2(POLICY, bak)
        try:
            run_mode("topup")
            run_mode("syn")
        finally:
            restore()
        sys.exit(analyze())
    elif cmd == "restore":
        restore()
    else:
        sys.exit(analyze())
