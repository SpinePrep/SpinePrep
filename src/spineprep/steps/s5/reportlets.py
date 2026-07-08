"""S5 reportlet rendering — CoSpine (Sci Data 2025) effectiveness metrics.

Three reportlets per run; the first two are quantitative and per-slice,
the third is a direct visual Before/After A/B:

1. ``slice_displacement`` — per-Z anteroposterior (Y-axis) cord-centerline
   displacement (mm) of the EPI cord vs the anat reference cord, Before
   and After distortion correction. Matches CoSpine Figure 3 / Methods
   §"Slice-by-slice Y-axis displacement". A perfectly corrected cord
   sits exactly on the anat centerline; remaining displacement is
   residual distortion (motion having already been removed in S4).
2. ``cord_dice_per_slice`` — per-Z 2D Dice between the EPI cord seg and
   the anat reference cord seg, Before and After. Matches CoSpine
   §"Spinal cord DSC". The 3D pooled Dice is also reported in the title.
3. ``distortion_effectiveness`` — mean BOLD Before vs mean BOLD After,
   sagittal pair on top + axial 3-tile-by-2-row grid below, with the
   anat-cord boundary overlaid as a yellow contour on every panel.
   Matches the fMRIPrep / qsiprep / CoSpine / SCT-QC consensus
   visualization (Esteban 2019, Wei 2025 Fig 3, De Leener 2017).
   Audit reference: .claude/specs/s5-distortion-effectiveness-reportlet.md.

Inputs are all in shared BOLD voxel geometry (S5 distortion correction
is in-grid). The anat reference is the S2 cord_dseg resampled into
BOLD space via FLIRT ``-applyxfm -usesqform`` with nearest-neighbour
interpolation (binary preserved). The EPI cord segs are computed by
``sct_deepseg_sc -c t2s`` on the mean BOLD (Before and After).

Both reportlets render a black-background figure with two panels:
left = per-slice trace (Z on Y-axis, metric on X-axis), right = summary
bar with mean ± SD across slices. Titles encode the distortion-
correction mode and the Δ (After − Before) summary.

When metrics cannot be computed (no anat reference, deepseg failure),
the renderers emit a placeholder figure explaining why; they never
raise.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


# ---------------------------------------------------------------------------
# Common helpers
# ---------------------------------------------------------------------------

_COLOR_BEFORE = "#888888"
_COLOR_AFTER = "#0086e6"


def _safe_mean(arr: Optional[np.ndarray]) -> Optional[float]:
    if arr is None:
        return None
    a = np.asarray(arr, dtype=float)
    if a.size == 0:
        return None
    finite = a[np.isfinite(a)]
    if finite.size == 0:
        return None
    return float(finite.mean())


def _safe_std(arr: Optional[np.ndarray]) -> Optional[float]:
    if arr is None:
        return None
    a = np.asarray(arr, dtype=float)
    finite = a[np.isfinite(a)]
    if finite.size < 2:
        return 0.0
    return float(finite.std(ddof=0))


def _placeholder(
    output_path: Path, title: str, reason: str
) -> None:
    """Emit a black placeholder PNG when metrics are unavailable."""
    fig, ax = plt.subplots(figsize=(9, 5), facecolor="black")
    ax.set_facecolor("black")
    ax.axis("off")
    ax.text(0.5, 0.55, title, ha="center", va="center",
            color="white", fontsize=13, fontweight="bold")
    ax.text(0.5, 0.40, reason, ha="center", va="center",
            color="#cccccc", fontsize=10, wrap=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=120, facecolor="black", bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Reportlet 1: slice_displacement
# ---------------------------------------------------------------------------

def render_s5_slice_displacement(
    metrics: dict[str, Any], output_path: Path, mode: str,
) -> None:
    """Render per-Z A–P cord-centerline displacement, Before vs After.

    ``metrics`` should carry:
      - ``per_slice_z``                : list[int]   (Z indices scored)
      - ``displacement_before_mm``     : list[float]
      - ``displacement_after_mm``      : list[float]
      - ``displacement_mean_before_mm``: float
      - ``displacement_mean_after_mm`` : float
      - ``displacement_delta_mm``      : float  (after − before)

    Missing keys → placeholder figure (never raises).
    """
    z = metrics.get("per_slice_z")
    db = metrics.get("displacement_before_mm")
    da = metrics.get("displacement_after_mm")
    if not z or db is None or da is None:
        reason = metrics.get("displacement_reason") or (
            "Cord A–P displacement not computed — anat reference unavailable.")
        _placeholder(output_path,
                     f"S5 slice-displacement — mode={mode}", reason)
        return

    z = np.asarray(z, dtype=int)
    db = np.asarray(db, dtype=float)
    da = np.asarray(da, dtype=float)
    mean_b = metrics.get("displacement_mean_before_mm")
    mean_a = metrics.get("displacement_mean_after_mm")
    delta = metrics.get("displacement_delta_mm")
    if mean_b is None:
        mean_b = _safe_mean(db)
    if mean_a is None:
        mean_a = _safe_mean(da)
    if delta is None and mean_b is not None and mean_a is not None:
        delta = mean_a - mean_b

    fig, axes = plt.subplots(
        1, 2, figsize=(11, 6),
        gridspec_kw={"width_ratios": [3, 1]},
        facecolor="black",
    )

    # Left: per-slice trace (Z on Y, displacement on X)
    ax = axes[0]
    ax.set_facecolor("black")
    ax.plot(db, z, "o-", color=_COLOR_BEFORE, label="Before",
            markersize=4, linewidth=1.4, alpha=0.95)
    ax.plot(da, z, "o-", color=_COLOR_AFTER, label="After",
            markersize=4, linewidth=1.6, alpha=0.95)
    ax.axvline(0.0, color="#444444", linestyle="--", linewidth=0.8)
    ax.set_xlabel("|cord A–P offset vs anat| (mm)", color="white")
    ax.set_ylabel("Z slice (BOLD)", color="white")
    ax.tick_params(colors="white")
    for spine in ax.spines.values():
        spine.set_color("#666666")
    ax.grid(alpha=0.2, color="#555555")
    leg = ax.legend(loc="best", facecolor="#222222", edgecolor="#444444",
                    labelcolor="white", framealpha=0.9)
    for t in leg.get_texts():
        t.set_color("white")

    # Right: summary bars
    ax = axes[1]
    ax.set_facecolor("black")
    xs = ["Before", "After"]
    ys = [mean_b if mean_b is not None else 0.0,
          mean_a if mean_a is not None else 0.0]
    es = [_safe_std(db) or 0.0, _safe_std(da) or 0.0]
    bars = ax.bar(xs, ys, yerr=es, color=[_COLOR_BEFORE, _COLOR_AFTER],
                  ecolor="#bbbbbb", capsize=4)
    for b, val in zip(bars, ys):
        ax.text(b.get_x() + b.get_width() / 2, val,
                f"{val:.2f}", ha="center", va="bottom",
                color="white", fontsize=10)
    ax.set_ylabel("mean displacement (mm)", color="white")
    ax.tick_params(colors="white")
    for spine in ax.spines.values():
        spine.set_color("#666666")
    ax.grid(alpha=0.2, color="#555555", axis="y")

    delta_str = f"{delta:+.2f}" if delta is not None else "n/a"
    fig.suptitle(
        f"Cord A–P displacement vs anat — mode={mode}, "
        f"Δmean = {delta_str} mm",
        color="white", fontsize=13,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=120, facecolor="black", bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Reportlet 2: cord_dice_per_slice
# ---------------------------------------------------------------------------

def render_s5_cord_dice_per_slice(
    metrics: dict[str, Any], output_path: Path, mode: str,
) -> None:
    """Render per-Z 2D Dice (EPI ∩ anat), Before vs After.

    ``metrics`` should carry:
      - ``per_slice_z``           : list[int]
      - ``dice_per_slice_before`` : list[float]
      - ``dice_per_slice_after``  : list[float]
      - ``dice_mean_before`` / ``dice_mean_after`` : float
      - ``dice_3d_before``   / ``dice_3d_after``   : float
      - ``dice_delta``                              : float

    Missing keys → placeholder figure.
    """
    z = metrics.get("per_slice_z")
    db = metrics.get("dice_per_slice_before")
    da = metrics.get("dice_per_slice_after")
    if not z or db is None or da is None:
        reason = metrics.get("dice_reason") or (
            "Cord Dice not computed — anat reference or EPI cord seg "
            "unavailable.")
        _placeholder(output_path,
                     f"S5 cord-Dice — mode={mode}", reason)
        return

    z = np.asarray(z, dtype=int)
    db = np.asarray(db, dtype=float)
    da = np.asarray(da, dtype=float)
    mean_b = metrics.get("dice_mean_before")
    mean_a = metrics.get("dice_mean_after")
    d3b = metrics.get("dice_3d_before")
    d3a = metrics.get("dice_3d_after")
    delta = metrics.get("dice_delta")
    if mean_b is None:
        mean_b = _safe_mean(db)
    if mean_a is None:
        mean_a = _safe_mean(da)
    if delta is None and mean_b is not None and mean_a is not None:
        delta = mean_a - mean_b

    fig, axes = plt.subplots(
        1, 2, figsize=(11, 6),
        gridspec_kw={"width_ratios": [3, 1]},
        facecolor="black",
    )

    ax = axes[0]
    ax.set_facecolor("black")
    ax.plot(db, z, "o-", color=_COLOR_BEFORE, label="Before",
            markersize=4, linewidth=1.4, alpha=0.95)
    ax.plot(da, z, "o-", color=_COLOR_AFTER, label="After",
            markersize=4, linewidth=1.6, alpha=0.95)
    ax.axvline(1.0, color="#444444", linestyle="--", linewidth=0.8)
    ax.set_xlim(0.0, 1.05)
    ax.set_xlabel("2D Dice (EPI cord ∩ anat cord)", color="white")
    ax.set_ylabel("Z slice (BOLD)", color="white")
    ax.tick_params(colors="white")
    for spine in ax.spines.values():
        spine.set_color("#666666")
    ax.grid(alpha=0.2, color="#555555")
    leg = ax.legend(loc="best", facecolor="#222222", edgecolor="#444444",
                    labelcolor="white", framealpha=0.9)
    for t in leg.get_texts():
        t.set_color("white")

    ax = axes[1]
    ax.set_facecolor("black")
    xs = ["Before", "After"]
    ys = [mean_b if mean_b is not None else 0.0,
          mean_a if mean_a is not None else 0.0]
    es = [_safe_std(db) or 0.0, _safe_std(da) or 0.0]
    bars = ax.bar(xs, ys, yerr=es, color=[_COLOR_BEFORE, _COLOR_AFTER],
                  ecolor="#bbbbbb", capsize=4)
    for b, val in zip(bars, ys):
        ax.text(b.get_x() + b.get_width() / 2, val,
                f"{val:.2f}", ha="center", va="bottom",
                color="white", fontsize=10)
    ax.set_ylim(0.0, 1.05)
    ax.set_ylabel("mean Dice", color="white")
    ax.tick_params(colors="white")
    for spine in ax.spines.values():
        spine.set_color("#666666")
    ax.grid(alpha=0.2, color="#555555", axis="y")

    delta_str = f"{delta:+.3f}" if delta is not None else "n/a"
    d3_str = ""
    if d3b is not None and d3a is not None:
        d3_str = f"  •  3D Dice: {d3b:.2f} → {d3a:.2f}"
    fig.suptitle(
        f"Cord Dice (EPI ∩ anat) — mode={mode}, "
        f"Δmean = {delta_str}{d3_str}",
        color="white", fontsize=13,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=120, facecolor="black", bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Reportlet 3: distortion_effectiveness — visual Before/After A/B
# ---------------------------------------------------------------------------

def render_s5_distortion_effectiveness(
    metrics: dict[str, Any],
    output_path: Path,
    mode: str,
    work_dir: Path,
    n_axial_tiles: int = 3,
    contour_lw: float = 2.0,
    dpi: int = 120,
) -> None:
    """Mean BOLD Before vs After with anat-cord contour overlay.

    Layout (figsize 16x9, BG dark per visual standard):
      - HEADER: title + subtitle "mode=... · 3D Dice=... · disp=..."
        + status pill (PASS when geometry improved, else WARN).
      - LEFT (~25% width): Sagittal Before (far left) and Sagittal After
        (next to it), each tall-narrow strip matching the cord's 1:~3.4
        aspect so the panel is filled instead of black-bar padded.
      - RIGHT (~70% width): Axial grid, 3 cord-bearing Z columns × 2 rows
        (Before / After) with square tiles. Z column headers above the
        grid; "Before"/"After" labels at the left edge of each row.
      - FOOTER: anat-cord legend, sagittal X, axial Z picks, intensity-
        window note.

    Inputs (from ``work_dir/cospine/``):
      - ``bold_before_mean.nii.gz``         mean BOLD Before correction
      - ``bold_after_mean.nii.gz``          mean BOLD After correction
      - ``anat_cord_dseg_in_bold.nii.gz``   anat cord seg in BOLD geom

    Missing inputs / ``cospine_skip_reason`` ⇒ placeholder PNG, never raises.

    Spec: ``.claude/specs/s5-distortion-effectiveness-reportlet.md``.
    Standard: ``.claude/specs/reportlet-visual-standard.md``.
    """
    title = "S5 — Distortion Correction (Before vs After)"

    if (skip := metrics.get("cospine_skip_reason")):
        _placeholder(output_path, f"{title} — mode={mode}",
                     f"CoSpine pipeline skipped: {skip}")
        return

    cospine_dir = Path(work_dir) / "cospine"
    paths = {
        "before": cospine_dir / "bold_before_mean.nii.gz",
        "after":  cospine_dir / "bold_after_mean.nii.gz",
        "anat":   cospine_dir / "anat_cord_dseg_in_bold.nii.gz",
    }
    missing = [k for k, p in paths.items() if not p.exists()]
    if missing:
        _placeholder(output_path, f"{title} — mode={mode}",
                     "Missing CoSpine inputs: " + ", ".join(missing))
        return

    import nibabel as nib
    try:
        before_img = nib.load(paths["before"])
        before = before_img.get_fdata().astype(np.float32)
        after = nib.load(paths["after"]).get_fdata().astype(np.float32)
        anat_cord = nib.load(paths["anat"]).get_fdata() > 0
    except Exception as e:
        _placeholder(output_path, f"{title} — mode={mode}",
                     f"Failed to load CoSpine inputs: {e}")
        return

    if before.shape != after.shape or before.shape != anat_cord.shape:
        _placeholder(output_path, f"{title} — mode={mode}",
                     f"Shape mismatch: before={before.shape} "
                     f"after={after.shape} anat={anat_cord.shape}")
        return
    if not anat_cord.any():
        _placeholder(output_path, f"{title} — mode={mode}",
                     "anat cord mask is empty in BOLD geometry")
        return

    from spineprep.reportlets_common import (
        BG, TEXT, MARKER_YELLOW,
        intensity_window, cord_bbox_xy, cord_zrange, uniform_z_picks,
        midcord_sagittal_slice, per_slice_centered_crop,
        add_header, add_footer, render_sagittal, render_axial_tile,
    )

    zooms = list(before_img.header.get_zooms()[:3]) + [1.0, 1.0, 1.0]
    zx, zy, zz = float(zooms[0]), float(zooms[1]), float(zooms[2])
    sag_aspect = zz / zy if zy > 0 else 1.0
    ax_aspect = zy / zx if zx > 0 else 1.0

    z0, z1 = cord_zrange(anat_cord)
    n_tiles = max(1, int(n_axial_tiles))
    z_picks = uniform_z_picks(z0, z1, n_tiles)
    if not z_picks:
        _placeholder(output_path, f"{title} — mode={mode}",
                     "No cord-bearing Z slices found in anat mask")
        return

    x_mid = midcord_sagittal_slice(anat_cord)
    global_bbox = cord_bbox_xy(anat_cord, margin=6)

    # Pooled intensity window so Before/After share the same scale.
    pooled = np.concatenate([
        before[np.isfinite(before)].ravel(),
        after[np.isfinite(after)].ravel(),
    ])
    if pooled.size == 0:
        _placeholder(output_path, f"{title} — mode={mode}",
                     "Mean BOLD has no finite voxels")
        return
    vmin, vmax = intensity_window(pooled, 2.0, 98.0)

    dice_after = metrics.get("dice_3d_after")
    disp_after = metrics.get("displacement_mean_after_mm")
    dice_delta = metrics.get("dice_delta")
    disp_delta = metrics.get("displacement_delta_mm")
    subtitle_parts = [f"mode={mode}"]
    if dice_after is not None:
        subtitle_parts.append(f"3D Dice={dice_after:.2f}")
    if disp_after is not None:
        subtitle_parts.append(f"disp={disp_after:.2f}mm")
    subtitle = "  ·  ".join(subtitle_parts)
    geometry_improved = (
        (dice_delta is not None and dice_delta > 0)
        or (disp_delta is not None and disp_delta < 0)
    )
    status = "PASS" if geometry_improved else "WARN"

    fig = plt.figure(figsize=(16.0, 9.0), facecolor=BG)
    fig.patch.set_facecolor(BG)
    add_header(fig, title, subtitle, status, None)

    # --- Left block: two tall-narrow sagittal strips side-by-side ---
    # Cord sagittal data is ~1:3.4 (W:H). Putting it in a square-ish
    # panel wasted ~70% of the canvas in v1; matching the panel aspect
    # lets the actual image fill the slot.
    sag_y0, sag_h = 0.07, 0.79
    sag_w_each = 0.085           # ~11% of figure width per sagittal
    sag_gap = 0.014
    sag_x_b = 0.040
    sag_x_a = sag_x_b + sag_w_each + sag_gap

    ax_sag_b = fig.add_axes((sag_x_b, sag_y0, sag_w_each, sag_h))
    ax_sag_a = fig.add_axes((sag_x_a, sag_y0, sag_w_each, sag_h))
    ax_sag_b.set_facecolor(BG)
    ax_sag_a.set_facecolor(BG)

    sag_b = before[x_mid, :, :]
    sag_a = after[x_mid, :, :]
    sag_anat = anat_cord[x_mid, :, :]
    sag_overlays = [(sag_anat, MARKER_YELLOW, 0.0, contour_lw)]

    render_sagittal(ax_sag_b, sag_b, sag_overlays, vmin, vmax,
                    pixel_aspect=sag_aspect)
    render_sagittal(ax_sag_a, sag_a, sag_overlays, vmin, vmax,
                    pixel_aspect=sag_aspect)
    # Place "Before"/"After" titles above the sagittals via fig.text
    # (ax.set_title's pad was overlapping the header in v1).
    sag_label_y = sag_y0 + sag_h + 0.012
    fig.text(sag_x_b + sag_w_each / 2, sag_label_y, "Before",
             color=TEXT, fontsize=13, fontweight="bold",
             ha="center", va="bottom")
    fig.text(sag_x_a + sag_w_each / 2, sag_label_y, "After",
             color=TEXT, fontsize=13, fontweight="bold",
             ha="center", va="bottom")

    # --- Right block: axial grid (3 cols × 2 rows, square tiles) ---
    grid_x0 = sag_x_a + sag_w_each + 0.05       # leave breathing room
    grid_x1 = 0.985
    grid_w = grid_x1 - grid_x0
    grid_y0 = sag_y0
    grid_y1 = sag_y0 + sag_h - 0.06             # reserve space for col headers
    grid_h = grid_y1 - grid_y0

    n_cols = len(z_picks)
    col_w = grid_w / n_cols
    row_h = grid_h / 2

    # Column headers (z=...) above each column
    for col, z in enumerate(z_picks):
        cx = grid_x0 + col * col_w + col_w / 2
        fig.text(cx, grid_y1 + 0.012, f"z = {z}",
                 color=TEXT, fontsize=12, fontweight="bold",
                 ha="center", va="bottom", family="monospace")

    # Row labels ("Before" / "After") to the left of the grid
    fig.text(grid_x0 - 0.012, grid_y0 + row_h * 1.5, "Before",
             color=TEXT, fontsize=12, fontweight="bold",
             rotation=90, ha="right", va="center")
    fig.text(grid_x0 - 0.012, grid_y0 + row_h * 0.5, "After",
             color=TEXT, fontsize=12, fontweight="bold",
             rotation=90, ha="right", va="center")

    for col, z in enumerate(z_picks):
        cell_x = grid_x0 + col * col_w
        # Before row (top)
        ax_b = fig.add_axes((
            cell_x + col_w * 0.03,
            grid_y0 + row_h + row_h * 0.03,
            col_w * 0.94, row_h * 0.94,
        ))
        # After row (bottom)
        ax_a = fig.add_axes((
            cell_x + col_w * 0.03,
            grid_y0 + row_h * 0.03,
            col_w * 0.94, row_h * 0.94,
        ))
        ax_b.set_facecolor(BG)
        ax_a.set_facecolor(BG)

        tile_crop = per_slice_centered_crop(
            anat_cord, z, window_vox=(22, 22), fallback_bbox=global_bbox,
        )
        overlays = [(anat_cord[:, :, z], MARKER_YELLOW, contour_lw)]

        render_axial_tile(ax_b, before[:, :, z], overlays,
                          vmin, vmax, z, first=(col == 0),
                          crop=tile_crop, pixel_aspect=ax_aspect)
        render_axial_tile(ax_a, after[:, :, z], overlays,
                          vmin, vmax, z, first=False,
                          crop=tile_crop, pixel_aspect=ax_aspect)

    add_footer(
        fig,
        legend_items=[(MARKER_YELLOW, "anat cord boundary")],
        metric_lines=[
            f"sagittal: midcord X={x_mid}",
            f"axial Z picks: {list(z_picks)}",
            "intensity window: 2–98% of pooled Before+After",
        ],
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=dpi, facecolor=BG,
                bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)
