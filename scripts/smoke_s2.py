#!/usr/bin/env python3
"""
Smoke test for S2_anat_cordref.

Runs the full S2 pipeline on 1 subject from regression data.
SCT is required — fails if not installed.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from spinalfmriprep.workfolder import get_next_workfolder


def check_sct() -> None:
    """Fail if SCT not installed."""
    result = subprocess.run(["which", "sct_version"], capture_output=True)
    if result.returncode != 0:
        print("ERROR: SCT not installed. Install from https://spinalcordtoolbox.com", file=sys.stderr)
        sys.exit(1)
    
    # Print version
    version_result = subprocess.run(["sct_version"], capture_output=True, text=True)
    print(f"SCT version: {version_result.stdout.strip()}")


def main() -> int:
    """Run S2 smoke test."""
    print("=" * 60)
    print("S2_anat_cordref Smoke Test")
    print("=" * 60)
    
    # Check SCT
    print("\n[1/5] Checking SCT installation...")
    check_sct()
    print("✓ SCT installed")
    
    # Get next workfolder
    print("\n[2/5] Creating workfolder...")
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
    
    # Run S1 first (S2 depends on S1 output)
    print(f"\n[3/5] Running S1_input_verify (prerequisite)...")
    s1_result = subprocess.run(
        [
            "poetry", "run", "spinalfmriprep", "run", "S1_input_verify",
            "--dataset-key", dataset_key,
            "--datasets-local", str(datasets_local),
            "--out", str(wf),
        ],
        cwd=project_root,
    )
    
    if s1_result.returncode != 0:
        print(f"\n✗ S1 run failed with exit code {s1_result.returncode}", file=sys.stderr)
        return 1
    print("✓ S1 completed (prerequisite for S2)")
    
    # Run S2
    print(f"\n[4/5] Running S2_anat_cordref on {dataset_key}...")
    run_result = subprocess.run(
        [
            "poetry", "run", "spinalfmriprep", "run", "S2_anat_cordref",
            "--dataset-key", dataset_key,
            "--datasets-local", str(datasets_local),
            "--out", str(wf),
        ],
        cwd=project_root,
    )
    
    if run_result.returncode != 0:
        print(f"\n✗ S2 run failed with exit code {run_result.returncode}", file=sys.stderr)
        return 1
    print("✓ S2 run completed")
    
    # Run check
    print(f"\n[5/5] Running S2_anat_cordref check...")
    check_result = subprocess.run(
        [
            "poetry", "run", "spinalfmriprep", "check", "S2_anat_cordref",
            "--dataset-key", dataset_key,
            "--out", str(wf),
        ],
        cwd=project_root,
    )
    
    if check_result.returncode != 0:
        print(f"\n✗ S2 check failed with exit code {check_result.returncode}", file=sys.stderr)
        return 1
    print("✓ S2 check completed")
    
    # Summary
    print("\n" + "=" * 60)
    print("SMOKE TEST PASSED")
    print("=" * 60)
    print(f"Workfolder: {wf}")
    print(f"Dashboard:  {wf}/dashboard/index.html")
    print(f"QC JSON:    {wf}/logs/S2_anat_cordref/{dataset_key}/qc.json")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
