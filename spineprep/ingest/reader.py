"""BIDS directory reader and metadata extractor."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import nibabel as nib


def parse_bids_entities(filepath: Path) -> dict[str, str]:
    """
    Parse BIDS entities from filepath.

    Args:
        filepath: Path to BIDS file

    Returns:
        Dict with subject, session, task, acq, run, modality
    """
    parts = filepath.parts
    filename = filepath.name

    # Extract subject
    subject = next((p for p in parts if p.startswith("sub-")), "")

    # Extract session
    session = next((p for p in parts if p.startswith("ses-")), "")

    # Extract modality from directory
    modality = next(
        (p for p in parts if p in {"anat", "func", "fmap", "dwi"}), "unknown"
    )

    # Parse filename entities using regex
    task_match = re.search(r"_task-([a-zA-Z0-9]+)", filename)
    task = task_match.group(1) if task_match else ""

    acq_match = re.search(r"_acq-([a-zA-Z0-9]+)", filename)
    acq = acq_match.group(1) if acq_match else ""

    run_match = re.search(r"_run-(\d+)", filename)
    run = run_match.group(1) if run_match else ""

    return {
        "subject": subject,
        "session": session,
        "task": task,
        "acq": acq,
        "run": run,
        "modality": modality,
    }


def read_json_sidecar(nifti_path: Path) -> dict[str, Any]:
    """
    Read JSON sidecar for a NIfTI file.

    Args:
        nifti_path: Path to NIfTI file

    Returns:
        Dict with JSON contents, empty if not found
    """
    # Find corresponding JSON
    json_path = nifti_path.with_suffix("").with_suffix(".json")
    if not json_path.exists():
        # Try without .gz
        if nifti_path.suffix == ".gz":
            json_path = nifti_path.with_suffix(".json")

    if json_path.exists():
        try:
            with open(json_path) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def extract_nifti_metadata(nifti_path: Path) -> dict[str, Any]:
    """
    Extract metadata from NIfTI header.

    Args:
        nifti_path: Path to NIfTI file

    Returns:
        Dict with voxel_size_mm, fov_mm, dim, nslices, volumes
    """
    try:
        img = nib.load(str(nifti_path))
        header = img.header
        shape = img.shape
        pixdim = header.get_zooms()

        # Handle 3D vs 4D
        if len(shape) == 3:
            nx, ny, nz = shape
            volumes = 1
        else:
            nx, ny, nz, volumes = shape[:4]

        vx, vy, vz = pixdim[:3]

        # Format strings
        voxel_size = f"{vx:.2f}x{vy:.2f}x{vz:.2f}"
        fov = f"{nx * vx:.1f}x{ny * vy:.1f}x{nz * vz:.1f}"
        dim = f"{nx}x{ny}x{nz}"

        return {
            "voxel_size_mm": voxel_size,
            "fov_mm": fov,
            "dim": dim,
            "nslices": nz,
            "volumes": int(volumes) if len(shape) == 4 else 1,
        }
    except Exception:
        # If header read fails, return NA values
        return {
            "voxel_size_mm": "NA",
            "fov_mm": "NA",
            "dim": "NA",
            "nslices": 0,
            "volumes": 0,
        }


def infer_coverage(fov_mm: str, filepath: Path) -> str:
    """
    Infer coverage type from FOV and filename.

    Simple heuristic:
    - If FOV superior-inferior ≥ 80mm and filename contains spine/cord: "cord-only"
    - If functional and contains brain-related terms: "brain+cord"
    - Otherwise: "unknown"

    Args:
        fov_mm: FOV string like "64.0x64.0x96.0"
        filepath: Path to file

    Returns:
        Coverage description
    """
    filename_lower = str(filepath).lower()

    # Parse FOV
    try:
        parts = fov_mm.split("x")
        if len(parts) == 3:
            si_fov = float(parts[2])  # Assume z is superior-inferior

            # Check for cord-only indicators
            if si_fov >= 80.0 and any(
                term in filename_lower for term in ["spine", "cord", "spinal"]
            ):
                return "cord-only"

            # Check for brain+cord
            if "func" in filename_lower and any(
                term in filename_lower for term in ["brain", "motor", "sensory"]
            ):
                return "brain+cord"
    except (ValueError, IndexError):
        pass

    return "unknown"


def scan_bids_directory(bids_dir: Path) -> list[dict[str, Any]]:
    """
    Scan BIDS directory and extract metadata for all imaging files.

    Args:
        bids_dir: Path to BIDS root directory

    Returns:
        List of dicts, each with manifest columns
    """
    # Check BIDS validity
    if not bids_dir.exists():
        raise FileNotFoundError(f"BIDS directory not found: {bids_dir}")

    dataset_desc = bids_dir / "dataset_description.json"
    if not dataset_desc.exists():
        raise ValueError(
            f"Invalid BIDS: missing dataset_description.json in {bids_dir}"
        )

    # Find all imaging files
    imaging_files = []
    for pattern in ["**/*_bold.nii*", "**/*_T2w.nii*", "**/*_T1w.nii*"]:
        imaging_files.extend(bids_dir.glob(pattern))

    # Skip derivatives
    imaging_files = [f for f in imaging_files if "derivatives" not in f.parts]

    if not imaging_files:
        # Return empty list if no imaging files found
        return []

    results = []
    for nifti_path in imaging_files:
        # Parse BIDS entities
        entities = parse_bids_entities(nifti_path)

        # Read JSON sidecar
        sidecar = read_json_sidecar(nifti_path)

        # Extract NIfTI metadata
        nifti_meta = extract_nifti_metadata(nifti_path)

        # Build manifest row
        row = {
            "subject": entities["subject"],
            "session": entities["session"] or "",
            "task": entities["task"] or "",
            "acq": entities["acq"] or "",
            "run": entities["run"] or "",
            "modality": entities["modality"],
            "pe_dir": sidecar.get("PhaseEncodingDirection", ""),
            "tr": sidecar.get("RepetitionTime", "NA"),
            "te": sidecar.get("EchoTime", "NA"),
            "voxel_size_mm": nifti_meta["voxel_size_mm"],
            "fov_mm": nifti_meta["fov_mm"],
            "dim": nifti_meta["dim"],
            "nslices": nifti_meta["nslices"],
            "volumes": nifti_meta["volumes"],
            "coverage_desc": infer_coverage(nifti_meta["fov_mm"], nifti_path),
            "filepath": str(nifti_path.resolve()),
        }

        results.append(row)

    # Sort by subject, session, run for deterministic output
    results.sort(key=lambda r: (r["subject"], r["session"], r["run"]))

    return results
