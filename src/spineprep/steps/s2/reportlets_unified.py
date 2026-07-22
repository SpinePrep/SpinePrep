"""S2 unified reportlets — implements the chain-wide visual standard.

Uses shared helpers from `spineprep.reportlets_common`. The
standard (.claude/specs/reportlet-visual-standard.md) is the single
source of truth for layout, palette, and overlay conventions; this
module just supplies the S2-specific overlay factories and metric
extraction.

Five S2 reportlets:
  S2.1  crop_box_sagittal         Discovery + crop bbox sanity
  S2.2a cordmask_montage          Cord seg quality
  S2.2b totalspineseg_montage     Vertebrae + discs + canal labeling
  S2.3  rootlets_montage          Dorsal rootlets by level
  S2.4  pam50_reg_overlay         PAM50 normalization quality

Each reportlet is a single PNG with a fixed structure:

  ┌──────────────────────────────────────────────────────────────┐
  │  S2.x — <title>           sub-XX • <dataset>     [STATUS]    │  header
  ├──────────────────────────────────────────────────────────────┤
  │                                                              │
  │           CORD-CROPPED          │     AXIAL MONTAGE          │
  │           SAGITTAL              │     (9 cord-bearing Z      │
  │           with contour          │     slices, with Z idx     │
  │           overlay               │     labels)                │
  │                                                              │
  ├──────────────────────────────────────────────────────────────┤
  │  Legend: <color> = <thing>     |  <metric label>: <value>    │  footer
  └──────────────────────────────────────────────────────────────┘

Design choices grounded in field standards:

- **Contour overlays, not solid fills.** Standard in SCT QC tool,
  fMRIPrep, MRIQC, CoSpine paper figures. Solid fills hide the tissue
  underneath; contours let the operator see whether the seg boundary
  matches the cord boundary.
- **Cord-cropped views.** The cord occupies a tiny fraction of the
  anat FOV (cervical cord diameter ~5–7 mm in a ~150×150 mm FOV).
  Cropping to a tight cord bbox maximizes information per pixel.
- **Per-slice Z indices and L/R orientation markers** on the first
  axial tile (BIDS-Derivatives + fMRIPrep convention).
- **Robust intensity windowing.** 2-98th percentile within the cord
  ROI so the anat contrast is dataset-agnostic.
- **Anatomically correct orientation.** Sagittal: anterior right, S–I
  top-to-bottom. Axial: anatomical right at viewer's left
  (radiological convention; matches SCT QC).
- **Dark theme + status pill** consistent with the S1 dashboard so
  navigation across the chain feels coherent (CLAUDE.md dev §4).
- **Headline metric in the corner** (Dice / CSA / vertebra count) so
  the operator gets both visual + quantitative signal in one glance.
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
from spineprep.lib.timing import timed_subprocess_run


# ---------------------------------------------------------------------------
# Visual palette (matches S1 + dashboard banner CSS)
# ---------------------------------------------------------------------------

_BG = "#0f1115"
_PANEL = "#1a1d23"
_BORDER = "#2a2e36"
_TEXT = "#e6e8ec"
_MUTED = "#9ca3af"

_STATUS = {
    "PASS":    {"fill": "#14532d", "edge": "#22c55e", "text": "#22c55e"},
    "WARN":    {"fill": "#3a2f00", "edge": "#f59e0b", "text": "#f59e0b"},
    "FAIL":    {"fill": "#3a1010", "edge": "#ef4444", "text": "#ef4444"},
    "UNKNOWN": {"fill": "#1a1d23", "edge": "#666666", "text": "#cccccc"},
}

# Semantic colors used across reportlets
_C_CORD       = "#ef4444"  # red
_C_DISCOVERY  = "#22d3ee"  # cyan
_C_CROP_BOX   = "#f59e0b"  # amber
_C_CANAL      = "#a78bfa"  # purple
_C_DISC       = "#facc15"  # yellow
_C_PAM50      = "#3b82f6"  # blue


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def _load_canonical(path: Path) -> tuple[np.ndarray, np.ndarray, tuple[float, float, float]]:
    """Load a NIfTI as canonical RAS-ish 3D array. Returns (data, affine, zooms)."""
    img = nib.as_closest_canonical(nib.load(path))
    data = img.get_fdata()
    if data.ndim > 3:
        data = data[..., 0]
    return data, img.affine, tuple(float(z) for z in img.header.get_zooms()[:3])


def _intensity_window(arr: np.ndarray, lo_pct: float = 2.0,
                       hi_pct: float = 98.0) -> tuple[float, float]:
    """Robust intensity window from percentiles."""
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return 0.0, 1.0
    vmin = float(np.percentile(finite, lo_pct))
    vmax = float(np.percentile(finite, hi_pct))
    if vmax <= vmin:
        vmax = vmin + 1.0
    return vmin, vmax


def _cord_bbox_xy(mask: np.ndarray, margin: int = 6) -> tuple[int, int, int, int]:
    """In-plane (X, Y) bbox of a 3D cord mask with margin in voxels."""
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


def _cord_zrange(mask: np.ndarray) -> tuple[int, int]:
    """First and last cord-bearing Z slices (inclusive)."""
    if mask.sum() == 0:
        return 0, mask.shape[2] - 1
    z_idx = np.where(mask.any(axis=(0, 1)))[0]
    return int(z_idx.min()), int(z_idx.max())


def _per_slice_centered_crop(
    cord_mask: np.ndarray, z: int, window_vox: tuple[int, int] = (20, 20),
    fallback_bbox: Optional[tuple[int, int, int, int]] = None,
) -> tuple[int, int, int, int]:
    """Return (x0, x1, y0, y1) centered on the cord centroid in axial slice z.

    Each axial tile centers on the cord at that Z, so the cord stays in
    the middle of every tile regardless of cord curvature along S-I.
    Falls back to ``fallback_bbox`` (typically the global cord bbox) when
    the slice has no cord voxels.
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


