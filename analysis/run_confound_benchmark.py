#!/usr/bin/env python3
"""C5 confound benchmark at full scale, standalone.

run_all caps the benchmark at a few runs per dataset because it refits ~7 designs
per run. This runs it over EVERY task run and writes only confound_benchmark.csv,
leaving the other (already valid) result tables untouched. Reads the locked
cohort read-only; writes nothing into it.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Optional

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from analysis import driver, confound_benchmark
from analysis.glm_spec import conditions_for

RESULTS = Path(__file__).resolve().parent / "results"


def _roots() -> dict:
    cfg = yaml.safe_load(Path("config/datasets_local.yaml").read_text()) or {}
    raw = cfg.get("datasets", cfg)
    out = {}
    for k, v in raw.items():
        p = Path(v.get("path") or v.get("bids_root")) if isinstance(v, dict) else Path(v)
        out[k] = p if p.is_absolute() else Path("/mnt/ssd1/SpinePrep") / p
    return out


def _events_and_start(run, roots):
    root = roots.get(run["dataset"])
    rows = None
    if root is not None:
        ev = next(iter(Path(root).rglob(f"{run['run_id']}_events.tsv")), None)
        if ev is not None:
            with open(ev) as fh:
                rows = list(csv.DictReader(fh, delimiter="\t"))
    start = 0.0
    sc = Path(str(run["bold"]).replace(".nii.gz", ".json"))
    if sc.exists():
        try:
            start = float(json.loads(sc.read_text()).get("StartTime") or 0.0)
        except Exception:
            start = 0.0
    return rows, start


def main() -> int:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/mnt/ssd1/spineprep_cohort_s2")
    roots = _roots()
    import nibabel as nib
    import numpy as np

    rows = []
    done = 0
    skipped_rest = 0
    for run in driver.iter_runs(out_dir):
        # task runs only: a run with no modelled condition is rest
        if not conditions_for(run["dataset"], run["run_id"]):
            skipped_rest += 1
            continue
        ev, start = _events_and_start(run, roots)
        if ev is None:
            continue
        cordp = run["cord"]
        if not Path(cordp).exists():
            continue
        cord = nib.load(str(cordp)).get_fdata() > 0.5
        try:
            r = confound_benchmark.benchmark_run(
                run["bold"], ev, run["confounds"], cord,
                run["dataset"], run["run_id"], start)
        except Exception as e:
            print(f"  SKIP {run['run_id']}: {type(e).__name__}: {str(e)[:80]}", flush=True)
            continue
        rows += r
        done += 1
        if done % 20 == 0:
            print(f"  benchmarked {done} task runs ({len(rows)} rows)", flush=True)

    RESULTS.mkdir(parents=True, exist_ok=True)
    outp = RESULTS / "confound_benchmark_full.csv"
    if rows:
        keys = sorted({k for r in rows for k in r})
        with open(outp, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=keys)
            w.writeheader()
            for r in rows:
                w.writerow(r)
    print(f"\nDONE: benchmarked {done} task runs, {len(rows)} rows, "
          f"{skipped_rest} rest runs skipped -> {outp}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
