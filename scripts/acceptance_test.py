#!/usr/bin/env python3
"""
Run acceptance tests for a ticket.

Verifies that acceptance criteria from ROADMAP are met.
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

# Add src to path for workfolder utilities
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from spineprep.workfolder import get_next_workfolder

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def verify_artifacts(step: str, dataset_key: str, out: str, artifacts: list[str]) -> bool:
    """Verify required artifacts exist."""
    out_path = Path(out)
    all_exist = True

    for artifact_pattern in artifacts:
        # Expand pattern
        artifact_path = out_path / artifact_pattern.format(
            OUT=out,
            DATASET_KEY=dataset_key,
            STEP=step,
        )

        # Check if file or any matching files exist
        if "*" in str(artifact_path):
            matches = list(glob.glob(str(artifact_path)))
            if not matches:
                print(f"  ✗ Missing: {artifact_pattern}")
                all_exist = False
            else:
                print(f"  ✓ Found: {artifact_pattern} ({len(matches)} files)")
        else:
            if artifact_path.exists():
                print(f"  ✓ Found: {artifact_pattern}")
            else:
                print(f"  ✗ Missing: {artifact_pattern}")
                all_exist = False

    return all_exist


def verify_qc_json(step: str, dataset_key: str, out: str) -> bool:
    """Verify QC JSON exists and is valid."""
    qc_path = Path(out) / "logs" / step / dataset_key / "qc_status.json"

    if not qc_path.exists():
        print(f"  ✗ Missing QC JSON: {qc_path}")
        return False

    try:
        with qc_path.open("r") as f:
            qc_data = json.load(f)

        # Check required fields
        required_fields = ["status"]
        for field in required_fields:
            if field not in qc_data:
                print(f"  ✗ QC JSON missing field: {field}")
                return False

        status = qc_data.get("status")
        if status not in ["PASS", "WARN", "FAIL"]:
            print(f"  ✗ QC JSON invalid status: {status}")
            return False

        print(f"  ✓ QC JSON valid: status={status}")
        return True
    except json.JSONDecodeError as e:
        print(f"  ✗ QC JSON invalid JSON: {e}")
        return False
    except Exception as e:
        print(f"  ✗ QC JSON error: {e}")
        return False


def main() -> int:
    """Run acceptance tests."""
    parser = argparse.ArgumentParser(description="Run acceptance tests for a ticket")
    parser.add_argument("--ticket", required=True, help="Ticket ID (e.g., BUILD-S3-T1)")
    parser.add_argument("--step", help="Step code (auto-detected from ticket if not provided)")
    parser.add_argument(
        "--dataset-key",
        default="reg_openneuro_ds004386_rest_subset",
        help="Dataset key for testing",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Output directory (default: auto-increment wf_full_XXX)",
    )

    args = parser.parse_args()
    
    # Use canonical workfolder naming if --out not specified
    if args.out is None:
        work_root = PROJECT_ROOT / "work"
        args.out = str(get_next_workfolder("full", work_root))

    # Extract step from ticket if not provided
    if not args.step:
        # BUILD-S3-T1 -> S3_func_init_and_crop
        try:
            step_num = args.ticket.split("-")[1].replace("S", "")
            step_map = {
                "0": "S0_SETUP",
                "1": "S1_input_verify",
                "2": "S2_anat_cordref",
                "3": "S3_func_init_and_crop",
            }
            args.step = step_map.get(step_num, f"S{step_num}_*")
        except (IndexError, ValueError):
            print(f"ERROR: Could not extract step from ticket: {args.ticket}", file=sys.stderr)
            print("Please provide --step explicitly", file=sys.stderr)
            return 1

    print(f"Acceptance Test: {args.ticket}")
    print(f"Step: {args.step}")
    print(f"Dataset: {args.dataset_key}")
    print(f"Output: {args.out}")
    print()

    # Common artifacts (should be customized per ticket based on ROADMAP)
    # For now, use generic patterns
    artifacts = [
        "runs/{STEP}/sub-*/ses-*/func/*/init/*.nii.gz",
        "logs/{STEP}/{DATASET_KEY}/qc_status.json",
    ]

    print("1. Verifying artifacts...")
    artifacts_ok = verify_artifacts(args.step, args.dataset_key, args.out, artifacts)

    print()
    print("2. Verifying QC JSON...")
    qc_ok = verify_qc_json(args.step, args.dataset_key, args.out)

    print()
    if artifacts_ok and qc_ok:
        print("✓ Acceptance tests PASSED")
        return 0
    else:
        print("✗ Acceptance tests FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())

