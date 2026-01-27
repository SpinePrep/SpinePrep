#!/usr/bin/env python3
"""
Validate step on regression datasets.

Runs a step on all regression dataset keys and checks QC outputs.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import yaml

# Add src to path for workfolder utilities
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from spinalfmriprep.workfolder import get_next_workfolder

PROJECT_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = PROJECT_ROOT / "policy" / "datasets.yaml"
LOCAL_MAP = PROJECT_ROOT / "config" / "datasets_local.yaml"


def get_regression_keys() -> list[str]:
    """Get list of regression dataset keys."""
    with POLICY_PATH.open("r", encoding="utf-8") as f:
        policy = yaml.safe_load(f)
    return [
        ds["key"]
        for ds in policy.get("datasets", [])
        if "regression" in ds.get("intended_use", [])
    ]


def main() -> int:
    """Run validation on regression datasets."""
    parser = argparse.ArgumentParser(description="Validate step on regression datasets")
    parser.add_argument("--step", required=True, help="Step code (e.g., S3_func_init_and_crop)")
    parser.add_argument(
        "--out",
        default=None,
        help="Output directory (default: auto-increment wf_reg_XXX)",
    )
    parser.add_argument("--only-missing", action="store_true", help="Only process missing outputs")

    args = parser.parse_args()
    
    # Use canonical workfolder naming if --out not specified
    if args.out is None:
        work_root = PROJECT_ROOT / "work"
        args.out = str(get_next_workfolder("reg", work_root))

    if not LOCAL_MAP.exists():
        print(f"ERROR: Missing datasets_local mapping: {LOCAL_MAP}", file=sys.stderr)
        return 1

    regression_keys = get_regression_keys()
    if not regression_keys:
        print("ERROR: No regression dataset keys found", file=sys.stderr)
        return 1

    print(f"Validating {args.step} on {len(regression_keys)} regression datasets")
    print()

    failures = []
    for key in regression_keys:
        print(f"Processing: {key}")
        cmd = [
            "poetry",
            "run",
            "spinalfmriprep",
            "run",
            args.step,
            "--dataset-key",
            key,
            "--datasets-local",
            str(LOCAL_MAP),
            "--out",
            args.out,
        ]
        if args.only_missing:
            cmd.append("--only-missing")

        print(f"  Running: {' '.join(cmd)}")
        result = subprocess.run(cmd, cwd=PROJECT_ROOT)
        if result.returncode != 0:
            failures.append(key)
            print(f"  ✗ FAILED")
        else:
            print(f"  ✓ PASSED")

        # Run check
        check_cmd = [
            "poetry",
            "run",
            "spinalfmriprep",
            "check",
            args.step,
            "--dataset-key",
            key,
            "--datasets-local",
            str(LOCAL_MAP),
            "--out",
            args.out,
        ]
        print(f"  Checking: {' '.join(check_cmd)}")
        check_result = subprocess.run(check_cmd, cwd=PROJECT_ROOT)
        if check_result.returncode != 0:
            if key not in failures:
                failures.append(key)
            print(f"  ✗ CHECK FAILED")
        else:
            print(f"  ✓ CHECK PASSED")
        print()

    if failures:
        print(f"✗ Validation failed for: {', '.join(failures)}", file=sys.stderr)
        return 1

    print(f"✓ Validation passed for all {len(regression_keys)} regression datasets")
    return 0


if __name__ == "__main__":
    sys.exit(main())

