"""BIDS-Derivatives tree layout and sidecar generation."""

from __future__ import annotations

import json
import os
import platform
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from spineprep._version import __version__


def build_confounds_sidecar(
    fd_method: str,
    dvars_method: str,
    tr_s: float,
    censor_params: dict[str, Any],
    acompcor_meta: dict[str, Any],
    sources: list[str] | None = None,
) -> dict[str, Any]:
    """
    Build BIDS-compliant JSON sidecar for confounds timeseries.

    Args:
        fd_method: FD computation method
        dvars_method: DVARS computation method
        tr_s: Repetition time in seconds
        censor_params: Censoring parameters and statistics
        acompcor_meta: aCompCor metadata (components, variance)
        sources: Source BIDS files

    Returns:
        Complete sidecar dictionary
    """
    sidecar = {
        "GeneratedBy": [
            {
                "Name": "SpinePrep",
                "Version": __version__,
                "CodeURL": "https://github.com/SpinePrep/SpinePrep",
            }
        ],
        "Sources": sources or [],
        "confounds": {
            "framewise_displacement": {
                "description": "Framewise Displacement (Power et al., 2012)",
                "units": "mm",
                "method": fd_method,
            },
            "dvars": {
                "description": "Root mean square of BOLD signal changes between consecutive volumes",
                "units": "normalized intensity",
                "method": dvars_method,
            },
        },
        "Parameters": {
            "tr_s": tr_s,
            "censor": censor_params,
        },
    }

    # Add frame_censor if censoring is enabled
    if censor_params.get("n_censored", 0) > 0 or "fd_thresh_mm" in censor_params:
        sidecar["confounds"]["frame_censor"] = {
            "description": "Frame censoring mask",
            "values": {"0": "kept", "1": "censored"},
        }

    # Add aCompCor metadata if present
    if acompcor_meta:
        sidecar["Parameters"]["acompcor"] = acompcor_meta

    return sidecar


