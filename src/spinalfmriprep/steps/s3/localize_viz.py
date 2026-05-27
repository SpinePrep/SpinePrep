"""S3.1 visualization: simple func-with-mask figure rendering."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import nibabel as nib
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from spinalfmriprep.lib.run import run_command as _run_command

from .reportlets import _write_ppm


def _load_font(size: int):
    """Load a default TTF if available, else a PIL bitmap fallback."""
    for candidate in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    ):
        try:
            return ImageFont.truetype(candidate, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _render_s3_1_simple_func_with_mask(
    func_path: Path,
    mask_path: Path,
    output_path: Path,
    policy: dict[str, Any],
    crop_box: Optional[list[int]] = None,
    padding_mm: float = 0.0,
    drift_gate: Optional[dict[str, Any]] = None,
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

        if not (ok and output_path.exists()):
            return None

        # Brain-contamination check banner (internal symbol: drift_gate).
        # Drawn AFTER the ImageMagick resize so the font and banner
        # height are sized relative to the final 1200-px image, not the
        # tiny pre-resize buffer (which would get scaled ~18x along
        # with the figure).
        if drift_gate and drift_gate.get("status") == "FAIL":
            with Image.open(output_path) as base:
                base_rgb = base.convert("RGB")
            w, h = base_rgb.size
            banner_h = 36
            font_size = 18
            font = _load_font(font_size)
            text = f"REJECTED  {drift_gate.get('reason', 'brain contamination check failed')}"
            measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
            while measure.textlength(text, font=font) > w - 16 and len(text) > 20:
                text = text[:-2]
            stacked = Image.new("RGB", (w, h + banner_h), (180, 28, 28))
            d = ImageDraw.Draw(stacked)
            d.text((8, (banner_h - font_size) // 2 - 1), text,
                   fill=(255, 255, 255), font=font)
            stacked.paste(base_rgb, (0, banner_h))
            stacked.save(output_path)

        return output_path

    except Exception as e:
        pass  # S3.1 figure render error
        return None
