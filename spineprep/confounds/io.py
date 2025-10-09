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


def write_confounds_extended_tsv_json(
    tsv_path: Path | str,
    json_path: Path | str,
    motion_params: np.ndarray,
    fd: np.ndarray,
    dvars: np.ndarray,
    acompcor_components: np.ndarray | None = None,
    tcompcor_components: np.ndarray | None = None,
    censor_fd: np.ndarray | None = None,
    censor_dvars: np.ndarray | None = None,
    censor_any: np.ndarray | None = None,
    metadata_extra: dict | None = None,
) -> None:
    """
    Write extended confounds TSV and JSON with CompCor and censoring columns.

    Args:
        tsv_path: Path to output TSV file
        json_path: Path to output JSON sidecar file
        motion_params: Array of shape (n_timepoints, 6)
        fd: Framewise displacement array (n_timepoints,)
        dvars: DVARS array (n_timepoints,)
        acompcor_components: Optional aCompCor array (n_timepoints, n_acompcor)
        tcompcor_components: Optional tCompCor array (n_timepoints, n_tcompcor)
        censor_fd: Optional FD censoring array (n_timepoints,) int8
        censor_dvars: Optional DVARS censoring array (n_timepoints,) int8
        censor_any: Optional combined censoring array (n_timepoints,) int8
        metadata_extra: Optional extra metadata (masks used, voxel counts, etc.)
    """
    tsv_path = Path(tsv_path)
    json_path = Path(json_path)

    # Create output directories
    tsv_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)

    n_timepoints = len(fd)

    # Build column list
    columns = [
        "trans_x",
        "trans_y",
        "trans_z",
        "rot_x",
        "rot_y",
        "rot_z",
        "fd",
        "dvars",
    ]

    # Add aCompCor columns
    n_acompcor = 0
    if acompcor_components is not None and acompcor_components.shape[1] > 0:
        n_acompcor = acompcor_components.shape[1]
        for i in range(n_acompcor):
            columns.append(f"acompcor_{i + 1:02d}")

    # Add tCompCor columns
    n_tcompcor = 0
    if tcompcor_components is not None and tcompcor_components.shape[1] > 0:
        n_tcompcor = tcompcor_components.shape[1]
        for i in range(n_tcompcor):
            columns.append(f"tcompcor_{i + 1:02d}")

    # Add censor columns
    if censor_fd is not None:
        columns.append("censor_fd")
    if censor_dvars is not None:
        columns.append("censor_dvars")
    if censor_any is not None:
        columns.append("censor_any")

    # Write TSV
    with tsv_path.open("w", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(columns)

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

            # Add aCompCor values
            if n_acompcor > 0:
                for j in range(n_acompcor):
                    row.append(float(acompcor_components[i, j]))

            # Add tCompCor values
            if n_tcompcor > 0:
                for j in range(n_tcompcor):
                    row.append(float(tcompcor_components[i, j]))

            # Add censor values
            if censor_fd is not None:
                row.append(int(censor_fd[i]))
            if censor_dvars is not None:
                row.append(int(censor_dvars[i]))
            if censor_any is not None:
                row.append(int(censor_any[i]))

            writer.writerow(row)

    # Build JSON metadata
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

    # Add aCompCor metadata
    for i in range(n_acompcor):
        col_name = f"acompcor_{i + 1:02d}"
        metadata[col_name] = {
            "LongName": f"aCompCor Component {i + 1}",
            "Description": f"Anatomical CompCor component {i + 1} from CSF/WM masks",
            "Units": "arbitrary",
            "Method": "aCompCor (Behzadi 2007): PCA of timeseries from anatomical masks",
            "Reference": "Behzadi Y et al. (2007). A component based noise correction method (CompCor) for BOLD and perfusion based fMRI. NeuroImage 37:90-101.",
        }

    # Add tCompCor metadata
    for i in range(n_tcompcor):
        col_name = f"tcompcor_{i + 1:02d}"
        metadata[col_name] = {
            "LongName": f"tCompCor Component {i + 1}",
            "Description": f"Temporal CompCor component {i + 1} from high-variance voxels",
            "Units": "arbitrary",
            "Method": "tCompCor (Behzadi 2007): PCA of timeseries from high temporal variance voxels",
            "Reference": "Behzadi Y et al. (2007). A component based noise correction method (CompCor) for BOLD and perfusion based fMRI. NeuroImage 37:90-101.",
        }

    # Add censor metadata
    if censor_fd is not None:
        metadata["censor_fd"] = {
            "LongName": "Censor FD",
            "Description": "Binary censoring flag based on FD threshold",
            "Units": "binary (0=keep, 1=censor)",
        }
    if censor_dvars is not None:
        metadata["censor_dvars"] = {
            "LongName": "Censor DVARS",
            "Description": "Binary censoring flag based on DVARS threshold",
            "Units": "binary (0=keep, 1=censor)",
        }
    if censor_any is not None:
        metadata["censor_any"] = {
            "LongName": "Censor Any",
            "Description": "Binary censoring flag for any motion criterion (FD OR DVARS)",
            "Units": "binary (0=keep, 1=censor)",
        }

    # Add extra metadata if provided
    if metadata_extra:
        metadata.update(metadata_extra)

    with json_path.open("w") as f:
        json.dump(metadata, f, indent=2)
