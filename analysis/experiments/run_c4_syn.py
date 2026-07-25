#!/usr/bin/env python3
"""C4: produce the SyN arm in an ISOLATED root, compare to the locked TopUp.

- Reference = the TopUp qc.json copied into the isolated root (same S3/S4 as the
  SyN arm will use, so the pairing is exact).
- Runs S5 with prefer_mode=syn ONLY into the isolated root; never writes to the
  locked cohort.
- The repo policy is edited transiently and restored from a scratchpad backup, so
  the locked working tree ends clean (verified by the caller).
"""
import json, os, shutil, subprocess, sys, statistics as st
from pathlib import Path

REPO = Path("/mnt/ssd1/SpinePrep")
C4 = Path("/mnt/ssd1/spineprep_c4_syn")
POLICY = REPO / "policy" / "S5_func_distortion_correction.yaml"
BACKUP = Path("/tmp/claude-1000/-mnt-ssd1-SpinePrep/"
              "f4e0bb8b-cddd-41fb-aa92-db62665bad69/scratchpad/S5_policy_backup.yaml")
SNAP = C4 / "_topup_reference"
DATASETS = ["openneuro_ds005883_cospine_pain", "openneuro_ds005884_cospine_motor"]


def snapshot_topup():
    SNAP.mkdir(parents=True, exist_ok=True)
    for ds in DATASETS:
        src = C4 / "logs" / "S5_func_distortion_correction" / ds / "qc.json"
        dst = SNAP / f"{ds}.qc.json"
        shutil.copy2(src, dst)
        n = len(json.loads(src.read_text()).get("runs", []))
        print(f"  topup reference snapshot: {ds} ({n} runs)")


def set_prefer_mode(mode):
    if not BACKUP.exists():
        shutil.copy2(POLICY, BACKUP)
    lines = POLICY.read_text().splitlines(keepends=True)
    out, done = [], False
    for ln in lines:
        s = ln.lstrip()
        if s.startswith("prefer_mode:") and not done:
            ind = ln[: len(ln) - len(s)]
            out.append(f'{ind}prefer_mode: "{mode}"  # C4 transient, restored after\n')
            done = True
        else:
            out.append(ln)
    assert done
    POLICY.write_text("".join(out))


def restore_policy():
    if BACKUP.exists():
        shutil.copy2(BACKUP, POLICY)


def run_syn(only=None):
    env = dict(os.environ, PYTHONPATH=str(REPO / "src"))
    for ds in DATASETS:
        if only and ds != only:
            continue
        print(f"\n=== S5 SyN (isolated) {ds} ===", flush=True)
        subprocess.run([sys.executable, "-m", "spineprep.cli", "run",
                        "S5_func_distortion_correction", "--dataset-key", ds,
                        "--out", str(C4), "--datasets-local",
                        "config/datasets_local.yaml", "--batch-workers", "8"],
                       cwd=REPO, env=env)


def analyze():
    import math
    rows = []
    for ds in DATASETS:
        ref = json.loads((SNAP / f"{ds}.qc.json").read_text())
        syn = json.loads((C4 / "logs" / "S5_func_distortion_correction" / ds / "qc.json").read_text())
        syn_by = {r.get("run_id"): r for r in syn.get("runs", [])}
        for rt in ref.get("runs", []):
            if rt.get("mode") != "topup":
                continue
            rid = rt.get("run_id"); rs = syn_by.get(rid)
            if not rs:
                continue
            mt, ms = rt.get("metrics") or {}, rs.get("metrics") or {}
            zt, zs = mt.get("per_slice_z"), ms.get("per_slice_z")
            dt, dsy, db = (mt.get("displacement_after_mm"),
                           ms.get("displacement_after_mm"),
                           mt.get("displacement_before_mm"))
            if not all(isinstance(x, list) for x in (zt, zs, dt, dsy, db)):
                continue
            tp = dict(zip(zt, dt)); bp = dict(zip(zt, db)); sp = dict(zip(zs, dsy))
            zc = [z for z in zt if z in sp and z in bp
                  and all(v is not None and math.isfinite(v) for v in (tp[z], bp[z], sp[z]))]
            if not zc:
                continue
            resid = st.mean(abs(sp[z] - tp[z]) for z in zc)
            base = st.mean(abs(bp[z] - tp[z]) for z in zc)
            gap = 1 - resid / base if base > 1e-6 else None
            worse = st.mean(1.0 if abs(sp[z]) > abs(bp[z]) else 0.0 for z in zc)
            rows.append({"dataset": ds, "run_id": rid, "n_slices": len(zc),
                         "resid_mm": round(resid, 4), "baseline_mm": round(base, 4),
                         "gap_closed": None if gap is None else round(gap, 4),
                         "syn_worsened_frac": round(worse, 4)})
    outp = REPO / "analysis" / "results" / "distortion.csv"
    if rows:
        import csv
        keys = ["dataset", "run_id", "n_slices", "resid_mm", "baseline_mm",
                "gap_closed", "syn_worsened_frac"]
        with open(outp, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=keys)
            w.writeheader(); w.writerows(rows)
    gaps = [r["gap_closed"] for r in rows if r["gap_closed"] is not None]
    print(f"\nC4 result: {len(rows)} paired runs")
    if gaps:
        print(f"  median gap_closed = {st.median(gaps):+.3f} "
              f"(1=SyN matches measured field, 0=no better than nothing, <0=worse)")
        print(f"  runs where SyN moved cord AWAY (gap<0): "
              f"{sum(1 for g in gaps if g < 0)}/{len(gaps)}")
        print(f"  median syn_worsened_frac (slices pushed past uncorrected): "
              f"{st.median([r['syn_worsened_frac'] for r in rows]):.3f}")
    print(f"  -> {outp}")
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    only = sys.argv[2] if len(sys.argv) > 2 else None
    if cmd in ("snapshot", "all"):
        snapshot_topup()
    if cmd in ("run", "all"):
        try:
            set_prefer_mode("syn")
            run_syn(only=only)
        finally:
            restore_policy()
    if cmd in ("analyze", "all"):
        analyze()