def _uniform_z_picks(z0: int, z1: int, n: int = 9,
                      edge_skip_frac: float = 0.08) -> list[int]:
    """n uniformly-spaced Z indices, with a margin from each end.

    Cord segs at the first/last cord-bearing Z slice are typically
    partial (the cord is entering/exiting the FOV), so they're poor
    QC samples. `edge_skip_frac` is the fraction of the total cord-Z
    range trimmed from each side before picking. Defaults to 8 %,
    which keeps endpoints in the cord-body region.
    """
    if z1 <= z0:
        return [z0]
    span = z1 - z0
    skip = int(round(edge_skip_frac * span))
    skip = max(1, skip)
    z_lo = min(z0 + skip, z1)
    z_hi = max(z1 - skip, z_lo)
    if z_hi < z_lo:
        z_lo, z_hi = z0, z1
    return np.linspace(z_lo, z_hi, num=min(n, z_hi - z_lo + 1),
                       dtype=int).tolist()


def _draw_pill(ax, x: float, y: float, w: float, h: float, label: str,
               status: str, fontsize: int = 13, transform=None) -> None:
    """Status pill — simple rectangle with text. The previous
    FancyBboxPatch implementation used `rounding_size=0.10` in axes
    coords which exceeded h/2 in the narrow header strip and produced
    a visible "double line" artifact above and below the pill."""
    pal = _STATUS.get(status, _STATUS["UNKNOWN"])
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


def _add_header(fig, title: str, subtitle: str, status: str,
                metric_text: Optional[str] = None) -> None:
    """Header strip with title (left), subtitle (center), status pill (right)."""
    ax = fig.add_axes((0.0, 0.92, 1.0, 0.08))
    ax.set_facecolor(_BG); ax.axis("off")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.text(0.012, 0.65, title, color=_TEXT, fontsize=18,
            fontweight="bold", transform=ax.transAxes, va="center")
    ax.text(0.012, 0.22, subtitle, color=_MUTED, fontsize=12,
            family="monospace", transform=ax.transAxes, va="center")
    if metric_text:
        ax.text(0.82, 0.5, metric_text, color=_TEXT, fontsize=14,
                fontweight="bold", ha="right", va="center",
                transform=ax.transAxes)
    _draw_pill(ax, 0.88, 0.25, 0.10, 0.50, status, status,
               fontsize=15, transform=ax.transAxes)


def _add_footer(fig, legend_items: Iterable[tuple[str, str]],
                metric_lines: Iterable[str] = ()) -> None:
    """Footer strip with legend swatches (left) + metric strings (right).

    Uses the matplotlib renderer to measure actual text widths so
    legend items don't overlap — earlier per-character estimate
    (`len(label) * 0.008`) underestimated proportional-font widths
    and merged adjacent labels.
    """
    ax = fig.add_axes((0.0, 0.0, 1.0, 0.06))
    ax.set_facecolor(_BG); ax.axis("off")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)

    # Pre-measure each label's rendered width in axes coords so we can
    # advance x by the true width rather than guess from character count.
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    inv = ax.transAxes.inverted()
    fontsize = 12

    swatch_w = 0.016     # swatch rectangle width in axes coords
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
        t = ax.text(text_x, 0.5, label, color=_TEXT, fontsize=fontsize,
                    ha="left", va="center", transform=ax.transAxes)
        bbox = t.get_window_extent(renderer=renderer)
        # Width in display coords → convert to axes coords
        x0, _ = inv.transform((bbox.x0, 0))
        x1, _ = inv.transform((bbox.x1, 0))
        label_w = max(0.0, x1 - x0)
        x = text_x + label_w + gap_between

    metrics_str = "    ".join(metric_lines)
    if metrics_str:
        ax.text(0.988, 0.5, metrics_str, color=_TEXT, fontsize=fontsize,
                family="monospace", ha="right", va="center",
                transform=ax.transAxes)


def _orient_marker(ax, label_left: str = "R", label_right: str = "L") -> None:
    """Anatomical orientation markers in the top corners of an axial tile."""
    ax.text(0.06, 0.94, label_left, transform=ax.transAxes,
            color="#facc15", fontsize=12, fontweight="bold",
            ha="left", va="top")
    ax.text(0.94, 0.94, label_right, transform=ax.transAxes,
            color="#facc15", fontsize=12, fontweight="bold",
            ha="right", va="top")


def _render_axial_tile(
    ax, slice_xy: np.ndarray,
    overlays: list,  # tuples of (mask, color, linewidth) or (mask, color, lw, alpha)
    vmin: float, vmax: float, z_idx: int, first: bool = False,
    crop: Optional[tuple[int, int, int, int]] = None,
) -> None:
    """Render one axial tile: anat slice in grayscale + overlays.

    overlay tuple = (binary_mask_2d, color_hex, linewidth) for contour-only,
    or (binary_mask_2d, color_hex, linewidth, fill_alpha) for filled +
    contour. fill_alpha=0 ⇒ contour only.
    """
    if crop is not None:
        x0, x1, y0, y1 = crop
        slice_xy = slice_xy[x0:x1, y0:y1]
        overlays_cropped = []
        for ov in overlays:
            m = ov[0][x0:x1, y0:y1]
            overlays_cropped.append((m, *ov[1:]))
    else:
        overlays_cropped = overlays
    disp = np.rot90(slice_xy)
    ax.imshow(disp, cmap="gray", vmin=vmin, vmax=vmax,
              interpolation="nearest", aspect="equal")
    for ov in overlays_cropped:
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
            ax.imshow(rgba, interpolation="nearest", aspect="equal")
        if lw > 0:
            ax.contour(m_rot, levels=[0.5], colors=[color],
                       linewidths=lw, alpha=0.95)
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_color(_BORDER); s.set_linewidth(0.8)
    # Z-index label with a dark backdrop for legibility on bright tiles
    ax.text(0.06, 0.06, f"z={z_idx}", transform=ax.transAxes,
            color="#facc15", fontsize=12, fontweight="bold",
            ha="left", va="bottom",
            bbox=dict(facecolor="black", alpha=0.55, edgecolor="none",
                      boxstyle="round,pad=0.25"))
    if first:
        _orient_marker(ax)


