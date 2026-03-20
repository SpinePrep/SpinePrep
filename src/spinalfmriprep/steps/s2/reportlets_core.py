"""Reportlet rendering core: image utilities, scaling, GIF helpers."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image

from .io import _run_command, _relpath, _copy_file


# ---------------------------------------------------------------------------
# Image morphology helpers (single canonical definitions)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Scaling / resizing helpers
# ---------------------------------------------------------------------------

def _scale_to_rgb(slice2d: np.ndarray) -> np.ndarray:
    """Scale a 2D slice to uint8 RGB using robust percentiles."""
    vmin, vmax = np.percentile(slice2d, [1, 99])
    if vmax <= vmin:
        vmin, vmax = float(slice2d.min()), float(slice2d.max())
    if vmax <= vmin:
        vmax = vmin + 1.0
    normalized = np.clip((slice2d - vmin) / (vmax - vmin), 0, 1)
    base = (normalized * 255).astype(np.uint8)
    return np.repeat(base[..., np.newaxis], 3, axis=2)


def _resize_rgb(rgb: np.ndarray, width: int, height: int) -> np.ndarray:
    img = Image.fromarray(rgb, mode="RGB")
    img = img.resize((int(width), int(height)), resample=2)  # 2 == BILINEAR
    return np.array(img, dtype=np.uint8)


def _resize_mask(mask: np.ndarray, width: int, height: int) -> np.ndarray:
    img = Image.fromarray((mask.astype(np.uint8) * 255), mode="L")
    img = img.resize((int(width), int(height)), resample=0)  # 0 == NEAREST
    return (np.array(img, dtype=np.uint8) > 0)


def _cover_resize_and_crop_rgb(rgb: np.ndarray, width: int, height: int) -> np.ndarray:
    """Resize to cover (width,height) preserving aspect, then center-crop."""
    img = Image.fromarray(rgb, mode="RGB")
    src_w, src_h = img.size
    if src_w <= 0 or src_h <= 0:
        return np.zeros((height, width, 3), dtype=np.uint8)
    scale = max(width / src_w, height / src_h)
    new_w = int(np.ceil(src_w * scale))
    new_h = int(np.ceil(src_h * scale))
    resized = img.resize((new_w, new_h), resample=2)  # 2 == BILINEAR
    left = max(0, (new_w - width) // 2)
    top = max(0, (new_h - height) // 2)
    cropped = resized.crop((left, top, left + width, top + height))
    return np.array(cropped, dtype=np.uint8)


def _cover_resize_and_crop_mask(mask: np.ndarray, width: int, height: int) -> np.ndarray:
    """Resize to cover (width,height) preserving aspect, then center-crop (nearest)."""
    img = Image.fromarray((mask.astype(np.uint8) * 255), mode="L")
    src_w, src_h = img.size
    if src_w <= 0 or src_h <= 0:
        return np.zeros((height, width), dtype=bool)
    scale = max(width / src_w, height / src_h)
    new_w = int(np.ceil(src_w * scale))
    new_h = int(np.ceil(src_h * scale))
    resized = img.resize((new_w, new_h), resample=0)  # 0 == NEAREST
    left = max(0, (new_w - width) // 2)
    top = max(0, (new_h - height) // 2)
    cropped = resized.crop((left, top, left + width, top + height))
    return (np.array(cropped, dtype=np.uint8) > 0)


def _fit_resize_and_paste_rgb(rgb: np.ndarray, width: int, height: int) -> np.ndarray:
    """Resize to fit within (width,height) preserving aspect, then paste on black background."""
    img = Image.fromarray(rgb, mode="RGB")
    src_w, src_h = img.size
    if src_w <= 0 or src_h <= 0:
        return np.zeros((height, width, 3), dtype=np.uint8)
    # Scale to fit (use min instead of max)
    scale = min(width / src_w, height / src_h)
    new_w = int(np.ceil(src_w * scale))
    new_h = int(np.ceil(src_h * scale))
    resized = img.resize((new_w, new_h), resample=2)  # 2 == BILINEAR
    # Paste on black background, centered
    canvas = Image.new("RGB", (width, height), (0, 0, 0))  # type: ignore[arg-type]
    left = (width - new_w) // 2
    top = (height - new_h) // 2
    canvas.paste(resized, (left, top))
    return np.array(canvas, dtype=np.uint8)


def _fit_resize_and_paste_mask(mask: np.ndarray, width: int, height: int) -> np.ndarray:
    """Resize to fit within (width,height) preserving aspect, then paste on black background."""
    img = Image.fromarray((mask.astype(np.uint8) * 255), mode="L")
    src_w, src_h = img.size
    if src_w <= 0 or src_h <= 0:
        return np.zeros((height, width), dtype=bool)
    # Scale to fit (use min instead of max)
    scale = min(width / src_w, height / src_h)
    new_w = int(np.ceil(src_w * scale))
    new_h = int(np.ceil(src_h * scale))
    resized = img.resize((new_w, new_h), resample=0)  # 0 == NEAREST
    # Paste on black background, centered
    canvas = Image.new("L", (width, height), 0)  # type: ignore[arg-type]
    left = (width - new_w) // 2
    top = (height - new_h) // 2
    canvas.paste(resized, (left, top))
    return (np.array(canvas, dtype=np.uint8) > 0)


# ---------------------------------------------------------------------------
# GIF / image writing helpers
# ---------------------------------------------------------------------------

def _make_gif(source: Optional[Path], dest: Path, out_root: Path) -> Optional[str]:
    if source is None:
        return None
    ok, _ = _run_command(["convert", str(source), str(dest)])
    if not ok:
        return None
    return _relpath(dest, out_root)


def _write_ppm(path: Path, rgb: np.ndarray) -> None:
    if rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError("RGB array must have shape (H, W, 3).")
    height, width, _ = rgb.shape
    header = f"P6\n{width} {height}\n255\n".encode("ascii")
    path.write_bytes(header + rgb.astype(np.uint8).tobytes())


def _compose_overlay(background: Path, overlay: Path, dest: Path) -> bool:
    ok, _ = _run_command(
        [
            "convert",
            str(background),
            str(overlay),
            "-compose",
            "over",
            "-composite",
            str(dest),
        ]
    )
    return ok


# ---------------------------------------------------------------------------
# Panel helpers
# ---------------------------------------------------------------------------

def _write_not_available_panel(dest: Path, out_root: Path, message: str) -> Optional[str]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    ok, _ = _run_command(
        [
            "convert",
            "-size",
            "1200x900",
            "xc:#111111",
            "-gravity",
            "center",
            "-pointsize",
            "36",
            "-fill",
            "#e6e6e6",
            "-annotate",
            "0",
            message,
            str(dest),
        ]
    )
    if not ok:
        return None
    return _relpath(dest, out_root)


def _find_qc_overlay(qc_root: Path) -> Optional[Path]:
    matches = sorted(qc_root.rglob("overlay_img.png"))
    return matches[-1] if matches else None


def _find_qc_background(qc_root: Path) -> Optional[Path]:
    matches = sorted(qc_root.rglob("background_img.png"))
    return matches[-1] if matches else None


def _copy_reportlet(source: Optional[Path], dest: Path, out_root: Path) -> Optional[str]:
    if source is None:
        return None
    _copy_file(source, dest)
    return _relpath(dest, out_root)
