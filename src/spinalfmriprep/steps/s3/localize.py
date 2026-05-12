"""S3.1: Dummy drop, fast median reference, cord localization, func_ref0."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import nibabel as nib
import numpy as np

from spinalfmriprep.lib.run import run_command as _run_command
from spinalfmriprep.subtask import (
    should_exit_after_subtask,
    subtask,
    subtask_context,
)

from .io import _extract_subject_session_from_work_dir
from .localize_viz import _render_s3_1_simple_func_with_mask  # noqa: F401


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _check_drift_gate(
    disc_data: np.ndarray,
    affine: np.ndarray,
    policy: dict[str, Any],
) -> tuple[bool, str, dict]:
    """Detect brain contamination in a cord segmentation.

    Spinal cord cross-sectional area is ~50-80 mm² cervical; once a segmentation
    leaks into the brain the per-slice area jumps by an order of magnitude. Two
    cheap checks on the most-superior `n_check` cord slices catch this:

    - absolute cap: any of those slices exceeds `absolute_area_cap_mm2`
    - spike ratio: top slice area / immediately-inferior slice area > `area_spike_threshold`

    Returns (passed, message, info-dict). `info` carries per-slice areas so
    the QC log can show why a run was rejected.
    """
    drift_cfg = (
        policy.get("func_localization", {})
        .get("discover", {})
        .get("drift_gate", {})
    )
    if not drift_cfg.get("enabled", True):
        return True, "drift_gate disabled", {}

    n_check = int(drift_cfg.get("superior_slices_check", 5))
    spike_ratio = float(drift_cfg.get("area_spike_threshold", 4.0))
    abs_cap_mm2 = float(drift_cfg.get("absolute_area_cap_mm2", 200.0))

    # Find the inferior-superior axis from the affine
    try:
        axcodes = nib.orientations.aff2axcodes(affine)
    except Exception:
        return True, "could not read orientation; drift_gate skipped", {}

    is_axis = None
    s_is_positive = None
    for i, c in enumerate(axcodes):
        if c == "S":
            is_axis, s_is_positive = i, True
            break
        if c == "I":
            is_axis, s_is_positive = i, False
            break
    if is_axis is None:
        return True, "no IS axis; drift_gate skipped", {}

    # Per-slice (along IS axis) area in mm²
    voxel_sizes = np.sqrt((affine[:3, :3] ** 2).sum(axis=0))
    in_plane = [i for i in (0, 1, 2) if i != is_axis]
    voxel_area_mm2 = float(voxel_sizes[in_plane[0]] * voxel_sizes[in_plane[1]])

    sum_axes = tuple(in_plane)
    slice_areas_mm2 = ((disc_data > 0).sum(axis=sum_axes) * voxel_area_mm2).astype(float)

    nonzero = np.where(slice_areas_mm2 > 0)[0]
    if nonzero.size == 0:
        return False, "empty segmentation", {"slice_areas_mm2": slice_areas_mm2.tolist()}

    # Order superior-to-inferior
    if s_is_positive:
        superior_zs = nonzero[-n_check:][::-1].tolist()
    else:
        superior_zs = nonzero[:n_check].tolist()

    info = {
        "slice_areas_mm2": slice_areas_mm2.tolist(),
        "is_axis": int(is_axis),
        "s_is_positive": bool(s_is_positive),
        "thresholds": {
            "absolute_area_cap_mm2": abs_cap_mm2,
            "area_spike_threshold": spike_ratio,
            "superior_slices_check": n_check,
        },
        "checked_slices": [int(z) for z in superior_zs],
    }

    # Absolute cap: any superior slice with area > cap is brain
    for z in superior_zs:
        a = slice_areas_mm2[z]
        if a > abs_cap_mm2:
            return (
                False,
                f"brain detected: slice z={int(z)} area {a:.1f} mm² > cap {abs_cap_mm2:.0f} mm²",
                info,
            )

    # Spike: top slice vs the slice immediately inferior to it
    if len(superior_zs) >= 1:
        for z in superior_zs:
            below_z = z - 1 if s_is_positive else z + 1
            if 0 <= below_z < slice_areas_mm2.size:
                below = slice_areas_mm2[below_z]
                top = slice_areas_mm2[z]
                if below > 0 and top / below > spike_ratio:
                    return (
                        False,
                        f"brain detected: area spike at z={int(z)} "
                        f"({top:.1f}/{below:.1f} = {top / below:.2f}× > {spike_ratio:.1f}×)",
                        info,
                    )

    return True, "ok", info


def _create_dummy_discovery(data: np.ndarray, affine: np.ndarray, seg_path: Path, roi_path: Path) -> None:
    """Fallback: Center-of-image dummy discovery."""
    discovery_seg_data = np.zeros_like(data)
    center_x = data.shape[0] // 2
    center_y = data.shape[1] // 2
    center_z = data.shape[2] // 2

    # Create a central box detection (approx 20x20x10 voxels)
    # This prevents the "horizontal bar" (full slice slab) appearance
    x_r, y_r, z_r = 10, 10, 5

    x_min, x_max = max(0, center_x - x_r), min(data.shape[0], center_x + x_r)
    y_min, y_max = max(0, center_y - y_r), min(data.shape[1], center_y + y_r)
    z_min, z_max = max(0, center_z - z_r), min(data.shape[2], center_z + z_r)

    discovery_seg_data[x_min:x_max, y_min:y_max, z_min:z_max] = 1

    nib.save(nib.Nifti1Image(discovery_seg_data, affine), seg_path)
    nib.save(nib.Nifti1Image(discovery_seg_data, affine), roi_path)


# ---------------------------------------------------------------------------
# S3.1 main processing function
# ---------------------------------------------------------------------------


@subtask("S3.1")
def _process_s3_1_dummy_drop_and_localization(
    bold_path: Path,
    work_dir: Path,
    policy: dict[str, Any],
    subject: Optional[str] = None,
    session: Optional[str] = None,
    out_root: Optional[Path] = None,
    cordref_std_path: Optional[Path] = None,
    cordmask_dseg_path: Optional[Path] = None,
    run_id: Optional[str] = None,
) -> dict[str, Any]:
    """
    S3.1: Dummy-volume drop + fast median reference + func cord localization + func_ref0.

    This function:
    1. Drops dummy volumes per policy
    2. Computes func_ref_fast (median of all frames)
    3. Localizes cord in func space (S2 exact spec)
    4. Computes func_ref0 from cropped region
    5. Renders S3.1 figure

    Returns:
        Dictionary with results including func_ref_fast, func_ref0, localization results.
    """
    # Create init directory
    init_dir = work_dir / "init"
    init_dir.mkdir(parents=True, exist_ok=True)

    # Define expected output paths
    func_ref_fast_path = init_dir / "func_ref_fast.nii.gz"
    func_ref0_path = init_dir / "func_ref0.nii.gz"
    localize_dir = init_dir / "localize"
    localize_dir.mkdir(parents=True, exist_ok=True)
    discovery_seg_path = localize_dir / "func_ref_fast_seg.nii.gz"
    roi_mask_path = localize_dir / "func_ref_fast_roi_mask.nii.gz"
    func_bold_coarse_path = init_dir / "func_bold_coarse.nii.gz"
    func_ref_fast_crop_path = localize_dir / "func_ref_fast_crop.nii.gz"

    ok = False
    out = ""

    # OPTIMIZATION: Check if S3.1 heavy outputs already exist to avoid expensive re-computation
    if func_ref_fast_path.exists() and discovery_seg_path.exists() and func_bold_coarse_path.exists():
         # Load func_ref_fast_data for bbox calculation/clipping limits
         func_ref_fast_img_tmp = nib.load(func_ref_fast_path)
         func_ref_fast_data = func_ref_fast_img_tmp.get_fdata()

         # Re-calculate bbox from discovery seg (fast, robust)
         disc_img = nib.load(discovery_seg_path)
         disc_data = disc_img.get_fdata()

         # Drift gate: reject runs where the segmentation has leaked into the brain.
         gate_ok, gate_msg, gate_info = _check_drift_gate(disc_data, disc_img.affine, policy)

         coords = np.argwhere(disc_data > 0)
         if coords.size > 0:
             pad_xy = 10
             pad_z = 0
             r_min, c_min, s_min = coords.min(axis=0) - [pad_xy, pad_xy, pad_z]
             r_max, c_max, s_max = coords.max(axis=0) + [pad_xy, pad_xy, pad_z]
             r_min, r_max = max(0, r_min), min(func_ref_fast_data.shape[0], r_max)
             c_min, c_max = max(0, c_min), min(func_ref_fast_data.shape[1], c_max)
             s_min, s_max = max(0, s_min), min(func_ref_fast_data.shape[2], s_max)
             crop_bbox = [int(r_min), int(r_max), int(c_min), int(c_max), int(s_min), int(s_max)]
         else:
             crop_bbox = None

         # Reconstruct figure path for dashboard consistency
         figure_prefix = run_id if run_id else (f"sub-{subject}_ses-{session}" if session else f"sub-{subject}")
         if out_root:
             fig_path = out_root / "derivatives" / "spinalfmriprep" / f"sub-{subject}" / (f"ses-{session}" if session else "") / "figures" / f"{figure_prefix}_desc-S3_func_localization_crop_box_sagittal.png"
         else:
             fig_path = None

         return {
              "func_ref_fast_path": func_ref_fast_path,
              "func_ref0_path": func_ref0_path,
              "discovery_seg_path": discovery_seg_path,
              "roi_mask_path": roi_mask_path,
              "func_ref_fast_crop_path": func_ref_fast_crop_path,
              "func_bold_coarse_path": func_bold_coarse_path,
              "discovery_seg_crop_path": localize_dir / "func_ref_fast_seg_crop.nii.gz",
              "localization_status": "PASS" if gate_ok else "FAIL",
              "failure_message": None if gate_ok else f"S3.1 drift gate: {gate_msg}",
              "figure_path": fig_path,
              "crop_bbox": crop_bbox,
              "drift_gate_info": gate_info,
         }

    # ELSE: Heavy Computation - Restore Logic

    # Load BOLD data
    bold_img = nib.load(bold_path)
    bold_affine = bold_img.affine
    bold_data = bold_img.get_fdata()

    # Get dummy volume count from policy
    dummy_volumes = policy.get("dummy_volumes", {}).get("count", 4)

    # Drop dummy volumes
    if bold_data.ndim == 4:
        bold_data_dropped = bold_data[:, :, :, dummy_volumes:]
    else:
            bold_data_dropped = bold_data

    # Compute func_ref_fast (median of all frames)
    if bold_data_dropped.ndim == 4:
        func_ref_fast_data = np.median(bold_data_dropped, axis=3)
    else:
        func_ref_fast_data = bold_data_dropped

    # Save func_ref_fast
    func_ref_fast_img = nib.Nifti1Image(func_ref_fast_data, bold_affine)
    nib.save(func_ref_fast_img, func_ref_fast_path)

    # Save func_ref0 (first volume)
    if bold_data_dropped.ndim == 4:
        func_ref0_data = bold_data_dropped[:, :, :, 0]
    else:
        func_ref0_data = bold_data_dropped
    func_ref0_img = nib.Nifti1Image(func_ref0_data, bold_affine)
    nib.save(func_ref0_img, func_ref0_path)

    # Real Localization: Contrast-agnostic model (SCT 7.x syntax)
    cmd_seg = [
        "sct_deepseg", "spinalcord",
        "-i", str(func_ref_fast_path),
        "-o", str(discovery_seg_path),
        "-largest", "1",
        "-qc", str(work_dir / "qc"),
        "-v", "0",
    ]
    ok, out = _run_command(cmd_seg)

    if ok and discovery_seg_path.exists():
         roi_mask_path = discovery_seg_path
    else:
         return {
             "func_ref_fast_path": func_ref_fast_path,
             "func_ref0_path": init_dir / "func_ref0.nii.gz",
             "discovery_seg_path": discovery_seg_path,
             "roi_mask_path": roi_mask_path,
             "func_ref_fast_crop_path": localize_dir / "func_ref_fast_crop.nii.gz",
             "localization_status": "FAIL",
             "failure_message": f"sct_deepseg seg_sc_contrast_agnostic failed: {out}",
             "figure_path": None,
             "crop_bbox": None,
         }

    # Calculate crop_bbox from discovery segmentation
    try:
        disc_img = nib.load(discovery_seg_path)
        disc_data = disc_img.get_fdata()
        coords = np.argwhere(disc_data > 0)
        if coords.size > 0:
            # ROI = bbox of cord pixels + padding
            pad_xy = 10  # 10 voxels padding around cord (approx 20mm total margin)
            pad_z = 0    # No Z padding
            r_min, c_min, s_min = coords.min(axis=0) - [pad_xy, pad_xy, pad_z]
            r_max, c_max, s_max = coords.max(axis=0) + [pad_xy, pad_xy, pad_z]

            # Clip to image bounds
            r_min, r_max = max(0, r_min), min(func_ref_fast_data.shape[0], r_max)
            c_min, c_max = max(0, c_min), min(func_ref_fast_data.shape[1], c_max)
            s_min, s_max = max(0, s_min), min(func_ref_fast_data.shape[2], s_max)

            crop_bbox = [int(r_min), int(r_max), int(c_min), int(c_max), int(s_min), int(s_max)]
        else:
             crop_bbox = [0, func_ref_fast_data.shape[0], 0, func_ref_fast_data.shape[1], 0, func_ref_fast_data.shape[2]]
    except Exception:
         crop_bbox = [0, func_ref_fast_data.shape[0], 0, func_ref_fast_data.shape[1], 0, func_ref_fast_data.shape[2]]

    # Crop the fast reference for func_ref_fast_crop_path
    func_ref_fast_crop_data = func_ref_fast_data[
        crop_bbox[0] : crop_bbox[1],
        crop_bbox[2] : crop_bbox[3],
        crop_bbox[4] : crop_bbox[5],
    ]
    func_ref_fast_crop_path = localize_dir / "func_ref_fast_crop.nii.gz"
    crop_affine = bold_affine.copy()
    crop_affine[:3, 3] = nib.affines.apply_affine(bold_affine, [crop_bbox[0], crop_bbox[2], crop_bbox[4]])
    nib.save(nib.Nifti1Image(func_ref_fast_crop_data, crop_affine), func_ref_fast_crop_path)


    # Save CROPPED discovery seg (EXACT match for crop_bbox)
    discovery_seg_crop_data = disc_data[
        crop_bbox[0] : crop_bbox[1],
        crop_bbox[2] : crop_bbox[3],
        crop_bbox[4] : crop_bbox[5],
    ]
    discovery_seg_crop_path = localize_dir / "func_ref_fast_seg_crop.nii.gz"
    nib.save(nib.Nifti1Image(discovery_seg_crop_data, crop_affine), discovery_seg_crop_path)

    # Compute func_ref0 from cropped region of 4D BOLD
    if bold_data_dropped.ndim == 4:
        bold_cropped = bold_data_dropped[
            crop_bbox[0] : crop_bbox[1],
            crop_bbox[2] : crop_bbox[3],
            crop_bbox[4] : crop_bbox[5],
            :,
        ]
        func_ref0_data = np.median(bold_cropped, axis=3)

        # Save coarse cropped BOLD (input for S3.3/S3.4)
        func_bold_coarse_path = init_dir / "func_bold_coarse.nii.gz"
        # Fix affine for crop
        new_affine = bold_affine.copy()
        new_affine[:3, 3] = nib.affines.apply_affine(bold_affine, [crop_bbox[0], crop_bbox[2], crop_bbox[4]])
        nib.save(nib.Nifti1Image(bold_cropped, new_affine), func_bold_coarse_path)
    else:
        func_ref0_data = func_ref_fast_crop_data
        func_bold_coarse_path = init_dir / "func_bold_coarse.nii.gz"
        # Handle 3D case
        new_affine = bold_affine.copy()
        new_affine[:3, 3] = nib.affines.apply_affine(bold_affine, [crop_bbox[0], crop_bbox[2], crop_bbox[4]])
        nib.save(nib.Nifti1Image(func_ref_fast_crop_data, new_affine), func_bold_coarse_path)

    # Save func_ref0
    func_ref0_path = init_dir / "func_ref0.nii.gz"
    func_ref0_img = nib.Nifti1Image(func_ref0_data, new_affine)  # Use corrected affine
    nib.save(func_ref0_img, func_ref0_path)

    # Try to use provided context, else extract
    if not (subject and out_root):
        extracted_sub, extracted_ses, extracted_root = _extract_subject_session_from_work_dir(work_dir)
        if not subject:
            subject = extracted_sub
        if not session:
            session = extracted_ses
        if not out_root:
            out_root = extracted_root

    # Determine figures directory (matching S2 structure)
    # Use run_id if available for unique per-run filenames
    if subject and out_root:
        if session:
            figures_dir = out_root / "derivatives" / "spinalfmriprep" / f"sub-{subject}" / f"ses-{session}" / "figures"
        else:
            figures_dir = out_root / "derivatives" / "spinalfmriprep" / f"sub-{subject}" / "figures"
        # Use run_id for unique filenames per functional run
        figure_prefix = run_id if run_id else (f"sub-{subject}_ses-{session}" if session else f"sub-{subject}")
        figure_name = f"{figure_prefix}_desc-S3_func_localization_crop_box_sagittal.png"
    else:
        # Fallback for test cases
        figures_dir = work_dir.parent.parent / "derivatives" / "spinalfmriprep" / "sub-test" / "ses-none" / "figures"
        figure_name = "test_desc-S3_func_localization_crop_box_sagittal.png"

    figures_dir.mkdir(parents=True, exist_ok=True)
    figure_path = figures_dir / figure_name

    # Generate S3.1 Figure immediately
    rendered_path = _render_s3_1_simple_func_with_mask(
        func_ref_fast_path,
        discovery_seg_path,
        figure_path,
        policy,
        crop_box=crop_bbox,
    )

    if rendered_path is None:
        return {
            "func_ref_fast_path": func_ref_fast_path,
            "func_ref0_path": func_ref0_path,
            "discovery_seg_path": discovery_seg_path,
            "roi_mask_path": roi_mask_path,
            "func_ref_fast_crop_path": func_ref_fast_crop_path,
            "localization_status": "FAIL",
            "failure_message": "Failed to render S3.1 figure",
            "figure_path": None,
            "crop_bbox": crop_bbox,
        }


    # Drift gate: reject runs where the discovery has leaked into the brain.
    gate_ok, gate_msg, gate_info = _check_drift_gate(disc_data, disc_img.affine, policy)

    result = {
        "func_ref_fast_path": func_ref_fast_path,
        "func_ref0_path": func_ref0_path,
        "discovery_seg_path": discovery_seg_path,
        "roi_mask_path": roi_mask_path,
        "discovery_seg_crop_path": discovery_seg_crop_path,  # Cropped mask for S3.2/S3.3
        "func_ref_fast_crop_path": func_ref_fast_crop_path,
        "func_bold_coarse_path": func_bold_coarse_path,
        "localization_status": "PASS" if gate_ok else "FAIL",
        "failure_message": None if gate_ok else f"S3.1 drift gate: {gate_msg}",
        "figure_path": rendered_path,
        "crop_bbox": crop_bbox,
        "drift_gate_info": gate_info,
    }

    # Check if we should exit after S3.1
    if should_exit_after_subtask("S3.1"):
        return result

    return result
