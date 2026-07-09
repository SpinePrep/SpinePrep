"""S6 reportlet rendering — chain-wide visual standard.

Two reportlets:

1. ``bold_on_anat`` — composite registration QC view: sagittal pair
   (BOLD + Anat, tall-narrow at midcord X) on the left + 3 cord-bearing
   axial Z columns × 2 modality rows (BOLD top, Anat bottom) on the
   right. Yellow anat-cord-seg contour and cyan EPI-cord-seg contour
   on every panel. Dual-modality so the cord is unambiguous on the
   anat panel (T2*-EPI shows CSF brighter than the cord which can be
   visually misleading on BOLD-only views).
2. ``cord_dice_per_slice`` — per-slice 3D-Dice bar chart, color-coded
   PASS/WARN/FAIL band. Quantitative complement to the visual overlay.
   Non-image plot, intentionally minimal chrome.

Audit references:
- ``.claude/specs/s6-algorithm-audit.md`` — Findings 8 (intensity-
  percentile contour → cord seg) and 9 (visual standard adherence).
- ``.claude/specs/s6-reportlet-set-audit.md`` — the standalone
  ``bold_on_anat_sagittal`` was dropped 2026-05-28 as redundant with
  the sagittal strips inside the composite. Field-standard pattern
  (fMRIPrep, qsiprep, SCT, CoSpine, Kaptan 2023) is composite-view +
  quantitative — exactly 2 reportlets per registration step.

Inputs include the warped anat **cord segmentation**
(``anat_dseg_in_bold``), not the warped anat intensity image; the
contour traces the cord boundary directly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import nibabel as nib
import numpy as np


# ---------------------------------------------------------------------------
# Reportlet 1: composite axial + sagittal pair, BOLD vs Anat
# ---------------------------------------------------------------------------


def render_s6_composite(
    bold_mean_path: Path,
    anat_dseg_in_bold_path: Path,
    cord_mask_path: Path,
    output_path: Path,
    anat_in_bold_path: Optional[Path] = None,
    funcref_path: Optional[Path] = None,
    n_axial: int = 3,
    dice: Optional[float] = None,
    hd95: Optional[float] = None,
    contour_lw: float = 2.0,
    dpi: int = 120,
    status: Optional[str] = None,
) -> None:
    """Dual-modality axial reportlet: BOLD vs anat at the same Z slices,
    with anat cord seg (yellow) and EPI cord seg (cyan) on every panel.

    Layout (figsize 16x9):
      - LEFT (~22% width): two tall-narrow sagittal strips —
        BOLD (left) and ANAT (right) at midcord X, both with the
        anat-cord + EPI-cord overlays.
      - RIGHT (~70% width): 3 cord-bearing Z columns × 2 rows axial
        grid. Row 1 = BOLD background, Row 2 = ANAT background.

    Why dual-modality: in T2*-weighted EPI the CSF is the brightest
    signal, often making the eye read the bright blob in the canal
    as "the cord". The actual cord is the slightly darker oval
    posterior to the CSF — easy to confirm against the anat T1w
    background which has clear cord-vs-bone contrast.
    """
    from spineprep.reportlets_common import (
        BG, TEXT, MARKER_YELLOW, SEMANTIC,
        intensity_window, cord_bbox_xy, cord_zrange, uniform_z_picks,
        midcord_sagittal_slice, per_slice_centered_crop,
        cord_centerline_x, curved_sagittal_reformat,
        add_header, add_footer, render_sagittal, render_axial_tile,
        stub_figure,
    )

    bold_img = nib.load(bold_mean_path)
    bold = bold_img.get_fdata().astype(np.float32)
    anat_cord = nib.load(anat_dseg_in_bold_path).get_fdata() > 0.5
    epi_cord = nib.load(cord_mask_path).get_fdata() > 0.5

    if bold.shape != anat_cord.shape or bold.shape != epi_cord.shape:
        stub_figure(output_path,
                    f"S6 axial: shape mismatch "
                    f"BOLD={bold.shape} anat={anat_cord.shape} "
                    f"EPI={epi_cord.shape}")
        return
    if not anat_cord.any() or not epi_cord.any():
        stub_figure(output_path,
                    "S6 axial: empty cord seg(s) — registration may have failed")
        return

    # Optional anat-in-BOLD intensity image; if missing, fall back to
    # using BOLD as both rows (less informative but at least renders).
    has_anat = anat_in_bold_path is not None and Path(anat_in_bold_path).exists()
    if has_anat:
        try:
            anat = nib.load(anat_in_bold_path).get_fdata().astype(np.float32)
            if anat.shape != bold.shape:
                has_anat = False
                anat = bold
        except Exception:
            has_anat = False
            anat = bold
    else:
        anat = bold

    zooms = list(bold_img.header.get_zooms()[:3]) + [1.0, 1.0, 1.0]
    zx, zy, zz = float(zooms[0]), float(zooms[1]), float(zooms[2])
    sag_aspect = zz / zy if zy > 0 else 1.0
    ax_aspect = zy / zx if zx > 0 else 1.0

    z0, z1 = cord_zrange(anat_cord)
    n_tiles = max(1, int(n_axial))
    z_picks = uniform_z_picks(z0, z1, n_tiles)
    if not z_picks:
        stub_figure(output_path,
                    "S6 axial: no cord-bearing Z slices in anat mask")
        return

    x_mid = midcord_sagittal_slice(anat_cord)
    # Centerline-following sagittal reformat: sample each SI level at the
    # cord's own L–R centroid so a curved cord shows in full (a single flat
    # sagittal plane truncates it wherever it drifts out of plane).
    x_center = cord_centerline_x(anat_cord)
    global_bbox = cord_bbox_xy(anat_cord, margin=6)

    # Per-image intensity windows (each modality has its own range).
    pool_b = bold[np.isfinite(bold)].ravel()
    vmin_b, vmax_b = intensity_window(pool_b, 2.0, 98.0) if pool_b.size else (0.0, 1.0)
    pool_a = anat[np.isfinite(anat) & (anat > 0)].ravel() if has_anat else pool_b
    vmin_a, vmax_a = intensity_window(pool_a, 2.0, 98.0) if pool_a.size else (vmin_b, vmax_b)

    epi_cyan = SEMANTIC.get("cord_epi", "#22d3ee")

    subtitle_parts = []
    if dice is not None:
        subtitle_parts.append(f"Dice={dice:.2f}")
    if hd95 is not None:
        subtitle_parts.append(f"HD95={hd95:.2f}mm")
    subtitle = "  ·  ".join(subtitle_parts) if subtitle_parts else ""
    # Use the run's real qc.json status when provided (the policy PASS gate is
    # Dice>=0.85, not 0.80); fall back to a coarse Dice heuristic only if the
    # caller didn't pass a status.
    if status is None:
        status = "PASS" if (dice is not None and dice >= 0.85) else "WARN"

    fig = plt.figure(figsize=(16.0, 9.0), facecolor=BG)
    fig.patch.set_facecolor(BG)
    add_header(fig, "S6 — BOLD vs Anat (Axial)", subtitle, status, None)

    # --- Sagittal pair: BOLD | anat at midcord X ---
    sag_y0, sag_h = 0.07, 0.79
    sag_w_each = 0.085
    sag_gap = 0.014
    sag_x_b = 0.040
    sag_x_a = sag_x_b + sag_w_each + sag_gap
    ax_sag_b = fig.add_axes((sag_x_b, sag_y0, sag_w_each, sag_h))
    ax_sag_a = fig.add_axes((sag_x_a, sag_y0, sag_w_each, sag_h))
    ax_sag_b.set_facecolor(BG)
    ax_sag_a.set_facecolor(BG)

    sag_overlays = [
        (curved_sagittal_reformat(anat_cord.astype(float), x_center,
                                  reduce="any") > 0.5, MARKER_YELLOW, 0.0, contour_lw),
        (curved_sagittal_reformat(epi_cord.astype(float), x_center,
                                  reduce="any") > 0.5, epi_cyan, 0.0, contour_lw),
    ]
    render_sagittal(ax_sag_b, curved_sagittal_reformat(bold, x_center),
                    sag_overlays, vmin_b, vmax_b,
                    pixel_aspect=sag_aspect, affine=bold_img.affine)
    render_sagittal(ax_sag_a, curved_sagittal_reformat(anat, x_center),
                    sag_overlays, vmin_a, vmax_a,
                    pixel_aspect=sag_aspect, affine=bold_img.affine)
    sag_label_y = sag_y0 + sag_h + 0.012
    fig.text(sag_x_b + sag_w_each / 2, sag_label_y, "BOLD",
             color=TEXT, fontsize=13, fontweight="bold", ha="center", va="bottom")
    fig.text(sag_x_a + sag_w_each / 2, sag_label_y,
             "Anat" if has_anat else "BOLD",
             color=TEXT, fontsize=13, fontweight="bold", ha="center", va="bottom")

    # --- Axial grid: 3 cols × 2 rows (BOLD top, anat bottom) ---
    # Use the full figure height (matching the sagittals) so the tiles
    # render at their proper square aspect instead of squashed into a
    # thin bottom strip.
    ax_y0, ax_h = sag_y0, sag_h - 0.04   # reserve ~0.04 for z= headers
    row_h = ax_h / 2
    n_cols = len(z_picks)
    grid_x0, grid_w = sag_x_a + sag_w_each + 0.05, 0.985 - (sag_x_a + sag_w_each + 0.05)
    col_w = grid_w / n_cols

    grid_y1 = ax_y0 + ax_h
    for col, z in enumerate(z_picks):
        cx = grid_x0 + col * col_w + col_w / 2
        fig.text(cx, grid_y1 + 0.012, f"z = {z}",
                 color=TEXT, fontsize=12, fontweight="bold",
                 ha="center", va="bottom", family="monospace")
    fig.text(grid_x0 - 0.012, ax_y0 + row_h * 1.5, "BOLD",
             color=TEXT, fontsize=12, fontweight="bold",
             rotation=90, ha="right", va="center")
    fig.text(grid_x0 - 0.012, ax_y0 + row_h * 0.5,
             "Anat" if has_anat else "BOLD",
             color=TEXT, fontsize=12, fontweight="bold",
             rotation=90, ha="right", va="center")

    for col, z in enumerate(z_picks):
        cell_x = grid_x0 + col * col_w
        ax_top = fig.add_axes((
            cell_x + col_w * 0.03,
            ax_y0 + row_h + row_h * 0.03,
            col_w * 0.94, row_h * 0.94,
        ))
        ax_bot = fig.add_axes((
            cell_x + col_w * 0.03,
            ax_y0 + row_h * 0.03,
            col_w * 0.94, row_h * 0.94,
        ))
        ax_top.set_facecolor(BG); ax_bot.set_facecolor(BG)
        tile_crop = per_slice_centered_crop(
            anat_cord, z, window_vox=(22, 22), fallback_bbox=global_bbox,
        )
        overlays = [
            (anat_cord[:, :, z], MARKER_YELLOW, contour_lw),
            (epi_cord[:, :, z], epi_cyan, contour_lw),
        ]
        render_axial_tile(ax_top, bold[:, :, z], overlays,
                          vmin_b, vmax_b, z, first=(col == 0),
                          crop=tile_crop, pixel_aspect=ax_aspect)
        render_axial_tile(ax_bot, anat[:, :, z], overlays,
                          vmin_a, vmax_a, z, first=False,
                          crop=tile_crop, pixel_aspect=ax_aspect)

    add_footer(
        fig,
        legend_items=[
            (MARKER_YELLOW, "anat cord seg"),
            (epi_cyan, "EPI cord seg"),
        ],
        metric_lines=[
            "sagittal: cord-centerline reformat",
            f"axial Z picks: {list(z_picks)}",
            ("BOLD top / Anat bottom — same warped seg on both"
             if has_anat else "anat-in-BOLD unavailable, BOLD shown twice"),
        ],
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=dpi, facecolor=BG,
                bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)


# Removed `render_s6_sagittal` 2026-05-28 — it duplicated the mid-
# sagittal cut, backgrounds, and overlays already shown as tall-narrow
# strips on the left of `render_s6_composite`. See
# .claude/specs/s6-reportlet-set-audit.md.


# ---------------------------------------------------------------------------
# Reportlet 2: per-slice Dice bar chart (kept simple, no chrome)
# ---------------------------------------------------------------------------


def render_s6_dice_per_slice(
    funccrop_mask_path: Path,
    anat_dseg_in_bold_path: Optional[Path],
    output_path: Path,
    thresholds: dict,
) -> None:
    """Per-slice cord Dice along Z, color-coded by PASS/WARN/FAIL band.

    Plain matplotlib (non-image plot doesn't benefit from the full
    visual-standard chrome). Yellow PASS line + red FAIL floor + green
    PASS floor → readable at a glance.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if anat_dseg_in_bold_path is None or not Path(anat_dseg_in_bold_path).exists():
        from spineprep.reportlets_common import stub_figure
        stub_figure(output_path,
                    "S6 cord_dice_per_slice: anat cord seg in BOLD geometry unavailable")
        return

    a_img = nib.load(funccrop_mask_path)
    a = a_img.get_fdata() > 0.5
    b = nib.load(anat_dseg_in_bold_path).get_fdata() > 0.5
    if a.shape != b.shape:
        from spineprep.reportlets_common import stub_figure
        stub_figure(output_path,
                    f"S6 cord_dice_per_slice: shape mismatch {a.shape} vs {b.shape}")
        return

    pass_min = thresholds.get("pass_dice_min", 0.85)
    fail_below = thresholds.get("fail_dice_below", 0.65)

    dice_z: list[float] = []
    for z in range(a.shape[2]):
        az = a[:, :, z]
        bz = b[:, :, z]
        n = int(az.sum()) + int(bz.sum())
        dice_z.append(float(2 * int((az & bz).sum()) / n) if n > 0 else float("nan"))

    fig, ax = plt.subplots(figsize=(9, 4), facecolor="#0f1115")
    ax.set_facecolor("#0f1115")
    colors = [("#22c55e" if (not np.isnan(d) and d >= pass_min)
               else "#f59e0b" if (not np.isnan(d) and d >= fail_below)
               else "#ef4444") for d in dice_z]
    ax.bar(range(len(dice_z)),
           [0 if np.isnan(d) else d for d in dice_z],
           color=colors, edgecolor="#1f2937", linewidth=0.4)
    ax.axhline(pass_min, linestyle="--", color="#22c55e", linewidth=0.9,
               label=f"PASS ≥ {pass_min:.2f}")
    ax.axhline(fail_below, linestyle="--", color="#ef4444", linewidth=0.9,
               label=f"FAIL < {fail_below:.2f}")
    ax.set_xlabel("Slice (Z)", color="#e6e8ec")
    # Caudal/rostral end labels from the mask's Z orientation (not hardcoded):
    # +Z toward Superior (head) = rostral; toward Inferior (feet) = caudal.
    _zc = nib.orientations.aff2axcodes(a_img.affine)[2]
    _lo, _hi = ("caudal", "rostral") if _zc == "S" else ("rostral", "caudal")
    ax.text(0.0, -0.16, f"← {_lo}", transform=ax.transAxes, color="#9aa0a6",
            fontsize=9, ha="left", va="top")
    ax.text(1.0, -0.16, f"{_hi} →", transform=ax.transAxes, color="#9aa0a6",
            fontsize=9, ha="right", va="top")
    ax.set_ylabel("Cord Dice (EPI ∩ anat)", color="#e6e8ec")
    ax.set_ylim(0, 1.0)
    ax.set_title("S6 — Cord segmentation Dice by slice",
                 color="#e6e8ec", fontsize=12, fontweight="bold")
    ax.tick_params(colors="#e6e8ec")
    for s in ax.spines.values():
        s.set_color("#374151")
    leg = ax.legend(loc="lower right", fontsize=9, facecolor="#1a1d23",
                    edgecolor="#374151", labelcolor="#e6e8ec")
    for t in leg.get_texts():
        t.set_color("#e6e8ec")
    ax.grid(alpha=0.15, color="#374151")
    fig.tight_layout()
    fig.savefig(output_path, dpi=120, facecolor="#0f1115", bbox_inches="tight")
    plt.close(fig)
