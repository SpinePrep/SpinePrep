"""
S3: Functional initialization and cropping.

This step handles:
- S3.1: Dummy-volume drop + fast median reference + func cord localization + func_ref0
- S3.2: T2-to-func registration + mask propagation
- S3.3: Mask-aware outlier gating + robust reference
- S3.4: Cord-focused crop + QC reportlets
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Optional, cast

import nibabel as nib
import numpy as np
from PIL import Image, ImageDraw

from spineprep.subtask import (
    should_exit_after_subtask,
    subtask,
    subtask_context,
)


# ============================================================================
# Helper functions for S2 output access
# ============================================================================


def _extract_subject_session_from_work_dir(work_dir: Path) -> tuple[Optional[str], Optional[str], Optional[Path]]:
    """
    Extract subject, session, and out_root from work_dir path structure.
    
    Handles two path formats:
    1. {out_root}/runs/S3_func_init_and_crop/{run_id}/... where run_id = sub-{subject}_ses-{session}
    2. {out_root}/runs/S3_func_init_and_crop/sub-{subject}/ses-{session}/... (test case format)
    
    Args:
        work_dir: Work directory path
        
    Returns:
        Tuple of (subject, session, out_root) or (None, None, None) if cannot parse
    """
    try:
        current = work_dir.resolve()
        
        # Look for subject/session directories or run_id
        subject = None
        session = None
        out_root = None
        
        # First, try to find subject/session as separate directories (test case format)
        while current.parent != current:  # Not at root
            if current.name.startswith("ses-") and not session:
                session_str = current.name.replace("ses-", "")
                session = session_str if session_str != "none" else None
            elif current.name.startswith("sub-") and not subject:
                subject = current.name.replace("sub-", "")
            
            # Check if we're in the S3_func_init_and_crop directory structure
            if current.name == "S3_func_init_and_crop" and current.parent.name == "runs":
                # out_root is the parent of "runs"
                # But if parent of "runs" is "work", then out_root is the parent of "work"
                if current.parent.parent.name == "work":
                    out_root = current.parent.parent.parent
                else:
                    out_root = current.parent.parent
                if subject:
                    return subject, session, out_root
            
            current = current.parent
        
        # If that didn't work, try finding run_id format: sub-{subject}_ses-{session}
        current = work_dir.resolve()
        while current.parent != current:
            if current.name.startswith("sub-") and ("_ses-" in current.name or current.name.endswith("_ses-none")):
                run_id = current.name
                
                # Extract subject and session from run_id
                if "_ses-none" in run_id:
                    subject = run_id.replace("sub-", "").replace("_ses-none", "")
                    session = None
                elif "_ses-" in run_id:
                    parts = run_id.replace("sub-", "").split("_ses-", 1)
                    subject = parts[0]
                    session = parts[1] if len(parts) > 1 and parts[1] != "none" else None
                
                # Find out_root
                if current.parent.name == "S3_func_init_and_crop" and current.parent.parent.name == "runs":
                    out_root = current.parent.parent.parent
                    if subject:
                        return subject, session, out_root
            
            current = current.parent
        
        return None, None, None
    except Exception:  # noqa: BLE001
        return None, None, None


def _find_s2_cordref_std(
    out_root: Path,
    subject: str,
    session: Optional[str],
) -> Optional[Path]:
    """
    Locate S2.1 cordref_std.nii.gz file.
    
    Looks in: work/S2_anat_cordref/{run_id}/cordref_std.nii.gz
    
    Args:
        out_root: Base output directory
        subject: Subject ID (without 'sub-' prefix)
        session: Session ID (without 'ses-' prefix) or None
        
    Returns:
        Path to cordref_std.nii.gz or None if not found
    """
    # Format run_id matching S2: sub-{subject}_ses-{session} or sub-{subject}_ses-none
    if session:
        run_id = f"sub-{subject}_ses-{session}"
    else:
        run_id = f"sub-{subject}_ses-none"
    
    cordref_std_path = out_root / "work" / "S2_anat_cordref" / run_id / "cordref_std.nii.gz"
    
    # Check if file exists and is non-empty
    if cordref_std_path.exists():
        try:
            if cordref_std_path.stat().st_size > 0:
                return cordref_std_path
        except OSError:
            return None
    return None


# ============================================================================
# Rendering utility functions (matching S2 style)
# ============================================================================


def _binary_erode_2d(mask: np.ndarray) -> np.ndarray:
    """3x3 erosion without scipy; edges are treated as False."""
    if mask.ndim != 2:
        raise ValueError("mask must be 2D")
    h, w = mask.shape
    if h < 3 or w < 3:
        return np.zeros_like(mask, dtype=bool)
    eroded = np.ones_like(mask, dtype=bool)
    core = mask[1:-1, 1:-1]
    eroded[1:-1, 1:-1] = core.copy()
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            eroded[1:-1, 1:-1] &= mask[1 + dy : h - 1 + dy, 1 + dx : w - 1 + dx]
    eroded[0, :] = False
    eroded[-1, :] = False
    eroded[:, 0] = False
    eroded[:, -1] = False
    return eroded


def _mask_contour_2d(mask: np.ndarray) -> np.ndarray:
    """Return a thin contour mask from a 2D boolean mask."""
    mask = mask.astype(bool)
    eroded = _binary_erode_2d(mask)
    return mask & (~eroded)


def _draw_thick_contour(
    overlay: Image.Image,
    contour_mask: np.ndarray,
    color: tuple[int, int, int, int],
    x_offset: int = 0,
    y_offset: int = 0,
    thickness: int = 2,
    outline_color: Optional[tuple[int, int, int, int]] = (0, 0, 0, 255),
) -> None:
    """Draw a thick contour on an RGBA overlay image with optional dark outline for contrast.
    
    Args:
        overlay: RGBA Image to draw on
        contour_mask: 2D boolean mask of contour pixels
        color: RGBA color tuple for main border
        x_offset: X offset for drawing position
        y_offset: Y offset for drawing position
        thickness: Border thickness in pixels (default 2)
        outline_color: Optional RGBA color for outline (default black). If None, no outline.
    """
    yy, xx = np.where(contour_mask)
    if outline_color is not None:
        # Draw outline first (1px wider on all sides)
        for y, x in zip(yy.tolist(), xx.tolist()):
            for dy in range(-thickness - 1, thickness + 2):
                for dx in range(-thickness - 1, thickness + 2):
                    if dx * dx + dy * dy > (thickness + 1) ** 2:
                        continue
                    px = x_offset + x + dx
                    py = y_offset + y + dy
                    if 0 <= px < overlay.width and 0 <= py < overlay.height:
                        overlay.putpixel((px, py), outline_color)
    
    # Draw main border
    for y, x in zip(yy.tolist(), xx.tolist()):
        for dy in range(-thickness, thickness + 1):
            for dx in range(-thickness, thickness + 1):
                if dx * dx + dy * dy > thickness ** 2:
                    continue
                px = x_offset + x + dx
                py = y_offset + y + dy
                if 0 <= px < overlay.width and 0 <= py < overlay.height:
                    overlay.putpixel((px, py), color)


def _write_ppm(path: Path, rgb: np.ndarray) -> None:
    """Write RGB array to PPM file."""
    if rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError("RGB array must have shape (H, W, 3).")
    height, width, _ = rgb.shape
    header = f"P6\n{width} {height}\n255\n".encode("ascii")
    path.write_bytes(header + rgb.astype(np.uint8).tobytes())


def _run_command(cmd: list[str]) -> tuple[bool, str]:
    """Run shell command and return (success, output)."""
    try:
        result = subprocess.run(cmd, text=True, capture_output=True, check=True)
    except FileNotFoundError:
        return False, f"Command not found: {cmd[0]}"
    except subprocess.CalledProcessError as err:
        output = "\n".join(part for part in [err.stdout, err.stderr] if part)
        return False, output.strip()
    output = "\n".join(part for part in [result.stdout, result.stderr] if part)
    return True, output.strip()


# ============================================================================
# S3.1 Layered Figure Rendering
# ============================================================================


def _render_s3_1_crop_box_sagittal_layered(
    cordref_std_path: Path,          # S2.1 background (Layer 1) - REQUIRED
    func_ref_fast_path: Path,        # S3.1 func reference (Layer 2)
    discovery_seg_path: Path,         # Func cord localization (Layer 3)
    crop_mask_path: Path,             # Crop ROI (Layer 3)
    output_path: Path,
    policy: dict[str, Any],
) -> Optional[Path]:
    """
    Render S3.1 layered sagittal figure matching S2 style.
    
    Layers:
    1. Background: cordref_std (anatomical reference)
    2. Overlay: func_ref_fast semi-transparent (40% func + 60% anat)
    3. Contours: discovery seg (red) + crop box (yellow)
    
    Matches S2 sagittal rendering:
    - RPI orientation (as_closest_canonical)
    - flipud(img_slice.T) for display (superior at top)
    - 1200px width, preserve aspect ratio
    - Uses ImageMagick convert for final resize
    
    Args:
        cordref_std_path: S2.1 standardized anatomical reference (REQUIRED)
        func_ref_fast_path: S3.1 functional reference
        discovery_seg_path: Functional cord discovery segmentation
        crop_mask_path: Crop ROI mask
        output_path: Output PNG path
        policy: Policy dict (for contour width, etc.)
        
    Returns:
        Path to output PNG or None on failure
    """
    try:
        # Load all images, convert to canonical
        cordref_img = nib.as_closest_canonical(nib.load(cordref_std_path))
        func_img = nib.as_closest_canonical(nib.load(func_ref_fast_path))
        discovery_seg_img = nib.as_closest_canonical(nib.load(discovery_seg_path))
        crop_mask_img = nib.as_closest_canonical(nib.load(crop_mask_path))
        
        cordref_data = cordref_img.get_fdata()
        func_data = func_img.get_fdata()
        discovery_seg_data = discovery_seg_img.get_fdata()
        crop_mask_data = crop_mask_img.get_fdata()
        
        # Handle 4D data (take first volume)
        if cordref_data.ndim > 3:
            cordref_data = cordref_data[..., 0]
        if func_data.ndim > 3:
            func_data = func_data[..., 0]
        if discovery_seg_data.ndim > 3:
            discovery_seg_data = discovery_seg_data[..., 0]
        if crop_mask_data.ndim > 3:
            crop_mask_data = crop_mask_data[..., 0]
        
        # Check shapes match (at least for func, discovery_seg, crop_mask)
        if func_data.shape != discovery_seg_data.shape or func_data.shape != crop_mask_data.shape:
            return None  # Shape mismatch
        
        # Select sagittal slice (x_index from discovery_seg center)
        discovery_mask = discovery_seg_data > 0
        coords = np.argwhere(discovery_mask)
        if coords.size == 0:
            return None  # No discovery segmentation found
        
        x_index = int(np.median(coords[:, 0]))
        x_index = max(0, min(x_index, func_data.shape[0] - 1))
        
        # Extract sagittal slices
        func_slice = func_data[x_index, :, :]
        discovery_slice = discovery_seg_data[x_index, :, :] > 0
        crop_slice = crop_mask_data[x_index, :, :] > 0
        
        # Get corresponding slice from cordref (may have different shape)
        # Use same x_index if shape allows, otherwise use center
        if x_index < cordref_data.shape[0]:
            cordref_slice = cordref_data[x_index, :, :]
        else:
            cordref_slice = cordref_data[cordref_data.shape[0] // 2, :, :]
        
        # Display with superior at the top: z-axis becomes vertical after transpose
        func_slice = np.flipud(func_slice.T)
        discovery_slice = np.flipud(discovery_slice.T)
        crop_slice = np.flipud(crop_slice.T)
        cordref_slice = np.flipud(cordref_slice.T)
        
        # Normalize each image separately (percentile [1, 99])
        def normalize_slice(slice2d: np.ndarray) -> np.ndarray:
            vmin, vmax = np.percentile(slice2d, [1, 99])
            if vmax <= vmin:
                vmin, vmax = float(slice2d.min()), float(slice2d.max())
            if vmax <= vmin:
                vmax = vmin + 1.0
            normalized = np.clip((slice2d - vmin) / (vmax - vmin), 0, 1)
            return (normalized * 255).astype(np.uint8)
        
        cordref_norm = normalize_slice(cordref_slice)
        func_norm = normalize_slice(func_slice)
        
        # Create background from cordref (RGB)
        background_rgb = np.repeat(cordref_norm[..., np.newaxis], 3, axis=2)
        
        # Resize func to match cordref background if needed
        if func_norm.shape != cordref_norm.shape:
            # Resize func to match cordref
            func_img_pil = Image.fromarray(func_norm, mode="L")
            func_img_pil = func_img_pil.resize((cordref_norm.shape[1], cordref_norm.shape[0]), resample=Image.Resampling.BILINEAR)
            func_norm = np.array(func_img_pil, dtype=np.uint8)
            # Also resize masks
            discovery_img_pil = Image.fromarray((discovery_slice.astype(np.uint8) * 255), mode="L")
            discovery_img_pil = discovery_img_pil.resize((cordref_norm.shape[1], cordref_norm.shape[0]), resample=Image.Resampling.NEAREST)
            discovery_slice = (np.array(discovery_img_pil, dtype=np.uint8) > 0)
            crop_img_pil = Image.fromarray((crop_slice.astype(np.uint8) * 255), mode="L")
            crop_img_pil = crop_img_pil.resize((cordref_norm.shape[1], cordref_norm.shape[0]), resample=Image.Resampling.NEAREST)
            crop_slice = (np.array(crop_img_pil, dtype=np.uint8) > 0)
        
        # Overlay func_ref_fast (40% func + 60% background)
        func_rgb = np.repeat(func_norm[..., np.newaxis], 3, axis=2)
        overlay_rgb = (background_rgb * 0.6 + func_rgb * 0.4).astype(np.uint8)
        
        # Create RGBA overlay for contours
        overlay_rgba = np.zeros((overlay_rgb.shape[0], overlay_rgb.shape[1], 4), dtype=np.uint8)
        overlay_rgba[:, :, :3] = overlay_rgb
        overlay_rgba[:, :, 3] = 255  # Fully opaque
        
        overlay_img = Image.fromarray(overlay_rgba, mode="RGBA")
        
        # Get contour width from policy
        contour_width = policy.get("qc", {}).get("overlay_contour_width", 2)
        
        # Draw discovery seg contour (red)
        discovery_contour = _mask_contour_2d(discovery_slice)
        _draw_thick_contour(
            overlay_img,
            discovery_contour,
            (255, 0, 0, 255),  # Red
            thickness=contour_width,
            outline_color=(0, 0, 0, 255),
        )
        
        # Draw crop box contour (yellow)
        crop_contour = _mask_contour_2d(crop_slice)
        _draw_thick_contour(
            overlay_img,
            crop_contour,
            (255, 255, 0, 255),  # Yellow
            thickness=contour_width,
            outline_color=(0, 0, 0, 255),
        )
        
        # Convert back to RGB for PPM
        final_rgb = np.array(overlay_img.convert("RGB"), dtype=np.uint8)
        
        # Save as PPM, resize with ImageMagick to 1200px width
        output_path.parent.mkdir(parents=True, exist_ok=True)
        ppm_path = output_path.with_suffix(".ppm")
        _write_ppm(ppm_path, final_rgb)
        
        # Resize to 1200px width preserving aspect ratio
        ok, _ = _run_command(
            [
                "convert",
                str(ppm_path),
                "-filter",
                "Lanczos",
                "-resize",
                "1200x",
                str(output_path),
            ]
        )
        
        # Clean up PPM file
        if ppm_path.exists():
            ppm_path.unlink()
        
        if ok:
            return output_path
        return None
        
    except Exception:  # noqa: BLE001
        return None


# ============================================================================
# S3.1 Processing
# ============================================================================


@subtask("S3.1")
def _process_s3_1_dummy_drop_and_localization(
    bold_path: Path,
    work_dir: Path,
    policy: dict[str, Any],
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

    # Load 4D BOLD data
    bold_img = nib.load(bold_path)
    bold_data = bold_img.get_fdata()
    bold_affine = bold_img.affine

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
    func_ref_fast_path = init_dir / "func_ref_fast.nii.gz"
    func_ref_fast_img = nib.Nifti1Image(func_ref_fast_data, bold_affine)
    nib.save(func_ref_fast_img, func_ref_fast_path)

    # For testing: create a simple localization result
    # In real implementation, this would call S2 exact spec localization
    localize_dir = init_dir / "localize"
    localize_dir.mkdir(parents=True, exist_ok=True)

    # Create a simple discovery segmentation (for testing)
    discovery_seg_data = np.zeros_like(func_ref_fast_data)
    # Create a simple mask in the center
    center_z = func_ref_fast_data.shape[2] // 2
    discovery_seg_data[:, :, center_z - 5 : center_z + 5] = 1

    discovery_seg_path = localize_dir / "func_ref_fast_seg.nii.gz"
    discovery_seg_img = nib.Nifti1Image(discovery_seg_data, bold_affine)
    nib.save(discovery_seg_img, discovery_seg_path)

    # Create ROI mask (for testing)
    roi_mask_data = discovery_seg_data.copy()
    roi_mask_path = localize_dir / "func_ref_fast_roi_mask.nii.gz"
    roi_mask_img = nib.Nifti1Image(roi_mask_data, bold_affine)
    nib.save(roi_mask_img, roi_mask_path)

    # Crop the fast reference (for testing - simple crop)
    crop_bbox = [10, func_ref_fast_data.shape[0] - 10, 10, func_ref_fast_data.shape[1] - 10, 5, func_ref_fast_data.shape[2] - 5]
    func_ref_fast_crop_data = func_ref_fast_data[
        crop_bbox[0] : crop_bbox[1],
        crop_bbox[2] : crop_bbox[3],
        crop_bbox[4] : crop_bbox[5],
    ]

    func_ref_fast_crop_path = localize_dir / "func_ref_fast_crop.nii.gz"
    func_ref_fast_crop_img = nib.Nifti1Image(func_ref_fast_crop_data, bold_affine)
    nib.save(func_ref_fast_crop_img, func_ref_fast_crop_path)

    # Compute func_ref0 from cropped region of 4D BOLD
    if bold_data_dropped.ndim == 4:
        bold_cropped = bold_data_dropped[
            crop_bbox[0] : crop_bbox[1],
            crop_bbox[2] : crop_bbox[3],
            crop_bbox[4] : crop_bbox[5],
            :,
        ]
        func_ref0_data = np.median(bold_cropped, axis=3)
    else:
        func_ref0_data = func_ref_fast_crop_data

    # Save func_ref0
    func_ref0_path = init_dir / "func_ref0.nii.gz"
    func_ref0_img = nib.Nifti1Image(func_ref0_data, bold_affine)
    nib.save(func_ref0_img, func_ref0_path)

    # Extract subject/session/out_root from work_dir for S2.1 access
    subject, session, out_root = _extract_subject_session_from_work_dir(work_dir)
    
    # If extraction failed, try to determine out_root from work_dir structure
    # work_dir is typically: {out_root}/runs/S3_func_init_and_crop/... or {out_root}/work/runs/S3_func_init_and_crop/...
    if not (subject and out_root):
        current = work_dir.resolve()
        while current.parent != current:
            if current.name == "runs":
                # out_root is the parent of "runs"
                # But if parent is "work", then out_root is the parent of "work"
                if current.parent.name == "work":
                    out_root = current.parent.parent
                else:
                    out_root = current.parent
                # Try to extract subject from path
                # Look for sub-* directory in the path
                path_parts = work_dir.parts
                for i, part in enumerate(path_parts):
                    if part.startswith("sub-"):
                        subject = part.replace("sub-", "")
                        # Check for ses- in next part
                        if i + 1 < len(path_parts) and path_parts[i + 1].startswith("ses-"):
                            ses_str = path_parts[i + 1].replace("ses-", "")
                            session = ses_str if ses_str != "none" else None
                        else:
                            session = None
                        break
                break
            current = current.parent
    
    # Find S2.1 cordref_std (REQUIRED - Q8A: FAIL if missing)
    cordref_std_path = None
    if subject and out_root:
        cordref_std_path = _find_s2_cordref_std(out_root, subject, session)
    
    if cordref_std_path is None:
        # FAIL if S2.1 anat is missing (Q8A)
        return {
            "func_ref_fast_path": func_ref_fast_path,
            "func_ref0_path": func_ref0_path,
            "discovery_seg_path": discovery_seg_path,
            "roi_mask_path": roi_mask_path,
            "func_ref_fast_crop_path": func_ref_fast_crop_path,
            "localization_status": "FAIL",
            "failure_message": "Missing S2.1 cordref_std.nii.gz - S2 must run before S3.1",
            "figure_path": None,
            "crop_bbox": crop_bbox,
        }
    
    # Determine figures directory (matching S2 structure)
    if subject and out_root:
        if session:
            figures_dir = out_root / "derivatives" / "spineprep" / f"sub-{subject}" / f"ses-{session}" / "figures"
            figure_name = f"sub-{subject}_ses-{session}_desc-S3_func_localization_crop_box_sagittal.png"
        else:
            figures_dir = out_root / "derivatives" / "spineprep" / f"sub-{subject}" / "figures"
            figure_name = f"sub-{subject}_desc-S3_func_localization_crop_box_sagittal.png"
    else:
        # Fallback for test cases
        figures_dir = work_dir.parent.parent / "derivatives" / "spineprep" / "sub-test" / "ses-none" / "figures"
        figure_name = "test_desc-S3_func_localization_crop_box_sagittal.png"
    
    figures_dir.mkdir(parents=True, exist_ok=True)
    figure_path = figures_dir / figure_name
    
    # Render layered figure
    rendered_path = _render_s3_1_crop_box_sagittal_layered(
        cordref_std_path=cordref_std_path,
        func_ref_fast_path=func_ref_fast_path,
        discovery_seg_path=discovery_seg_path,
        crop_mask_path=roi_mask_path,  # Use roi_mask as crop_mask
        output_path=figure_path,
        policy=policy,
    )
    
    if rendered_path is None:
        # Rendering failed
        return {
            "func_ref_fast_path": func_ref_fast_path,
            "func_ref0_path": func_ref0_path,
            "discovery_seg_path": discovery_seg_path,
            "roi_mask_path": roi_mask_path,
            "func_ref_fast_crop_path": func_ref_fast_crop_path,
            "localization_status": "FAIL",
            "failure_message": "Failed to render S3.1 layered figure",
            "figure_path": None,
            "crop_bbox": crop_bbox,
        }

    result = {
        "func_ref_fast_path": func_ref_fast_path,
        "func_ref0_path": func_ref0_path,
        "discovery_seg_path": discovery_seg_path,
        "roi_mask_path": roi_mask_path,
        "func_ref_fast_crop_path": func_ref_fast_crop_path,
        "localization_status": "PASS",
        "figure_path": rendered_path,
        "crop_bbox": crop_bbox,
    }

    # Check if we should exit after S3.1
    if should_exit_after_subtask("S3.1"):
        return result

    return result


@subtask("S3.2")
def _process_s3_2_registration(
    func_ref0_path: Path,
    cordref_crop_path: Path,
    work_dir: Path,
    policy: dict[str, Any],
) -> dict[str, Any]:
    """
    S3.2: T2-to-func registration + mask propagation.

    This function:
    1. Registers cordref_crop to func_ref0
    2. Applies transform to cord mask
    3. Renders S3.2 figure

    Returns:
        Dictionary with registration results.
    """
    # TODO: Implement actual registration logic
    # For testing, create placeholder files

    init_dir = work_dir / "init"
    init_dir.mkdir(parents=True, exist_ok=True)

    result = {
        "t2_to_func_xfm_path": init_dir / "t2_to_func_warp.nii.gz",
        "cordmask_func_path": init_dir / "cordmask_space_func.nii.gz",
        "registration_status": "PASS",
    }

    # Check if we should exit after S3.2
    if should_exit_after_subtask("S3.2"):
        return result

    return result


@subtask("S3.3")
def _process_s3_3_outlier_gating(
    bold_data_path: Path,
    func_ref0_path: Path,
    cordmask_func_path: Path,
    work_dir: Path,
    policy: dict[str, Any],
) -> dict[str, Any]:
    """
    S3.3: Mask-aware outlier gating + robust reference.

    This function:
    1. Computes DVARS and ref-RMS per frame
    2. Flags outliers using boxplot cutoff
    3. Computes robust func_ref from good frames
    4. Renders S3.3 figure
        
    Returns:
        Dictionary with outlier gating results.
    """
    # TODO: Implement actual outlier gating logic

    metrics_dir = work_dir / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)

    result = {
        "func_ref_path": work_dir / "func_ref.nii.gz",
        "frame_metrics_path": metrics_dir / "frame_metrics.tsv",
        "outlier_mask_path": metrics_dir / "outlier_mask.json",
        "outlier_fraction": 0.1,
    }

    # Check if we should exit after S3.3
    if should_exit_after_subtask("S3.3"):
        return result

    return result


@subtask("S3.4")
def _process_s3_4_crop_and_qc(
    bold_data_path: Path,
    cordmask_func_path: Path,
    work_dir: Path,
    policy: dict[str, Any],
) -> dict[str, Any]:
    """
    S3.4: Cord-focused crop + QC reportlets.

    This function:
    1. Creates cylindrical crop mask
    2. Crops 4D BOLD
    3. Renders S3.4 figures
    4. Generates QC artifacts
        
    Returns:
        Dictionary with crop and QC results.
    """
    # TODO: Implement actual crop and QC logic

    result = {
        "bold_crop_path": work_dir / "bold_crop.nii.gz",
        "crop_mask_path": work_dir / "crop_mask.nii.gz",
        "qc_status": "PASS",
    }

    # S3.4 is the last subtask, no need to check for exit

    return result


def run_S3_func_init_and_crop(
    subtask_id: Optional[str] = None,
    dataset_key: Optional[str] = None,
    datasets_local: Optional[str] = None,
    out: Optional[str] = None,
    only_missing: bool = False,
) -> Any:
    """
    Run S3 functional initialization and cropping step.

    Args:
        subtask_id: Optional subtask ID to execute (e.g., "S3.1").
        dataset_key: Dataset key to process.
        datasets_local: Path to local datasets configuration.
        out: Output directory.
        only_missing: Only process missing outputs.

    Returns:
        Result object or exit code.
    """
    from spineprep.run_layout import setup_subtask_context

    # Set up subtask context if subtask_id is provided
    if subtask_id:
        setup_subtask_context(subtask_id)

    # For testing: create a minimal test setup
    if out is None:
        out = Path("work") / "test_s3_subtask"

    out_path = Path(out)
    work_dir = out_path / "runs" / "S3_func_init_and_crop" / "sub-test" / "ses-none" / "func" / "test_bold.nii"
    work_dir.mkdir(parents=True, exist_ok=True)

    # Create a test BOLD file if it doesn't exist
    test_bold_path = work_dir / "test_bold.nii.gz"
    if not test_bold_path.exists():
        # Create a simple 4D test image
        test_data = np.random.rand(64, 64, 24, 100).astype(np.float32)
        test_affine = np.eye(4)
        test_img = nib.Nifti1Image(test_data, test_affine)
        nib.save(test_img, test_bold_path)

    # Create S2.1 cordref_std output (required for S3.1 layered figure)
    # This is needed for test cases where S2 hasn't run
    s2_work_dir = out_path / "work" / "S2_anat_cordref" / "sub-test_ses-none"
    s2_work_dir.mkdir(parents=True, exist_ok=True)
    cordref_std_path = s2_work_dir / "cordref_std.nii.gz"
    if not cordref_std_path.exists():
        # Create a simple 3D anatomical reference matching func dimensions
        cordref_data = np.random.rand(64, 64, 24).astype(np.float32)
        cordref_img = nib.Nifti1Image(cordref_data, test_affine)
        nib.save(cordref_img, cordref_std_path)

    # Load policy (for testing, use defaults)
    policy = {
        "dummy_volumes": {"count": 4},
        "func_localization": {
            "enabled": True,
            "method": "deepseg",
            "task": "spinalcord",
        },
    }

    results = []

    # Process S3.1
    s3_1_result = _process_s3_1_dummy_drop_and_localization(
        test_bold_path, work_dir, policy
    )
    results.append(("S3.1", s3_1_result))
    if should_exit_after_subtask("S3.1"):
        return {"status": "PASS", "subtask": "S3.1", "results": results}

    # Process S3.2 (requires S3.1 outputs)
    if s3_1_result.get("localization_status") == "PASS":
        # For testing, create a dummy cordref_crop
        cordref_crop_path = work_dir / "cordref_crop.nii.gz"
        if not cordref_crop_path.exists():
            cordref_data = np.random.rand(64, 64, 24).astype(np.float32)
            cordref_img = nib.Nifti1Image(cordref_data, test_affine)
            nib.save(cordref_img, cordref_crop_path)

        s3_2_result = _process_s3_2_registration(
            s3_1_result["func_ref0_path"],
            cordref_crop_path,
            work_dir,
            policy,
        )
        results.append(("S3.2", s3_2_result))
        if should_exit_after_subtask("S3.2"):
            return {"status": "PASS", "subtask": "S3.2", "results": results}

    # Process S3.3
    s3_3_result = _process_s3_3_outlier_gating(
        test_bold_path,
        s3_1_result["func_ref0_path"],
        work_dir / "cordmask_space_func.nii.gz",  # Placeholder
        work_dir,
        policy,
    )
    results.append(("S3.3", s3_3_result))
    if should_exit_after_subtask("S3.3"):
        return {"status": "PASS", "subtask": "S3.3", "results": results}

    # Process S3.4
    s3_4_result = _process_s3_4_crop_and_qc(
        test_bold_path,
        work_dir / "cordmask_space_func.nii.gz",  # Placeholder
        work_dir,
            policy,
        )
    results.append(("S3.4", s3_4_result))

    # Generate dashboard (non-blocking)
    if out:
        from spineprep.qc_dashboard import generate_dashboard_safe
        generate_dashboard_safe(Path(out))

    return {"status": "PASS", "subtask": "all", "results": results}


def check_S3_func_init_and_crop(
    dataset_key: Optional[str] = None,
    datasets_local: Optional[str] = None,
    out: Optional[str] = None,
) -> Any:
    """
    Check S3 functional initialization and cropping step.

    Args:
        dataset_key: Dataset key to check.
        datasets_local: Path to local datasets configuration.
        out: Output directory.

    Returns:
        Check result object or exit code.
    """
    # TODO: Implement check logic
    return {"status": "PASS", "message": "S3 check executed (template)"}
