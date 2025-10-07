#!/usr/bin/env python3
"""
BIDS dataset discovery and file path utilities.

Pure Python implementation for discovering subjects, sessions, and runs
in a BIDS-compliant dataset.
"""

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional


def list_subjects(
    bids_root: str,
    include: Optional[List[str]] = None,
    exclude: Optional[List[str]] = None,
) -> List[str]:
    """List all subject directories in the BIDS root.

    Args:
        bids_root: Path to BIDS dataset root
        include: Optional list of subject IDs to include (e.g., ['sub-001', 'sub-002'])
        exclude: Optional list of subject IDs to exclude

    Returns:
        Sorted list of subject IDs (e.g., ['sub-001', 'sub-002'])
    """
    bids_path = Path(bids_root)
    if not bids_path.exists():
        return []

    subjects = []
    for item in bids_path.iterdir():
        if (
            item.is_dir()
            and not item.name.startswith(".")
            and item.name.startswith("sub-")
        ):
            sub_id = item.name
            if include is None or sub_id in include:
                if exclude is None or sub_id not in exclude:
                    subjects.append(sub_id)

    return sorted(subjects)


def list_sessions(bids_root: str, sub: str) -> List[str]:
    """List all session directories for a subject.

    Args:
        bids_root: Path to BIDS dataset root
        sub: Subject ID (e.g., 'sub-001')

    Returns:
        Sorted list of session IDs, or empty list if no sessions
    """
    sub_path = Path(bids_root) / sub
    if not sub_path.exists():
        return []

    sessions = []
    for item in sub_path.iterdir():
        if (
            item.is_dir()
            and not item.name.startswith(".")
            and item.name.startswith("ses-")
        ):
            sessions.append(item.name)

    return sorted(sessions)


def list_runs(
    bids_root: str, sub: str, ses: Optional[str], task: Optional[str] = None
) -> List[str]:
    """List all run IDs for a subject/session combination.

    Args:
        bids_root: Path to BIDS dataset root
        sub: Subject ID (e.g., 'sub-001')
        ses: Session ID (e.g., 'ses-01') or None if no sessions
        task: Optional task name to filter by

    Returns:
        Sorted list of run IDs (e.g., ['01', '02', '10'])
    """
    # Build path to func directory
    if ses:
        func_path = Path(bids_root) / sub / ses / "func"
    else:
        func_path = Path(bids_root) / sub / "func"

    if not func_path.exists():
        return []

    runs = set()
    pattern_parts = [sub]
    if ses:
        pattern_parts.append(ses)

    # Build regex pattern for BOLD files
    if task:
        pattern = f"^{sub}(_{ses})?_task-{re.escape(task)}_run-(\\d+)_bold\\.nii\\.gz$"
    else:
        pattern = f"^{sub}(_{ses})?_task-.*_run-(\\d+)_bold\\.nii\\.gz$"

    regex = re.compile(pattern)

    for file_path in func_path.iterdir():
        if file_path.is_file() and not file_path.name.startswith("."):
            match = regex.match(file_path.name)
            if match:
                run_id = match.group(2)  # The run number
                runs.add(run_id)

    # Sort numerically
    return sorted(runs, key=lambda x: int(x))


def bold_nii(
    bids_root: str, sub: str, ses: Optional[str], run: str, task: Optional[str] = None
) -> str:
    """Get the path to a BOLD NIfTI file.

    Args:
        bids_root: Path to BIDS dataset root
        sub: Subject ID (e.g., 'sub-001')
        ses: Session ID (e.g., 'ses-01') or None if no sessions
        run: Run ID (e.g., '01')
        task: Optional task name

    Returns:
        Path to the BOLD NIfTI file

    Raises:
        FileNotFoundError: If the file doesn't exist
    """
    # Build path to func directory
    if ses:
        func_path = Path(bids_root) / sub / ses / "func"
    else:
        func_path = Path(bids_root) / sub / "func"

    if not func_path.exists():
        raise FileNotFoundError(f"Func directory not found: {func_path}")

    # Build filename pattern
    if task:
        pattern = f"{sub}"
        if ses:
            pattern += f"_{ses}"
        pattern += f"_task-{task}_run-{run}_bold.nii.gz"
    else:
        # Find any task file with this run
        pattern = f"{sub}"
        if ses:
            pattern += f"_{ses}"
        pattern += f"_task-*_run-{run}_bold.nii.gz"

    # Look for matching files
    matching_files = []
    for file_path in func_path.iterdir():
        if file_path.is_file() and not file_path.name.startswith("."):
            if task:
                if file_path.name == pattern:
                    matching_files.append(file_path)
            else:
                # Use regex for wildcard matching
                regex_pattern = pattern.replace("*", ".*")
                if re.match(regex_pattern, file_path.name):
                    matching_files.append(file_path)

    if not matching_files:
        raise FileNotFoundError(
            f"No BOLD file found for {sub}, {ses}, run {run}, task {task}"
        )

    # If multiple files match, pick the shortest name (deterministic)
    best_file = min(matching_files, key=lambda x: len(x.name))
    return str(best_file)


def discover(bids_root: str, task: Optional[str] = None) -> Dict[str, Any]:
    """Discover the complete structure of a BIDS dataset.

    Args:
        bids_root: Path to BIDS dataset root
        task: Optional task name to filter by

    Returns:
        Dictionary with dataset structure and counts
    """
    bids_path = Path(bids_root).resolve()

    subjects_data = []
    total_sessions = 0
    total_runs = 0

    for sub_id in list_subjects(str(bids_path)):
        sessions = list_sessions(str(bids_path), sub_id)

        if not sessions:
            # No sessions - check for direct func data
            runs = list_runs(str(bids_path), sub_id, None, task)
            if runs:
                subjects_data.append(
                    {"id": sub_id, "sessions": [{"id": None, "runs": runs}]}
                )
                total_sessions += 1
                total_runs += len(runs)
        else:
            # Has sessions
            session_data = []
            for ses_id in sessions:
                runs = list_runs(str(bids_path), sub_id, ses_id, task)
                if runs:
                    session_data.append({"id": ses_id, "runs": runs})
                    total_sessions += 1
                    total_runs += len(runs)

            if session_data:
                subjects_data.append({"id": sub_id, "sessions": session_data})

    return {
        "bids_root": str(bids_path),
        "subjects": subjects_data,
        "counts": {
            "subjects": len(subjects_data),
            "sessions": total_sessions,
            "runs": total_runs,
        },
    }


def main():
    """Command-line interface for BIDS discovery."""
    parser = argparse.ArgumentParser(description="Discover BIDS dataset structure")
    parser.add_argument("--root", required=True, help="Path to BIDS dataset root")
    parser.add_argument("--task", help="Optional task name to filter by")

    args = parser.parse_args()

    try:
        result = discover(args.root, args.task)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