def _render_sagittal(
    ax, sag_yz: np.ndarray, overlays: list[tuple[np.ndarray, str, float, float]],
    vmin: float, vmax: float,
    z_label_levels: Optional[dict[int, str]] = None,
) -> None:
    """Sagittal panel: anat with semi-transparent overlays + optional contours.

    overlays = list of (binary_mask_yz, color_hex, alpha, linewidth).
    If linewidth > 0, render as contour; if alpha > 0 and linewidth == 0,
    render as filled overlay.
    """
    # sag_yz: shape (n_y, n_z). Rotate so head is up.
    disp = np.rot90(sag_yz)
    ax.imshow(disp, cmap="gray", vmin=vmin, vmax=vmax,
              interpolation="nearest", aspect="equal")
    for m, color, alpha, lw in overlays:
        m_rot = np.rot90(m.astype(bool))
        if not m_rot.any():
            continue
        if lw > 0:
            ax.contour(m_rot, levels=[0.5], colors=[color],
                       linewidths=lw, alpha=0.95)
        elif alpha > 0:
            overlay_rgba = np.zeros((*m_rot.shape, 4))
            rgb = matplotlib.colors.to_rgb(color)
            overlay_rgba[..., 0] = rgb[0]
            overlay_rgba[..., 1] = rgb[1]
            overlay_rgba[..., 2] = rgb[2]
            overlay_rgba[..., 3] = m_rot.astype(float) * alpha
            ax.imshow(overlay_rgba, interpolation="nearest", aspect="equal")
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_color(_BORDER); s.set_linewidth(0.8)
    # Anatomical orientation markers with dark backdrops for legibility
    _bbox = dict(facecolor="black", alpha=0.55, edgecolor="none",
                 boxstyle="round,pad=0.25")
    ax.text(0.05, 0.97, "S", transform=ax.transAxes, color="#facc15",
            fontsize=14, fontweight="bold", ha="left", va="top", bbox=_bbox)
    ax.text(0.05, 0.03, "I", transform=ax.transAxes, color="#facc15",
            fontsize=14, fontweight="bold", ha="left", va="bottom", bbox=_bbox)
    ax.text(0.03, 0.5, "A", transform=ax.transAxes, color="#facc15",
            fontsize=14, fontweight="bold", ha="left", va="center", bbox=_bbox)
    ax.text(0.97, 0.5, "P", transform=ax.transAxes, color="#facc15",
            fontsize=14, fontweight="bold", ha="right", va="center", bbox=_bbox)
    if z_label_levels:
        # `disp = np.rot90(sag_yz)` puts superior (max Z) at the top. A level
        # whose voxels centre on superior index `z` therefore sits at axes
        # fraction (z + 0.5)/n_z from the BOTTOM (transAxes y: 0=bottom, 1=top).
        # The earlier `1 - z/n_z` mirrored this, printing C1 at the bottom.
        for z, lbl in z_label_levels.items():
            ax.text(0.99, (z + 0.5) / sag_yz.shape[1],
                    lbl, transform=ax.transAxes, color=_TEXT,
                    fontsize=10, family="monospace", fontweight="bold",
                    ha="right", va="center",
                    bbox=dict(facecolor="black", alpha=0.6,
                              edgecolor="none", boxstyle="round,pad=0.15"))


def _midcord_sagittal_slice(mask: np.ndarray) -> int:
    """X-axis (sagittal) slice index at the cord centerline."""
    if mask.sum() == 0:
        return mask.shape[0] // 2
    xs = np.argwhere(mask)[:, 0]
    return int(np.median(xs))


def _cord_centerline_x(cord_mask: np.ndarray) -> np.ndarray:
    """Per-SI-level L–R (X) centroid of the cord — the cord centerline.

    Length-``n_z`` float array; empty levels filled by interpolation so it
    is finite everywhere. Basis for the curved sagittal reformat that keeps
    a cord which curves in L–R fully in view (a single flat plane truncates
    it wherever it drifts out of plane).
    """
    nz = cord_mask.shape[2]
    xc = np.full(nz, np.nan, dtype=float)
    for z in range(nz):
        sl = cord_mask[:, :, z]
        if sl.any():
            xc[z] = float(np.nonzero(sl)[0].mean())
    valid = np.isfinite(xc)
    if not valid.any():
        xc[:] = cord_mask.shape[0] / 2.0
        return xc
    idx = np.arange(nz)
    return np.interp(idx, idx[valid], xc[valid])


def _curved_sagittal_reformat(
    vol: np.ndarray, x_center: np.ndarray,
    slab_halfwidth: int = 0, reduce: str = "max",
) -> np.ndarray:
    """Centerline-following sagittal reformat: for each SI level, sample the
    A–P column at that level's cord X-centroid and assemble into one 2D
    ``(n_y, n_z)`` image that follows the curving cord. ``slab_halfwidth>0``
    reduces over ``x_center[z] ± k`` (reduce ∈ {"max","mean","any"})."""
    nx, ny, nz = vol.shape
    xc = np.clip(np.rint(np.asarray(x_center, dtype=float)).astype(int), 0, nx - 1)
    out = np.zeros((ny, nz), dtype=float)
    k = max(0, int(slab_halfwidth))
    for z in range(nz):
        x = int(xc[z])
        if k > 0:
            lo, hi = max(0, x - k), min(nx, x + k + 1)
            col = vol[lo:hi, :, z]
            if reduce == "mean":
                out[:, z] = col.mean(axis=0)
            elif reduce == "any":
                out[:, z] = col.any(axis=0)
            else:
                out[:, z] = col.max(axis=0)
        else:
            out[:, z] = vol[x, :, z]
    return out


def _layout_figure(fig_w: float = 13.0, fig_h: float = 7.0) -> plt.Figure:
    fig = plt.figure(figsize=(fig_w, fig_h), facecolor=_BG)
    fig.patch.set_facecolor(_BG)
    return fig


def _stub_figure(output_path: Path, reason: str) -> None:
    """Tiny placeholder figure when inputs are missing."""
    fig = plt.figure(figsize=(8, 3), facecolor=_BG)
    ax = fig.add_subplot(111)
    ax.set_facecolor(_BG); ax.axis("off")
    ax.text(0.5, 0.5, reason, ha="center", va="center",
            color=_MUTED, fontsize=12, transform=ax.transAxes)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=120, facecolor=_BG, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Reportlet 1: crop_box_sagittal (S2.1 — Discovery + Crop)
# ---------------------------------------------------------------------------

