#!/usr/bin/env python3
"""
Mark a step as done by creating a symlink after validating QC.

Usage:
    python3 scripts/mark_done.py {scope} S{N} {workfolder}

Example:
    python3 scripts/mark_done.py reg S2 work/wf_reg_018

This script:
1. Validates that QC status is PASS in the workfolder
2. Creates symlink: work/done/{scope}/S{N}/ → {workfolder}
3. Reports success or failure
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def find_qc_files(workfolder: Path, step: str) -> list[Path]:
    """Find QC JSON files for a step in the workfolder."""
    logs_dir = workfolder / "logs"
    if not logs_dir.exists():
        return []
    
    qc_files = []
    
    # Pattern 1: logs/{step}_qc.json
    step_lower = step.lower()
    for qc_file in logs_dir.glob("*_qc.json"):
        if step_lower in qc_file.stem.lower():
            qc_files.append(qc_file)
    
    # Pattern 2: logs/{step}/{dataset_key}/qc.json
    step_dir = logs_dir / step.replace("S", "S").replace("s", "S")
    if not step_dir.exists():
        # Try with underscore variants
        for variant in [step, step.lower(), step.upper()]:
            for dir_path in logs_dir.iterdir():
                if dir_path.is_dir() and variant.lower() in dir_path.name.lower():
                    step_dir = dir_path
                    break
    
    if step_dir.exists():
        for qc_file in step_dir.glob("*/qc.json"):
            qc_files.append(qc_file)
    
    return qc_files


def validate_qc(workfolder: Path, step: str) -> tuple[bool, str]:
    """
    Validate that QC status is PASS for the step.
    
    Returns (passed, message).
    """
    qc_files = find_qc_files(workfolder, step)
    
    if not qc_files:
        return False, f"No QC files found for {step} in {workfolder}"
    
    all_pass = True
    messages = []
    
    for qc_file in qc_files:
        try:
            with open(qc_file, "r", encoding="utf-8") as f:
                qc_data = json.load(f)
            
            status = qc_data.get("status", "UNKNOWN")
            dataset_key = qc_data.get("dataset_key", qc_file.parent.name)
            
            if status == "PASS":
                messages.append(f"  ✓ {dataset_key}: PASS")
            else:
                all_pass = False
                failure_msg = qc_data.get("failure_message", "unknown reason")
                messages.append(f"  ✗ {dataset_key}: {status} - {failure_msg}")
        except Exception as e:
            all_pass = False
            messages.append(f"  ✗ {qc_file}: Failed to read - {e}")
    
    summary = "\n".join(messages)
    return all_pass, summary


def create_symlink(done_dir: Path, workfolder: Path) -> tuple[bool, str]:
    """
    Create the done symlink.
    
    Returns (success, message).
    """
    done_dir.parent.mkdir(parents=True, exist_ok=True)
    
    # Check if symlink already exists
    if done_dir.exists() or done_dir.is_symlink():
        if done_dir.is_symlink():
            current_target = os.readlink(done_dir)
            if Path(current_target).resolve() == workfolder.resolve():
                return True, f"Symlink already exists and points to correct target"
            else:
                # Remove old symlink
                done_dir.unlink()
        else:
            return False, f"Path exists but is not a symlink: {done_dir}"
    
    # Create relative symlink
    try:
        # Compute relative path from done_dir to workfolder
        rel_path = os.path.relpath(workfolder.resolve(), done_dir.parent.resolve())
        done_dir.symlink_to(rel_path)
        return True, f"Created symlink: {done_dir} → {rel_path}"
    except Exception as e:
        return False, f"Failed to create symlink: {e}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Mark a step as done by creating a symlink after validating QC."
    )
    parser.add_argument(
        "scope",
        choices=["smoke", "reg", "full"],
        help="Scope chain (smoke, reg, or full)",
    )
    parser.add_argument(
        "step",
        help="Step code (e.g., S1, S2, S2_anat_cordref)",
    )
    parser.add_argument(
        "workfolder",
        type=Path,
        help="Path to the workfolder to mark as done",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip QC validation (use with caution)",
    )
    
    args = parser.parse_args()
    
    # Normalize step to S{N} format
    step = args.step
    if "_" in step:
        # Extract step number from full name like S2_anat_cordref
        step_num = step.split("_")[0]
    else:
        step_num = step
    
    # Ensure step starts with S
    if not step_num.upper().startswith("S"):
        step_num = f"S{step_num}"
    step_num = step_num.upper()
    
    # Resolve workfolder
    workfolder = args.workfolder.resolve()
    if not workfolder.exists():
        print(f"ERROR: Workfolder does not exist: {workfolder}", file=sys.stderr)
        return 1
    
    print(f"Marking {step_num} as done in {args.scope} chain")
    print(f"Workfolder: {workfolder}")
    print()
    
    # Validate QC
    if not args.force:
        print("Validating QC status...")
        passed, message = validate_qc(workfolder, step)
        print(message)
        print()
        
        if not passed:
            print("ERROR: QC validation failed. Cannot mark as done.", file=sys.stderr)
            print("Use --force to skip validation (not recommended).", file=sys.stderr)
            return 1
        
        print("✓ QC validation passed")
    else:
        print("WARNING: Skipping QC validation (--force)")
    
    print()
    
    # Create symlink
    work_root = Path(__file__).parent.parent / "work"
    done_dir = work_root / "done" / args.scope / step_num
    
    print(f"Creating symlink: {done_dir}")
    success, message = create_symlink(done_dir, workfolder)
    print(message)
    
    if not success:
        print("ERROR: Failed to create symlink", file=sys.stderr)
        return 1
    
    print()
    print(f"✓ {step_num} marked as done in {args.scope} chain")
    print(f"  Symlink: {done_dir}")
    print(f"  Target:  {workfolder}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
