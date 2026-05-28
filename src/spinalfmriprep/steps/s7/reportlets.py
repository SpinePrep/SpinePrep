"""S7 reportlet rendering — chain-wide visual standard.

Two reportlets per run, matching the field-standard composition for
template normalization QC (Kaptan 2023, CoSpine 2025, Valošek 2025,
fMRIPrep, qsiprep, SCT QC — all converge on composite + quantitative):

1. ``pam50_on_func`` — composite registration QC view. Tall-narrow
   sagittal funcref strip on the left with PAM50_cord contour
   (yellow) + PAM50_spinal_levels color blocks for vertebral
   context. 3 cord-bearing axial Z columns × 2 modality rows
   (funcref top, PAM50_t2s warped to func bottom) on the right;
   yellow anat-cord-seg contour (PAM50_cord) and cyan EPI-cord-seg
   contour (S6 funccrop) on every panel.
2. ``cord_dice_per_level`` — per-vertebral-level 3D Dice bar chart,
   color-coded PASS / WARN / FAIL. One bar per PAM50_spinal_levels
   value present in the BOLD FOV. Catches "global Dice high but
   C7-T1 alignment poor" — the actual failure mode for cervical-
   cord scans.

Audit references:
- ``.claude/specs/s7-algorithm-audit.md`` — Findings 1, 2, 3, 4, 9
  (visual standard, contour thickness, broken metrics + reportlet)
- ``.claude/specs/s7-reportlet-set-audit.md`` — redundancy +
  per-level Dice rationale
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
# Reportlet 1: pam50_on_func composite
# ---------------------------------------------------------------------------


def render_s7_pam50_on_func(
    funcref_path: Path,
    pam50_cord_in_func_path: Path,
    pam50_levels_in_func_path: Optional[Path],
    func_cord_seg_path: Path,
    output_path: Path,
    dice: Optional[float] = None,
    contour_lw: float = 2.0,
    dpi: int = 120,
) -> None:
    """Composite axial + sagittal funcref with PAM50_cord + EPI-cord
    contours, plus PAM50_spinal_levels color-block sagittal context.

    Layout (figsize 16x9, BG dark per visual standard):
      LEFT (~22% width): two tall-narrow sagittal strips —
        Funcref (left) with cord-only contours, and PAM50 spinal_levels
        (right) as a color-coded sagittal slice for vertebral context.
      RIGHT (~70% width): 3 cord-bearing Z columns × 1 row of
        funcref axial tiles, with PAM50_cord (yellow) and EPI-cord
        seg (cyan) overlays.

    Yellow contour = PAM50_cord warped into native func space (the
    template-driven cord boundary). Cyan = the EPI's own cord seg from
    S6. The two contours should overlap.
    """
    from spinalfmriprep.reportlets_common import (
        BG, TEXT, MARKER_YELLOW, SEMANTIC,
        intensity_window, cord_bbox_xy, cord_zrange, uniform_z_picks,
        midcord_sagittal_slice, per_slice_centered_crop,
        add_header, add_footer, render_sagittal, render_axial_tile,
        stub_figure,
    )

    fimg = nib.load(funcref_path)
    func = fimg.get_fdata().astype(np.float32)
    pam_cord = nib.load(pam50_cord_in_func_path).get_fdata() > 0.5
    epi_cord = nib.load(func_cord_seg_path).get_fdata() > 0.5

    if func.shape != pam_cord.shape or func.shape != epi_cord.shape:
        stub_figure(output_path,
                    f"S7 composite: shape mismatch "
                    f"func={func.shape} pam={pam_cord.shape} epi={epi_cord.shape}")
        return
    if not pam_cord.any():
        stub_figure(output_path,
                    "S7 composite: PAM50_cord in native func is empty — "
                    "warp composition likely failed")
        return

    has_levels = (pam50_levels_in_func_path is not None
                  and Path(pam50_levels_in_func_path).exists())
    if has_levels:
        try:
            levels = nib.load(pam50_levels_in_func_path).get_fdata().astype(np.int32)
            if levels.shape != func.shape:
                has_levels = False
        except Exception:
            has_levels = False
    if not has_levels:
        levels = np.zeros_like(func, dtype=np.int32)

    zooms = list(fimg.header.get_zooms()[:3]) + [1.0, 1.0, 1.0]
    zx, zy, zz = float(zooms[0]), float(zooms[1]), float(zooms[2])
    sag_aspect = zz / zy if zy > 0 else 1.0
    ax_aspect = zy / zx if zx > 0 else 1.0

    z0, z1 = cord_zrange(pam_cord)
    z_picks = uniform_z_picks(z0, z1, 3)
    if not z_picks:
        stub_figure(output_path,
                    "S7 composite: no cord-bearing Z slices found")
        return
    x_mid = midcord_sagittal_slice(pam_cord)
    global_bbox = cord_bbox_xy(pam_cord, margin=6)

    pool = func[np.isfinite(func) & (func > 0)].ravel()
    vmin, vmax = intensity_window(pool, 2.0, 98.0) if pool.size else (0.0, 1.0)

    subtitle_parts = []
    if dice is not None:
        subtitle_parts.append(f"Dice={dice:.2f}")
    if has_levels:
        levels_present = sorted(int(v) for v in np.unique(levels) if v > 0)
        if levels_present:
            subtitle_parts.append(
                f"levels {min(levels_present)}–{max(levels_present)} ({len(levels_present)})"
            )
    subtitle = "  ·  ".join(subtitle_parts) if subtitle_parts else ""
    status = "PASS" if (dice is not None and dice >= 0.80) else "WARN"

    epi_cyan = SEMANTIC.get("cord_epi", "#22d3ee")

    fig = plt.figure(figsize=(16.0, 9.0), facecolor=BG)
    fig.patch.set_facecolor(BG)
    add_header(fig, "S7 — PAM50 on Func (Composite)", subtitle, status, None)

    # --- Left block: two tall-narrow sagittal strips ---
    sag_y0, sag_h = 0.07, 0.79
    sag_w_each = 0.085
    sag_gap = 0.014
    sag_x_f = 0.040
    sag_x_l = sag_x_f + sag_w_each + sag_gap
    ax_sag_f = fig.add_axes((sag_x_f, sag_y0, sag_w_each, sag_h))
    ax_sag_l = fig.add_axes((sag_x_l, sag_y0, sag_w_each, sag_h))
    ax_sag_f.set_facecolor(BG)
    ax_sag_l.set_facecolor(BG)

    sag_func = func[x_mid, :, :]
    sag_pam = pam_cord[x_mid, :, :]
    sag_epi = epi_cord[x_mid, :, :]
    sag_overlays = [
        (sag_pam, MARKER_YELLOW, 0.0, contour_lw),
        (sag_epi, epi_cyan, 0.0, contour_lw),
    ]
    render_sagittal(ax_sag_f, sag_func, sag_overlays, vmin, vmax,
                    pixel_aspect=sag_aspect)

    # Spinal-levels sagittal: render the level integers as a color
    # block backdrop, with the cord contour drawn on top so the user
    # sees BOTH "which level is each Z" AND "is the cord aligned".
    if has_levels and levels.any():
        sag_lvl = levels[x_mid, :, :]
        disp = np.rot90(sag_lvl)
        masked = np.ma.masked_where(disp == 0, disp)
        n_lvls = max(int(sag_lvl.max()), 1)
        cmap = plt.get_cmap("tab20", max(n_lvls + 1, 2))
        ax_sag_l.imshow(masked, cmap=cmap, vmin=1, vmax=max(n_lvls, 1),
                        interpolation="nearest", aspect=sag_aspect)
        # Cord contour on top
        sag_pam_rot = np.rot90(sag_pam.astype(bool))
        if sag_pam_rot.any():
            ax_sag_l.contour(sag_pam_rot, levels=[0.5], colors=[MARKER_YELLOW],
                             linewidths=contour_lw)
        sag_epi_rot = np.rot90(sag_epi.astype(bool))
        if sag_epi_rot.any():
            ax_sag_l.contour(sag_epi_rot, levels=[0.5], colors=[epi_cyan],
                             linewidths=contour_lw)
        ax_sag_l.set_xticks([]); ax_sag_l.set_yticks([])
        for s in ax_sag_l.spines.values():
            s.set_color("#374151"); s.set_linewidth(0.8)
    else:
        # No levels — show a second funcref strip so the layout is balanced
        render_sagittal(ax_sag_l, sag_func, sag_overlays, vmin, vmax,
                        pixel_aspect=sag_aspect)

    sag_label_y = sag_y0 + sag_h + 0.012
    fig.text(sag_x_f + sag_w_each / 2, sag_label_y, "Funcref",
             color=TEXT, fontsize=13, fontweight="bold", ha="center", va="bottom")
    fig.text(sag_x_l + sag_w_each / 2, sag_label_y,
             "PAM50 levels" if has_levels else "Funcref",
             color=TEXT, fontsize=13, fontweight="bold", ha="center", va="bottom")

    # --- Right block: axial 3×1 montage (funcref with two contours) ---
    grid_x0 = sag_x_l + sag_w_each + 0.05
    grid_w = 0.985 - grid_x0
    grid_y0 = sag_y0
    grid_h = sag_h - 0.04
    n_cols = len(z_picks)
    col_w = grid_w / n_cols
    grid_y1 = grid_y0 + grid_h

    # Compute per-tile level annotation
    def _level_at_z(z: int) -> str:
        if not has_levels:
            return ""
        vals = levels[:, :, z]
        present = [int(v) for v in np.unique(vals) if v > 0]
        if not present:
            return ""
        return f"L{min(present)}" if len(present) == 1 else f"L{min(present)}-{max(present)}"

    for col, z in enumerate(z_picks):
        cx = grid_x0 + col * col_w + col_w / 2
        lvl_str = _level_at_z(z)
        header = f"z = {z}" + (f"  ·  {lvl_str}" if lvl_str else "")
        fig.text(cx, grid_y1 + 0.012, header,
                 color=TEXT, fontsize=12, fontweight="bold",
                 ha="center", va="bottom", family="monospace")

    for col, z in enumerate(z_picks):
        cell_x = grid_x0 + col * col_w
        ax = fig.add_axes((
            cell_x + col_w * 0.03,
            grid_y0 + 0.05,
            col_w * 0.94, grid_h * 0.90,
        ))
        ax.set_facecolor(BG)
        tile_crop = per_slice_centered_crop(
            pam_cord, z, window_vox=(22, 22), fallback_bbox=global_bbox,
        )
        overlays = [
            (pam_cord[:, :, z], MARKER_YELLOW, contour_lw),
            (epi_cord[:, :, z], epi_cyan, contour_lw),
        ]
        render_axial_tile(ax, func[:, :, z], overlays,
                          vmin, vmax, z, first=(col == 0),
                          crop=tile_crop, pixel_aspect=ax_aspect)

    add_footer(
        fig,
        legend_items=[
            (MARKER_YELLOW, "PAM50 cord (in func)"),
            (epi_cyan, "EPI cord seg"),
        ],
        metric_lines=[
            f"sagittal: midcord X={x_mid}",
            f"axial Z picks: {list(z_picks)}",
        ],
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=dpi, facecolor=BG,
                bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Reportlet 2: cord_dice_per_level
# ---------------------------------------------------------------------------


def render_s7_cord_dice_per_level(
    per_level: dict,
    thresholds: dict,
    output_path: Path,
) -> None:
    """Per-vertebral-level cord Dice bar chart, color-coded PASS / WARN /
    FAIL.

    One bar per PAM50_spinal_levels integer present in the BOLD FOV.
    Bar height = 3D Dice within that level's Z slices. Matches the
    Kaptan 2023 / CoSpine 2025 / Valošek 2025 per-vertebral-level
    standard.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pass_min = float(thresholds.get("pass_dice_min", 0.80))
    fail_below = float(thresholds.get("fail_dice_below", 0.65))

    if not per_level:
        from spinalfmriprep.reportlets_common import stub_figure
        stub_figure(output_path,
                    "S7 per-level Dice: cord_dice_per_level not computed "
                    "(PAM50_spinal_levels missing or empty in FOV)")
        return

    # Normalise: per_level keys may be strings (from qc.json) or ints.
    items = sorted(
        ((int(k), float(v)) for k, v in per_level.items()),
        key=lambda kv: kv[0],
    )
    levels = [k for k, _ in items]
    dices = [v for _, v in items]
    colors = [
        "#22c55e" if d >= pass_min
        else "#f59e0b" if d >= fail_below
        else "#ef4444"
        for d in dices
    ]

    fig, ax = plt.subplots(figsize=(9, 4.5), facecolor="#0f1115")
    ax.set_facecolor("#0f1115")
    xs = np.arange(len(levels))
    ax.bar(xs, dices, color=colors, edgecolor="#1f2937", linewidth=0.4)
    ax.axhline(pass_min, linestyle="--", color="#22c55e", linewidth=0.9,
               label=f"PASS ≥ {pass_min:.2f}")
    ax.axhline(fail_below, linestyle="--", color="#ef4444", linewidth=0.9,
               label=f"FAIL < {fail_below:.2f}")
    ax.set_xticks(xs)
    ax.set_xticklabels([f"L{lvl}" for lvl in levels],
                       color="#e6e8ec", fontsize=10)
    ax.set_xlabel("PAM50 spinal level (1..20)", color="#e6e8ec")
    ax.set_ylabel("Cord Dice (PAM50 ∩ EPI seg)", color="#e6e8ec")
    ax.set_ylim(0, 1.0)
    ax.set_title("S7 — Cord Dice by vertebral level (PAM50 spinal_levels)",
                 color="#e6e8ec", fontsize=12, fontweight="bold")
    ax.tick_params(colors="#e6e8ec")
    for s in ax.spines.values():
        s.set_color("#374151")
    leg = ax.legend(loc="lower right", fontsize=9, facecolor="#1a1d23",
                    edgecolor="#374151", labelcolor="#e6e8ec")
    for t in leg.get_texts():
        t.set_color("#e6e8ec")
    ax.grid(alpha=0.15, color="#374151", axis="y")
    fig.tight_layout()
    fig.savefig(output_path, dpi=120, facecolor="#0f1115", bbox_inches="tight")
    plt.close(fig)
