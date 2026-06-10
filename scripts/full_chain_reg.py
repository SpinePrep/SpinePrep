#!/usr/bin/env python3
"""Full chain reg runner: S2 -> S3 -> S4 -> S5 -> S6 -> S7 -> S8 -> S9 -> S10 -> S11 on all reg datasets.

For each step:
  1. Allocate a fresh wf_reg_NNN.
  2. Link logs/ from all prior chain steps; link work/ and derivatives/
     from the appropriate predecessor (S1's work tree, prior step's
     derivatives).
  3. Run the step on every reg dataset key (from policy/datasets.yaml).
  4. Call scripts/mark_done.py with --force (chain promotes regardless
     of FAIL on individual datasets; we want the chain to advance for
     iteration purposes).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from spinalfmriprep.workfolder import get_next_workfolder

PROJECT_ROOT = Path(__file__).resolve().parents[1]
POLICY = PROJECT_ROOT / "policy" / "datasets.yaml"
LOCAL_MAP = PROJECT_ROOT / "config" / "datasets_local.yaml"

ALL_CHAIN_STEPS = [
    ("S2", "S2_anat_cordref"),
    ("S3", "S3_func_init_and_crop"),
    ("S4", "S4_func_motion_correction"),
    ("S5", "S5_func_distortion_correction"),
    ("S6", "S6_func_to_anat_registration"),
    ("S7", "S7_template_normalization"),
    ("S8", "S8_confounds_and_physio_regressors"),
    ("S9", "S9_primary_functional_derivatives"),
    # S10_roi_timeseries_and_connectivity removed from the active pipeline
    # 2026-06-11 — connectivity/ICC is downstream analysis (analyst-owned),
    # not preprocessing. Chain now runs S9 -> S11 directly. The S10 step code
    # is retained (deferred, not deleted); see the S10 spec.
    ("S11", "S11_qc_aggregation_and_release"),
]


def chain_steps_from(start: str) -> list[tuple[str, str]]:
    codes = [c for c, _ in ALL_CHAIN_STEPS]
    if start not in codes:
        return ALL_CHAIN_STEPS
    i = codes.index(start)
    return ALL_CHAIN_STEPS[i:]


def reg_keys() -> list[str]:
    p = yaml.safe_load(POLICY.read_text())
    return [d["key"] for d in p.get("datasets", [])
            if "regression" in d.get("intended_use", [])]


def link_chain(wf: Path, predecessors: list[str], current_code: str) -> None:
    """Set up chain inputs for the current step.

    Conventions:
      - logs/<step>/ : link in each predecessor's per-step logs.
      - work/        : link S1's inventory tree.
      - derivatives/ : link from the immediate predecessor (read+write).
      - runs/        : ONLY when the current step is S4+ (S4 reads
        S3's runs/). For S3 itself, do NOT link — S3 creates its own
        runs/. For S2, runs/ does not exist conceptually.

    Why this matters: S3's _extract_subject_session_from_work_dir uses
    work_dir.resolve(), which follows symlinks. If we link runs/ from an
    upstream chain that itself has runs/ as a symlink (stale from a
    previous chain), out_root resolves into the wrong workfolder and
    later relative_to(out_root) fails with "is not in the subpath of".
    """
    (wf / "logs").mkdir(parents=True, exist_ok=True)
    for code in predecessors:
        src_logs = (PROJECT_ROOT / "work" / "done" / "reg" / code).resolve() / "logs"
        if not src_logs.exists():
            continue
        for item in src_logs.iterdir():
            t = wf / "logs" / item.name
            if not t.exists() and not t.is_symlink():
                t.symlink_to(item)
    # S1 holds the inventory/work tree
    s1 = (PROJECT_ROOT / "work" / "done" / "reg" / "S1").resolve()
    if s1.exists() and not (wf / "work").exists():
        (wf / "work").symlink_to(s1 / "work")
    # Immediate predecessor provides derivatives.
    if predecessors:
        last = predecessors[-1]
        last_root = (PROJECT_ROOT / "work" / "done" / "reg" / last).resolve()
        deriv = last_root / "derivatives"
        if deriv.exists() and not (wf / "derivatives").exists():
            (wf / "derivatives").symlink_to(deriv)
    # runs/ is S3-specific. Only link for downstream consumers (S4+).
    if current_code in ("S4", "S5", "S6", "S7", "S8", "S9", "S11"):
        s3 = (PROJECT_ROOT / "work" / "done" / "reg" / "S3").resolve()
        s3_runs = s3 / "runs"
        if s3_runs.exists() and not (wf / "runs").exists():
            (wf / "runs").symlink_to(s3_runs)


def run_step(step_full: str, wf: Path, keys: list[str]) -> dict:
    """Run a step on each key sequentially. Returns {key: status}."""
    results = {}
    for k in keys:
        print(f"\n--- {step_full} :: {k} ---")
        cmd = ["poetry", "run", "spinalfmriprep", "run", step_full,
               "--dataset-key", k,
               "--datasets-local", str(LOCAL_MAP),
               "--out", str(wf)]
        r = subprocess.run(cmd, cwd=PROJECT_ROOT)
        results[k] = "OK" if r.returncode == 0 else "FAIL"
    return results


def mark_done(code: str, wf: Path) -> None:
    subprocess.run(
        ["python", "scripts/mark_done.py", "reg", code, str(wf), "--force"],
        cwd=PROJECT_ROOT, check=False,
    )


def main() -> int:
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="S2", help="First step to run (S2..S11)")
    args = p.parse_args()
    keys = reg_keys()
    print(f"Reg datasets: {len(keys)}")
    for k in keys:
        print(f"  {k}")

    work_root = PROJECT_ROOT / "work"
    all_codes = [c for c, _ in ALL_CHAIN_STEPS]
    start_idx = all_codes.index(args.start) if args.start in all_codes else 0
    completed_codes: list[str] = ["S1"] + all_codes[:start_idx]
    steps_to_run = ALL_CHAIN_STEPS[start_idx:]
    for code, full in steps_to_run:
        wf = get_next_workfolder("reg", work_root)
        wf.mkdir(parents=True)
        print(f"\n===== {full} :: {wf.name} =====")
        link_chain(wf, completed_codes, current_code=code)
        results = run_step(full, wf, keys)
        passed = [k for k, v in results.items() if v == "OK"]
        failed = [k for k, v in results.items() if v != "OK"]
        print(f"  PASS={len(passed)}  FAIL={len(failed)}")
        if failed:
            print(f"  failed: {failed}")
        mark_done(code, wf)
        completed_codes.append(code)
    print("\n=== full chain complete ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
