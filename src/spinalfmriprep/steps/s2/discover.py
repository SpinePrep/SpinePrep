"""S2.1: cord discovery, standardization, cropping."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, cast

import nibabel as nib
import numpy as np

from .io import _run_command


def _select_cordref(candidates: list[dict], preference: list[str]) -> Optional[dict]:
    if not candidates:
        return None
    by_modality: dict[str, list[dict]] = {}
    for cand in candidates:
        by_modality.setdefault(cand["modality"], []).append(cand)
    for modality in preference:
        if modality in by_modality:
            return sorted(by_modality[modality], key=lambda c: c["path"])[0]
    return sorted(candidates, key=lambda c: c["path"])[0]


def _standardize_orientation(source: Path, dest: Path, orientation: str) -> tuple[bool, str]:
    return _run_command(["sct_image", "-i", str(source), "-setorient", orientation, "-o", str(dest)])


def _run_discovery_segmentation(
    standard_path: Path,
    discovery_seg_path: Path,
    contrast: str,
    min_z_slices: int,
    method: str,
    task: Optional[str] = None,
) -> tuple[bool, str]:
    """
    Run discovery segmentation on standardized image to find cord location.

    Args:
        standard_path: Path to standardized input image
        discovery_seg_path: Path to output discovery segmentation
        contrast: Contrast string (e.g., "t2", "t1") - used for sct_deepseg_sc
        min_z_slices: Minimum number of z-slices required in segmentation
        method: Discovery method ("sct_deepseg_sc" or "deepseg")
        task: Task name for deepseg method (e.g., "spinalcord") - required when method="deepseg"

    Returns:
        (success, error_message) tuple
    """
    if method == "deepseg":
        # Use sct_deepseg with task parameter (contrast-agnostic)
        if not task:
            return False, "discover.task is required when discover.method='deepseg'"
        cmd = [
            "sct_deepseg",
            str(task),
            "-i",
            str(standard_path),
            "-o",
            str(discovery_seg_path),
        ]
    elif method == "sct_deepseg_sc":
        # Use sct_deepseg_sc with contrast parameter
        cmd = [
            "sct_deepseg_sc",
            "-i",
            str(standard_path),
            "-c",
            str(contrast),
            "-o",
            str(discovery_seg_path),
        ]
    else:
        return False, f"Unknown discovery method: {method}"

    ok, message = _run_command(cmd)
    if not ok:
        return False, f"Discovery segmentation failed: {message}"

    # Validate min_z_slices requirement
    if not discovery_seg_path.exists():
        return False, "Discovery segmentation output not found"

    try:
        img = cast(Any, nib.load(discovery_seg_path))
        data = img.get_fdata()
        if data.ndim > 3:
            data = data[..., 0]
        mask = data > 0
        slice_counts = mask.sum(axis=(0, 1))
        slice_present = slice_counts > 0
        num_slices = int(slice_present.sum())

        if num_slices < min_z_slices:
            return False, (
                f"Discovery segmentation has {num_slices} slices, "
                f"but minimum {min_z_slices} slices required"
            )
    except Exception as e:
        return False, f"Failed to validate discovery segmentation: {e}"

    return True, ""


def _crop_based_on_mask(
    standard_path: Path,
    discovery_seg_path: Path,
    cropped_path: Path,
    crop_mask_path: Path,
    mask_diameter_mm: float,
    dilate_xyz: list[int],
    min_z_slices: int,
) -> tuple[bool, str]:
    """
    Crop standardized image based on discovered cord segmentation using SCT tools.

    This follows SCT best practice:
    1. Create a cylindrical mask centered on the cord centerline
    2. Crop the image using the mask

    Args:
        standard_path: Path to standardized input image
        discovery_seg_path: Path to discovery segmentation (used for centerline)
        cropped_path: Path to output cropped image
        crop_mask_path: Path to output crop mask (work dir, for QC)
        mask_diameter_mm: Diameter of the cylindrical mask in mm
        dilate_xyz: Dilation margins in voxels [x, y, z]
        min_z_slices: Minimum number of z-slices required in cropped image

    Returns:
        (success, error_message) tuple
    """
    # Step 1: Create crop mask using sct_create_mask with centerline method
    ok, message = _run_command(
        [
            "sct_create_mask",
            "-i",
            str(standard_path),
            "-p",
            f"centerline,{discovery_seg_path}",
            "-size",
            f"{mask_diameter_mm}mm",
            "-f",
            "cylinder",
            "-o",
            str(crop_mask_path),
        ]
    )
    if not ok:
        return False, f"Crop mask creation failed: {message}"

    if not crop_mask_path.exists():
        return False, "Crop mask output not found"

    # Step 2: Crop image using sct_crop_image with the mask
    dilate_str = f"{dilate_xyz[0]}x{dilate_xyz[1]}x{dilate_xyz[2]}"
    ok, message = _run_command(
        [
            "sct_crop_image",
            "-i",
            str(standard_path),
            "-m",
            str(crop_mask_path),
            "-dilate",
            dilate_str,
            "-o",
            str(cropped_path),
        ]
    )
    if not ok:
        return False, f"Image cropping failed: {message}"

    if not cropped_path.exists():
        return False, "Cropped image output not found"

    # Step 3: Validate min_z_slices requirement
    try:
        img = cast(Any, nib.load(cropped_path))
        data = img.get_fdata()
        if data.ndim > 3:
            data = data[..., 0]
        num_z_slices = data.shape[2]

        if num_z_slices < min_z_slices:
            return False, (
                f"Cropped image has {num_z_slices} z-slices, "
                f"but minimum {min_z_slices} slices required"
            )
    except Exception as e:
        return False, f"Failed to validate cropped image: {e}"

    return True, ""
