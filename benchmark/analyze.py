#!/usr/bin/env python3
"""Summarise SpinePrep runtime from the timing records in each step's qc.json.

BENCHMARK module -- not a pipeline step. Read-only consumer of
``logs/<step>/<dataset>/qc.json``, mirroring the ``validation/`` layout.

Two numbers, deliberately kept apart
------------------------------------
LATENCY is one run start-to-finish on an idle machine: what a user processing a
single subject waits. It is the only figure comparable across papers.

THROUGHPUT is runs per hour at N workers on a saturated machine: what a lab
planning a 40-subject study needs.

They differ by roughly the worker count. Quoting one when the reader wants the
other is the most common way pipeline benchmarks mislead, so this script refuses
to pool them: records are partitioned on ``n_workers`` and reported separately.

What is excluded, and why
-------------------------
* Resumed runs -- served from cache in milliseconds; averaging them in would
  deflate every summary.
* FAILed runs -- a run that died in its first minute is not a measurement of how
  long the step takes.
Both exclusions are counted and reported, never silent.

Usage
-----
    python3 benchmark/analyze.py <out_dir> [--json report.json]
"""
from __future__ import annotations

import argparse
import json
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

STEPS = [
    ("S2", "S2_anat_cordref"),
    ("S3", "S3_func_init_and_crop"),
    ("S4", "S4_func_motion_correction"),
    ("S5", "S5_func_distortion_correction"),
    ("S6", "S6_func_to_anat_registration"),
    ("S7", "S7_template_normalization"),
    ("S8", "S8_confounds_and_physio_regressors"),
    ("S9", "S9_primary_functional_derivatives"),
]

# Steps whose cost grows with the number of volumes. The rest operate on a 3D
# reference and are roughly flat in run length, so a single "seconds per volume"
# normaliser across all steps would be wrong.
VOLUME_SCALING = {"S4", "S5", "S8", "S9"}


def collect(out_dir: Path) -> tuple[list[dict], dict[str, int]]:
    """Flatten every run's timing record. Returns (records, exclusion counts)."""
    rows: list[dict] = []
    excl: dict[str, int] = defaultdict(int)
    for short, full in STEPS:
        for qc in sorted((out_dir / "logs" / full).glob("*/qc.json")):
            try:
                data = json.loads(qc.read_text())
            except Exception:
                excl["unreadable_qc"] += 1
                continue
            for run in data.get("runs", []):
                t = run.get("timing")
                if not isinstance(t, dict) or t.get("wall_s") is None:
                    excl["no_timing_record"] += 1
                    continue
                if t.get("resumed"):
                    excl["resumed"] += 1
                    continue
                if run.get("status") == "FAIL":
                    excl["failed_run"] += 1
                    continue
                rows.append({
                    "step": short,
                    "dataset": qc.parent.name,
                    "run_id": run.get("run_id"),
                    "status": run.get("status"),
                    "n_volumes": (run.get("metrics") or {}).get("n_volumes"),
                    **{k: t.get(k) for k in
                       ("wall_s", "tool_s", "overhead_s", "n_tool_calls",
                        "n_workers", "gpu_slots", "load_avg_start",
                        "benchmark_mode", "concurrent_tool_calls")},
                })
    return rows, dict(excl)


def _summ(vals: list[float]) -> dict[str, Any]:
    """Median and range, not mean +/- SD: wall-clock is right-skewed and SD
    implies a symmetry the distribution does not have."""
    v = sorted(x for x in vals if isinstance(x, (int, float)))
    if not v:
        return {"n": 0}
    return {
        "n": len(v),
        "median_s": round(st.median(v), 1),
        "min_s": round(v[0], 1),
        "max_s": round(v[-1], 1),
        "p90_s": round(v[min(len(v) - 1, int(0.9 * len(v)))], 1),
        "total_s": round(sum(v), 1),
    }


