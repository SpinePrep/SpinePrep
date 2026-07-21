#!/usr/bin/env python3
"""Master orchestrator: run every analysis endpoint over the cohort.

ANALYSIS driver -- not part of the preprocessing toolbox.

Ties the five analysis layers into one pass and writes tidy result tables:

  driver.run_endpoints        quality + reliability, per run, all tiers
  glm.fit_run + effects       effect family, per run, aggregated to tiers
  driver.group_endpoints      ICC / split-half aggregated across subjects
  effects.group_effects       Cohen's d + detectability across subjects
  biological_validity         C3: laterality + dorsal/ventral dissociation
  confound_benchmark          C5: confound-family importance (task-run subset)
  distortion.compare_cohort   C4: SyN falsification (only if a SyN-mode qc exists)

Outputs, under analysis/results/:
  endpoints_long.csv     every per-run endpoint (quality, reliability, effect)
  group_reliability.csv  ICC / split-half group rows
  group_effects.csv      Cohen's d + detectability
  biological.csv         C3 validation table
  confound_benchmark.csv C5 grid (subset of runs)
  distortion.csv         C4 falsification table (if the SyN run is present)
  MANIFEST.json          what ran, counts, and what was skipped and why

Numbers are provisional until the crop-fix cohort lands; the module reads
whatever OUT_DIR it is pointed at, so re-running on the corrected derivatives is
the same command with a different path.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Optional

import yaml

from analysis import driver, effects, biological_validity, confound_benchmark
from analysis import distortion as dist
from analysis.glm import fit_run
from analysis.glm_spec import repetition_time_s

RESULTS = Path(__file__).resolve().parent / "results"


def _dataset_roots() -> dict[str, Path]:
    cfg = yaml.safe_load(Path("config/datasets_local.yaml").read_text()) or {}
    raw = cfg.get("datasets", cfg)
    roots = {}
    for k, v in raw.items():
        p = Path(v.get("path") or v.get("bids_root")) if isinstance(v, dict) else Path(v)
        roots[k] = p if p.is_absolute() else Path("/mnt/ssd1/SpinePrep") / p
    return roots


def _events_and_start(run: dict, roots: dict) -> tuple[Optional[list], float]:
    """Resolve the events rows and the BOLD StartTime for a run."""
    root = roots.get(run["dataset"])
    rows = None
    if root is not None:
        ev = next(iter(Path(root).rglob(f"{run['run_id']}_events.tsv")), None)
        if ev is not None:
            with open(ev) as fh:
                rows = list(csv.DictReader(fh, delimiter="\t"))
    start = 0.0
    sidecar = Path(str(run["bold"]).replace(".nii.gz", ".json"))
    if sidecar.exists():
        try:
            start = float(json.loads(sidecar.read_text()).get("StartTime") or 0.0)
        except Exception:
            start = 0.0
    return rows, start


def _write_csv(path: Path, rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
        return
    keys = sorted({k for r in rows for k in r})
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def run(out_dir: Path, limit: Optional[int] = None,
        benchmark_per_dataset: int = 4) -> dict:
    roots = _dataset_roots()
    endpoint_rows: list[dict] = []      # quality + reliability + effect, per run
    effect_rows: list[dict] = []        # the effect subset, for group + biological
    bench_rows: list[dict] = []
    manifest = {"out_dir": str(out_dir), "runs": 0, "glm_fit": 0,
                "glm_skipped_no_task": 0, "benchmarked": 0, "skipped": []}
    bench_count: dict[str, int] = {}

    for i, run_rec in enumerate(driver.iter_runs(out_dir)):
        if limit is not None and i >= limit:
            break
        manifest["runs"] += 1
        # quality + reliability (driver handles its own tier bookkeeping)
        driver.run_endpoints(run_rec, endpoint_rows)

        # effect family via the GLM
        parcels, _ = driver.build_parcels(run_rec)
        if "cord" not in parcels:
            continue
        ev, start = _events_and_start(run_rec, roots)
        if ev is None:
            continue
        glm = fit_run(run_rec["bold"], ev, run_rec["confounds"],
                      parcels["cord"]["cord"], run_rec["dataset"],
                      run_rec["run_id"], start)
        if glm is None:
            manifest["glm_skipped_no_task"] += 1
            continue
        manifest["glm_fit"] += 1
        effects.run_effects(glm, parcels, effect_rows,
                            dataset=run_rec["dataset"], subject=run_rec["subject"],
                            session=run_rec["session"], run_id=run_rec["run_id"])

        # confound benchmark on a per-dataset subset (it refits ~7 designs/run)
        c = bench_count.get(run_rec["dataset"], 0)
        if c < benchmark_per_dataset:
            bench_rows += confound_benchmark.benchmark_run(
                run_rec["bold"], ev, run_rec["confounds"],
                parcels["cord"]["cord"], run_rec["dataset"],
                run_rec["run_id"], start)
            bench_count[run_rec["dataset"]] = c + 1
            manifest["benchmarked"] += 1

    endpoint_rows += effect_rows
    manifest["effect_rows"] = len(effect_rows)

    # group aggregations
    group_rel = driver.group_endpoints(endpoint_rows)
    group_eff = effects.group_effects(effect_rows)
    bio = biological_validity.biological_validity(effect_rows)

    # the grey-matter horn tier (and the dorsal/ventral C3 test + tier-4
    # reliability) needs S7's 4D PAM50atlas_probseg. Record its presence so an
    # empty dorsal/ventral table reads as "input absent", not "no effect".
    has_gmhorn = any(r.get("tier") == "gmhorn" for r in effect_rows)
    manifest["gmhorn_tier_present"] = has_gmhorn
    if not has_gmhorn:
        manifest["skipped"].append(
            "gmhorn tier absent cohort-wide (S7 did not emit PAM50atlas_probseg); "
            "dorsal/ventral C3 test and tier-4 reliability gated on the re-run")

    # distortion: only if a SyN-mode qc exists next to the topup one
    dist_rows: list[dict] = []
    for ds in dist.REVERSED_PE_DATASETS:
        topup = Path(out_dir) / "logs" / "S5_func_distortion_correction" / ds / "qc.json"
        syn = topup.parent / "qc_syn.json"
        if topup.exists() and syn.exists():
            dist_rows += dist.compare_cohort(topup, syn, ds)
        elif topup.exists():
            manifest["skipped"].append(
                f"distortion {ds}: no SyN-mode qc (qc_syn.json); dual run pending")

    _write_csv(RESULTS / "endpoints_long.csv", endpoint_rows)
    _write_csv(RESULTS / "group_reliability.csv", group_rel)
    _write_csv(RESULTS / "group_effects.csv", group_eff)
    _write_csv(RESULTS / "biological.csv", bio)
    _write_csv(RESULTS / "confound_benchmark.csv", bench_rows)
    _write_csv(RESULTS / "distortion.csv", dist_rows)
    if dist_rows:
        manifest["distortion_summary"] = {
            ds: dist.summarise([r for r in dist_rows if r["dataset"] == ds])
            for ds in dist.REVERSED_PE_DATASETS}
    (RESULTS / "MANIFEST.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir", type=Path, help="cohort OUT_DIR (S9 derivatives)")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--benchmark-per-dataset", type=int, default=4)
    a = ap.parse_args()
    m = run(a.out_dir, a.limit, a.benchmark_per_dataset)
    print(json.dumps(m, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
