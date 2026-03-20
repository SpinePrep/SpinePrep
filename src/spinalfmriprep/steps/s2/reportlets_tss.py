"""Reportlet renderers: TotalSpineSeg montage and rootlets montage."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import nibabel as nib
import numpy as np
from PIL import Image

from .io import _run_command
from .segment import TSS_LABELS, TSS_VERTEBRA_NAMES, TSS_DISC_NAMES
from .validate import _largest_connected_component
from .reportlets_core import _write_ppm
from .reportlets_montage import _render_sagittal_mask_panel_from_ref


def _render_totalspineseg_montage(
    qc_root: Path,
    image: Optional[Path],
    tss_output_path: Optional[Path],
    cord_path: Optional[Path],
    canal_path: Optional[Path],
) -> Optional[Path]:
    """
    Render TotalSpineSeg-style comprehensive visualization.

    Shows a sagittal view with vertebrae, discs, cord, canal overlays
    and label annotations on left/right margins.
    """
    if image is None or tss_output_path is None:
        return None
    qc_root.mkdir(parents=True, exist_ok=True)

    try:
        img = nib.as_closest_canonical(nib.load(image))
        tss_img = nib.as_closest_canonical(nib.load(tss_output_path))
    except Exception:
        return None

    img_data = img.get_fdata()
    tss_data = tss_img.get_fdata()
    if img_data.ndim > 3:
        img_data = img_data[..., 0]
    if tss_data.ndim > 3:
        tss_data = tss_data[..., 0]
    if img_data.shape != tss_data.shape:
        return None

    cord_data = None
    canal_data = None
    if cord_path and cord_path.exists():
        try:
            cord_img = nib.as_closest_canonical(nib.load(cord_path))
            cord_data = cord_img.get_fdata()
            if cord_data.ndim > 3:
                cord_data = cord_data[..., 0]
        except Exception:
            cord_data = None
    if canal_path and canal_path.exists():
        try:
            canal_img = nib.as_closest_canonical(nib.load(canal_path))
            canal_data = canal_img.get_fdata()
            if canal_data.ndim > 3:
                canal_data = canal_data[..., 0]
        except Exception:
            canal_data = None

    tss_mask = tss_data > 0
    if not tss_mask.any():
        return None
    coords = np.argwhere(tss_mask)
    if coords.size == 0:
        return None
    x_index = int(np.median(coords[:, 0]))
    x_index = max(0, min(x_index, img_data.shape[0] - 1))

    img_slice = img_data[x_index, :, :]
    tss_slice = tss_data[x_index, :, :]
    if img_slice.ndim != 2:
        return None

    img_slice = np.flipud(img_slice.T)
    tss_slice = np.flipud(tss_slice.T)

    vmin, vmax = np.percentile(img_slice, [1, 99])
    if vmax <= vmin:
        vmin, vmax = float(img_slice.min()), float(img_slice.max())
    if vmax <= vmin:
        vmax = vmin + 1.0
    normalized = np.clip((img_slice - vmin) / (vmax - vmin), 0, 1)
    base = (normalized * 255).astype(np.uint8)
    base_rgb = np.repeat(base[..., np.newaxis], 3, axis=2)
    overlay = base_rgb.copy()

    # Color palettes - vertebrae (cervical: blues/cyans, thoracic: warm, lumbar: greens)
    vertebrae_colors = {11: (135,206,250), 12: (100,149,237), 13: (255,215,0), 14: (255,165,0), 15: (50,205,50), 16: (144,238,144), 17: (178,102,255), 21: (255,99,71), 22: (255,215,0), 23: (255,182,193), 24: (152,251,152), 25: (135,206,235), 26: (238,130,238), 27: (255,160,122), 28: (173,216,230), 29: (255,228,181), 30: (221,160,221), 31: (176,224,230), 32: (250,250,210), 41: (144,238,144), 42: (189,183,107), 43: (216,191,216), 44: (245,222,179), 45: (188,143,143), 50: (139,69,19)}  # fmt: skip
    # Disc colors (slightly darker/different hue than adjacent vertebrae)
    disc_colors = {63: (255,200,100), 64: (255,180,80), 65: (255,160,60), 66: (255,140,40), 67: (255,120,20), 71: (200,100,100), 72: (180,100,120), 73: (160,100,140), 74: (140,100,160), 75: (120,100,180), 76: (100,100,200), 77: (100,120,180), 78: (100,140,160), 79: (100,160,140), 80: (100,180,120), 81: (100,200,100), 82: (120,180,100), 91: (140,160,100), 92: (160,140,100), 93: (180,120,100), 94: (200,100,100), 95: (220,80,100), 100: (240,60,100)}  # fmt: skip

    for label, color in vertebrae_colors.items():
        mask = tss_slice == label
        if mask.any():
            overlay[mask] = (overlay[mask] * 0.3 + np.array(color) * 0.7).astype(np.uint8)
    for label, color in disc_colors.items():
        mask = tss_slice == label
        if mask.any():
            overlay[mask] = (overlay[mask] * 0.2 + np.array(color) * 0.8).astype(np.uint8)

    if canal_data is not None:
        canal_slice = canal_data[x_index, :, :]
        canal_slice = np.flipud(canal_slice.T)
        canal_mask = canal_slice > 0
        if canal_mask.any():
            overlay[canal_mask] = (overlay[canal_mask] * 0.5 + np.array([0, 200, 200]) * 0.5).astype(np.uint8)
    else:
        canal_mask = tss_slice == TSS_LABELS["spinal_canal"]
        if canal_mask.any():
            overlay[canal_mask] = (overlay[canal_mask] * 0.5 + np.array([0, 200, 200]) * 0.5).astype(np.uint8)

    if cord_data is not None:
        cord_slice = cord_data[x_index, :, :]
        cord_slice = np.flipud(cord_slice.T)
        cord_mask = cord_slice > 0
        if cord_mask.any():
            overlay[cord_mask] = (overlay[cord_mask] * 0.4 + np.array([65, 105, 225]) * 0.6).astype(np.uint8)
    else:
        cord_mask = tss_slice == TSS_LABELS["spinal_cord"]
        if cord_mask.any():
            overlay[cord_mask] = (overlay[cord_mask] * 0.4 + np.array([65, 105, 225]) * 0.6).astype(np.uint8)

    output = qc_root / "tss_montage.png"
    ppm_path = qc_root / "tss_overlay.ppm"
    _write_ppm(ppm_path, overlay)

    present_vertebrae: list[tuple[int, int, str]] = []
    present_discs: list[tuple[int, int, str]] = []
    for label, name in TSS_VERTEBRA_NAMES.items():
        mask = tss_slice == label
        if mask.any():
            coords2d = np.argwhere(mask)
            z_center = float(np.median(coords2d[:, 0]))
            present_vertebrae.append((int(z_center), label, name))
    for label, name in TSS_DISC_NAMES.items():
        mask = tss_slice == label
        if mask.any():
            coords2d = np.argwhere(mask)
            z_center = float(np.median(coords2d[:, 0]))
            present_discs.append((int(z_center), label, name))

    present_vertebrae.sort(key=lambda t: t[0])
    present_discs.sort(key=lambda t: t[0])

    target_width = 1200
    src_h, src_w = int(overlay.shape[0]), int(overlay.shape[1])
    if src_w <= 0:
        return None
    scale = target_width / src_w
    out_h = max(1, int(round(src_h * scale)))

    left_margin = 200
    right_margin = 200
    pointsize = 28
    min_spacing = 32

    vert_labels: list[tuple[int, str, str]] = []
    for z_pos, label, name in present_vertebrae:
        y_out = int(round(z_pos * scale))
        y_out = max(0, min(y_out, out_h - 1))
        color = vertebrae_colors.get(label, (255, 255, 255))
        rgb_fill = f"rgb({color[0]},{color[1]},{color[2]})"
        vert_labels.append((y_out, name, rgb_fill))

    vert_adjusted: list[tuple[int, str, str]] = []
    last_y = -10_000
    for y_out, name, rgb_fill in vert_labels:
        y_adj = y_out
        if y_adj - last_y < min_spacing:
            y_adj = last_y + min_spacing
        y_adj = max(0, min(y_adj, out_h - 1))
        vert_adjusted.append((y_adj, name, rgb_fill))
        last_y = y_adj

    disc_labels_list: list[tuple[int, str, str]] = []
    for z_pos, label, name in present_discs:
        y_out = int(round(z_pos * scale))
        y_out = max(0, min(y_out, out_h - 1))
        color = disc_colors.get(label, (255, 200, 100))
        rgb_fill = f"rgb({color[0]},{color[1]},{color[2]})"
        disc_labels_list.append((y_out, name, rgb_fill))

    disc_adjusted: list[tuple[int, str, str]] = []
    last_y = -10_000
    for y_out, name, rgb_fill in disc_labels_list:
        y_adj = y_out
        if y_adj - last_y < min_spacing:
            y_adj = last_y + min_spacing
        y_adj = max(0, min(y_adj, out_h - 1))
        disc_adjusted.append((y_adj, name, rgb_fill))
        last_y = y_adj

    cmd = [
        "convert", str(ppm_path),
        "-filter", "Lanczos", "-resize", f"{target_width}x",
        "-background", "#000000",
        "-gravity", "West", "-splice", f"{left_margin}x0",
        "-gravity", "East", "-splice", f"{right_margin}x0",
        "-gravity", "NorthWest",
        "-pointsize", str(pointsize),
        "-stroke", "#000000", "-strokewidth", "1",
    ]
    for y, name, rgb_fill in disc_adjusted:
        cmd.extend(["-fill", rgb_fill, "-annotate", f"+10+{max(0, y - pointsize // 2)}", name])
    for y, name, rgb_fill in vert_adjusted:
        cmd.extend(["-fill", rgb_fill, "-annotate", f"+{left_margin + target_width + 10}+{max(0, y - pointsize // 2)}", name])
    cmd.append(str(output))

    ok, _ = _run_command(cmd)
    return output if ok else None


def _render_rootlets_tile(
    out_dir: Path,
    slice_data: np.ndarray,
    rootlets_slice: np.ndarray,
    cord_slice: np.ndarray,
    z_index: int,
    tile_size: int,
    level_text: str,
    level_color: tuple[int, int, int],
    frame_id: str,
) -> Optional[Path]:
    if slice_data.ndim != 2 or rootlets_slice.ndim != 2 or cord_slice.ndim != 2:
        return None
    cord_coords = np.argwhere(cord_slice > 0)
    if cord_coords.size == 0:
        return None
    min_xy = cord_coords.min(axis=0)
    max_xy = cord_coords.max(axis=0)
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
    rootlets_slice = (rootlets_slice[x0:x1, y0:y1] > 0)
    slice_data = np.flipud(slice_data.T)
    rootlets_slice = np.flipud(rootlets_slice.T)

    vmin, vmax = np.percentile(slice_data, [1, 99])
    if vmax <= vmin:
        vmin, vmax = float(slice_data.min()), float(slice_data.max())
    if vmax <= vmin:
        vmax = vmin + 1.0
    normalized = np.clip((slice_data - vmin) / (vmax - vmin), 0, 1)
    base = (normalized * 255).astype(np.uint8)
    rgb = np.repeat(base[..., np.newaxis], 3, axis=2)
    overlay_color = np.array([255, 0, 0], dtype=np.uint8)
    rgb[rootlets_slice] = (rgb[rootlets_slice] * 0.3 + overlay_color * 0.7).astype(np.uint8)

    ppm_path = out_dir / f"axial_{frame_id}_{z_index:04d}.ppm"
    png_path = out_dir / f"axial_{frame_id}_{z_index:04d}.png"
    _write_ppm(ppm_path, rgb)
    r, g, b = level_color
    fill = f"rgb({int(r)},{int(g)},{int(b)})"
    ok, _ = _run_command(
        [
            "convert", str(ppm_path), "-filter", "Lanczos", "-resize", f"{tile_size}x{tile_size}",
            "-gravity", "north", "-pointsize", "32",
            "-stroke", "#ffffff", "-strokewidth", "1",
            "-fill", fill, "-undercolor", "#000000aa",
            "-annotate", "0", level_text, str(png_path),
        ]
    )
    return png_path if ok else None


def _render_rootlets_montage(
    qc_root: Path,
    image: Optional[Path],
    rootlets: Optional[Path],
    vertebral_labels: Optional[Path],
    cordmask: Optional[Path],
    tile_size: int = 200,
) -> Optional[Path]:
    run_id = "post-fix2"
    if image is None or rootlets is None or vertebral_labels is None or cordmask is None:
        return None
    qc_root.mkdir(parents=True, exist_ok=True)
    try:
        img = nib.as_closest_canonical(nib.load(image))
        root_img = nib.as_closest_canonical(nib.load(rootlets))
        lab_img = nib.as_closest_canonical(nib.load(vertebral_labels))
        cord_img = nib.as_closest_canonical(nib.load(cordmask))
    except Exception:
        return None
    img_data = img.get_fdata()
    root_data = root_img.get_fdata()
    lab_data = lab_img.get_fdata()
    cord_data = cord_img.get_fdata()
    if img_data.ndim > 3:
        img_data = img_data[..., 0]
    if root_data.ndim > 3:
        root_data = root_data[..., 0]
    if lab_data.ndim > 3:
        lab_data = lab_data[..., 0]
    if cord_data.ndim > 3:
        cord_data = cord_data[..., 0]
    if img_data.shape != root_data.shape or img_data.shape != lab_data.shape or img_data.shape != cord_data.shape:
        return None

    cord_mask = _largest_connected_component(cord_data > 0)
    if not cord_mask.any():
        return None
    root_mask = root_data > 0
    lab_mask = lab_data > 0
    if not lab_mask.any():
        return None

    def _level_name(label_value: int) -> str:
        if label_value <= 0:
            return str(label_value)
        if label_value <= 7:
            return f"C{label_value}"
        if label_value <= 19:
            return f"T{label_value - 7}"
        if label_value <= 24:
            return f"L{label_value - 19}"
        return str(label_value)

    palette = np.array(
        [[255, 0, 0], [255, 165, 0], [255, 255, 0], [0, 255, 0], [0, 255, 255], [0, 0, 255], [255, 0, 255]],
        dtype=np.uint8,
    )

    present_levels = sorted({int(v) for v in np.unique(lab_data.astype(int)) if v > 0})
    if not present_levels:
        return None

    z_dim = img_data.shape[2]
    y_dim = img_data.shape[1]
    sagittal_height = int(round(z_dim * 1200 / max(y_dim, 1)))
    sagittal_height = max(sagittal_height, tile_size)
    scale = sagittal_height / max(z_dim, 1)
    desired_tiles = min(len(present_levels), 24)
    if desired_tiles > 0:
        tile_size = min(tile_size, max(90, sagittal_height // desired_tiles))
    min_gap = max(6, tile_size // 10)

    level_infos: list[dict] = []
    lab_int = lab_data.astype(int)
    for lab in present_levels:
        coords = np.argwhere(lab_int == lab)
        if coords.size == 0:
            continue
        z_idx = int(round(np.median(coords[:, 2])))
        z_idx = max(0, min(z_idx, z_dim - 1))
        level_infos.append({"lab": lab, "z": z_idx})
    if not level_infos:
        return None

    tiles_dir = qc_root / "tiles"
    tiles_dir.mkdir(parents=True, exist_ok=True)
    tile_frames: list[dict] = []
    max_frames = 0
    for info in level_infos:
        lab = int(info["lab"])
        color = palette[(lab - 1) % len(palette)]
        level_mask = (lab_int == lab)
        level_root_mask = root_mask
        z_level = [int(z) for z in np.where(level_mask.any(axis=(0, 1)))[0].tolist()]
        z_root = [int(z) for z in np.where(level_root_mask.any(axis=(0, 1)))[0].tolist()]
        z_candidates_root = sorted(set(z_level).intersection(z_root))
        if not z_candidates_root:
            continue
        if len(z_candidates_root) > 10:
            idxs = np.linspace(0, len(z_candidates_root) - 1, num=10, dtype=int)
            z_samples = [z_candidates_root[i] for i in idxs]
        else:
            z_samples = z_candidates_root

        frame_paths: list[Path] = []
        for z in z_samples:
            slice_data = img_data[:, :, z]
            root_slice = root_mask[:, :, z]
            cord_slice = cord_mask[:, :, z]
            if slice_data.ndim != 2:
                continue
            frame = _render_rootlets_tile(
                out_dir=tiles_dir, slice_data=slice_data, rootlets_slice=root_slice,
                cord_slice=cord_slice, z_index=z, tile_size=tile_size,
                level_text=_level_name(lab),
                level_color=(int(color[0]), int(color[1]), int(color[2])),
                frame_id=f"lab{lab}",
            )
            if frame is not None:
                frame_paths.append(frame)
        if not frame_paths:
            continue
        max_frames = max(max_frames, len(frame_paths))
        tile_frames.append({"lab": lab, "z": int(info["z"]), "color": color, "frames": frame_paths})
    if not tile_frames:
        return None

    column = qc_root / "axial_column.png"
    ok, _ = _run_command(["convert", "-size", f"{tile_size}x{sagittal_height}", "xc:#000000", str(column)])
    if not ok:
        return None

    tile_items = [(t["frames"][0], t["z"], t["lab"]) for t in tile_frames]
    tile_items.sort(key=lambda item: item[1], reverse=True)
    max_y = max(0, sagittal_height - tile_size)
    targets = []
    for tile_path, z_index, _lab in tile_items:
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

    sagittal = _render_sagittal_mask_panel_from_ref(
        qc_root=qc_root / "sagittal", image=image, mask=root_mask, ref_mask=cord_mask,
    )
    if sagittal is None:
        return None
    sagittal_resized = qc_root / "sagittal_resized.png"
    ok, _ = _run_command(
        ["convert", str(sagittal), "-filter", "Lanczos", "-resize", f"x{sagittal_height}", str(sagittal_resized)]
    )
    if not ok:
        return None

    frames_dir = qc_root / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    montage_frames: list[Path] = []
    try:
        sag_img = Image.open(sagittal_resized).convert("RGB")
    except Exception:
        return None
    column_width = tile_size
    frame_lookup = {t["frames"][0]: t for t in tile_frames}
    for frame_idx in range(max_frames):
        column_img = Image.new("RGB", (column_width, sagittal_height), (0, 0, 0))  # type: ignore[arg-type]
        for (target, tile_path, _), y_offset in zip(targets, positions):
            tile_entry = frame_lookup.get(tile_path)
            if tile_entry is None:
                continue
            frames = tile_entry["frames"]
            if not frames:
                continue
            frame_path = frames[frame_idx % len(frames)]
            try:
                tile_img = Image.open(frame_path).convert("RGB")
            except Exception:
                continue
            column_img.paste(tile_img, (0, y_offset))
        montage_img = Image.new(
            "RGB", (sag_img.width + column_img.width, max(sag_img.height, column_img.height)), (0, 0, 0)  # type: ignore[arg-type]
        )
        montage_img.paste(sag_img, (0, 0))
        montage_img.paste(column_img, (sag_img.width, 0))
        frame_path = frames_dir / f"frame_{frame_idx:03d}.png"
        montage_img.save(frame_path)
        montage_frames.append(frame_path)

    if not montage_frames:
        return None

    montage_gif = qc_root / "rootlets_montage.gif"
    ok, _ = _run_command(
        ["convert", "-delay", "20", "-loop", "0", *[str(p) for p in montage_frames], str(montage_gif)]
    )
    if not ok:
        return None

    montage_png = qc_root / "rootlets_montage.png"
    _run_command(["convert", str(montage_frames[0]), str(montage_png)])
    return montage_gif
