"""Temporal crop detection and IO utilities."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Dict, Optional, Union

import numpy as np

try:
    import pandas as pd

    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False


def detect_crop(
    confounds_tsv: Optional[str],
    bold_path: str,
    cord_mask: Optional[str],
    opts: Dict[str, Union[bool, int, float, str]],
) -> Dict[str, Union[int, str]]:
    """
    Detect temporal crop indices using robust z-statistics on cord ROI mean signal.

    Args:
        confounds_tsv: Path to confounds TSV file (optional)
        bold_path: Path to 4D BOLD NIfTI file
        cord_mask: Path to cord mask NIfTI file (optional)
        opts: Detection options with keys: enable, method, max_trim_start, max_trim_end, z_thresh

    Returns:
        Dictionary with keys: from, to, nvols, reason
    """
    if not opts.get("enable", True):
        # Return no cropping
        nvols = _get_nvols(bold_path)
        return {"from": 0, "to": nvols, "nvols": nvols, "reason": "disabled"}

    try:
        # Get number of volumes
        nvols = _get_nvols(bold_path)
        if nvols <= 0:
            return {"from": 0, "to": nvols, "nvols": nvols, "reason": "invalid_nvols"}

        # If we have confounds data, use its length instead of bold_path
        if confounds_tsv and Path(confounds_tsv).exists():
            if HAS_PANDAS:
                df = pd.read_csv(confounds_tsv, sep="\t")
                if "global_signal" in df.columns:
                    nvols = len(df)
            else:
                # Fallback: count lines in TSV
                with open(confounds_tsv, "r") as f:
                    nvols = sum(1 for line in f) - 1  # Subtract header

        # Compute per-volume mean signal
        if confounds_tsv and Path(confounds_tsv).exists():
            if HAS_PANDAS:
                # Use confounds global signal if available
                df = pd.read_csv(confounds_tsv, sep="\t")
                if "global_signal" in df.columns:
                    signal = df["global_signal"].values
                else:
                    signal = _compute_mean_signal(bold_path, cord_mask)
            else:
                # Fallback: read TSV manually
                signal = []
                with open(confounds_tsv, "r") as f:
                    lines = f.readlines()
                    header = lines[0].strip().split("\t")
                    if "global_signal" in header:
                        col_idx = header.index("global_signal")
                        for line in lines[1:]:
                            signal.append(float(line.strip().split("\t")[col_idx]))
                    else:
                        signal = _compute_mean_signal(bold_path, cord_mask)
        else:
            # Compute from BOLD data
            signal = _compute_mean_signal(bold_path, cord_mask)

        if len(signal) != nvols:
            # Signal length mismatch, use no cropping
            return {"from": 0, "to": nvols, "nvols": nvols, "reason": "signal_mismatch"}

        # Apply robust z-statistics detection
        z_thresh = opts.get("z_thresh", 2.5)
        max_trim_start = opts.get("max_trim_start", 10)
        max_trim_end = opts.get("max_trim_end", 10)

        crop_from, crop_to = _detect_crop_indices(
            signal, z_thresh, max_trim_start, max_trim_end
        )

        return {
            "from": crop_from,
            "to": crop_to,
            "nvols": nvols,
            "reason": "robust_z_detection",
        }

    except Exception as e:
        # Fallback to no cropping on any error
        nvols = _get_nvols(bold_path)
        return {"from": 0, "to": nvols, "nvols": nvols, "reason": f"error: {str(e)}"}


def _get_nvols(bold_path: str) -> int:
    """Get number of volumes in 4D NIfTI file."""
    try:
        result = subprocess.run(
            ["fslval", bold_path, "dim4"], capture_output=True, text=True, check=True
        )
        return int(result.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError):
        # Fallback: try to read with nibabel if available
        try:
            import nibabel as nib

            img = nib.load(bold_path)
            return img.shape[3] if len(img.shape) == 4 else 1
        except ImportError:
            # Ultimate fallback
            return 100


def _compute_mean_signal(bold_path: str, cord_mask: Optional[str]) -> np.ndarray:
    """Compute per-volume mean signal from BOLD data."""
    try:
        # Try to use FSL for fast computation
        if cord_mask and Path(cord_mask).exists():
            # Use cord mask if available
            cmd = ["fslmeants", "-i", bold_path, "-m", cord_mask]
        else:
            # Use whole brain
            cmd = ["fslmeants", "-i", bold_path]

        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        signal = np.array([float(x) for x in result.stdout.strip().split()])
        return signal

    except (subprocess.CalledProcessError, FileNotFoundError):
        # Fallback to nibabel
        try:
            import nibabel as nib

            img = nib.load(bold_path)
            data = img.get_fdata()

            if cord_mask and Path(cord_mask).exists():
                mask_img = nib.load(cord_mask)
                mask = mask_img.get_fdata() > 0
                signal = np.mean(data[mask], axis=0)
            else:
                signal = np.mean(data, axis=(0, 1, 2))

            return signal

        except ImportError:
            # Ultimate fallback: return zeros
            nvols = _get_nvols(bold_path)
            return np.zeros(nvols)


def _detect_crop_indices(
    signal: np.ndarray, z_thresh: float, max_trim_start: int, max_trim_end: int
) -> tuple[int, int]:
    """
    Detect crop indices using robust z-statistics.

    Args:
        signal: Per-volume mean signal
        z_thresh: Z-score threshold for outlier detection
        max_trim_start: Maximum volumes to trim from start
        max_trim_end: Maximum volumes to trim from end

    Returns:
        Tuple of (crop_from, crop_to) indices
    """
    nvols = len(signal)

    # Compute robust z-scores using median and MAD
    median = np.median(signal)
    mad = np.median(np.abs(signal - median))

    # If MAD is too small, use standard deviation as fallback
    if mad < 1e-6:
        std = np.std(signal)
        if std > 1e-6:
            z_scores = (signal - median) / std
        else:
            # No variation, no cropping needed
            return 0, nvols
    else:
        z_scores = 0.6745 * (signal - median) / mad  # 0.6745 = 1/1.4826 for normal MAD

    # Find leading outliers
    crop_from = 0
    for i in range(min(max_trim_start, nvols)):
        if abs(z_scores[i]) > z_thresh:
            crop_from = i + 1
        else:
            break

    # Find trailing outliers
    crop_to = nvols
    for i in range(min(max_trim_end, nvols)):
        idx = nvols - 1 - i
        if abs(z_scores[idx]) > z_thresh:
            crop_to = idx
        else:
            break

    # Ensure valid range
    crop_from = max(0, min(crop_from, nvols))
    crop_to = max(crop_from, min(crop_to, nvols))

    return crop_from, crop_to


def write_crop_json(out_path: str, info: Dict[str, Union[int, str]]) -> None:
    """Write crop information to JSON file."""
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(info, f, indent=2)


def read_crop_json(path: str) -> Dict[str, Union[int, str]]:
    """Read crop information from JSON file."""
    with open(path, "r") as f:
        return json.load(f)


def crop_sidecar_path(bold_path: str, deriv_root: str) -> str:
    """Generate crop sidecar path from BOLD path and derivatives root."""
    from pathlib import Path

    bold_file = Path(bold_path)
    # Extract subject, task, run from BOLD filename
    # Format: sub-XX_task-YY_run-ZZ_bold.nii.gz
    name_parts = bold_file.stem.split("_")
    sub = name_parts[0]  # sub-XX
    task = (
        name_parts[1]
        if len(name_parts) > 1 and name_parts[1].startswith("task-")
        else "task-unknown"
    )
    run = (
        name_parts[2]
        if len(name_parts) > 2 and name_parts[2].startswith("run-")
        else "run-01"
    )

    # Generate crop sidecar path
    crop_path = (
        f"{deriv_root}/sub-{sub.split('-')[1]}/func/{sub}_{task}_{run}_desc-crop.json"
    )
    return crop_path
