"""Reportlet rendering core: image utilities, scaling, GIF helpers."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image

from .io import _run_command, _relpath, _copy_file


# ---------------------------------------------------------------------------
# Image morphology helpers — delegated to lib/image.py
# ---------------------------------------------------------------------------
from spineprep.lib.image import binary_erode_2d as _binary_erode_2d  # noqa: E402, F401
from spineprep.lib.image import mask_contour_2d as _mask_contour_2d  # noqa: E402, F401
from spineprep.lib.image import draw_thick_contour as _draw_thick_contour  # noqa: E402, F401


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
