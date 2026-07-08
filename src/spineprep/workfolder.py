"""
Workfolder management utilities for canonical work directory naming.

Provides functions to manage workfolders with the naming convention:
- wf_smoke_XXX: Smoke tests
- wf_reg_XXX: Regression validation
- wf_full_XXX: Full runs (v1 validation datasets, acceptance tests)
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional


def find_existing_workfolders(type: str, work_root: Path = Path("work")) -> list[Path]:
    """
    Find all existing workfolders of a given type.
    
    Args:
        type: Workfolder type ('smoke', 'reg', 'full')
        work_root: Root directory to search in (default: 'work')
        
    Returns:
        Sorted list of Path objects for existing workfolders of the given type
    """
    if not work_root.exists():
        return []
    
    pattern = f"wf_{type}_*"
    workfolders = []
    
    for item in work_root.iterdir():
        if not item.is_dir():
            continue
        if item.name.startswith(f"wf_{type}_"):
            # Extract number to validate format
            match = re.match(rf"wf_{type}_(\d+)", item.name)
            if match:
                workfolders.append(item)
    
    # Sort by number
    def get_number(path: Path) -> int:
        match = re.match(rf"wf_{type}_(\d+)", path.name)
        return int(match.group(1)) if match else 0
    
    return sorted(workfolders, key=get_number)


def get_next_workfolder(type: str, work_root: Path = Path("work")) -> Path:
    """
    Get the next available workfolder path for a given type.
    
    Finds the highest existing number for the type and returns the next one.
    If no workfolders exist, starts at 001.
    
    Args:
        type: Workfolder type ('smoke', 'reg', 'full')
        work_root: Root directory (default: 'work')
        
    Returns:
        Path to the next workfolder (e.g., work/wf_smoke_003)
    """
    existing = find_existing_workfolders(type, work_root)
    
    if not existing:
        next_number = 1
    else:
        # Extract number from the last (highest) workfolder
        last = existing[-1]
        match = re.match(rf"wf_{type}_(\d+)", last.name)
        if match:
            next_number = int(match.group(1)) + 1
        else:
            next_number = 1
    
    return work_root / f"wf_{type}_{next_number:03d}"


def migrate_workfolder(old_path: Path, new_path: Path, dry_run: bool = False) -> bool:
    """
    Migrate (rename) a workfolder from old path to new path.
    
    Args:
        old_path: Current path of the workfolder
        new_path: Target path for the workfolder
        dry_run: If True, don't actually rename, just check
        
    Returns:
        True if migration successful or would succeed, False if target exists
    """
    if not old_path.exists():
        return False
    
    if new_path.exists():
        return False  # Target exists, skip
    
    if dry_run:
        return True  # Would succeed
    
    try:
        old_path.rename(new_path)
        return True
    except Exception:
        return False