def render_crop_box_sagittal(
    output_path: Path,
    cordref_std_path: Path,
    discovery_seg_path: Optional[Path],
    crop_mask_path: Optional[Path],
    subject: str = "?",
    dataset_key: str = "?",
    status: str = "UNKNOWN",
) -> None:
    """S2.1: full-FOV sagittal with discovery cord contour + crop bbox."""
    try:
        if not cordref_std_path or not cordref_std_path.exists():
            _stub_figure(output_path, "Anat reference unavailable")
            return
        anat, _, zooms = _load_canonical(cordref_std_path)
        discovery = None
        if discovery_seg_path and discovery_seg_path.exists():
            d, _, _ = _load_canonical(discovery_seg_path)
            if d.shape == anat.shape:
                discovery = d > 0
        crop_mask = None
        if crop_mask_path and crop_mask_path.exists():
            c, _, _ = _load_canonical(crop_mask_path)
            if c.shape == anat.shape:
                crop_mask = c > 0

        ref_mask = discovery if discovery is not None else crop_mask
        if ref_mask is None or not ref_mask.any():
            ref_mask = np.zeros_like(anat, dtype=bool)
            ref_mask[anat.shape[0]//2-2:anat.shape[0]//2+2, :, :] = True

        # Centerline-following reformat so a cord that curves in L–R shows
        # in full (single flat plane truncates it). Falls back to the median
        # slice when there is no usable mask.
        if ref_mask.any():
            _xc = _cord_centerline_x(ref_mask)
            sag = _curved_sagittal_reformat(anat, _xc)
        else:
            _xc = None
            x_mid = _midcord_sagittal_slice(ref_mask)
            sag = anat[x_mid, :, :]
        vmin, vmax = _intensity_window(sag)

        bbox_extent = ""
        if crop_mask is not None and crop_mask.any():
            x0, x1, y0, y1 = _cord_bbox_xy(crop_mask, margin=0)
            z = np.where(crop_mask.any(axis=(0, 1)))[0]
            z0, z1 = int(z.min()), int(z.max())
            dx = (x1 - x0) * zooms[0]
            dy = (y1 - y0) * zooms[1]
            dz = (z1 - z0 + 1) * zooms[2]
            bbox_extent = f"bbox {dx:.0f}×{dy:.0f}×{dz:.0f} mm"

        # Aspect-match: sagittal after rot90 is `n_z × n_y` (rows × cols).
        # Pick figure dims so the image fills the body without empty
        # margins. Header 0.6", footer 0.4". Cap height at 11".
        n_y, n_z = sag.shape
        img_w_in = max(1, n_y) * float(zooms[1])  # AP extent (mm)
        img_h_in = max(1, n_z) * float(zooms[2])  # S-I extent (mm)
        # Mid-cord sagittal is typically taller than wide for cervical
        # acquisitions; scale to ~5 in height for the image body.
        target_h = 6.5
        body_w = max(2.5, target_h * (img_w_in / img_h_in))
        fig_w = max(8.0, body_w + 1.5)  # padding for axis margins
        fig_h = target_h + 1.0          # header + footer
        fig = _layout_figure(fig_w, fig_h)
        _add_header(fig, "S2.1 — Discovery + Crop",
                     f"sub-{subject} • {dataset_key}", status, bbox_extent)

        # Single sagittal panel centered horizontally, sized to image aspect
        body_h_frac = 0.84
        body_w_frac = body_w / fig_w
        body_x0 = (1.0 - body_w_frac) / 2.0
        ax = fig.add_axes((body_x0, 0.08, body_w_frac, body_h_frac))
        ax.set_facecolor(_BG)
        def _sag_overlay(mask3d: np.ndarray) -> np.ndarray:
            if _xc is not None:
                return _curved_sagittal_reformat(
                    mask3d.astype(float), _xc, reduce="any") > 0.5
            return mask3d[x_mid, :, :]

        overlays = []
        if discovery is not None:
            overlays.append((_sag_overlay(discovery), _C_DISCOVERY, 0.0, 1.4))
        if crop_mask is not None:
            overlays.append((_sag_overlay(crop_mask), _C_CROP_BOX, 0.15, 1.8))
        _render_sagittal(ax, sag, overlays, vmin, vmax)

        _add_footer(fig, [
            (_C_DISCOVERY, "discovery cord"),
            (_C_CROP_BOX,  "crop bbox"),
        ], [bbox_extent] if bbox_extent else [])

        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path, dpi=130, facecolor=_BG,
                    bbox_inches="tight", pad_inches=0.05)
        plt.close(fig)
    except Exception as e:
        _stub_figure(output_path, f"crop_box render failed: {e}")


# ---------------------------------------------------------------------------
# Shared layout: sagittal + axial montage
# ---------------------------------------------------------------------------

