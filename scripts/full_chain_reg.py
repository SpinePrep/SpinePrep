#!/usr/bin/env python3
"""Full chain runner: S1 -> S2 -> ... -> S9 -> S11 on a set of dataset keys.

Defaults reproduce the original regression behaviour exactly:
  --scope reg, --datasets = every key with intended_use: regression, --start S2
  (the reg cohort's S1 is already promoted at work/done/reg/S1).

To run an arbitrary cohort (e.g. the balgrist experiment) in its OWN scope,
isolated from the locked reg chain:
  full_chain_reg.py --scope exp --start S1 \
      --datasets internal_balgrist_motor_11 internal_balgrist_painmotor_21

For each step:
  1. Allocate a fresh wf_<scope>_NNN.
  2. Link logs/ from prior chain steps; link work/ (the S1 inventory tree) and
     derivatives/ from the appropriate predecessor.
  3. Run the step on every dataset key.
  4. mark_done --force so the chain advances regardless of per-dataset FAILs.
"""

from __future__ import annotations

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
    ("S1", "S1_input_verify"),
    ("S2", "S2_anat_cordref"),
    ("S3", "S3_func_init_and_crop"),
    ("S4", "S4_func_motion_correction"),
    ("S5", "S5_func_distortion_correction"),
    ("S6", "S6_func_to_anat_registration"),
    ("S7", "S7_template_normalization"),
    ("S8", "S8_confounds_and_physio_regressors"),
    ("S9", "S9_primary_functional_derivatives"),
    # S10 removed from the active pipeline 2026-06-11 (analyst-owned analysis).
    ("S11", "S11_qc_aggregation_and_release"),
]


def reg_keys() -> list[str]:
    p = yaml.safe_load(POLICY.read_text())
    return [d["key"] for d in p.get("datasets", [])
            if "regression" in d.get("intended_use", [])]


def link_chain(wf: Path, scope: str, predecessors: list[str], current_code: str) -> None:
    """Set up chain inputs for the current step within ``scope``.

      - logs/<step>/ : link in each predecessor's per-step logs.
      - work/        : link the S1 inventory tree (skipped for S1 itself).
      - derivatives/ : link from the immediate predecessor (read+write).
      - runs/        : only for S4+ (they read S3's runs/).
    """
    done = PROJECT_ROOT / "work" / "done" / scope
    (wf / "logs").mkdir(parents=True, exist_ok=True)
    for code in predecessors:
        src_logs = (done / code).resolve() / "logs"
        if not src_logs.exists():
            continue
        for item in src_logs.iterdir():
            t = wf / "logs" / item.name
            if not t.exists() and not t.is_symlink():
                t.symlink_to(item)
    # S1 holds the inventory/work tree (S1 builds its own; don't link for it).
    if current_code != "S1":
        s1 = (done / "S1").resolve()
        if s1.exists() and not (wf / "work").exists():
            (wf / "work").symlink_to(s1 / "work")
    # Immediate predecessor provides derivatives.
    if predecessors:
        last_root = (done / predecessors[-1]).resolve()
        deriv = last_root / "derivatives"
        if deriv.exists() and not (wf / "derivatives").exists():
            (wf / "derivatives").symlink_to(deriv)
    # runs/ is S3-specific. Only link for downstream consumers (S4+).
    if current_code in ("S4", "S5", "S6", "S7", "S8", "S9", "S11"):
        s3_runs = (done / "S3").resolve() / "runs"
        if s3_runs.exists() and not (wf / "runs").exists():
            (wf / "runs").symlink_to(s3_runs)


def run_step(step_full: str, wf: Path, keys: list[str]) -> dict:
    """Run a step on each key sequentially. Returns {key: status}."""
    results = {}
    for k in keys:
        print(f"\n--- {step_full} :: {k} ---", flush=True)
        cmd = ["poetry", "run", "spinalfmriprep", "run", step_full,
               "--dataset-key", k,
               "--datasets-local", str(LOCAL_MAP),
               "--out", str(wf)]
        r = subprocess.run(cmd, cwd=PROJECT_ROOT)
        results[k] = "OK" if r.returncode == 0 else "FAIL"
    return results


def mark_done(scope: str, code: str, wf: Path) -> None:
    subprocess.run(
        ["python", "scripts/mark_done.py", scope, code, str(wf), "--force"],
        cwd=PROJECT_ROOT, check=False,
    )


def main() -> int:
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="S2", help="First step to run (S1..S11)")
    p.add_argument("--scope", default="reg",
                   help="Chain scope (work/done/<scope>/...). Default reg.")
    p.add_argument("--datasets", nargs="+", default=None,
                   help="Dataset keys to run. Default: all intended_use=regression keys.")
    args = p.parse_args()

    keys = args.datasets if args.datasets else reg_keys()
    scope = args.scope
    print(f"Scope: {scope}   Datasets ({len(keys)}):")
    for k in keys:
        print(f"  {k}")

    work_root = PROJECT_ROOT / "work"
    all_codes = [c for c, _ in ALL_CHAIN_STEPS]
    start_idx = all_codes.index(args.start) if args.start in all_codes else 1
    completed_codes: list[str] = all_codes[:start_idx]
    steps_to_run = ALL_CHAIN_STEPS[start_idx:]
    for code, full in steps_to_run:
        wf = get_next_workfolder(scope, work_root)
        wf.mkdir(parents=True)
        print(f"\n===== {full} :: {wf.name} =====", flush=True)
        link_chain(wf, scope, completed_codes, current_code=code)
        results = run_step(full, wf, keys)
        passed = [k for k, v in results.items() if v == "OK"]
        failed = [k for k, v in results.items() if v != "OK"]
        print(f"  PASS={len(passed)}  FAIL={len(failed)}")
        if failed:
            print(f"  failed: {failed}")
        mark_done(scope, code, wf)
        completed_codes.append(code)
    print("\n=== full chain complete ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
