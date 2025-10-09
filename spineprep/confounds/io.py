"""Confounds I/O: write TSV and JSON with schema v1 compliance."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np

from spineprep import __version__


def write_confounds_tsv_json(
    tsv_path: Path | str,
    json_path: Path | str,
    motion_params: np.ndarray,
    fd: np.ndarray,
    dvars: np.ndarray,
) -> None:
    """
    Write confounds TSV and JSON sidecar with schema v1 compliance.

    Args:
        tsv_path: Path to output TSV file
        json_path: Path to output JSON sidecar file
        motion_params: Array of shape (n_timepoints, 6) with columns:
                       trans_x, trans_y, trans_z, rot_x, rot_y, rot_z
        fd: Framewise displacement array (n_timepoints,)
        dvars: DVARS array (n_timepoints,)
    """
    tsv_path = Path(tsv_path)
    json_path = Path(json_path)

    # Create output directories
    tsv_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)

    n_timepoints = len(fd)

    # Validate inputs
    if motion_params.shape[0] != n_timepoints:
        raise ValueError(
            f"Motion params ({motion_params.shape[0]}) and FD ({n_timepoints}) length mismatch"
        )
    if len(dvars) != n_timepoints:
        raise ValueError(
            f"DVARS ({len(dvars)}) and FD ({n_timepoints}) length mismatch"
        )

    # Write TSV with canonical column order
    with tsv_path.open("w", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        # Header
        writer.writerow(
            ["trans_x", "trans_y", "trans_z", "rot_x", "rot_y", "rot_z", "fd", "dvars"]
        )
        # Data rows
        for i in range(n_timepoints):
            row = [
                float(motion_params[i, 0]),
                float(motion_params[i, 1]),
                float(motion_params[i, 2]),
                float(motion_params[i, 3]),
                float(motion_params[i, 4]),
                float(motion_params[i, 5]),
                float(fd[i]),
                float(dvars[i]),
            ]
            writer.writerow(row)

    # Write JSON sidecar with schema v1 metadata
    metadata = {
        "SpinePrepSchemaVersion": "1.0",
        "SoftwareName": "SpinePrep",
        "SoftwareVersion": __version__,
        "trans_x": {
            "LongName": "Translation X",
            "Description": "Translational motion parameter along X axis (left-right)",
            "Units": "mm",
        },
        "trans_y": {
            "LongName": "Translation Y",
            "Description": "Translational motion parameter along Y axis (anterior-posterior)",
            "Units": "mm",
        },
        "trans_z": {
            "LongName": "Translation Z",
            "Description": "Translational motion parameter along Z axis (superior-inferior)",
            "Units": "mm",
        },
        "rot_x": {
            "LongName": "Rotation X (pitch)",
            "Description": "Rotational motion parameter around X axis",
            "Units": "radians",
        },
        "rot_y": {
            "LongName": "Rotation Y (roll)",
            "Description": "Rotational motion parameter around Y axis",
            "Units": "radians",
        },
        "rot_z": {
            "LongName": "Rotation Z (yaw)",
            "Description": "Rotational motion parameter around Z axis",
            "Units": "radians",
        },
        "fd": {
            "LongName": "Framewise Displacement",
            "Description": "Framewise displacement computed using Power et al. 2012 method",
            "Units": "mm",
            "Method": "Power et al. (2012): sum of absolute translational displacements + radius * sum of absolute rotational displacements",
            "Reference": "Power JD et al. (2012). Spurious but systematic correlations in functional connectivity MRI networks arise from subject motion. NeuroImage 59:2142-2154.",
            "RotationRadius": "50mm",
        },
        "dvars": {
            "LongName": "DVARS",
            "Description": "Temporal derivative of RMS variance over voxels (within mask)",
            "Units": "arbitrary",
            "Method": "sqrt(mean(voxelwise squared temporal differences))",
            "Reference": "Power JD et al. (2012). Spurious but systematic correlations in functional connectivity MRI networks arise from subject motion. NeuroImage 59:2142-2154.",
        },
    }

    with json_path.open("w") as f:
        json.dump(metadata, f, indent=2)
