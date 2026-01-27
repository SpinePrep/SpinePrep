#!/usr/bin/env python3
"""
Run S3 on all datasets in a workfolder (e.g., wf_reg_010).

This script:
1. Finds all datasets in the workfolder
2. For each dataset, finds functional BOLD files and corresponding S2 outputs
3. Runs S3.1 on each BOLD file
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from spinalfmriprep.S3_func_init_and_crop import _process_s3_1_dummy_drop_and_localization
import yaml


def load_policy(policy_path: Path) -> dict:
    """Load policy YAML file."""
    with open(policy_path, "r") as f:
        return yaml.safe_load(f)


def find_bold_files(inventory: dict, bids_root: Path) -> list[dict]:
    """Find functional BOLD files from inventory."""
    bold_files = []
    for run in inventory.get("runs", []):
        if run.get("modality") == "func" and "bold" in str(run.get("path", "")).lower():
            path = bids_root / run["path"]
            if path.exists():
                bold_files.append({
                    "path": path,
                    "subject": run.get("subject"),
                    "session": run.get("session"),
                    "classification": run.get("classification"),
                })
    return bold_files


def find_s2_cordref(out_root: Path, subject: str, session: str | None) -> Path | None:
    """Find S2.1 cordref_std.nii.gz output."""
    # Try multiple path patterns
    patterns = []
    
    # Pattern 1: sub-XX_ses-YY or sub-XX_ses-none
    if session:
        patterns.append(out_root / "work" / "S2_anat_cordref" / f"sub-{subject}_ses-{session}" / "cordref_std.nii.gz")
    else:
        patterns.append(out_root / "work" / "S2_anat_cordref" / f"sub-{subject}_ses-none" / "cordref_std.nii.gz")
    
    # Pattern 2: sub-XX/ses-YY or sub-XX
    if session:
        patterns.append(out_root / "work" / "S2_anat_cordref" / f"sub-{subject}" / f"ses-{session}" / "cordref_std.nii.gz")
    else:
        patterns.append(out_root / "work" / "S2_anat_cordref" / f"sub-{subject}" / "cordref_std.nii.gz")
    
    # Pattern 3: Check parent workfolder (for centralized S2 outputs)
    parent_workfolder = out_root.parent if out_root.name.startswith("reg_") else out_root
    if session:
        patterns.append(parent_workfolder / "work" / "S2_anat_cordref" / f"sub-{subject}_ses-{session}" / "cordref_std.nii.gz")
        patterns.append(parent_workfolder / "work" / "S2_anat_cordref" / f"sub-{subject}" / f"ses-{session}" / "cordref_std.nii.gz")
    else:
        patterns.append(parent_workfolder / "work" / "S2_anat_cordref" / f"sub-{subject}_ses-none" / "cordref_std.nii.gz")
        patterns.append(parent_workfolder / "work" / "S2_anat_cordref" / f"sub-{subject}" / "cordref_std.nii.gz")
    
    for pattern in patterns:
        if pattern.exists():
            return pattern
    
    return None


def main() -> int:
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <workfolder_path>")
        print("Example: {sys.argv[0]} work/wf_reg_010")
        return 1
    
    workfolder = Path(sys.argv[1])
    if not workfolder.exists():
        print(f"ERROR: Workfolder does not exist: {workfolder}")
        return 1
    
    # Load policy
    policy_path = Path("policy") / "S3_func_init_and_crop.yaml"
    if not policy_path.exists():
        print(f"ERROR: Policy file not found: {policy_path}")
        return 1
    
    policy = load_policy(policy_path)
    
    # Map policy structure to what S3.1 expects
    policy_dict = {
        "dummy_volumes": {"count": policy.get("dummy", {}).get("drop_count", 4)},
        "func_localization": {
            "enabled": policy.get("func_localization", {}).get("enabled", True),
            "method": policy.get("func_localization", {}).get("method", "deepseg"),
            "task": policy.get("func_localization", {}).get("task", "spinalcord"),
        },
        "qc": {
            "overlay_contour_width": 2,
        },
    }
    
    # Find all datasets in workfolder
    inventory_pattern = workfolder / "**" / "work" / "S1_input_verify" / "bids_inventory.json"
    inventory_files = list(workfolder.glob(str(inventory_pattern.relative_to(workfolder))))
    
    if not inventory_files:
        print(f"ERROR: No inventory files found in {workfolder}")
        return 1
    
    print(f"Found {len(inventory_files)} dataset(s) in {workfolder}")
    print()
    
    total_processed = 0
    total_failed = 0
    
    for inv_path in sorted(inventory_files):
        # Determine out_root (parent of "work" directory)
        out_root = inv_path.parent.parent.parent
        
        # Load inventory
        with open(inv_path, "r") as f:
            inventory = json.load(f)
        
        dataset_key = inventory.get("dataset_key", "unknown")
        bids_root = Path(inventory.get("bids_root", ""))
        
        if not bids_root.exists():
            print(f"⚠ Skipping {dataset_key}: BIDS root not found: {bids_root}")
            continue
        
        print(f"Processing dataset: {dataset_key}")
        print(f"  Out root: {out_root}")
        print(f"  BIDS root: {bids_root}")
        
        # Find BOLD files
        bold_files = find_bold_files(inventory, bids_root)
        print(f"  Found {len(bold_files)} BOLD file(s)")
        
        if not bold_files:
            print("  ⚠ No BOLD files found, skipping")
            print()
            continue
        
        # Process each BOLD file
        for bold_info in bold_files:
            subject = bold_info["subject"]
            session = bold_info["session"]
            bold_path = bold_info["path"]
            
            # Check if S2 output exists (verify before running)
            s2_cordref = find_s2_cordref(out_root, subject, session)
            if not s2_cordref:
                # Try to find it manually for debugging
                expected_path = out_root / "work" / "S2_anat_cordref" / f"sub-{subject}_ses-{session or 'none'}" / "cordref_std.nii.gz"
                print(f"  ⚠ Skipping {bold_path.name}: No S2 output found")
                print(f"    Expected at: {expected_path}")
                print(f"    Exists: {expected_path.exists()}")
                continue
            
            print(f"    S2 found: {s2_cordref}")
            
            # Set up work directory (should be a directory, not including the filename)
            # Structure: {out_root}/runs/S3_func_init_and_crop/{run_id}/func/{run_name}/
            if session:
                work_dir = out_root / "runs" / "S3_func_init_and_crop" / f"sub-{subject}_ses-{session}" / "func" / bold_path.stem
            else:
                work_dir = out_root / "runs" / "S3_func_init_and_crop" / f"sub-{subject}_ses-none" / "func" / bold_path.stem
            
            work_dir.mkdir(parents=True, exist_ok=True)
            
            # The BOLD file path passed to S3 should be the actual file
            bold_file_path = bold_path
            
            print(f"  Processing: {bold_path.name} (sub-{subject}, ses-{session or 'none'})")
            
            # Run S3.1
            try:
                result = _process_s3_1_dummy_drop_and_localization(
                    bold_path=bold_path,
                    work_dir=work_dir,
                    policy=policy_dict,
                )
                
                if result.get("localization_status") == "PASS":
                    print(f"    ✓ PASS - Figure: {result.get('figure_path', 'N/A')}")
                    total_processed += 1
                else:
                    print(f"    ✗ FAIL - {result.get('failure_message', 'Unknown error')}")
                    total_failed += 1
            except Exception as e:
                print(f"    ✗ ERROR - {e}")
                total_failed += 1
        
        print()
    
    print("=" * 60)
    print(f"Summary: {total_processed} processed, {total_failed} failed")
    print("=" * 60)
    
    return 0 if total_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