def _render_sagittal_plus_montage(
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
) -> None:
    """Generic 2-panel layout: sagittal on left, axial grid montage on right.

    The axial grid is `n_axial_cols × ⌈n_axial / n_axial_cols⌉`. Defaults to
    8 tiles in a 2×4 grid — large enough to read each slice without
    losing cord-length coverage.

    `sag_slab_halfwidth_x` thickens the sagittal slab to a max-projection
    over X ± k voxels. Useful for off-midline features like rootlets.
    """
    x_mid = _midcord_sagittal_slice(cord_mask)
    x0, x1, y0, y1 = _cord_bbox_xy(cord_mask, margin=margin_vox)
    z0, z1 = _cord_zrange(cord_mask)
    z_picks = _uniform_z_picks(z0, z1, n_axial)

    # Sagittal: centerline-following (curved) reformat so a cord that curves
    # in L–R as it descends stays fully in view. `sag_slab_halfwidth_x`
    # thickens the slab around the centerline for off-midline features
    # (e.g. rootlets). 3D overlay masks follow the same reformat; 2D
    # overlays (pre-sliced by the caller) pass through unchanged.
    k = max(0, int(sag_slab_halfwidth_x))
    sag_overlays_slab: list[tuple[np.ndarray, str, float, float]] = []
    if cord_mask.any():
        x_center = _cord_centerline_x(cord_mask)
        sag = _curved_sagittal_reformat(anat, x_center, slab_halfwidth=k,
                                        reduce="max")
        for m, color, alpha, lw in sag_overlays:
            if m.ndim == 2:
                sag_overlays_slab.append((m, color, alpha, lw))
            else:
                slab = _curved_sagittal_reformat(
                    m.astype(float), x_center, slab_halfwidth=k,
                    reduce="any") > 0.5
                sag_overlays_slab.append((slab, color, alpha, lw))
    else:
        x_lo, x_hi = max(0, x_mid - k), min(anat.shape[0], x_mid + k + 1)
        sag = anat[x_lo:x_hi, :, :].max(axis=0)
        for m, color, alpha, lw in sag_overlays:
            if m.ndim == 2:
                sag_overlays_slab.append((m, color, alpha, lw))
            else:
                slab = m[x_lo:x_hi, :, :].any(axis=0)
                sag_overlays_slab.append((slab, color, alpha, lw))
    vmin_sag, vmax_sag = _intensity_window(sag)
    mid_z = (z0 + z1) // 2
    vmin_ax, vmax_ax = _intensity_window(anat[:, :, mid_z])

    fig = _layout_figure(16.0, 9.0)
    _add_header(fig, title, subtitle, status, metric_header)

    # Sagittal occupies the LEFT (slightly under 40%)
    ax_sag = fig.add_axes((0.025, 0.10, 0.36, 0.80))
    ax_sag.set_facecolor(_BG)
    _render_sagittal(ax_sag, sag, sag_overlays_slab, vmin_sag, vmax_sag,
                     z_label_levels=z_label_levels)

    # Axial grid on the RIGHT
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

    # Order tiles top-to-bottom = superior-to-inferior, left-to-right within row
    z_top_first = list(reversed(z_picks))
    for i, z in enumerate(z_top_first):
        row = i // n_cols
        col = i % n_cols
        ax = fig.add_axes((
            grid_x0 + col * cell_w + cell_w * 0.04,
            grid_y0 + (n_rows - 1 - row) * cell_h + cell_h * 0.04,
            cell_w * 0.92, cell_h * 0.92,
        ))
        ax.set_facecolor(_BG)
        overlays = axial_overlays_factory(z)
        # Per-slice cord-centered crop — keeps the cord in the middle
        # of every tile regardless of cord curvature along S-I. Falls
        # back to the global cord bbox when this slice has no cord.
        if axial_window_vox is not None:
            tile_crop = _per_slice_centered_crop(
                cord_mask, z, window_vox=axial_window_vox,
                fallback_bbox=global_bbox,
            )
        else:
            tile_crop = global_bbox
        _render_axial_tile(ax, anat[:, :, z], overlays,
                            vmin_ax, vmax_ax, z, first=(i == 0),
                            crop=tile_crop)

    _add_footer(fig, legend_items, metric_lines)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=130, facecolor=_BG,
                bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Reportlet 2: cordmask_montage (S2.2 — Cord seg)
# ---------------------------------------------------------------------------

def render_cordmask_montage(
    output_path: Path,
    cordref_path: Path,
    cordmask_path: Path,
    subject: str = "?",
    dataset_key: str = "?",
    status: str = "UNKNOWN",
    metrics: Optional[dict] = None,
) -> None:
    try:
        if not cordref_path.exists() or not cordmask_path.exists():
            _stub_figure(output_path, "cordref or cord_dseg missing")
            return
        anat, _, _ = _load_canonical(cordref_path)
        cord, _, _ = _load_canonical(cordmask_path)
        if anat.shape != cord.shape:
            _stub_figure(output_path, "anat and cord_dseg shape mismatch")
            return
        cord_mask = cord > 0

        m = metrics or {}
        csa_mean = m.get("csa_mean_mm2")
        cord_vol = m.get("cord_volume_mm3")
        cord_len = m.get("cord_length_mm")
        dice = m.get("pam50_cord_dice")
        metric_header = ""
        if csa_mean is not None:
            metric_header += f"CSA {csa_mean:.1f} mm²"
        if cord_vol is not None:
            metric_header += f"  •  vol {cord_vol/1000:.1f} cm³"

        # 3D mask → reformatted along the cord centerline by the shared
        # montage helper (whole curved cord shows in the sagittal panel).
        sag_overlays = [(cord_mask, _C_CORD, 0.0, 1.4)]

        def axial_overlays(z):
            return [(cord_mask[:, :, z], _C_CORD, 1.5)]

        metric_lines = []
        if cord_len is not None:
            metric_lines.append(f"length {cord_len:.0f} mm")
        if dice is not None:
            metric_lines.append(f"pam50_cord_dice {dice:.2f}")

        _render_sagittal_plus_montage(
            output_path=output_path,
            title="S2.2 — Cord segmentation",
            subtitle=f"sub-{subject} • {dataset_key}  (sct_deepseg spinalcord)",
            status=status, metric_header=metric_header,
            anat=anat, cord_mask=cord_mask,
            sag_overlays=sag_overlays,
            axial_overlays_factory=axial_overlays,
            legend_items=[(_C_CORD, "cord seg")],
            metric_lines=metric_lines,
            axial_window_vox=(28, 28),  # extra context around the cord
        )
    except Exception as e:
        _stub_figure(output_path, f"cordmask render failed: {e}")


# ---------------------------------------------------------------------------
# Reportlet 3: totalspineseg_montage (S2.2 — Spine anatomy)
# ---------------------------------------------------------------------------

