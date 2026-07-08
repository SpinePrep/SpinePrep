"""Shared reportlet helpers — one visual language across the chain.

The standard is documented in `.claude/specs/reportlet-visual-standard.md`.
New renderers `from spineprep.reportlets_common import …`; existing
renderers adopt at next touch (principle §6: lock and ship).

References followed by the standard:
- SCT QC tool conventions (sct_qc HTML reports)
- fMRIPrep / nipreps section-banner + SVG cuts
- MRIQC IQM badges + mosaic plots
- CoSpine 2025 (Wei et al., Sci Data) sagittal label + axial montage
- Cohen-Adad lab cord viz conventions (R/L radiological)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import nibabel as nib
import numpy as np


# ---------------------------------------------------------------------------
# Palette (per §"Color palette" of the standard)
# ---------------------------------------------------------------------------

BG = "#0f1115"
PANEL = "#1a1d23"
BORDER = "#2a2e36"
TEXT = "#e6e8ec"
MUTED = "#9ca3af"
MARKER_YELLOW = "#facc15"

STATUS: dict[str, dict[str, str]] = {
    "PASS":    {"fill": "#14532d", "edge": "#22c55e", "text": "#22c55e"},
    "WARN":    {"fill": "#3a2f00", "edge": "#f59e0b", "text": "#f59e0b"},
    "FAIL":    {"fill": "#3a1010", "edge": "#ef4444", "text": "#ef4444"},
    "UNKNOWN": {"fill": "#1a1d23", "edge": "#666666", "text": "#cccccc"},
}

# Semantic data colors — extend, don't re-pick.
SEMANTIC = {
    "cord":          "#ef4444",  # red — subject cord seg
    "cord_template": "#3b82f6",  # blue — PAM50 / template cord
    "discovery":     "#22d3ee",  # cyan — discovery cord
    "crop_box":      "#f59e0b",  # amber — crop bbox
    "canal":         "#a78bfa",  # purple
    "disc":          "#facc15",  # yellow
    "vertebrae":     "#22c55e",  # green
    "before":        "#888888",  # gray — "before" line in 2-state plots
    "after":         "#0086e6",  # blue — "after" line
}


# ---------------------------------------------------------------------------
# NIfTI + mask geometry helpers
# ---------------------------------------------------------------------------

def load_canonical(
    path: Path,
) -> tuple[np.ndarray, np.ndarray, tuple[float, float, float]]:
    """Load a NIfTI in canonical (RAS) orientation. Returns (data, affine, zooms)."""
    img = nib.as_closest_canonical(nib.load(path))
    data = img.get_fdata()
    if data.ndim > 3:
        data = data[..., 0]
    return data, img.affine, tuple(float(z) for z in img.header.get_zooms()[:3])


def intensity_window(
    arr: np.ndarray, lo_pct: float = 2.0, hi_pct: float = 98.0,
) -> tuple[float, float]:
    """Robust intensity window from percentiles. Returns (vmin, vmax)."""
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return 0.0, 1.0
    vmin = float(np.percentile(finite, lo_pct))
    vmax = float(np.percentile(finite, hi_pct))
    if vmax <= vmin:
        vmax = vmin + 1.0
    return vmin, vmax


def cord_bbox_xy(
    mask: np.ndarray, margin: int = 6,
) -> tuple[int, int, int, int]:
    """In-plane (X, Y) bbox of a 3D cord mask with `margin` in voxels."""
    if mask.sum() == 0:
        nx, ny = mask.shape[0], mask.shape[1]
        return 0, nx, 0, ny
    plane = mask.any(axis=2)
    xs, ys = np.nonzero(plane)
    x0 = max(0, int(xs.min()) - margin)
    x1 = min(mask.shape[0], int(xs.max()) + margin + 1)
    y0 = max(0, int(ys.min()) - margin)
    y1 = min(mask.shape[1], int(ys.max()) + margin + 1)
    return x0, x1, y0, y1


def cord_zrange(mask: np.ndarray) -> tuple[int, int]:
    """First and last cord-bearing Z slices (inclusive)."""
    if mask.sum() == 0:
        return 0, mask.shape[2] - 1
    z_idx = np.where(mask.any(axis=(0, 1)))[0]
    return int(z_idx.min()), int(z_idx.max())


def uniform_z_picks(
    z0: int, z1: int, n: int = 6, edge_skip_frac: float = 0.08,
) -> list[int]:
    """N uniformly-spaced Z indices with a margin from each end.

    Skips the partial-cord edge slices (cord entering/exiting FOV) so
    the displayed tiles all show full cord cross-sections.
    """
    if z1 <= z0:
        return [z0]
    span = z1 - z0
    skip = max(1, int(round(edge_skip_frac * span)))
    z_lo = min(z0 + skip, z1)
    z_hi = max(z1 - skip, z_lo)
    if z_hi < z_lo:
        z_lo, z_hi = z0, z1
    return np.linspace(z_lo, z_hi, num=min(n, z_hi - z_lo + 1),
                       dtype=int).tolist()


def midcord_sagittal_slice(mask: np.ndarray) -> int:
    """X-axis (sagittal) slice index at the cord centerline."""
    if mask.sum() == 0:
        return mask.shape[0] // 2
    xs = np.argwhere(mask)[:, 0]
    return int(np.median(xs))


def per_slice_centered_crop(
    cord_mask: np.ndarray, z: int,
    window_vox: tuple[int, int] = (22, 22),
    fallback_bbox: Optional[tuple[int, int, int, int]] = None,
) -> tuple[int, int, int, int]:
    """Cord-centered (X, Y) crop bbox for axial slice z.

    Each axial tile centers on that slice's cord centroid. Falls back
    to ``fallback_bbox`` (typically the global 3D cord bbox) when the
    slice has no cord voxels.
    """
    sl = cord_mask[:, :, z]
    nx, ny = cord_mask.shape[0], cord_mask.shape[1]
    hx, hy = window_vox
    if not sl.any():
        if fallback_bbox is not None:
            return fallback_bbox
        cx, cy = nx // 2, ny // 2
    else:
        xs, ys = np.nonzero(sl)
        cx = int(round(float(xs.mean())))
        cy = int(round(float(ys.mean())))
    x0 = max(0, cx - hx // 2)
    x1 = min(nx, x0 + hx)
    x0 = max(0, x1 - hx)
    y0 = max(0, cy - hy // 2)
    y1 = min(ny, y0 + hy)
    y0 = max(0, y1 - hy)
    return x0, x1, y0, y1


# ---------------------------------------------------------------------------
# Header / footer / pill primitives
# ---------------------------------------------------------------------------

def draw_pill(
    ax, x: float, y: float, w: float, h: float, label: str,
    status: str, fontsize: int = 13, transform=None,
) -> None:
    """Status pill — plain Rectangle, no FancyBboxPatch (no rounding
    artifacts in narrow header strips)."""
    pal = STATUS.get(status, STATUS["UNKNOWN"])
    if transform is None:
        transform = ax.transAxes
    box = mpatches.Rectangle(
        (x, y), w, h,
        facecolor=pal["fill"], edgecolor=pal["edge"], linewidth=1.2,
        transform=transform, zorder=5,
    )
    ax.add_patch(box)
    ax.text(x + w / 2, y + h / 2, label, ha="center", va="center",
            color=pal["text"], fontsize=fontsize, fontweight="bold",
            transform=transform, zorder=6)


def add_header(
    fig, title: str, subtitle: str, status: str,
    metric_text: Optional[str] = None,
) -> None:
    """Top header strip: title (left), subtitle (left), metric (right),
    status pill (far right)."""
    ax = fig.add_axes((0.0, 0.92, 1.0, 0.08))
    ax.set_facecolor(BG); ax.axis("off")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.text(0.012, 0.65, title, color=TEXT, fontsize=18,
            fontweight="bold", transform=ax.transAxes, va="center")
    ax.text(0.012, 0.22, subtitle, color=MUTED, fontsize=12,
            family="monospace", transform=ax.transAxes, va="center")
    if metric_text:
        ax.text(0.82, 0.5, metric_text, color=TEXT, fontsize=14,
                fontweight="bold", ha="right", va="center",
                transform=ax.transAxes)
    draw_pill(ax, 0.88, 0.25, 0.10, 0.50, status, status,
              fontsize=15, transform=ax.transAxes)


def add_footer(
    fig, legend_items: Iterable[tuple[str, str]],
    metric_lines: Iterable[str] = (),
) -> None:
    """Bottom footer strip: legend swatches (left) + metric strings
    (right). Uses the renderer to measure each label's actual width
    so adjacent labels don't overlap regardless of font / DPI /
    figure width."""
    ax = fig.add_axes((0.0, 0.0, 1.0, 0.06))
    ax.set_facecolor(BG); ax.axis("off")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)

    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    inv = ax.transAxes.inverted()
    fontsize = 12
    swatch_w = 0.016
    pad_after_swatch = 0.008
    gap_between = 0.024

    x = 0.012
    for color, label in legend_items:
        ax.add_patch(mpatches.Rectangle(
            (x, 0.32), swatch_w, 0.36,
            facecolor=color, edgecolor="none",
            transform=ax.transAxes,
        ))
        text_x = x + swatch_w + pad_after_swatch
        t = ax.text(text_x, 0.5, label, color=TEXT, fontsize=fontsize,
                    ha="left", va="center", transform=ax.transAxes)
        bbox = t.get_window_extent(renderer=renderer)
        x0, _ = inv.transform((bbox.x0, 0))
        x1, _ = inv.transform((bbox.x1, 0))
        label_w = max(0.0, x1 - x0)
        x = text_x + label_w + gap_between

    metrics_str = "    ".join(metric_lines)
    if metrics_str:
        ax.text(0.988, 0.5, metrics_str, color=TEXT, fontsize=fontsize,
                family="monospace", ha="right", va="center",
                transform=ax.transAxes)


# ---------------------------------------------------------------------------
# Slice rendering primitives
# ---------------------------------------------------------------------------

def _orient_axial(ax) -> None:
    """R / L radiological convention markers on first axial tile."""
    ax.text(0.06, 0.94, "R", transform=ax.transAxes,
            color=MARKER_YELLOW, fontsize=12, fontweight="bold",
            ha="left", va="top")
    ax.text(0.94, 0.94, "L", transform=ax.transAxes,
            color=MARKER_YELLOW, fontsize=12, fontweight="bold",
            ha="right", va="top")


def render_axial_tile(
    ax, slice_xy: np.ndarray,
    overlays: list,  # 3-tuple (mask, color, lw) or 4-tuple (mask, color, lw, fill_alpha)
    vmin: float, vmax: float, z_idx: int,
    first: bool = False,
    crop: Optional[tuple[int, int, int, int]] = None,
    pixel_aspect: float = 1.0,  # = (y_voxel_mm / x_voxel_mm), set from header zooms
) -> None:
    """Render one axial tile: anat slice in grayscale + overlays.

    overlay tuple = (mask, color, linewidth) — contour only;
    or (mask, color, linewidth, fill_alpha) — fill_alpha > 0 ⇒
    alpha-blended fill in addition to the contour. fill_alpha=0
    behaves identically to the 3-tuple form. lw=0 ⇒ no contour
    (rare: fill-only).
    """
    if crop is not None:
        x0, x1, y0, y1 = crop
        slice_xy = slice_xy[x0:x1, y0:y1]
        overlays_c = [(ov[0][x0:x1, y0:y1], *ov[1:]) for ov in overlays]
    else:
        overlays_c = overlays
    disp = np.rot90(slice_xy)
    ax.imshow(disp, cmap="gray", vmin=vmin, vmax=vmax,
              interpolation="nearest", aspect=pixel_aspect)
    for ov in overlays_c:
        m, color, lw = ov[0], ov[1], ov[2]
        fill_alpha = ov[3] if len(ov) > 3 else 0.0
        m_rot = np.rot90(m.astype(bool))
        if not m_rot.any():
            continue
        if fill_alpha > 0:
            rgba = np.zeros((*m_rot.shape, 4))
            rgb = matplotlib.colors.to_rgb(color)
            rgba[..., 0] = rgb[0]; rgba[..., 1] = rgb[1]; rgba[..., 2] = rgb[2]
            rgba[..., 3] = m_rot.astype(float) * fill_alpha
            ax.imshow(rgba, interpolation="nearest", aspect=pixel_aspect)
        if lw > 0:
            ax.contour(m_rot, levels=[0.5], colors=[color],
                       linewidths=lw, alpha=1.0)
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_color(BORDER); s.set_linewidth(0.8)
    ax.text(0.06, 0.06, f"z={z_idx}", transform=ax.transAxes,
            color=MARKER_YELLOW, fontsize=12, fontweight="bold",
            ha="left", va="bottom",
            bbox=dict(facecolor="black", alpha=0.55, edgecolor="none",
                      boxstyle="round,pad=0.25"))
    if first:
        _orient_axial(ax)


def _sagittal_markers(affine: Optional[np.ndarray]) -> tuple[str, str, str, str]:
    """(top, bottom, left, right) orientation letters for the rot90'd sagittal
    display of data[x, :, :] (axes y=1, z=2). Derived from the affine so the
    A/P and S/I markers are correct for any orientation (BUG-4); falls back to
    the RAS assumption (S,I,A,P) when no affine is given.

    rot90 maps the (ny,nz) slice to display rows = Z (top=max Z) and display
    cols = Y (left=min Y): top = +Z dir, bottom = −Z, left = −Y, right = +Y.
    """
    if affine is None:
        return "S", "I", "A", "P"
    codes = nib.orientations.aff2axcodes(affine)  # e.g. ('L','A','S')
    opp = {"R": "L", "L": "R", "A": "P", "P": "A", "S": "I", "I": "S"}
    y_code, z_code = codes[1], codes[2]
    return z_code, opp[z_code], opp[y_code], y_code


def render_sagittal(
    ax, sag_yz: np.ndarray,
    overlays: list[tuple[np.ndarray, str, float, float]],
    vmin: float, vmax: float,
    z_label_levels: Optional[dict[int, str]] = None,
    pixel_aspect: float = 1.0,  # = (y_voxel_mm / z_voxel_mm) AFTER rot90
    affine: Optional[np.ndarray] = None,  # source affine → correct S/I/A/P
) -> None:
    """Sagittal panel: anat with semi-transparent overlays + contours.

    overlays = list of (binary_mask_yz, color_hex, alpha, linewidth).
    `linewidth > 0` ⇒ contour; `alpha > 0 and linewidth == 0` ⇒
    alpha-blended fill. S/I/A/P orientation markers (affine-derived) + optional
    vertebral-level labels along the right margin.
    """
    disp = np.rot90(sag_yz)
    ax.imshow(disp, cmap="gray", vmin=vmin, vmax=vmax,
              interpolation="nearest", aspect=pixel_aspect)
    for m, color, alpha, lw in overlays:
        m_rot = np.rot90(m.astype(bool))
        if not m_rot.any():
            continue
        if lw > 0:
            ax.contour(m_rot, levels=[0.5], colors=[color],
                       linewidths=lw, alpha=1.0)
        elif alpha > 0:
            rgba = np.zeros((*m_rot.shape, 4))
            rgb = matplotlib.colors.to_rgb(color)
            rgba[..., 0] = rgb[0]; rgba[..., 1] = rgb[1]; rgba[..., 2] = rgb[2]
            rgba[..., 3] = m_rot.astype(float) * alpha
            ax.imshow(rgba, interpolation="nearest", aspect=pixel_aspect)
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_color(BORDER); s.set_linewidth(0.8)
    _bbox = dict(facecolor="black", alpha=0.55, edgecolor="none",
                 boxstyle="round,pad=0.25")
    _top, _bot, _left, _right = _sagittal_markers(affine)
    ax.text(0.05, 0.97, _top, transform=ax.transAxes, color=MARKER_YELLOW,
            fontsize=14, fontweight="bold", ha="left", va="top", bbox=_bbox)
    ax.text(0.05, 0.03, _bot, transform=ax.transAxes, color=MARKER_YELLOW,
            fontsize=14, fontweight="bold", ha="left", va="bottom", bbox=_bbox)
    ax.text(0.03, 0.5, _left, transform=ax.transAxes, color=MARKER_YELLOW,
            fontsize=14, fontweight="bold", ha="left", va="center", bbox=_bbox)
    ax.text(0.97, 0.5, _right, transform=ax.transAxes, color=MARKER_YELLOW,
            fontsize=14, fontweight="bold", ha="right", va="center", bbox=_bbox)
    if z_label_levels:
        for z, lbl in z_label_levels.items():
            ax.text(0.99, 1.0 - (z / sag_yz.shape[1]),
                    lbl, transform=ax.transAxes, color=TEXT,
                    fontsize=10, family="monospace", fontweight="bold",
                    ha="right", va="center",
                    bbox=dict(facecolor="black", alpha=0.6,
                              edgecolor="none", boxstyle="round,pad=0.15"))


def render_sagittal_plus_montage(
    output_path: Path,
    title: str,
    subtitle: str,
    status: str,
    metric_header: Optional[str],
    anat: np.ndarray,
    cord_mask: np.ndarray,
    sag_overlays: list[tuple[np.ndarray, str, float, float]],
    axial_overlays_factory,  # callable: z -> list[(mask_xy, color, lw)]
    legend_items: list[tuple[str, str]],
    metric_lines: list[str],
    n_axial: int = 6,
    n_axial_cols: int = 2,
    margin_vox: int = 6,
    z_label_levels: Optional[dict[int, str]] = None,
    sag_slab_halfwidth_x: int = 0,
    axial_window_vox: Optional[tuple[int, int]] = (22, 22),
    zooms: Optional[tuple[float, float, float]] = None,
    intensity_pct: tuple[float, float] = (2.0, 98.0),
) -> None:
    """Standard 2-panel reportlet: sagittal (~36%) + axial grid (~58%).

    Pass per-tile `axial_overlays_factory(z) -> list of (mask, color,
    lw)` so each reportlet supplies its own overlays. `sag_overlays`
    elements may be 2D (single slice) or 3D (sliced/projected here).
    `sag_slab_halfwidth_x` enables off-midline projection (e.g.
    rootlets) — see standard §"Sagittal panel".
    """
    x_mid = midcord_sagittal_slice(cord_mask)
    x0, x1, y0, y1 = cord_bbox_xy(cord_mask, margin=margin_vox)
    z0, z1 = cord_zrange(cord_mask)
    z_picks = uniform_z_picks(z0, z1, n_axial)

    k = max(0, int(sag_slab_halfwidth_x))
    x_lo, x_hi = max(0, x_mid - k), min(anat.shape[0], x_mid + k + 1)
    sag = anat[x_lo:x_hi, :, :].max(axis=0)
    sag_overlays_slab: list[tuple[np.ndarray, str, float, float]] = []
    for m, color, alpha, lw in sag_overlays:
        if m.ndim == 2:
            sag_overlays_slab.append((m, color, alpha, lw))
        else:
            sag_overlays_slab.append(
                (m[x_lo:x_hi, :, :].any(axis=0), color, alpha, lw))
    lo_pct, hi_pct = intensity_pct
    vmin_sag, vmax_sag = intensity_window(sag, lo_pct, hi_pct)
    mid_z = (z0 + z1) // 2
    vmin_ax, vmax_ax = intensity_window(anat[:, :, mid_z], lo_pct, hi_pct)

    # Pixel aspects from voxel zooms — keeps anisotropic data
    # geometrically faithful instead of squishing it square.
    if zooms is not None and len(zooms) >= 3:
        zx, zy, zz = float(zooms[0]), float(zooms[1]), float(zooms[2])
    else:
        zx = zy = zz = 1.0
    # Sagittal after rot90: rows = Z (S-I), cols = Y (A-P).
    # imshow aspect = (y-data-unit-size / x-data-unit-size) so to make
    # each ROW = zz mm and each COL = zy mm, aspect = zz / zy.
    sag_aspect = zz / zy if zy > 0 else 1.0
    # Axial after rot90: rows = Y (A-P), cols = X (R-L). aspect = zy / zx.
    ax_aspect = zy / zx if zx > 0 else 1.0

    fig = plt.figure(figsize=(16.0, 9.0), facecolor=BG)
    fig.patch.set_facecolor(BG)
    add_header(fig, title, subtitle, status, metric_header)

    ax_sag = fig.add_axes((0.025, 0.10, 0.36, 0.80))
    ax_sag.set_facecolor(BG)
    render_sagittal(ax_sag, sag, sag_overlays_slab, vmin_sag, vmax_sag,
                    z_label_levels=z_label_levels, pixel_aspect=sag_aspect)

    n_tiles = len(z_picks)
    n_cols = max(1, min(n_axial_cols, n_tiles))
    n_rows = (n_tiles + n_cols - 1) // n_cols
    grid_x0 = 0.42
    grid_x1 = 0.985
    grid_y0 = 0.10
    grid_y1 = 0.90
    cell_w = (grid_x1 - grid_x0) / n_cols
    cell_h = (grid_y1 - grid_y0) / n_rows
    global_bbox = (x0, x1, y0, y1)

    z_top_first = list(reversed(z_picks))
    for i, z in enumerate(z_top_first):
        row = i // n_cols
        col = i % n_cols
        ax = fig.add_axes((
            grid_x0 + col * cell_w + cell_w * 0.04,
            grid_y0 + (n_rows - 1 - row) * cell_h + cell_h * 0.04,
            cell_w * 0.92, cell_h * 0.92,
        ))
        ax.set_facecolor(BG)
        overlays = axial_overlays_factory(z)
        if axial_window_vox is not None:
            tile_crop = per_slice_centered_crop(
                cord_mask, z, window_vox=axial_window_vox,
                fallback_bbox=global_bbox)
        else:
            tile_crop = global_bbox
        render_axial_tile(ax, anat[:, :, z], overlays,
                          vmin_ax, vmax_ax, z, first=(i == 0),
                          crop=tile_crop, pixel_aspect=ax_aspect)

    add_footer(fig, legend_items, metric_lines)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=130, facecolor=BG,
                bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)


def stub_figure(output_path: Path, reason: str) -> None:
    """Tiny placeholder figure when inputs are missing. Used by per-
    reportlet renderers as a graceful fallback."""
    fig = plt.figure(figsize=(8, 3), facecolor=BG)
    ax = fig.add_subplot(111)
    ax.set_facecolor(BG); ax.axis("off")
    ax.text(0.5, 0.5, reason, ha="center", va="center",
            color=MUTED, fontsize=12, transform=ax.transAxes)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=120, facecolor=BG, bbox_inches="tight")
    plt.close(fig)
