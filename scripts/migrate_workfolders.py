#!/usr/bin/env python3
"""
Migrate existing work directories to canonical naming convention.

Migrates:
- wf_001, wf_002, etc. → wf_full_001, wf_full_002, etc. (preserve numbers)
- work/validation → wf_reg_XXX (find next available number)
- work/acceptance → wf_full_XXX (find next available number)
- work/s2_smoke → wf_smoke_XXX (find next available number)
- work/s2_acceptance/* → wf_full_XXX/* (if applicable)
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from spinalfmriprep.workfolder import get_next_workfolder, migrate_workfolder


def migrate_wf_directories(work_root: Path, dry_run: bool = False) -> list[tuple[Path, Path, bool]]:
    """
    Migrate old wf_XXX directories to wf_full_XXX.
    
    Returns list of (old_path, new_path, success) tuples.
    """
    results = []
    
    # Find all wf_XXX directories (old pattern)
    for item in work_root.iterdir():
        if not item.is_dir():
            continue
        
        # Match wf_XXX where XXX is digits only (old pattern)
        match = re.match(r"wf_(\d+)$", item.name)
        if match:
            number = match.group(1)
            old_path = item
            new_path = work_root / f"wf_full_{number}"
            
            success = migrate_workfolder(old_path, new_path, dry_run)
            results.append((old_path, new_path, success))
            
            if dry_run:
                if new_path.exists():
                    print(f"  [SKIP] {old_path.name} → {new_path.name} (target exists)")
                else:
                    print(f"  [MIGRATE] {old_path.name} → {new_path.name}")
            elif success:
                print(f"  ✓ Migrated {old_path.name} → {new_path.name}")
            else:
                print(f"  ✗ Skipped {old_path.name} → {new_path.name} (target exists)")
    
    return results


def migrate_validation_directory(work_root: Path, dry_run: bool = False) -> tuple[Path, Path, bool] | None:
    """Migrate work/validation to wf_reg_XXX."""
    old_path = work_root / "validation"
    if not old_path.exists():
        return None
    
    new_path = get_next_workfolder("reg", work_root)
    success = migrate_workfolder(old_path, new_path, dry_run)
    
    if dry_run:
        if new_path.exists():
            print(f"  [SKIP] validation → {new_path.name} (target exists)")
        else:
            print(f"  [MIGRATE] validation → {new_path.name}")
    elif success:
        print(f"  ✓ Migrated validation → {new_path.name}")
    else:
        print(f"  ✗ Skipped validation → {new_path.name} (target exists)")
    
    return (old_path, new_path, success)


def migrate_acceptance_directory(work_root: Path, dry_run: bool = False) -> tuple[Path, Path, bool] | None:
    """Migrate work/acceptance to wf_full_XXX."""
    old_path = work_root / "acceptance"
    if not old_path.exists():
        return None
    
    new_path = get_next_workfolder("full", work_root)
    success = migrate_workfolder(old_path, new_path, dry_run)
    
    if dry_run:
        if new_path.exists():
            print(f"  [SKIP] acceptance → {new_path.name} (target exists)")
        else:
            print(f"  [MIGRATE] acceptance → {new_path.name}")
    elif success:
        print(f"  ✓ Migrated acceptance → {new_path.name}")
    else:
        print(f"  ✗ Skipped acceptance → {new_path.name} (target exists)")
    
    return (old_path, new_path, success)


def migrate_s2_smoke_directory(work_root: Path, dry_run: bool = False) -> tuple[Path, Path, bool] | None:
    """Migrate work/s2_smoke to wf_smoke_XXX."""
    old_path = work_root / "s2_smoke"
    if not old_path.exists():
        return None
    
    new_path = get_next_workfolder("smoke", work_root)
    success = migrate_workfolder(old_path, new_path, dry_run)
    
    if dry_run:
        if new_path.exists():
            print(f"  [SKIP] s2_smoke → {new_path.name} (target exists)")
        else:
            print(f"  [MIGRATE] s2_smoke → {new_path.name}")
    elif success:
        print(f"  ✓ Migrated s2_smoke → {new_path.name}")
    else:
        print(f"  ✗ Skipped s2_smoke → {new_path.name} (target exists)")
    
    return (old_path, new_path, success)


def migrate_s2_acceptance_directories(work_root: Path, dry_run: bool = False) -> list[tuple[Path, Path, bool]]:
    """
    Migrate work/s2_acceptance/* to wf_full_XXX/*.
    
    Note: This migrates the parent s2_acceptance directory structure.
    Individual dataset directories under s2_acceptance are kept as-is.
    """
    results = []
    s2_acceptance = work_root / "s2_acceptance"
    
    if not s2_acceptance.exists():
        return results
    
    # For s2_acceptance, we need to handle it differently
    # If it contains dataset directories, we might want to migrate the whole thing
    # or migrate individual datasets. For now, we'll migrate the whole directory.
    new_path = get_next_workfolder("full", work_root)
    
    # Check if new_path already has content - if so, we might need a different approach
    if new_path.exists():
        print(f"  [SKIP] s2_acceptance → {new_path.name} (target exists)")
        return results
    
    success = migrate_workfolder(s2_acceptance, new_path, dry_run)
    results.append((s2_acceptance, new_path, success))
    
    if dry_run:
        print(f"  [MIGRATE] s2_acceptance → {new_path.name}")
    elif success:
        print(f"  ✓ Migrated s2_acceptance → {new_path.name}")
    else:
        print(f"  ✗ Skipped s2_acceptance → {new_path.name} (target exists)")
    
    return results


def main() -> int:
    """Run migration of work directories."""
    parser = argparse.ArgumentParser(description="Migrate work directories to canonical naming")
    parser.add_argument(
        "--work-root",
        type=Path,
        default=Path("work"),
        help="Work root directory (default: work)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be migrated without actually migrating",
    )
    
    args = parser.parse_args()
    
    work_root = args.work_root.resolve()
    
    if not work_root.exists():
        print(f"ERROR: Work root does not exist: {work_root}", file=sys.stderr)
        return 1
    
    print("=" * 60)
    if args.dry_run:
        print("DRY RUN: Migration Preview")
    else:
        print("Migrating Work Directories")
    print("=" * 60)
    print(f"Work root: {work_root}")
    print()
    
    all_results = []
    
    # 1. Migrate old wf_XXX directories
    print("1. Migrating wf_XXX → wf_full_XXX...")
    wf_results = migrate_wf_directories(work_root, args.dry_run)
    all_results.extend(wf_results)
    print()
    
    # 2. Migrate work/validation
    print("2. Migrating work/validation → wf_reg_XXX...")
    val_result = migrate_validation_directory(work_root, args.dry_run)
    if val_result:
        all_results.append(val_result)
    print()
    
    # 3. Migrate work/acceptance
    print("3. Migrating work/acceptance → wf_full_XXX...")
    acc_result = migrate_acceptance_directory(work_root, args.dry_run)
    if acc_result:
        all_results.append(acc_result)
    print()
    
    # 4. Migrate work/s2_smoke
    print("4. Migrating work/s2_smoke → wf_smoke_XXX...")
    smoke_result = migrate_s2_smoke_directory(work_root, args.dry_run)
    if smoke_result:
        all_results.append(smoke_result)
    print()
    
    # 5. Migrate work/s2_acceptance
    print("5. Migrating work/s2_acceptance → wf_full_XXX...")
    s2_acc_results = migrate_s2_acceptance_directories(work_root, args.dry_run)
    all_results.extend(s2_acc_results)
    print()
    
    # Summary
    print("=" * 60)
    print("Summary")
    print("=" * 60)
    successful = sum(1 for _, _, success in all_results if success)
    skipped = sum(1 for _, _, success in all_results if not success)
    total = len(all_results)
    
    print(f"Total migrations: {total}")
    if args.dry_run:
        print(f"Would migrate: {successful}")
        print(f"Would skip: {skipped}")
    else:
        print(f"Migrated: {successful}")
        print(f"Skipped: {skipped}")
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