def render_totalspineseg_montage(
    output_path: Path,
    cordref_path: Path,
    cordmask_path: Path,
    tss_output_path: Optional[Path],
    canal_path: Optional[Path],
    vertebral_labels_path: Optional[Path],
    disc_labels_path: Optional[Path],
    subject: str = "?",
    dataset_key: str = "?",
    status: str = "UNKNOWN",
    metrics: Optional[dict] = None,
) -> None:
    try:
        if not cordref_path.exists():
            _stub_figure(output_path, "cordref missing")
            return
        anat, _, _ = _load_canonical(cordref_path)
        cord, _, _ = _load_canonical(cordmask_path)
        cord_mask = cord > 0

        canal_mask = None
        if canal_path and canal_path.exists():
            c, _, _ = _load_canonical(canal_path)
            if c.shape == anat.shape:
                canal_mask = c > 0

        vert_labels = None
        disc_labels = None
        if vertebral_labels_path and vertebral_labels_path.exists():
            v, _, _ = _load_canonical(vertebral_labels_path)
            if v.shape == anat.shape:
                vert_labels = v.astype(int)
        if disc_labels_path and disc_labels_path.exists():
            d, _, _ = _load_canonical(disc_labels_path)
            if d.shape == anat.shape:
                disc_labels = d.astype(int)

        # Build a single combined mask of vertebrae (for sagittal overlay)
        vert_mask = (vert_labels > 0) if vert_labels is not None else None
        disc_mask = (disc_labels > 0) if disc_labels is not None else None

        # Vertebral level z-position labels for the sagittal panel
        z_labels: dict[int, str] = {}
        if vert_labels is not None and vert_labels.any():
            n_z = vert_labels.shape[2]
            for v in sorted({int(x) for x in np.unique(vert_labels) if x > 0}):
                lvl_mask = (vert_labels == v)
                if not lvl_mask.any():
                    continue
                zs = np.argwhere(lvl_mask)[:, 2]
                z_med = int(np.median(zs))
                name = _vert_name_from_label(v)
                if name:
                    z_labels[z_med] = name

        # 3D masks → reformatted along the cord centerline by the shared
        # montage helper (cord + canal/vertebrae/discs follow the curve).
        sag_overlays = [(cord_mask, _C_CORD, 0.0, 1.0)]
        if canal_mask is not None:
            sag_overlays.append((canal_mask, _C_CANAL, 0.18, 0.0))
        if vert_mask is not None:
            sag_overlays.append((vert_mask, "#22c55e", 0.30, 0.0))
        if disc_mask is not None:
            sag_overlays.append((disc_mask, _C_DISC, 0.45, 0.0))

        def axial_overlays(z):
            # Tuple format: (mask, color, contour_lw, fill_alpha).
            # Cord stays as contour-only (its boundary is the truth).
            # Canal / vertebrae / discs get filled overlays so they're
            # visually distinct from each other even when they overlap
            # the cord region.
            ov: list = [(cord_mask[:, :, z], _C_CORD, 1.6, 0.0)]
            if vert_mask is not None:
                ov.append((vert_mask[:, :, z], "#22c55e", 1.4, 0.22))
            if disc_mask is not None:
                ov.append((disc_mask[:, :, z], _C_DISC, 1.4, 0.35))
            if canal_mask is not None:
                ov.append((canal_mask[:, :, z], _C_CANAL, 1.4, 0.25))
            return ov

        m = metrics or {}
        n_vert = m.get("n_vertebral_levels")
        n_disc = m.get("n_disc_levels")
        metric_header = ""
        if n_vert is not None:
            metric_header += f"{n_vert} vertebrae"
        if n_disc is not None:
            metric_header += f"  •  {n_disc} discs"

        metric_lines = []
        canal_vol = m.get("canal_volume_mm3")
        if canal_vol is not None:
            metric_lines.append(f"canal vol {canal_vol/1000:.1f} cm³")

        _render_sagittal_plus_montage(
            output_path=output_path,
            title="S2.2 — Spine anatomy (TotalSpineSeg)",
            subtitle=f"sub-{subject} • {dataset_key}",
            status=status, metric_header=metric_header,
            anat=anat, cord_mask=cord_mask,
            sag_overlays=sag_overlays,
            axial_overlays_factory=axial_overlays,
            legend_items=[
                (_C_CORD,  "cord"),
                (_C_CANAL, "canal"),
                ("#22c55e", "vertebrae"),
                (_C_DISC,  "discs"),
            ],
            metric_lines=metric_lines,
            z_label_levels=z_labels,
            # TSS needs to show vertebra body (anterior, ~10-20 vox from
            # cord) + canal (around cord) + cord. Widen axial window so
            # all structures fit with margin.
            axial_window_vox=(44, 44),
        )
    except Exception as e:
        _stub_figure(output_path, f"totalspineseg render failed: {e}")


def _vert_name_from_label(v: int) -> str:
    """Map a numeric vertebral label to its conventional name."""
    if 1 <= v <= 7:
        return f"C{v}"
    if 8 <= v <= 19:
        return f"T{v - 7}"
    if 20 <= v <= 24:
        return f"L{v - 19}"
    return ""


# ---------------------------------------------------------------------------
# Reportlet 4: rootlets_montage (S2.3)
# ---------------------------------------------------------------------------

