"""Manifest CSV writer and validation."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

MANIFEST_COLUMNS = [
    "subject",
    "session",
    "task",
    "acq",
    "run",
    "modality",
    "pe_dir",
    "tr",
    "te",
    "voxel_size_mm",
    "fov_mm",
    "dim",
    "nslices",
    "volumes",
    "coverage_desc",
    "filepath",
]


def validate_bids_essentials(bids_dir: Path) -> tuple[bool, list[str]]:
    """
    Validate BIDS directory has essential components.

    Args:
        bids_dir: Path to BIDS root

    Returns:
        Tuple of (is_valid, warnings)
    """
    warnings = []

    if not bids_dir.exists():
        return False, [f"BIDS directory does not exist: {bids_dir}"]

    # Check dataset_description.json
    dataset_desc = bids_dir / "dataset_description.json"
    if not dataset_desc.exists():
        warnings.append("Missing dataset_description.json")
        return False, warnings

    # Check for at least one sub-* directory
    subjects = list(bids_dir.glob("sub-*"))
    if not subjects:
        warnings.append("No subject directories (sub-*) found")
        return False, warnings

    return True, warnings


def write_manifest(rows: list[dict[str, Any]], out_path: Path) -> Path:
    """
    Write manifest CSV with standardized columns.

    Args:
        rows: List of dicts with manifest data
        out_path: Path to write CSV (will be created/overwritten)

    Returns:
        Path to written manifest
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=MANIFEST_COLUMNS)
        writer.writeheader()

        for row in rows:
            # Ensure all columns present, fill missing with empty string
            clean_row = {col: row.get(col, "") for col in MANIFEST_COLUMNS}
            writer.writerow(clean_row)

    return out_path
