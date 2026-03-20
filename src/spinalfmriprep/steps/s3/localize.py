"""S3.1: Dummy drop, fast median reference, cord localization, func_ref0."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import nibabel as nib
import numpy as np
from PIL import Image, ImageDraw

from spinalfmriprep.lib.run import run_command as _run_command
from spinalfmriprep.subtask import (
    should_exit_after_subtask,
    subtask,
    subtask_context,
)

from .io import _extract_subject_session_from_work_dir
from .reportlets import _write_ppm


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
# S3.1 simple func-with-mask figure
# ---------------------------------------------------------------------------


def _render_s3_1_simple_func_with_mask(
    func_path: Path,
    mask_path: Path,
    output_path: Path,
    policy: dict[str, Any],
    crop_box: Optional[list[int]] = None,
    padding_mm: float = 0.0,
) -> Optional[Path]:
    """
    Render simple S3.1 figure: functional image with cord mask (BLUE) and crop box (RED).

    Args:
        func_path: Path to functional reference image
        mask_path: Path to cord mask in functional space
        output_path: Output PNG path
        policy: Policy dict
        crop_box: Optional crop box coordinates [r_min, r_max, c_min, c_max, s_min, s_max]

    Returns:
        Path to output PNG or None on failure
    """
    try:
        # Load images
        func_img = nib.as_closest_canonical(nib.load(func_path))
        mask_img = nib.as_closest_canonical(nib.load(mask_path))

        func_data = func_img.get_fdata()
        mask_data = mask_img.get_fdata()

        # Handle 4D
        if func_data.ndim > 3:
            func_data = func_data[..., 0]
        if mask_data.ndim > 3:
            mask_data = mask_data[..., 0]

        # Find center sagittal slice from mask
        mask_binary = mask_data > 0
        coords = np.argwhere(mask_binary)
        if coords.size == 0:
            # Fallback to center
            x_index = func_data.shape[0] // 2
        else:
            x_index = int(np.median(coords[:, 0]))

        # Clip x_index to valid range for both volumes
        x_index = max(0, min(x_index, func_data.shape[0] - 1, mask_data.shape[0] - 1))

        # Extract sagittal slices
        func_slice = func_data[x_index, :, :]
        # Check alignment logic skipped for simplicity/speed (assume same space)

        # Rotate func for display (superior at top)
        func_slice = np.flipud(func_slice.T)

        # Determine mask placement in func slice using affines
        inv_func_affine = np.linalg.inv(func_img.affine)

        # Create mask overlay array matching func_slice shape
        aligned_mask = np.zeros_like(func_slice, dtype=bool)

        # Physical coordinates of all mask voxels
        mask_voxels = np.argwhere(mask_data > 0)
        if mask_voxels.size > 0:
            # Physical coords
            phys_coords = nib.affines.apply_affine(mask_img.affine, mask_voxels)
            # Func voxel coords
            func_voxels = nib.affines.apply_affine(inv_func_affine, phys_coords)
            func_voxels = np.round(func_voxels).astype(int)

            # Filter voxels in the current sagittal slice (x_index)
            in_slice = func_voxels[func_voxels[:, 0] == x_index]

            for vox in in_slice:
                # vox is (x, y, z) in RAS functional space
                _, c, s = vox
                # After flipud(T) on (P-A, I-S) slice:
                # height = S-I, width = P-A
                row = func_data.shape[2] - 1 - s
                col = c
                if 0 <= row < func_slice.shape[0] and 0 <= col < func_slice.shape[1]:
                    aligned_mask[row, col] = True

        # Normalize func
        vmin, vmax = np.percentile(func_slice, [1, 99])
        if vmax <= vmin:
            vmax = vmin + 1.0
        func_norm = np.clip((func_slice - vmin) / (vmax - vmin), 0, 1)
        func_uint8 = (func_norm * 255).astype(np.uint8)

        # Create RGB background
        background_rgb = np.repeat(func_uint8[..., np.newaxis], 3, axis=2)

        # Convert to RGBA for transparency
        img = Image.fromarray(background_rgb, mode="RGB").convert("RGBA")

        # Create transparent BLUE overlay for mask (S2.1 match)
        if aligned_mask.any():
            mask_overlay = np.zeros((*aligned_mask.shape, 4), dtype=np.uint8)
            # Blue: R=0, G=100, B=200, A=180
            mask_overlay[:, :, 0] = 0
            mask_overlay[:, :, 1] = 100
            mask_overlay[:, :, 2] = 200
            mask_overlay[:, :, 3] = (aligned_mask.astype(np.uint8) * 180)
            mask_pil = Image.fromarray(mask_overlay, mode="RGBA")
            img = Image.alpha_composite(img, mask_pil)


        # Draw Red Crop Box if provided OR if padding_mm > 0 (computed from aligned mask)
        # S2.1 match or S3.3 robust crop
        box_to_draw = None

        if crop_box:
             # crop_box = [r_min, r_max, c_min, c_max, s_min, s_max]
             # sagittal view corresponds to c (cols/y) and s (slices/z)
             c_min, c_max = crop_box[2], crop_box[3]
             s_min, s_max = crop_box[4], crop_box[5]

             # Map to display coordinates (flipud T)
             height = func_slice.shape[0]

             y_min_disp = height - 1 - s_max
             y_max_disp = height - 1 - s_min
             x_min_disp = c_min
             x_max_disp = c_max

             box_to_draw = [(x_min_disp, y_min_disp), (x_max_disp, y_max_disp)]

        elif padding_mm > 0 and aligned_mask.any():
             mask_coords = np.argwhere(aligned_mask)
             if mask_coords.size > 0:
                 r_min, c_min = mask_coords.min(axis=0)
                 r_max, c_max = mask_coords.max(axis=0)

                 zooms = func_img.header.get_zooms()
                 py_mm = zooms[2]  # Z
                 px_mm = zooms[1]  # Y

                 pad_y = int(padding_mm / py_mm)
                 pad_x = int(padding_mm / px_mm)

                 r_min = max(0, r_min - pad_y)
                 r_max = min(aligned_mask.shape[0]-1, r_max + pad_y)

                 c_min = max(0, c_min - pad_x)
                 c_max = min(aligned_mask.shape[1]-1, c_max + pad_x)

                 box_to_draw = [(c_min, r_min), (c_max, r_max)]

        if box_to_draw:
             draw = ImageDraw.Draw(img)
             draw.rectangle(
                 box_to_draw,
                 outline=(255, 0, 0, 255),
                 width=1
             )

        # Convert back to RGB for saving
        img = img.convert("RGB")

        # Save
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Aspect Ratio Correction
        try:
           zooms = func_img.header.get_zooms()
           dy, dz = zooms[1], zooms[2]  # Sagittal view: y (width), z (height)
           if dy > 0:
               ratio = dz / dy
               if abs(ratio - 1.0) > 0.1:  # Only correct if significantly anisotropic
                   w, h = img.size
                   new_h = int(h * ratio)
                   img = img.resize((w, new_h), resample=Image.Resampling.NEAREST)
        except Exception as e:
            pass  # Aspect ratio correction skipped

        # Use ImageMagick for resize
        ppm_path = output_path.with_suffix(".ppm")
        _write_ppm(ppm_path, np.array(img))

        ok, _ = _run_command([
            "convert", str(ppm_path),
            "-filter", "Point",
            "-resize", "1200x",
            str(output_path)
        ])

        if ppm_path.exists():
            ppm_path.unlink()

        if ok and output_path.exists():
            return output_path
        return None

    except Exception as e:
        pass  # S3.1 figure render error
        return None


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
              "localization_status": "PASS",
              "failure_message": None,
              "figure_path": fig_path,
              "crop_bbox": crop_bbox,
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


    result = {
        "func_ref_fast_path": func_ref_fast_path,
        "func_ref0_path": func_ref0_path,
        "discovery_seg_path": discovery_seg_path,
        "roi_mask_path": roi_mask_path,
        "discovery_seg_crop_path": discovery_seg_crop_path,  # Cropped mask for S3.2/S3.3
        "func_ref_fast_crop_path": func_ref_fast_crop_path,
        "func_bold_coarse_path": func_bold_coarse_path,
        "localization_status": "PASS",
        "figure_path": rendered_path,
        "crop_bbox": crop_bbox,
    }

    # Check if we should exit after S3.1
    if should_exit_after_subtask("S3.1"):
        return result

    return result