def render_rootlets_montage(
    output_path: Path,
    cordref_path: Path,
    cordmask_path: Path,
    rootlets_path: Optional[Path],
    subject: str = "?",
    dataset_key: str = "?",
    status: str = "UNKNOWN",
    metrics: Optional[dict] = None,
) -> None:
    """S2.3 dorsal rootlets — rootlet-aware layout.

    Rootlets are tiny (typical 5-80 voxels per level total) and sparse
    in Z (each level spans 6-15 slices). The standard cord-axial
    layout misses them entirely because (a) uniform Z picks miss
    rootlet-bearing slices, (b) thin contours on 5-vox masks are
    invisible, (c) a cord-centered 22×22 crop puts rootlets at the
    edge.

    This renderer:
      - Picks ONE Z per detected rootlet level at that level's median Z.
      - Projects each tile across a ±3 voxel Z slab to maximize visible
        rootlet voxels.
      - Crop centered between cord centroid and the slab's rootlet
        centroid so rootlets sit clearly in-frame.
      - Dilated filled rootlet overlay (alpha 0.85) for visibility.
      - Wider 30×30 voxel window.
    """
    try:
        if not cordref_path.exists():
            _stub_figure(output_path, "cordref missing")
            return
        if not rootlets_path or not Path(rootlets_path).exists():
            _stub_figure(output_path, "Rootlets not available (file missing)")
            return
        anat, _, _ = _load_canonical(cordref_path)
        cord, _, _ = _load_canonical(cordmask_path)
        if anat.shape != cord.shape:
            _stub_figure(output_path, "shape mismatch")
            return
        roots, _, _ = _load_canonical(rootlets_path)
        if roots.shape != anat.shape:
            _stub_figure(output_path, "rootlets shape mismatch")
            return
        cord_mask = cord > 0
        roots = roots.astype(int)
        unique = sorted({int(x) for x in np.unique(roots) if x > 0})
        if not unique:
            _stub_figure(output_path, "Rootlets file has no nonzero labels")
            return

        from scipy.ndimage import binary_dilation

        cmap = plt.get_cmap("turbo")
        level_colors = {
            lab: matplotlib.colors.to_hex(cmap(i / max(len(unique) - 1, 1)))
            for i, lab in enumerate(unique)
        }

        # Per-level median Z and per-level rootlet centroid (X, Y)
        level_info: list[dict] = []
        nx, ny, nz = roots.shape
        for lab in unique:
            mask_3d = roots == lab
            if not mask_3d.any():
                continue
            zs = np.where(mask_3d.any(axis=(0, 1)))[0]
            z_med = int(np.median(zs))
            coords = np.argwhere(mask_3d)
            level_info.append({
                "lab": lab,
                "z": z_med,
                "cx": int(round(float(coords[:, 0].mean()))),
                "cy": int(round(float(coords[:, 1].mean()))),
                "color": level_colors[lab],
            })

        # Sagittal panel: wide slab across X so off-midline rootlets project in.
        sag_overlays: list[tuple[np.ndarray, str, float, float]] = [
            (cord_mask, _C_CORD, 0.0, 1.2),
        ]
        for info in level_info:
            sag_overlays.append(
                ((roots == info["lab"]), info["color"], 0.85, 0.0)
            )

        # Custom layout: one axial tile per rootlet level, picks at
        # that level's median Z. Use the shared layout for the
        # sagittal + header + footer, but pass rootlet-aware z_picks
        # and overlay factory.
        n_tiles = len(level_info)
        if n_tiles == 0:
            _stub_figure(output_path, "No rootlet level voxels")
            return

        slab_halfwidth_z = 3

        def axial_overlays(z):
            """Per-tile overlays: cord contour + filled+dilated rootlets
            projected across ±slab_halfwidth_z in Z."""
            z_lo = max(0, z - slab_halfwidth_z)
            z_hi = min(nz, z + slab_halfwidth_z + 1)
            cord_slab = cord_mask[:, :, z_lo:z_hi].any(axis=2)
            ov: list[tuple[np.ndarray, str, float]] = [
                (cord_slab, _C_CORD, 1.4),
            ]
            for info in level_info:
                slab_xy = (roots[:, :, z_lo:z_hi] == info["lab"]).any(axis=2)
                if not slab_xy.any():
                    continue
                # Dilate 1 voxel for visibility on tiny clusters
                slab_xy_dilated = binary_dilation(slab_xy, iterations=1)
                ov.append((slab_xy_dilated, info["color"], 2.4))
            return ov

        m = metrics or {}
        n_lvl = len(unique)
        metric_header = f"{n_lvl} rootlet levels"
        legend_items: list[tuple[str, str]] = [(_C_CORD, "cord")]
        for info in level_info:
            legend_items.append(
                (info["color"], _rootlet_level_name(info["lab"]))
            )

        # We need per-tile crops centered on (cord_centroid + rootlet)
        # midpoint so dorsal rootlets sit clearly inside the window.
        _render_rootlets_custom_layout(
            output_path=output_path,
            title="S2.3 — Dorsal rootlets",
            subtitle=f"sub-{subject} • {dataset_key}",
            status=status,
            metric_header=metric_header,
            anat=anat,
            cord_mask=cord_mask,
            roots=roots,
            level_info=level_info,
            slab_halfwidth_z=slab_halfwidth_z,
            sag_overlays=sag_overlays,
            axial_overlays_factory=axial_overlays,
            legend_items=legend_items,
            sag_slab_halfwidth_x=15,
            axial_window_vox=(30, 30),
        )
    except Exception as e:
        _stub_figure(output_path, f"rootlets render failed: {e}")


