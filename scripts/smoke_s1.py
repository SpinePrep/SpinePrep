#!/usr/bin/env python3
"""
Smoke test for S1_input_verify.

Runs the full S1 pipeline on 1 subject from regression data.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from spinalfmriprep.workfolder import get_next_workfolder


def main() -> int:
    """Run S1 smoke test."""
    print("=" * 60)
    print("S1_input_verify Smoke Test")
    print("=" * 60)
    
    # Get next workfolder
    print("\n[1/3] Creating workfolder...")
    work_root = Path(__file__).parent.parent / "work"
    work_root.mkdir(exist_ok=True)
    wf = get_next_workfolder("smoke", work_root)
    wf.mkdir(parents=True, exist_ok=True)
    print(f"✓ Workfolder: {wf}")
    
    # Dataset key for smoke test
    dataset_key = "reg_openneuro_ds005884_cospine_motor_subset"
    
    # Local datasets mapping
    project_root = Path(__file__).parent.parent
    datasets_local = project_root / "config" / "datasets_local.yaml"
    
    if not datasets_local.exists():
        print(f"ERROR: Missing datasets_local mapping: {datasets_local}", file=sys.stderr)
        print("Create config/datasets_local.yaml with paths to regression datasets", file=sys.stderr)
        return 1
    
    # Run S1
    print(f"\n[2/3] Running S1_input_verify on {dataset_key}...")
    run_result = subprocess.run(
        [
            "poetry", "run", "spinalfmriprep", "run", "S1_input_verify",
            "--dataset-key", dataset_key,
            "--datasets-local", str(datasets_local),
            "--out", str(wf),
        ],
        cwd=project_root,
    )
    
    if run_result.returncode != 0:
        print(f"\n✗ S1 run failed with exit code {run_result.returncode}", file=sys.stderr)
        return 1
    print("✓ S1 run completed")
    
    # Run check
    print(f"\n[3/3] Running S1_input_verify check...")
    check_result = subprocess.run(
        [
            "poetry", "run", "spinalfmriprep", "check", "S1_input_verify",
            "--dataset-key", dataset_key,
            "--datasets-local", str(datasets_local),
            "--out", str(wf),
        ],
        cwd=project_root,
    )
    
    if check_result.returncode != 0:
        print(f"\n✗ S1 check failed with exit code {check_result.returncode}", file=sys.stderr)
        return 1
    print("✓ S1 check completed")
    
    # Summary
    print("\n" + "=" * 60)
    print("SMOKE TEST PASSED")
    print("=" * 60)
    print(f"Workfolder: {wf}")
    print(f"Dashboard:  {wf}/dashboard/index.html")
    print(f"QC JSON:    {wf}/logs/S1_input_verify/{dataset_key}/qc.json")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
