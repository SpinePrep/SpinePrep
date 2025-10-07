"""Confounds computation utilities for SpinePrep."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional

import numpy as np
import pandas as pd

try:
    import nibabel as nib

    HAS_NIBABEL = True
except ImportError:
    HAS_NIBABEL = False


def read_motion_params(tsv_path: str) -> np.ndarray:
    """
    Read motion parameters from TSV file.

    Args:
        tsv_path: Path to motion parameters TSV file

    Returns:
        Array of shape (T, 6) with columns: trans_x, trans_y, trans_z, rot_x, rot_y, rot_z

    Raises:
        FileNotFoundError: If file doesn't exist
        ValueError: If file format is invalid
    """
    if not Path(tsv_path).exists():
        raise FileNotFoundError(f"Motion parameters file not found: {tsv_path}")

    try:
        df = pd.read_csv(tsv_path, sep="\t")
        required_cols = ["trans_x", "trans_y", "trans_z", "rot_x", "rot_y", "rot_z"]

        if not all(col in df.columns for col in required_cols):
            raise ValueError(
                f"Missing required columns. Expected: {required_cols}, got: {list(df.columns)}"
            )

        # Extract the 6 motion parameters
        params = df[required_cols].values.astype(np.float64)
        return params

    except Exception as e:
        raise ValueError(f"Failed to read motion parameters from {tsv_path}: {e}")


def compute_fd_from_params(params: np.ndarray, tr_s: float = 1.0) -> np.ndarray:
    """
    Compute Framewise Displacement (Power) from motion parameters.

    Args:
        params: Motion parameters array of shape (T, 6) with columns:
                trans_x, trans_y, trans_z, rot_x, rot_y, rot_z
        tr_s: Repetition time in seconds (for rotation scaling)

    Returns:
        Array of shape (T,) with FD values. First volume has FD=0.
    """
    if params.shape[1] != 6:
        raise ValueError(f"Expected 6 motion parameters, got {params.shape[1]}")

    n_vols = params.shape[0]
    fd = np.zeros(n_vols)

    # Compute FD for volumes 1 to T-1
    for t in range(1, n_vols):
        # Translation differences (in mm)
        trans_diff = params[t, :3] - params[t - 1, :3]

        # Rotation differences (convert to mm using 50mm radius)
        rot_diff = params[t, 3:] - params[t - 1, 3:]
        rot_diff_mm = rot_diff * 50.0  # 50mm radius assumption

        # Power FD = sqrt(sum of squared differences)
        fd[t] = np.sqrt(np.sum(trans_diff**2) + np.sum(rot_diff_mm**2))

    return fd


def compute_dvars(bold_path: str, mask_path: Optional[str] = None) -> np.ndarray:
    """
    Compute DVARS from BOLD data.

    Args:
        bold_path: Path to 4D BOLD NIfTI file
        mask_path: Optional path to brain mask (if None, uses whole brain)

    Returns:
        Array of shape (T,) with DVARS values. First volume has DVARS=0.
    """
    if not HAS_NIBABEL:
        raise ImportError("nibabel is required for DVARS computation")

    if not Path(bold_path).exists():
        raise FileNotFoundError(f"BOLD file not found: {bold_path}")

    # Load BOLD data
    img = nib.load(bold_path)
    data = img.get_fdata()

    if len(data.shape) != 4:
        raise ValueError(f"Expected 4D BOLD data, got {len(data.shape)}D")

    n_vols = data.shape[3]
    dvars = np.zeros(n_vols)

    # Apply mask if provided
    if mask_path and Path(mask_path).exists():
        mask_img = nib.load(mask_path)
        mask = mask_img.get_fdata().astype(bool)
        if mask.shape != data.shape[:3]:
            raise ValueError(
                f"Mask shape {mask.shape} doesn't match BOLD shape {data.shape[:3]}"
            )
    else:
        # Use whole brain (non-zero voxels)
        mask = np.any(data != 0, axis=3)

    # Compute DVARS for volumes 1 to T-1
    for t in range(1, n_vols):
        # Voxelwise difference between consecutive volumes
        diff = data[:, :, :, t] - data[:, :, :, t - 1]

        # DVARS = sqrt(mean of squared differences) within mask
        masked_diff = diff[mask]
        if len(masked_diff) > 0:
            dvars[t] = np.sqrt(np.mean(masked_diff**2))
        else:
            dvars[t] = 0.0

    return dvars


def assemble_confounds(
    fd: np.ndarray, dvars: np.ndarray, extra: Optional[Dict] = None
) -> pd.DataFrame:
    """
    Assemble confounds DataFrame from FD and DVARS.

    Args:
        fd: Framewise displacement array
        dvars: DVARS array
        extra: Optional dictionary of additional confounds

    Returns:
        DataFrame with at least 'framewise_displacement' and 'dvars' columns
    """
    if len(fd) != len(dvars):
        raise ValueError(
            f"FD and DVARS arrays must have same length: {len(fd)} vs {len(dvars)}"
        )

    # Create base DataFrame
    df = pd.DataFrame({"framewise_displacement": fd, "dvars": dvars})

    # Add extra confounds if provided
    if extra:
        for key, value in extra.items():
            if isinstance(value, (list, np.ndarray)) and len(value) == len(fd):
                df[key] = value
            elif isinstance(value, (int, float)):
                df[key] = value

    return df


def write_confounds_tsv_json(
    df: pd.DataFrame, out_tsv: str, out_json: str, meta: Dict
) -> None:
    """
    Write confounds TSV and JSON files.

    Args:
        df: Confounds DataFrame
        out_tsv: Output TSV file path
        out_json: Output JSON file path
        meta: Metadata dictionary for JSON sidecar
    """
    # Ensure output directories exist
    Path(out_tsv).parent.mkdir(parents=True, exist_ok=True)
    Path(out_json).parent.mkdir(parents=True, exist_ok=True)

    # Write TSV
    df.to_csv(out_tsv, sep="\t", index=False)

    # Write JSON metadata
    with open(out_json, "w") as f:
        json.dump(meta, f, indent=2)


def build_censor(fd: np.ndarray, dvars: np.ndarray, cfg: Dict) -> Dict:
    """
    Build censor vector based on FD and DVARS thresholds with contiguity rules.

    Args:
        fd: Framewise displacement array
        dvars: DVARS array
        cfg: Censor configuration dict with keys:
             - fd_thresh_mm: FD threshold in mm
             - dvars_thresh: DVARS threshold
             - min_contig_vols: minimum consecutive non-censored volumes
             - pad_vols: padding around censored frames

    Returns:
        Dict with keys:
        - censor: binary array (1=censored, 0=kept)
        - keep_mask: boolean array (True=kept, False=censored)
        - kept_segments: list of [start, end] tuples for kept runs
        - n_censored: number of censored frames
        - n_kept: number of kept frames
    """
    if len(fd) != len(dvars):
        raise ValueError(
            f"FD and DVARS must have same length: {len(fd)} vs {len(dvars)}"
        )

    n_vols = len(fd)
    fd_thresh = cfg["fd_thresh_mm"]
    dvars_thresh = cfg["dvars_thresh"]
    min_contig = cfg["min_contig_vols"]
    pad_vols = cfg["pad_vols"]

    # Step 1: Initial censoring based on thresholds
    censor = ((fd > fd_thresh) | (dvars > dvars_thresh)).astype(int)

    # Step 2: Apply padding around censored frames
    if pad_vols > 0:
        censor_padded = censor.copy()
        for i in range(n_vols):
            if censor[i] == 1:
                # Pad before
                start_pad = max(0, i - pad_vols)
                censor_padded[start_pad:i] = 1
                # Pad after
                end_pad = min(n_vols, i + pad_vols + 1)
                censor_padded[i + 1 : end_pad] = 1
        censor = censor_padded

    # Step 3: Remove short kept segments that violate min_contig_vols
    if min_contig > 1:
        # Find runs of kept frames (0s in censor array)
        kept_runs = []
        in_run = False
        run_start = 0

        for i in range(n_vols):
            if censor[i] == 0:  # kept frame
                if not in_run:
                    run_start = i
                    in_run = True
            else:  # censored frame
                if in_run:
                    run_length = i - run_start
                    if run_length >= min_contig:
                        kept_runs.append((run_start, i))
                    else:
                        # Mark short runs as censored
                        censor[run_start:i] = 1
                    in_run = False

        # Handle case where run extends to end
        if in_run:
            run_length = n_vols - run_start
            if run_length >= min_contig:
                kept_runs.append((run_start, n_vols))
            else:
                censor[run_start:] = 1
    else:
        # No contiguity requirement - all kept segments are valid
        kept_runs = []
        in_run = False
        run_start = 0

        for i in range(n_vols):
            if censor[i] == 0:  # kept frame
                if not in_run:
                    run_start = i
                    in_run = True
            else:  # censored frame
                if in_run:
                    kept_runs.append((run_start, i))
                    in_run = False

        # Handle case where run extends to end
        if in_run:
            kept_runs.append((run_start, n_vols))

    # Create boolean mask for kept frames
    keep_mask = censor == 0

    return {
        "censor": censor,
        "keep_mask": keep_mask,
        "kept_segments": kept_runs,
        "n_censored": int(censor.sum()),
        "n_kept": int((1 - censor).sum()),
    }


def append_censor_columns(df: pd.DataFrame, censor_dict: Dict) -> pd.DataFrame:
    """
    Append censor columns to confounds DataFrame.

    Args:
        df: Base confounds DataFrame
        censor_dict: Output from build_censor()

    Returns:
        DataFrame with additional 'frame_censor' column
    """
    df_out = df.copy()
    df_out["frame_censor"] = censor_dict["censor"]

    # Ensure canonical column order
    canonical_cols = ["framewise_displacement", "dvars", "frame_censor"]
    other_cols = [col for col in df_out.columns if col not in canonical_cols]
    df_out = df_out[canonical_cols + other_cols]

    return df_out
