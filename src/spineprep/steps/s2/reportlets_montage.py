"""Reportlet montage renderers: crop box, cordmask, TSS, sagittal panels, mask tiles."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import nibabel as nib
import numpy as np
from PIL import Image, ImageDraw

from .io import _run_command
from .segment import TSS_LABELS, TSS_VERTEBRA_NAMES, TSS_DISC_NAMES
from .validate import _largest_connected_component
from .reportlets_core import (
    _scale_to_rgb,
    _fit_resize_and_paste_rgb,
    _write_ppm,
)


def _render_crop_box_sagittal(
    qc_root: Path,
    cordref_std_path: Optional[Path],
    cordref_crop_path: Optional[Path],
    discovery_seg_path: Optional[Path],
    crop_mask_path: Optional[Path],
) -> Optional[Path]:
    """
    Render S2.1 crop box sagittal figure showing discovery and crop region.

    Shows the standardized anatomical reference with:
    - Blue contour: cord mask (discovery segmentation in std space)
    - Red contour: crop box region (from crop mask in std space)
    """
    if cordref_std_path is None:
        return None
    if not cordref_std_path.exists():
        return None

    qc_root.mkdir(parents=True, exist_ok=True)

    try:
        std_img = nib.as_closest_canonical(nib.load(cordref_std_path))
        std_data = std_img.get_fdata()
        if std_data.ndim > 3:
            std_data = std_data[..., 0]
        std_shape = std_data.shape

        # Load discovery segmentation (in std space)
        discovery_seg_data = None
        if discovery_seg_path and discovery_seg_path.exists():
            try:
                discovery_seg_img = nib.as_closest_canonical(nib.load(discovery_seg_path))
                discovery_seg_data = discovery_seg_img.get_fdata()
                if discovery_seg_data.ndim > 3:
                    discovery_seg_data = discovery_seg_data[..., 0]
                if discovery_seg_data.shape != std_shape:
                    discovery_seg_data = None
            except Exception:
                discovery_seg_data = None

        # Load crop mask (in std space)
        crop_mask_data = None
        if crop_mask_path and crop_mask_path.exists():
            try:
                crop_mask_img = nib.as_closest_canonical(nib.load(crop_mask_path))
                crop_mask_data = crop_mask_img.get_fdata()
                if crop_mask_data.ndim > 3:
                    crop_mask_data = crop_mask_data[..., 0]
                if crop_mask_data.shape != std_shape:
                    crop_mask_data = None
                else:
                    crop_mask_data = crop_mask_data > 0
            except Exception:
                crop_mask_data = None

        # If crop mask not available, fall back to computing from cropped image
        if crop_mask_data is None and cordref_crop_path and cordref_crop_path.exists():
            try:
                crop_img = nib.as_closest_canonical(nib.load(cordref_crop_path))
                crop_data = crop_img.get_fdata()
                if crop_data.ndim > 3:
                    crop_data = crop_data[..., 0]
                crop_shape = crop_data.shape
                size_x, size_y = crop_shape[0], crop_shape[1]
                center = (std_shape[0] // 2, std_shape[1] // 2, std_shape[2] // 2)
                x0 = max(0, center[0] - size_x // 2)
                y0 = max(0, center[1] - size_y // 2)
                x1 = min(std_shape[0], x0 + size_x)
                y1 = min(std_shape[1], y0 + size_y)
                x0 = max(0, x1 - size_x)
                y0 = max(0, y1 - size_y)
                z0, z1 = 0, std_shape[2]
                crop_mask_data = np.zeros(std_shape, dtype=bool)
                crop_mask_data[x0:x1, y0:y1, z0:z1] = True
            except Exception:
                crop_mask_data = None

        # Find center slice for sagittal view
        if discovery_seg_data is not None:
            coords = np.argwhere(discovery_seg_data > 0)
        elif crop_mask_data is not None:
            coords = np.argwhere(crop_mask_data)
        else:
            coords = np.array([[std_shape[0] // 2, std_shape[1] // 2, std_shape[2] // 2]])

        if coords.size == 0:
            return None
        x_index = int(np.median(coords[:, 0]))
        x_index = max(0, min(x_index, std_shape[0] - 1))

        img_slice = std_data[x_index, :, :]
        discovery_slice_2d = None
        if discovery_seg_data is not None:
            discovery_slice_2d = discovery_seg_data[x_index, :, :] > 0
        crop_slice = None
        if crop_mask_data is not None:
            crop_slice = crop_mask_data[x_index, :, :]

        if img_slice.ndim != 2:
            return None

        # Display with superior at the top
        img_slice = np.flipud(img_slice.T)
        if crop_slice is not None:
            crop_slice = np.flipud(crop_slice.T)
        if discovery_slice_2d is not None:
            discovery_slice_2d = np.flipud(discovery_slice_2d.T)

        # Keep the FULL raw FOV as the background (no in-plane crop). The red
        # rectangle drawn later from `crop_slice` indicates where the cord
        # crop was extracted relative to the original acquisition. Aspect is
        # corrected from voxel zooms so anisotropic data (e.g. MEGRE
        # 0.5x0.5x5mm) doesn't render as a flattened slat.
        try:
            zooms = std_img.header.get_zooms()[:3]
            zoom_disp_h = float(zooms[2])  # mm per displayed row (Z)
            zoom_disp_w = float(zooms[1])  # mm per displayed column (Y)
            n_rows, n_cols = img_slice.shape
            mm_h = n_rows * zoom_disp_h
            mm_w = n_cols * zoom_disp_w
            target_w = 1200
            target_h = int(round(target_w * mm_h / max(mm_w, 1e-6)))
            target_h = max(80, min(target_h, 4000))
            resize_spec = f"{target_w}x{target_h}!"
        except Exception:
            resize_spec = "1200x"

        vmin, vmax = np.percentile(img_slice, [1, 99])
        if vmax <= vmin:
            vmin, vmax = float(img_slice.min()), float(img_slice.max())
        if vmax <= vmin:
            vmax = vmin + 1.0
        normalized = np.clip((img_slice - vmin) / (vmax - vmin), 0, 1)
        base = (normalized * 255).astype(np.uint8)
        base_rgb = np.repeat(base[..., np.newaxis], 3, axis=2)
        overlay_img = Image.fromarray(base_rgb, mode="RGB").convert("RGBA")

        # Draw discovery segmentation as solid transparent overlay (blue)
        if discovery_slice_2d is not None:
            mask_array = discovery_slice_2d.astype(np.uint8) * 180
            blue_overlay = np.zeros((*discovery_slice_2d.shape, 4), dtype=np.uint8)
            blue_overlay[:, :, 0] = 0
            blue_overlay[:, :, 1] = 100
            blue_overlay[:, :, 2] = 200
            blue_overlay[:, :, 3] = mask_array
            mask_img = Image.fromarray(blue_overlay, mode="RGBA")
            overlay_img = Image.alpha_composite(overlay_img, mask_img)

        # Draw crop box as thin rectangular border (red)
        if crop_slice is not None:
            coords = np.argwhere(crop_slice)
            if coords.size > 0:
                y_min, z_min = coords.min(axis=0)
                y_max, z_max = coords.max(axis=0)
                draw = ImageDraw.Draw(overlay_img)
                draw.rectangle(
                    [(z_min, y_min), (z_max + 1, y_max + 1)],
                    outline=(255, 0, 0, 255),
                    width=1,
                )

        final_rgb = np.array(overlay_img.convert("RGB"), dtype=np.uint8)
        output = qc_root / "crop_box_sagittal.png"
        ppm_path = qc_root / "crop_box_sagittal.ppm"
        _write_ppm(ppm_path, final_rgb)

        ok, _ = _run_command(
            ["convert", str(ppm_path), "-filter", "Lanczos", "-resize", resize_spec, str(output)]
        )
        if ppm_path.exists():
            ppm_path.unlink()
        return output if ok else None

    except Exception:  # noqa: BLE001
        return None


def _render_cordmask_montage(
    qc_root: Path,
    image: Optional[Path],
    cordmask: Optional[Path],
    tile_size: int = 200,
    max_tiles: Optional[int] = None,
) -> Optional[Path]:
    if image is None or cordmask is None:
        return None
    qc_root.mkdir(parents=True, exist_ok=True)
    try:
        img = nib.as_closest_canonical(nib.load(image))
        mask_img = nib.as_closest_canonical(nib.load(cordmask))
    except Exception:
        return None
    img_data = img.get_fdata()
    mask_data = mask_img.get_fdata()
    if img_data.ndim > 3:
        img_data = img_data[..., 0]
    if mask_data.ndim > 3:
        mask_data = mask_data[..., 0]
    if img_data.shape != mask_data.shape:
        return None
    mask = _largest_connected_component(mask_data > 0)
    coords = np.argwhere(mask)
    if coords.size == 0:
        return None

    z_dim = img_data.shape[2]
    y_dim = img_data.shape[1]
    sagittal_height = int(round(z_dim * 1200 / max(y_dim, 1)))
    sagittal_height = max(sagittal_height, tile_size)
    scale = sagittal_height / max(z_dim, 1)
    min_gap = max(6, tile_size // 10)

    slice_infos = []
    for z in np.unique(coords[:, 2]):
        slice_mask = mask[:, :, z]
        if not slice_mask.any():
            continue
        indices = np.argwhere(slice_mask)
        center = indices.mean(axis=0)
        slice_infos.append({"z": int(z), "center": center})
    if not slice_infos:
        return None

    desired_tiles = min(len(slice_infos), 12)
    if desired_tiles > 0:
        tile_size = min(tile_size, max(120, sagittal_height // desired_tiles))
    max_tiles_dynamic = max(8, sagittal_height // tile_size)
    tile_cap = min(max_tiles_dynamic, max_tiles) if max_tiles is not None else max_tiles_dynamic

    slice_infos.sort(key=lambda item: item["z"], reverse=True)
    min_sep_z = max(1, int(np.ceil((tile_size + min_gap) / max(scale, 1e-6))))
    selected = []
    last_z = None
    for info in slice_infos:
        if last_z is None or (last_z - info["z"]) >= min_sep_z:
            selected.append(info)
            last_z = info["z"]
        if len(selected) >= tile_cap:
            break
    if not selected:
        return None

    tiles_dir = qc_root / "tiles"
    tiles_dir.mkdir(parents=True, exist_ok=True)
    tile_items: list[tuple[Path, int]] = []
    for info in selected:
        z = info["z"]
        slice_data = img_data[:, :, z]
        mask_slice = mask[:, :, z]
        if slice_data.ndim != 2:
            continue
        tile = _render_mask_tile(
            out_dir=tiles_dir,
            slice_data=slice_data,
            mask_slice=mask_slice,
            z_index=z,
            tile_size=tile_size,
        )
        if tile is not None:
            tile_items.append((tile, z))
    if not tile_items:
        return None

    column = qc_root / "axial_column.png"
    ok, _ = _run_command(["convert", "-size", f"{tile_size}x{sagittal_height}", "xc:#000000", str(column)])
    if not ok:
        return None

    tile_items.sort(key=lambda item: item[1], reverse=True)
    max_y = max(0, sagittal_height - tile_size)
    targets = []
    for tile_path, z_index in tile_items:
        row = (z_dim - 1 - z_index) * scale
        target = int(round(row - tile_size / 2))
        target = max(0, min(target, max_y))
        targets.append((target, tile_path, z_index))

    targets.sort(key=lambda item: item[0])
    positions = [t[0] for t in targets]
    for i in range(1, len(positions)):
        positions[i] = max(positions[i], positions[i - 1] + tile_size + min_gap)
    if positions:
        positions[-1] = min(positions[-1], max_y)
        for i in range(len(positions) - 2, -1, -1):
            positions[i] = min(positions[i], positions[i + 1] - tile_size - min_gap)
            positions[i] = max(0, positions[i])
        for i in range(1, len(positions)):
            positions[i] = max(positions[i], positions[i - 1] + tile_size + min_gap)

    for (target, tile_path, z_index), y_offset in zip(targets, positions):
        ok, _ = _run_command(
            ["convert", str(column), str(tile_path), "-geometry", f"+0+{y_offset}", "-composite", str(column)]
        )
        if not ok:
            return None

    sagittal = _render_sagittal_mask_panel(
        qc_root=qc_root / "sagittal",
        image=image,
        mask=mask,
    )
    if sagittal is None:
        return None

    sagittal_resized = qc_root / "sagittal_resized.png"
    ok, _ = _run_command(
        ["convert", str(sagittal), "-filter", "Lanczos", "-resize", f"x{sagittal_height}", str(sagittal_resized)]
    )
    if not ok:
        return None

    montage = qc_root / "cordmask_montage.png"
    ok, _ = _run_command(["convert", str(sagittal_resized), str(column), "+append", str(montage)])
    return montage if ok else None


def _render_mask_tile(
    out_dir: Path,
    slice_data: np.ndarray,
    mask_slice: np.ndarray,
    z_index: int,
    tile_size: int,
) -> Optional[Path]:
    if slice_data.ndim != 2 or mask_slice.ndim != 2:
        return None
    mask_coords = np.argwhere(mask_slice > 0)
    if mask_coords.size == 0:
        return None
    min_xy = mask_coords.min(axis=0)
    max_xy = mask_coords.max(axis=0)
    margin = 6
    min_xy = np.maximum(min_xy - margin, 0)
    max_xy = np.minimum(max_xy + margin, np.array(slice_data.shape) - 1)
    size_xy = max_xy - min_xy + 1
    min_size = 32
    target_size = int(max(size_xy.max(), min_size))
    half = target_size // 2
    center_xy = np.round((min_xy + max_xy) / 2).astype(int)
    x0 = max(center_xy[0] - half, 0)
    y0 = max(center_xy[1] - half, 0)
    x1 = min(x0 + target_size, slice_data.shape[0])
    y1 = min(y0 + target_size, slice_data.shape[1])
    x0 = max(x1 - target_size, 0)
    y0 = max(y1 - target_size, 0)

    slice_data = slice_data[x0:x1, y0:y1]
    mask_slice = mask_slice[x0:x1, y0:y1]

    # Axial view in canonical RAS: anterior up.
    slice_data = np.flipud(slice_data.T)
    mask_slice = np.flipud(mask_slice.T)

    vmin, vmax = np.percentile(slice_data, [1, 99])
    if vmax <= vmin:
        vmin, vmax = float(slice_data.min()), float(slice_data.max())
    if vmax <= vmin:
        vmax = vmin + 1.0
    normalized = np.clip((slice_data - vmin) / (vmax - vmin), 0, 1)
    base = (normalized * 255).astype(np.uint8)
    rgb = np.repeat(base[..., np.newaxis], 3, axis=2)
    mask = mask_slice.astype(bool)
    rgb[mask] = (rgb[mask] * 0.4 + np.array([255, 0, 0]) * 0.6).astype(np.uint8)

    ppm_path = out_dir / f"axial_{z_index:04d}.ppm"
    png_path = out_dir / f"axial_{z_index:04d}.png"
    _write_ppm(ppm_path, rgb)
    ok, _ = _run_command(
        ["convert", str(ppm_path), "-filter", "Lanczos", "-resize", f"{tile_size}x{tile_size}", str(png_path)]
    )
    return png_path if ok else None


def _render_sagittal_mask_panel(
    qc_root: Path,
    image: Optional[Path],
    mask: np.ndarray,
) -> Optional[Path]:
    qc_root.mkdir(parents=True, exist_ok=True)
    try:
        img = nib.as_closest_canonical(nib.load(image)) if image else None
    except Exception:
        return None
    if img is None:
        return None
    img_data = img.get_fdata()
    if img_data.ndim > 3:
        img_data = img_data[..., 0]
    if img_data.shape != mask.shape:
        return None
    coords = np.argwhere(mask)
    if coords.size == 0:
        return None
    x_index = int(np.median(coords[:, 0]))
    x_index = max(0, min(x_index, img_data.shape[0] - 1))
    img_slice = img_data[x_index, :, :]
    mask_proj = mask.any(axis=0)
    if img_slice.ndim != 2:
        return None

    img_slice = np.flipud(img_slice.T)
    mask_proj = np.flipud(mask_proj.T)

    vmin, vmax = np.percentile(img_slice, [1, 99])
    if vmax <= vmin:
        vmin, vmax = float(img_slice.min()), float(img_slice.max())
    if vmax <= vmin:
        vmax = vmin + 1.0

    normalized = np.clip((img_slice - vmin) / (vmax - vmin), 0, 1)
    base = (normalized * 255).astype(np.uint8)
    base_rgb = np.repeat(base[..., np.newaxis], 3, axis=2)
    overlay = base_rgb.copy()
    overlay[mask_proj] = (overlay[mask_proj] * 0.4 + np.array([255, 0, 0]) * 0.6).astype(np.uint8)

    output = qc_root / "overlay.png"
    ppm_path = qc_root / "overlay.ppm"
    _write_ppm(ppm_path, overlay)
    ok, _ = _run_command(
        ["convert", str(ppm_path), "-filter", "Lanczos", "-resize", "1200x", str(output)]
    )
    return output if ok else None


def _render_sagittal_mask_panel_from_ref(
    qc_root: Path,
    image: Optional[Path],
    mask: np.ndarray,
    ref_mask: np.ndarray,
    color: tuple[int, int, int] = (255, 0, 0),
) -> Optional[Path]:
    """Render a sagittal overlay panel using ref_mask to choose the slice and mask for overlay."""
    if image is None:
        return None
    qc_root.mkdir(parents=True, exist_ok=True)
    try:
        img = nib.as_closest_canonical(nib.load(image))
    except Exception:
        return None
    img_data = img.get_fdata()
    if img_data.ndim > 3:
        img_data = img_data[..., 0]
    if img_data.shape != mask.shape or img_data.shape != ref_mask.shape:
        return None

    coords = np.argwhere(ref_mask)
    if coords.size == 0:
        return None
    x_index = int(np.median(coords[:, 0]))
    x_index = max(0, min(x_index, img_data.shape[0] - 1))
    img_slice = img_data[x_index, :, :]
    mask_proj = mask.any(axis=0)
    if img_slice.ndim != 2:
        return None

    img_slice = np.flipud(img_slice.T)
    mask_proj = np.flipud(mask_proj.T)

    vmin, vmax = np.percentile(img_slice, [1, 99])
    if vmax <= vmin:
        vmin, vmax = float(img_slice.min()), float(img_slice.max())
    if vmax <= vmin:
        vmax = vmin + 1.0

    normalized = np.clip((img_slice - vmin) / (vmax - vmin), 0, 1)
    base = (normalized * 255).astype(np.uint8)
    base_rgb = np.repeat(base[..., np.newaxis], 3, axis=2)
    overlay = base_rgb.copy()
    c = np.array(color, dtype=np.uint8)
    overlay[mask_proj] = (overlay[mask_proj] * 0.4 + c * 0.6).astype(np.uint8)

    output = qc_root / "overlay.png"
    ppm_path = qc_root / "overlay.ppm"
    _write_ppm(ppm_path, overlay)
    ok, _ = _run_command(
        ["convert", str(ppm_path), "-filter", "Lanczos", "-resize", "1200x", str(output)]
    )
    return output if ok else None
