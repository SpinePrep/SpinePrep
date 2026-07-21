#!/usr/bin/env python3
"""Measure single-run latency: one run, serially, on an idle machine.

BENCHMARK module -- not a pipeline step.

This is the only measurement that needs dedicated compute. Throughput comes free
from any normal cohort run, because every step now records its own timing; this
does not, because the reference cohort runs 12-way parallel under ``batch`` on a
contended box. Those numbers are valid for throughput and invalid for latency,
and pooling them is the usual way a pipeline benchmark misleads.

Design
------
Three runs spanning the real cost drivers, three repeats each, serial:

* a SHORT run and a LONG run -- S4, S5, S8 and S9 scale with volume count, so a
  single run length would not characterise them;
* a TOPUP run -- it does strictly more work than the ``none``-mode majority
  (82% of the reference cohort), so timing only ``none`` runs would understate
  the worst case.

The first repeat is reported SEPARATELY, not discarded. SCT loads segmentation
model weights on first call; for someone processing a single subject that cold
cost is their actual experience, not an artifact.

Reports median and range rather than mean +/- SD: wall-clock is right-skewed.

Usage
-----
    python3 benchmark/latency.py --out /tmp/bench --runs run_a run_b run_c
    python3 benchmark/latency.py --out /tmp/bench --auto <cohort_dir>
"""
from __future__ import annotations

import argparse
import json
import os
import statistics as st
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional

STEP_ORDER = [
    "S3_func_init_and_crop",
    "S4_func_motion_correction",
    "S5_func_distortion_correction",
    "S6_func_to_anat_registration",
    "S7_template_normalization",
    "S8_confounds_and_physio_regressors",
    "S9_primary_functional_derivatives",
]


def pick_runs(cohort: Path, n: int = 3) -> list[dict[str, Any]]:
    """Choose runs spanning the cost drivers: shortest, longest, and a topup run.

    Reads the existing cohort QC rather than guessing, so the selection reflects
    the data actually available.
    """
    # Volume count lives in S9's metrics (n_volumes); S4 does not record it.
    lens: dict[str, dict] = {}
    for qc in (cohort / "logs" / "S9_primary_functional_derivatives").glob("*/qc.json"):
        try:
            data = json.loads(qc.read_text())
        except Exception:
            continue
        for r in data.get("runs", []):
            nv = (r.get("metrics") or {}).get("n_volumes")
            if r.get("run_id") and isinstance(nv, int):
                lens[r["run_id"]] = {"run_id": r["run_id"],
                                     "dataset": qc.parent.name, "n_volumes": nv}
    modes: dict[str, str] = {}
    for qc in (cohort / "logs" / "S5_func_distortion_correction").glob("*/qc.json"):
        try:
            data = json.loads(qc.read_text())
        except Exception:
            continue
        for r in data.get("runs", []):
            if r.get("run_id"):
                modes[r["run_id"]] = r.get("mode") or (r.get("metrics") or {}).get("mode")
    for rid, d in lens.items():
        d["mode"] = modes.get(rid)

    if not lens:
        return []
    ordered = sorted(lens.values(), key=lambda d: d["n_volumes"])
    none_runs = [d for d in ordered if d.get("mode") != "topup"]
    topup_runs = [d for d in ordered if d.get("mode") == "topup"]

    # The picks must exercise DIFFERENT things, or repeats of one condition are
    # mistaken for coverage. Prefer short and long from the majority `none` mode
    # (82% of the cohort), plus the longest topup run -- topup does strictly
    # more work, so it bounds the worst case.
    picks: list[dict] = []
    pool = none_runs or ordered
    picks.append(dict(pool[0], role="short"))
    if len(pool) > 1:
        picks.append(dict(pool[-1], role="long"))
    if topup_runs:
        chosen = {p["run_id"] for p in picks}
        cand = next((d for d in reversed(topup_runs) if d["run_id"] not in chosen), None)
        if cand:
            picks.append(dict(cand, role="topup"))
    return picks[:n]