def build_motion_sidecar(
    engine: str,
    slice_axis: str,
    sources: list[str],
    temporal_crop: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Build BIDS-compliant JSON sidecar for motion parameters.

    Args:
        engine: Motion correction engine
        slice_axis: Slice-wise correction axis
        sources: Source BIDS files
        temporal_crop: Optional crop info

    Returns:
        Complete sidecar dictionary
    """
    sidecar = {
        "GeneratedBy": [
            {
                "Name": "SpinePrep",
                "Version": __version__,
                "CodeURL": "https://github.com/SpinePrep/SpinePrep",
            }
        ],
        "Sources": sources,
        "Parameters": {
            "engine": engine,
            "slice_axis": slice_axis,
        },
    }

    if temporal_crop:
        sidecar["Parameters"]["temporal_crop"] = temporal_crop

    return sidecar


def build_dataset_description(
    source_datasets: list[str],
    pipeline_version: str,
) -> dict[str, Any]:
    """
    Build BIDS-Derivatives dataset_description.json.

    Args:
        source_datasets: List of source BIDS dataset paths
        pipeline_version: Pipeline version

    Returns:
        Complete dataset description
    """
    return {
        "Name": "SpinePrep Derivatives",
        "BIDSVersion": "1.8.0",
        "DatasetType": "derivative",
        "GeneratedBy": [
            {
                "Name": "SpinePrep",
                "Version": pipeline_version,
                "Description": "Spinal cord fMRI preprocessing pipeline",
                "CodeURL": "https://github.com/SpinePrep/SpinePrep",
            }
        ],
        "SourceDatasets": [
            {"URL": path, "Version": "unknown"} for path in source_datasets
        ],
    }


def build_provenance_snapshot(
    config_path: str,
    bids_root: str,
    deriv_root: str,
    sct_version: str | None = None,
    dag_path: str | None = None,
) -> dict[str, Any]:
    """
    Build comprehensive provenance snapshot.

    Args:
        config_path: Path to configuration file
        bids_root: BIDS root directory
        deriv_root: Derivatives root directory
        sct_version: SCT version (if available)
        dag_path: Path to DAG SVG (if available)

    Returns:
        Provenance dictionary
    """
    prov = {
        "pipeline_version": __version__,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "python_version": platform.python_version(),
            "os": platform.system(),
            "kernel": platform.release(),
            "pythonpath": os.environ.get("PYTHONPATH", ""),
        },
        "paths": {
            "bids_root": str(Path(bids_root).resolve()),
            "deriv_root": str(Path(deriv_root).resolve()),
            "config_path": str(Path(config_path).resolve()) if config_path else None,
            "dag_svg": str(Path(dag_path).resolve()) if dag_path else None,
        },
        "tools": {},
    }

    # Add SCT version if available
    if sct_version:
        prov["tools"]["sct"] = sct_version

    return prov


def derive_paths(
    deriv_root: str,
    sub: str,
    task: str,
    run: str,
    session: str | None = None,
) -> dict[str, str]:
    """
    Derive derivative file paths following BIDS-Derivatives naming.

    Args:
        deriv_root: Derivatives root directory
        sub: Subject ID (with or without 'sub-' prefix)
        task: Task label (with or without 'task-' prefix)
        run: Run number (with or without 'run-' prefix)
        session: Session label (optional)

    Returns:
        Dictionary of derivative file paths
    """
    # Normalize entity labels
    if not sub.startswith("sub-"):
        sub = f"sub-{sub}"
    if not task.startswith("task-"):
        task = f"task-{task}"
    if not run.startswith("run-"):
        run = f"run-{run}"

    # Build base directory
    deriv = Path(deriv_root)
    sub_dir = deriv / sub
    if session:
        if not session.startswith("ses-"):
            session = f"ses-{session}"
        func_dir = sub_dir / session / "func"
    else:
        func_dir = sub_dir / "func"

    # Build base filename
    base_parts = [sub]
    if session:
        base_parts.append(session)
    base_parts.extend([task, run])
    base_name = "_".join(base_parts)

    return {
        "confounds_tsv": str(func_dir / f"{base_name}_desc-confounds_timeseries.tsv"),
        "confounds_json": str(func_dir / f"{base_name}_desc-confounds_timeseries.json"),
        "motion_params_tsv": str(func_dir / f"{base_name}_desc-motion_params.tsv"),
        "motion_params_json": str(func_dir / f"{base_name}_desc-motion_params.json"),
        "motion_bold": str(func_dir / f"{base_name}_desc-motion_bold.nii.gz"),
        "mppca_bold": str(func_dir / f"{base_name}_desc-mppca_bold.nii.gz"),
    }


def write_provenance_json(data: dict[str, Any], out_path: Path) -> None:
    """
    Write provenance JSON file.

    Args:
        data: Provenance data dictionary
        out_path: Output file path
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(data, f, indent=2)


def build_intended_for(
    sources: list[str],
    deriv_root: str,
) -> list[str]:
    """
    Build IntendedFor field with relative BIDS paths.

    Args:
        sources: List of source file paths
        deriv_root: Derivatives root directory

    Returns:
        List of relative BIDS paths
    """
    # For MVP, just return the basenames
    # In future, compute proper relative paths from BIDS root
    intended = []
    for src in sources:
        # Extract BIDS-relative path (strip leading directories until sub-XX)
        path_parts = Path(src).parts
        sub_idx = next(
            (i for i, p in enumerate(path_parts) if p.startswith("sub-")), None
        )
        if sub_idx is not None:
            bids_rel = "/".join(path_parts[sub_idx:])
            intended.append(bids_rel)

    return intended


def write_dataset_description(
    deriv_root: Path,
    source_datasets: list[str],
) -> None:
    """
    Write dataset_description.json to derivatives root.

    Args:
        deriv_root: Derivatives root directory
        source_datasets: List of source BIDS dataset paths
    """
    desc = build_dataset_description(source_datasets, __version__)
    desc_path = deriv_root / "dataset_description.json"
    write_provenance_json(desc, desc_path)
