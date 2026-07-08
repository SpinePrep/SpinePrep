"""Rendering helpers for S3 QC reportlets."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import nibabel as nib
import numpy as np
import matplotlib.pyplot as plt
from PIL import Image, ImageDraw

from spineprep.lib.run import run_command as _run_command


# ---------------------------------------------------------------------------
# Low-level drawing utilities — delegated to lib/image.py
# ---------------------------------------------------------------------------
from spineprep.lib.image import binary_erode_2d as _binary_erode_2d  # noqa: E402, F401
from spineprep.lib.image import mask_contour_2d as _mask_contour_2d  # noqa: E402, F401
from spineprep.lib.image import draw_thick_contour as _draw_thick_contour  # noqa: E402, F401


def _write_ppm(path: Path, rgb: np.ndarray) -> None:
    """Write RGB array to PPM file."""
    if rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError("RGB array must have shape (H, W, 3).")
    height, width, _ = rgb.shape
    header = f"P6\n{width} {height}\n255\n".encode("ascii")
    path.write_bytes(header + rgb.astype(np.uint8).tobytes())


def normalize_slice(slice2d: np.ndarray) -> np.ndarray:
    """Normalize a 2-D image slice to [0, 1] using percentile clipping."""
    vmin, vmax = np.percentile(slice2d, [1, 99])
    if vmax <= vmin:
        vmin, vmax = float(slice2d.min()), float(slice2d.max())
    if vmax <= vmin:
        vmax = vmin + 1.0
    normalized = np.clip((slice2d - vmin) / (vmax - vmin), 0, 1)
    return normalized


# ---------------------------------------------------------------------------
# Layered sagittal figure (cordref + func + discovery seg + crop box)
# ---------------------------------------------------------------------------


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
    2. Overlay: func_ref_fast (pure func overlay)
    3. Overlays: discovery seg (blue solid transparent) + crop box (red thin border)

    Matches S2 sagittal rendering:
    - RPI orientation (as_closest_canonical)
    - flipud(img_slice.T) for display (superior at top)
    - 1200px width, preserve aspect ratio
    - Uses ImageMagick convert for final resize
    - Layer 3 exactly matches S2.1 style (blue overlay + red rectangle)

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

        cordref_norm = (normalize_slice(cordref_slice) * 255).astype(np.uint8)
        func_norm_float = normalize_slice(func_slice)

        # Create background from cordref (RGB)
        background_rgb = np.repeat(cordref_norm[..., np.newaxis], 3, axis=2)

        # Resize func to match cordref background if needed
        if func_norm_float.shape != cordref_norm.shape:
            # Resize func to match cordref
            func_img_pil = Image.fromarray((func_norm_float * 255).astype(np.uint8), mode="L")
            func_img_pil = func_img_pil.resize((cordref_norm.shape[1], cordref_norm.shape[0]), resample=Image.Resampling.NEAREST)
            func_norm_float = np.array(func_img_pil, dtype=np.float32) / 255.0

            # Also resize masks
            discovery_img_pil = Image.fromarray((discovery_slice.astype(np.uint8) * 255), mode="L")
            discovery_img_pil = discovery_img_pil.resize((cordref_norm.shape[1], cordref_norm.shape[0]), resample=Image.Resampling.NEAREST)
            discovery_slice = (np.array(discovery_img_pil, dtype=np.uint8) > 0)
            crop_img_pil = Image.fromarray((crop_slice.astype(np.uint8) * 255), mode="L")
            crop_img_pil = crop_img_pil.resize((cordref_norm.shape[1], cordref_norm.shape[0]), resample=Image.Resampling.NEAREST)
            crop_slice = (np.array(crop_img_pil, dtype=np.uint8) > 0)

        # Layer 2: Overlay func_ref_fast (using magma colormap)
        # Apply colormap to normalized float data [0, 1]
        func_rgba_mapped = plt.cm.magma(func_norm_float)  # Returns RGBA [0, 1]
        func_rgb = (func_rgba_mapped[:, :, :3] * 255).astype(np.uint8)

        # Start with background
        overlay_img_array = background_rgb.astype(np.float32)

        # Additive blend of colormap overlay (scaled for visibility)
        blend_weight = 0.5  # 50% blend
        overlay_img_array = (1.0 - blend_weight) * overlay_img_array + blend_weight * func_rgb.astype(np.float32)
        overlay_img_array = np.clip(overlay_img_array, 0, 255).astype(np.uint8)

        # Convert to PIL for drawing overlays
        overlay_img = Image.fromarray(overlay_img_array, mode="RGB").convert("RGBA")

        # Layer 3: Draw discovery segmentation as solid transparent overlay (blue) - exactly like S2.1
        if discovery_slice is not None and discovery_slice.any():
            # Create mask overlay: fill actual cord mask pixels with blue transparency
            mask_array = discovery_slice.astype(np.uint8) * 180  # Alpha for ~70% opacity
            blue_overlay = np.zeros((*discovery_slice.shape, 4), dtype=np.uint8)
            blue_overlay[:, :, 0] = 0      # R
            blue_overlay[:, :, 1] = 100    # G
            blue_overlay[:, :, 2] = 200    # B
            blue_overlay[:, :, 3] = mask_array  # A (alpha - only where mask is True)

            # Convert to PIL Image and composite
            mask_pil = Image.fromarray(blue_overlay, mode="RGBA")
            overlay_img = Image.alpha_composite(overlay_img, mask_pil)

        # Draw crop box as thin rectangular border (red) - exactly like S2.1
        if crop_slice is not None and crop_slice.any():
            # Compute bounding box of crop mask
            coords = np.argwhere(crop_slice)
            if coords.size > 0:
                y_min, z_min = coords.min(axis=0)
                y_max, z_max = coords.max(axis=0)

                # Draw thick rectangular border (2px thick)
                draw = ImageDraw.Draw(overlay_img)
                # PIL rectangle expects [x0, y0, x1, y1] or [(x0, y0), (x1, y1)]
                # Our indexing is (row, col) = (y, z) in sagittal
                draw.rectangle(
                    [(z_min, y_min), (z_max, y_max)],
                    outline=(255, 0, 0, 255),  # Red
                    width=2,
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
                "Point",
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


# ---------------------------------------------------------------------------
# T2-to-func overlay (side-by-side sagittal: S2 anatomy vs S3 func ref)
# ---------------------------------------------------------------------------


def _render_t2_to_func_overlay(
    func_ref_path: Path,
    cordref_std_path: Optional[Path],
    cordmask_func_path: Path,
    output_path: Path,
    n_slices: int = 9,
    tile_size: int = 128,
) -> None:
    """Render T2-to-func overlay: side-by-side sagittal views of S2 anatomy and S3 func ref.

    Left panel: mid-sagittal of S2 cordref_std (anatomical reference).
    Right panel: mid-sagittal of S3 func_ref with cord discovery mask contour (green).
    This lets the reviewer verify spatial coherence between anat and func spaces.
    """
    import nibabel.processing

    func_img = nib.as_closest_canonical(nib.load(func_ref_path))
    func_data = func_img.get_fdata()
    if func_data.ndim > 3:
        func_data = func_data[..., 0]

    # Load cord mask and resample to func space
    mask_raw = nib.as_closest_canonical(nib.load(cordmask_func_path))
    mask_img = nibabel.processing.resample_from_to(mask_raw, func_img, order=0)
    mask_data = mask_img.get_fdata() > 0

    # Mid-sagittal slice index from cord mask center of mass
    mask_coords = np.argwhere(mask_data)
    if mask_coords.size > 0:
        x_mid = int(np.median(mask_coords[:, 0]))
    else:
        x_mid = func_data.shape[0] // 2

    # Extract func sagittal slice
    func_sag = np.flipud(func_data[x_mid, :, :].T)
    mask_sag = np.flipud(mask_data[x_mid, :, :].T)

    # Normalize func
    vmin, vmax = np.percentile(func_sag[func_sag > 0], [1, 99]) if np.any(func_sag > 0) else (0, 1)
    if vmax <= vmin:
        vmax = vmin + 1
    func_norm = np.clip((func_sag - vmin) / (vmax - vmin), 0, 1)
    func_rgb = np.repeat((func_norm * 255).astype(np.uint8)[..., np.newaxis], 3, axis=2)
    func_pil = Image.fromarray(func_rgb).convert("RGBA")

    # Draw cord mask contour in green
    contour = _mask_contour_2d(mask_sag)
    _draw_thick_contour(func_pil, contour, color=(0, 255, 0, 255), thickness=2)

    # Left panel: S2 anatomy (if available)
    if cordref_std_path and cordref_std_path.exists():
        anat_img = nib.as_closest_canonical(nib.load(cordref_std_path))
        anat_data = anat_img.get_fdata()
        if anat_data.ndim > 3:
            anat_data = anat_data[..., 0]
        anat_x_mid = anat_data.shape[0] // 2
        anat_sag = np.flipud(anat_data[anat_x_mid, :, :].T)

        a_vmin, a_vmax = np.percentile(anat_sag[anat_sag > 0], [1, 99]) if np.any(anat_sag > 0) else (0, 1)
        if a_vmax <= a_vmin:
            a_vmax = a_vmin + 1
        anat_norm = np.clip((anat_sag - a_vmin) / (a_vmax - a_vmin), 0, 1)
        anat_rgb = np.repeat((anat_norm * 255).astype(np.uint8)[..., np.newaxis], 3, axis=2)
        anat_pil = Image.fromarray(anat_rgb).convert("RGBA")
    else:
        # No anat available -- create a black placeholder
        anat_pil = Image.new("RGBA", func_pil.size, (0, 0, 0, 255))

    # Resize both to same height for side-by-side
    target_h = max(anat_pil.height, func_pil.height, 256)
    anat_w = max(1, int(anat_pil.width * target_h / max(anat_pil.height, 1)))
    func_w = max(1, int(func_pil.width * target_h / max(func_pil.height, 1)))

    anat_resized = anat_pil.resize((anat_w, target_h), resample=Image.Resampling.LANCZOS)
    func_resized = func_pil.resize((func_w, target_h), resample=Image.Resampling.LANCZOS)

    # Compose side-by-side with labels
    gap = 4
    total_w = anat_w + gap + func_w
    canvas = Image.new("RGBA", (total_w, target_h + 20), (0, 0, 0, 255))
    canvas.paste(anat_resized, (0, 20))
    canvas.paste(func_resized, (anat_w + gap, 20))

    draw = ImageDraw.Draw(canvas)
    draw.text((4, 2), "S2 Anatomy", fill=(255, 255, 255, 255))
    draw.text((anat_w + gap + 4, 2), "S3 Func Ref + Cord (green)", fill=(0, 255, 0, 255))

    canvas.convert("RGB").save(output_path)