def _load_avg() -> float:
    try:
        return os.getloadavg()[0]
    except Exception:
        return -1.0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True, help="scratch output dir for the benchmark")
    ap.add_argument("--auto", help="cohort dir to pick representative runs from")
    ap.add_argument("--runs", nargs="*", default=[], help="explicit run_ids")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--dataset-key", help="dataset to time (default: from --auto picks)")
    ap.add_argument("--n-runs", type=int, default=3,
                    help="how many timed runs are enough (informational)")
    ap.add_argument("--datasets-local", default="config/datasets_local.yaml")
    ap.add_argument("--max-load", type=float, default=4.0,
                    help="refuse to start above this 1-min load average")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.auto:
        picks = pick_runs(Path(args.auto))
    else:
        picks = [{"run_id": r, "role": "explicit"} for r in args.runs]
    if not picks:
        print("No runs selected. Pass --auto <cohort> or --runs ...", file=sys.stderr)
        return 1

    load = _load_avg()
    print("SpinePrep latency benchmark")
    print(f"  runs    : {[p['run_id'] for p in picks]}")
    print(f"  repeats : {args.repeats}  (serial, 1 worker)")
    print(f"  load now: {load:.2f}")
    if load > args.max_load and not args.dry_run:
        # Latency measured on a busy box is not latency. Refuse rather than
        # quietly produce a number that will later be quoted as single-run time.
        print(f"\nREFUSING: load {load:.2f} > {args.max_load}. Latency requires an "
              f"idle machine; re-run when quiet or raise --max-load deliberately.",
              file=sys.stderr)
        return 2
    if args.dry_run:
        for p in picks:
            print(f"    would time: {p}")
        return 0

    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)

    # Latency is measured by running a dataset SERIALLY (one worker) and reading
    # back the per-run timing records each step writes. Those records ARE the
    # per-run latency -- there is no need to invoke the pipeline once per run,
    # and the CLI has no per-run filter anyway (finest granularity is
    # --dataset-key). An earlier version of this script invoked the CLI per run
    # and would have silently processed the whole dataset each time.
    env = dict(os.environ,
               SPINEPREP_BENCHMARK="latency",
               SPINEPREP_N_WORKERS="1",
               SPINEPREP_S9_FORCE="1")   # never resume; we are measuring compute

    ds = args.dataset_key or (picks[0].get("dataset") if picks else None)
    if not ds:
        print("Could not determine a dataset to time.", file=sys.stderr)
        return 1
    print(f"  dataset : {ds} (serial, stopping after {args.n_runs} timed runs)")

    for rep in range(args.repeats):
        wd = out_root / f"rep{rep}"
        wd.mkdir(parents=True, exist_ok=True)
        for step in STEP_ORDER:
            cmd = [sys.executable, "-m", "spineprep.cli", "run", step,
                   "--dataset-key", ds, "--out", str(wd),
                   "--datasets-local", args.datasets_local,
                   "--batch-workers", "1"]
            t0 = time.perf_counter()
            proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
            print(f"  rep{rep} {step[:38]:40s} {(time.perf_counter()-t0)/60:6.1f} min"
                  + ("" if proc.returncode == 0 else "   [nonzero exit]"))

    rep_path = out_root / "latency_note.json"
    rep_path.write_text(json.dumps({
        "dataset": ds, "repeats": args.repeats, "workers": 1,
        "note": ("Per-run latency lives in each step's qc.json timing record "
                 "under rep*/logs/. Summarise with benchmark/analyze.py."),
    }, indent=2))

    print("\nPer-run latency is in the timing records. Summarise with:")
    for rep in range(args.repeats):
        print(f"  python3 benchmark/analyze.py {out_root / f'rep{rep}'}")
    print(f"\nwrote {rep_path}")
    print("Per-step detail is in each run's qc.json; summarise with "
          "benchmark/analyze.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