def _render_rootlets_custom_layout(
    output_path: Path,
    title: str,
    subtitle: str,
    status: str,
    metric_header: Optional[str],
    anat: np.ndarray,
    cord_mask: np.ndarray,
    roots: np.ndarray,
    level_info: list[dict],
    slab_halfwidth_z: int,
    sag_overlays: list[tuple[np.ndarray, str, float, float]],
    axial_overlays_factory,
    legend_items: list[tuple[str, str]],
    sag_slab_halfwidth_x: int = 15,
    axial_window_vox: tuple[int, int] = (30, 30),
) -> None:
    """Rootlets-specific layout: one tile per detected level, per-tile
    crop centered between cord and rootlet centroids."""
    k = max(0, int(sag_slab_halfwidth_x))
    sag_overlays_slab: list[tuple[np.ndarray, str, float, float]] = []
    if cord_mask.any():
        # Centerline-following reformat with a wide X slab so off-midline
        # dorsal rootlets still project in while the curved cord stays whole.
        x_center = _cord_centerline_x(cord_mask)
        sag = _curved_sagittal_reformat(anat, x_center, slab_halfwidth=k,
                                        reduce="max")
        for m, color, alpha, lw in sag_overlays:
            if m.ndim == 2:
                sag_overlays_slab.append((m, color, alpha, lw))
            else:
                slab = _curved_sagittal_reformat(
                    m.astype(float), x_center, slab_halfwidth=k,
                    reduce="any") > 0.5
                sag_overlays_slab.append((slab, color, alpha, lw))
    else:
        x_mid = _midcord_sagittal_slice(cord_mask)
        x_lo, x_hi = max(0, x_mid - k), min(anat.shape[0], x_mid + k + 1)
        sag = anat[x_lo:x_hi, :, :].max(axis=0)
        for m, color, alpha, lw in sag_overlays:
            if m.ndim == 2:
                sag_overlays_slab.append((m, color, alpha, lw))
            else:
                sag_overlays_slab.append(
                    (m[x_lo:x_hi, :, :].any(axis=0), color, alpha, lw))
    vmin_sag, vmax_sag = _intensity_window(sag)

    # Axial intensity windowing from a mid-cord slice
    z_mid_cord = int(np.median(np.argwhere(cord_mask)[:, 2]))
    vmin_ax, vmax_ax = _intensity_window(anat[:, :, z_mid_cord])

    fig = _layout_figure(16.0, 9.0)
    _add_header(fig, title, subtitle, status, metric_header)

    ax_sag = fig.add_axes((0.025, 0.10, 0.36, 0.80))
    ax_sag.set_facecolor(_BG)
    _render_sagittal(ax_sag, sag, sag_overlays_slab, vmin_sag, vmax_sag)

    # Axial grid: one tile per detected level
    n_tiles = len(level_info)
    n_cols = 2
    n_rows = (n_tiles + n_cols - 1) // n_cols
    grid_x0 = 0.42
    grid_x1 = 0.985
    grid_y0 = 0.10
    grid_y1 = 0.90
    cell_w = (grid_x1 - grid_x0) / n_cols
    cell_h = (grid_y1 - grid_y0) / n_rows

    # Sort levels by Z descending so top row = superior
    levels_sorted = sorted(level_info, key=lambda d: d["z"], reverse=True)

    hx, hy = axial_window_vox
    nx, ny = cord_mask.shape[:2]
    for i, info in enumerate(levels_sorted):
        row = i // n_cols
        col = i % n_cols
        ax = fig.add_axes((
            grid_x0 + col * cell_w + cell_w * 0.04,
            grid_y0 + (n_rows - 1 - row) * cell_h + cell_h * 0.04,
            cell_w * 0.92, cell_h * 0.92,
        ))
        ax.set_facecolor(_BG)

        # Per-tile crop centered on midpoint between cord centroid (this Z)
        # and rootlet centroid (this level), so dorsal rootlets sit
        # clearly inside the frame.
        z = info["z"]
        cord_slab = cord_mask[:, :, max(0, z-slab_halfwidth_z):min(cord_mask.shape[2], z+slab_halfwidth_z+1)].any(axis=2)
        if cord_slab.any():
            cord_xs, cord_ys = np.nonzero(cord_slab)
            cord_cx = int(round(float(cord_xs.mean())))
            cord_cy = int(round(float(cord_ys.mean())))
        else:
            cord_cx, cord_cy = nx // 2, ny // 2
        # Midpoint between cord and rootlet
        cx = (cord_cx + info["cx"]) // 2
        cy = (cord_cy + info["cy"]) // 2
        x0 = max(0, cx - hx // 2); x1 = min(nx, x0 + hx); x0 = max(0, x1 - hx)
        y0 = max(0, cy - hy // 2); y1 = min(ny, y0 + hy); y0 = max(0, y1 - hy)
        tile_crop = (x0, x1, y0, y1)

        overlays = axial_overlays_factory(z)
        _render_axial_tile(ax, anat[:, :, z], overlays,
                            vmin_ax, vmax_ax, z, first=(i == 0),
                            crop=tile_crop)
        # Level label badge in top-left of each tile
        ax.text(0.06, 0.92,
                _rootlet_level_name(info["lab"]),
                transform=ax.transAxes,
                color=info["color"], fontsize=13, fontweight="bold",
                ha="left", va="top",
                bbox=dict(facecolor="black", alpha=0.65,
                          edgecolor="none", boxstyle="round,pad=0.25"))

    _add_footer(fig, legend_items, [])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=130, facecolor=_BG,
                bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)


def _rootlet_level_name(v: int) -> str:
    if 1 <= v <= 7:
        return f"C{v}"
    if v == 8:
        return "C8"
    if 9 <= v <= 19:
        return f"T{v - 8}"
    return f"L{v}"


# ---------------------------------------------------------------------------
# Reportlet 5: pam50_reg_overlay (S2.4)
# ---------------------------------------------------------------------------

def _warp_pam50_cord_to_anat(
    warp_template2anat: Path, anat_ref: Path, work_dir: Path,
) -> Optional[Path]:
    """Apply the S2 PAM50→anat warp to the PAM50 cord template; return the
    warped binary mask path (in anat space). Used by the PAM50 reportlet."""
    try:
        from .register import _find_pam50_cord_mask, _resolve_pam50_dir
        import subprocess
        pam50_dir = _resolve_pam50_dir()
        if pam50_dir is None:
            return None
        pam50_cord = _find_pam50_cord_mask(pam50_dir)
        if pam50_cord is None or not warp_template2anat.exists():
            return None
        work_dir.mkdir(parents=True, exist_ok=True)
        out = work_dir / "pam50_cord_in_anat.nii.gz"
        p = timed_subprocess_run(
            ["sct_apply_transfo", "-i", str(pam50_cord),
             "-d", str(anat_ref), "-w", str(warp_template2anat),
             "-x", "nn", "-o", str(out)],
            capture_output=True, timeout=120,
        )
        return out if (p.returncode == 0 and out.exists()) else None
    except Exception:
        return None


def render_pam50_reg_overlay(
    output_path: Path,
    cordref_path: Path,
    cordmask_path: Path,
    pam50_cord_in_anat_path: Optional[Path],
    subject: str = "?",
    dataset_key: str = "?",
    status: str = "UNKNOWN",
    metrics: Optional[dict] = None,
) -> None:
    """S2.4: subject anat with PAM50 cord contour overlaid (after warp)."""
    try:
        if not cordref_path.exists() or not cordmask_path.exists():
            _stub_figure(output_path, "cordref or cord_dseg missing")
            return
        anat, _, _ = _load_canonical(cordref_path)
        cord, _, _ = _load_canonical(cordmask_path)
        if anat.shape != cord.shape:
            _stub_figure(output_path, "shape mismatch")
            return
        cord_mask = cord > 0

        pam50_mask = None
        if pam50_cord_in_anat_path and Path(pam50_cord_in_anat_path).exists():
            p, _, _ = _load_canonical(pam50_cord_in_anat_path)
            if p.shape == anat.shape:
                pam50_mask = p > 0

        m = metrics or {}
        dice = m.get("pam50_cord_dice")
        metric_header = f"Dice {dice:.2f}" if dice is not None else "Dice n/a"

        # 3D masks → reformatted along the cord centerline by the shared
        # montage helper (subject + PAM50 cords follow the curve).
        sag_overlays = [(cord_mask, _C_CORD, 0.0, 1.0)]
        if pam50_mask is not None:
            sag_overlays.append((pam50_mask, _C_PAM50, 0.0, 1.4))

        def axial_overlays(z):
            ov = [(cord_mask[:, :, z], _C_CORD, 1.0)]
            if pam50_mask is not None:
                ov.append((pam50_mask[:, :, z], _C_PAM50, 1.4))
            return ov

        legend_items = [(_C_CORD, "subject cord")]
        if pam50_mask is not None:
            legend_items.append((_C_PAM50, "PAM50 cord (warped)"))

        metric_lines = []
        if dice is not None:
            metric_lines.append(f"pam50_cord_dice {dice:.3f}")

        _render_sagittal_plus_montage(
            output_path=output_path,
            title="S2.4 — PAM50 normalization",
            subtitle=f"sub-{subject} • {dataset_key}",
            status=status, metric_header=metric_header,
            anat=anat, cord_mask=cord_mask,
            sag_overlays=sag_overlays,
            axial_overlays_factory=axial_overlays,
            legend_items=legend_items,
            metric_lines=metric_lines,
        )
    except Exception as e:
        _stub_figure(output_path, f"pam50 reg render failed: {e}")