def report(rows: list[dict], excl: dict[str, int]) -> dict[str, Any]:
    out: dict[str, Any] = {"excluded": excl}
    if not rows:
        return out

    # Partition on worker count -- the latency/throughput divide.
    by_workers: dict[Any, list[dict]] = defaultdict(list)
    for r in rows:
        by_workers[r.get("n_workers") or 1].append(r)

    out["conditions"] = {}
    for w, rs in sorted(by_workers.items(), key=lambda kv: (kv[0] is None, kv[0])):
        loads = [r["load_avg_start"] for r in rs
                 if isinstance(r.get("load_avg_start"), (int, float))]
        cond: dict[str, Any] = {
            "n_workers": w,
            "kind": "latency (serial)" if w == 1 else f"throughput ({w} workers)",
            "n_records": len(rs),
            "median_load_avg": round(st.median(loads), 1) if loads else None,
            "per_step": {},
        }
        per_run_wall: dict[str, float] = defaultdict(float)
        for short, _ in STEPS:
            sub = [r for r in rs if r["step"] == short]
            if not sub:
                continue
            s = _summ([r["wall_s"] for r in sub])
            s["tool"] = _summ([r["tool_s"] for r in sub])
            ov = [r["overhead_s"] for r in sub if r.get("overhead_s") is not None]
            s["overhead"] = _summ(ov)
            s["n_concurrent_tool_runs"] = sum(
                1 for r in sub if r.get("concurrent_tool_calls"))
            s["scales_with_volumes"] = short in VOLUME_SCALING
            cond["per_step"][short] = s
            for r in sub:
                per_run_wall[f"{r['dataset']}/{r['run_id']}"] += r["wall_s"] or 0.0

        if per_run_wall:
            cond["per_run_total"] = _summ(list(per_run_wall.values()))
            cond["n_complete_runs"] = len(per_run_wall)
        # Wall-clock share per step: where the time actually goes.
        tot = sum(v["total_s"] for v in cond["per_step"].values())
        if tot:
            cond["share_pct"] = {
                k: round(100.0 * v["total_s"] / tot, 1)
                for k, v in sorted(cond["per_step"].items(),
                                   key=lambda kv: -kv[1]["total_s"])
            }
        out["conditions"][str(w)] = cond

    # Per-dataset, never pooled: heterogeneity is the signal here as much as it
    # is for quality (design invariant 8).
    by_ds: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_ds[r["dataset"]].append(r)
    out["per_dataset"] = {
        ds: {"n_records": len(rs), **_summ([r["wall_s"] for r in rs])}
        for ds, rs in sorted(by_ds.items())
    }
    return out


def render(rep: dict[str, Any]) -> str:
    L: list[str] = []
    A = L.append
    A("SpinePrep runtime")
    A("=" * 66)
    ex = rep.get("excluded") or {}
    if ex:
        A("excluded: " + ", ".join(f"{v} {k}" for k, v in sorted(ex.items())))
    if not rep.get("conditions"):
        A("")
        A("No timing records found.")
        A("Timing was added 2026-07-21; runs processed before that carry none.")
        return "\n".join(L)

    for _, c in sorted(rep["conditions"].items(), key=lambda kv: int(kv[0])):
        A("")
        A(f"{c['kind']}   ({c['n_records']} step-records"
          + (f", median load {c['median_load_avg']}" if c["median_load_avg"] else "")
          + ")")
        A("-" * 66)
        A(f"  {'step':6s} {'n':>4s} {'median':>9s} {'p90':>9s} {'max':>9s} "
          f"{'tool%':>6s} {'share':>6s}")
        share = c.get("share_pct", {})
        for step, s in c["per_step"].items():
            if not s.get("n"):
                continue
            toolpct = ""
            if s["tool"].get("median_s") and s.get("median_s"):
                toolpct = f"{100.0 * s['tool']['median_s'] / s['median_s']:.0f}%"
            flag = " *" if s.get("scales_with_volumes") else ""
            A(f"  {step:6s} {s['n']:4d} {s['median_s']:8.1f}s {s['p90_s']:8.1f}s "
              f"{s['max_s']:8.1f}s {toolpct:>6s} {share.get(step, 0):5.1f}%{flag}")
        if c.get("per_run_total"):
            t = c["per_run_total"]
            A(f"  {'-'*62}")
            A(f"  per run, all steps: median {t['median_s']/60:.1f} min "
              f"(range {t['min_s']/60:.1f}-{t['max_s']/60:.1f}), "
              f"n={c.get('n_complete_runs')}")
    A("")
    A("  * cost scales with number of volumes; unmarked steps work on a 3D")
    A("    reference and are roughly flat in run length.")
    A("  tool% = share of wall-clock inside SCT/FSL/ANTs. The remainder is")
    A("    SpinePrep's own overhead.")

    if rep.get("per_dataset"):
        A("")
        A("per dataset (not pooled -- acquisition differences are the point)")
        A("-" * 66)
        for ds, s in rep["per_dataset"].items():
            if s.get("n"):
                A(f"  {ds[:44]:46s} n={s['n']:4d}  median {s['median_s']:7.1f}s")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("out_dir", help="pipeline output directory")
    ap.add_argument("--json", help="also write the full report as JSON")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    if not (out_dir / "logs").exists():
        print(f"No logs/ under {out_dir}", file=sys.stderr)
        return 1
    rows, excl = collect(out_dir)
    rep = report(rows, excl)
    print(render(rep))
    if args.json:
        Path(args.json).write_text(json.dumps(rep, indent=2))
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
