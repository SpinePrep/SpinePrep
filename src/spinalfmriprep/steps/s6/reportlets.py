"""S6 reportlet rendering — chain-wide visual standard.

Three reportlets:

1. ``bold_on_anat_axial`` — sagittal pair (Before/After context isn't
   meaningful here, but a sagittal anchor + axial montage is the
   standard cord-fMRI QC view) + 6 cord-bearing axial tiles. Yellow
   anat-cord contour on every panel.
2. ``bold_on_anat_sagittal`` — single mid-sagittal slice (BOLD-in-anat
   geometry) with yellow anat-cord-seg contour and cyan EPI-cord-seg
   contour. Quick visual: do the two cords line up along Z?
3. ``cord_dice_per_slice`` — per-slice 3D-Dice bar chart, color-coded
   PASS/WARN/FAIL band. Kept simple (non-image plot doesn't need
   visual-standard chrome).

Audit reference: ``.claude/specs/s6-algorithm-audit.md`` — fixes
Findings 8 (intensity-percentile contour → cord seg) and 9 (visual
standard adherence). Inputs include the warped anat **cord
segmentation** (``anat_dseg_in_bold``), not the warped anat intensity
image; the contour now traces the cord boundary directly.
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
# Reportlet 1+2: axial + sagittal overlays, using reportlets_common chrome
# ---------------------------------------------------------------------------


def render_s6_axial(
    bold_mean_path: Path,
    anat_dseg_in_bold_path: Path,
    cord_mask_path: Path,
    output_path: Path,
    funcref_path: Optional[Path] = None,
    n_axial: int = 6,
    dice: Optional[float] = None,
    hd95: Optional[float] = None,
    contour_lw: float = 2.0,
    dpi: int = 120,
) -> None:
    """Sagittal anchor + axial montage of mean BOLD with the anat cord
    seg (yellow) and the EPI cord seg (cyan) overlaid.

    The two contours line up ⇒ registration worked. Yellow drifts off
    the cord centroid ⇒ low Dice / high HD95.

    ``anat_dseg_in_bold`` must be the warped **anat cord segmentation**,
    not the warped anat intensity image — that's the audit Finding 8
    fix.
    """
    from spinalfmriprep.reportlets_common import (
        BG, MARKER_YELLOW, SEMANTIC,
        render_sagittal_plus_montage,
    )

    bold_img = nib.load(bold_mean_path)
    bold = bold_img.get_fdata().astype(np.float32)
    anat_cord = nib.load(anat_dseg_in_bold_path).get_fdata() > 0.5
    epi_cord = nib.load(cord_mask_path).get_fdata() > 0.5

    if bold.shape != anat_cord.shape or bold.shape != epi_cord.shape:
        from spinalfmriprep.reportlets_common import stub_figure
        stub_figure(output_path,
                    f"S6 axial: shape mismatch "
                    f"BOLD={bold.shape} anat={anat_cord.shape} "
                    f"EPI={epi_cord.shape}")
        return

    zooms = tuple(bold_img.header.get_zooms()[:3])

    subtitle_parts = []
    if dice is not None:
        subtitle_parts.append(f"Dice={dice:.2f}")
    if hd95 is not None:
        subtitle_parts.append(f"HD95={hd95:.2f}mm")
    subtitle = "  ·  ".join(subtitle_parts) if subtitle_parts else ""

    # Status pill from Dice (mirrors the qc.json classifier's gate)
    status = "PASS" if (dice is not None and dice >= 0.80) else "WARN"

    epi_cyan = SEMANTIC.get("cord_epi", "#22d3ee")

    def _factory(z):
        # Per-axial-tile overlays: anat cord (yellow) + EPI cord (cyan).
        return [
            (anat_cord[:, :, z], MARKER_YELLOW, contour_lw),
            (epi_cord[:, :, z], epi_cyan, contour_lw),
        ]

    render_sagittal_plus_montage(
        output_path,
        title="S6 — BOLD on Anat (Axial)",
        subtitle=subtitle,
        status=status,
        metric_header=None,
        anat=bold,                                     # BOLD as background
        cord_mask=anat_cord,                           # used for cord crop/range
        sag_overlays=[
            (anat_cord, MARKER_YELLOW, 0.0, contour_lw),
            (epi_cord, epi_cyan, 0.0, contour_lw),
        ],
        axial_overlays_factory=_factory,
        legend_items=[
            (MARKER_YELLOW, "anat cord seg"),
            (epi_cyan, "EPI cord seg"),
        ],
        metric_lines=[],
        n_axial=n_axial,
        n_axial_cols=3,
        zooms=zooms,
    )


def render_s6_sagittal(
    bold_mean_path: Path,
    anat_dseg_in_bold_path: Path,
    cord_mask_path: Path,
    output_path: Path,
    dice: Optional[float] = None,
    hd95: Optional[float] = None,
    contour_lw: float = 2.2,
    dpi: int = 120,
) -> None:
    """Mid-sagittal-only reportlet: BOLD with anat cord (yellow) +
    EPI cord (cyan) contours. Same chrome as the axial reportlet,
    but a single big sagittal — useful for checking S-I alignment
    of the cord centerline.
    """
    from spinalfmriprep.reportlets_common import (
        BG, TEXT, BORDER, MARKER_YELLOW, SEMANTIC,
        intensity_window, midcord_sagittal_slice,
        add_header, add_footer, render_sagittal,
    )

    bold_img = nib.load(bold_mean_path)
    bold = bold_img.get_fdata().astype(np.float32)
    anat_cord = nib.load(anat_dseg_in_bold_path).get_fdata() > 0.5
    epi_cord = nib.load(cord_mask_path).get_fdata() > 0.5

    if bold.shape != anat_cord.shape or bold.shape != epi_cord.shape:
        from spinalfmriprep.reportlets_common import stub_figure
        stub_figure(output_path,
                    "S6 sagittal: shape mismatch between BOLD / anat-cord / EPI-cord")
        return
    if not anat_cord.any() or not epi_cord.any():
        from spinalfmriprep.reportlets_common import stub_figure
        stub_figure(output_path,
                    "S6 sagittal: empty cord seg(s) — registration may have failed")
        return

    x_mid = midcord_sagittal_slice(anat_cord)
    sag_bold = bold[x_mid, :, :]
    sag_anat = anat_cord[x_mid, :, :]
    sag_epi = epi_cord[x_mid, :, :]

    zooms = list(bold_img.header.get_zooms()[:3]) + [1.0, 1.0, 1.0]
    zx, zy, zz = float(zooms[0]), float(zooms[1]), float(zooms[2])
    sag_aspect = zz / zy if zy > 0 else 1.0

    vmin, vmax = intensity_window(sag_bold, 2.0, 98.0)

    subtitle_parts = []
    if dice is not None:
        subtitle_parts.append(f"Dice={dice:.2f}")
    if hd95 is not None:
        subtitle_parts.append(f"HD95={hd95:.2f}mm")
    subtitle = "  ·  ".join(subtitle_parts) if subtitle_parts else ""
    status = "PASS" if (dice is not None and dice >= 0.80) else "WARN"

    epi_cyan = SEMANTIC.get("cord_epi", "#22d3ee")

    fig = plt.figure(figsize=(8.0, 9.0), facecolor=BG)
    fig.patch.set_facecolor(BG)
    add_header(fig, "S6 — BOLD on Anat (Mid-Sagittal)",
               subtitle, status, None)

    ax = fig.add_axes((0.14, 0.10, 0.72, 0.78))
    ax.set_facecolor(BG)
    sag_overlays = [
        (sag_anat, MARKER_YELLOW, 0.0, contour_lw),
        (sag_epi, epi_cyan, 0.0, contour_lw),
    ]
    render_sagittal(ax, sag_bold, sag_overlays, vmin, vmax,
                    pixel_aspect=sag_aspect)

    add_footer(
        fig,
        legend_items=[
            (MARKER_YELLOW, "anat cord seg"),
            (epi_cyan, "EPI cord seg"),
        ],
        metric_lines=[f"midcord X = {x_mid}"],
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=dpi, facecolor=BG,
                bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Reportlet 3: per-slice Dice bar chart (kept simple, no chrome)
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
        from spinalfmriprep.reportlets_common import stub_figure
        stub_figure(output_path,
                    "S6 cord_dice_per_slice: anat cord seg in BOLD geometry unavailable")
        return

    a = nib.load(funccrop_mask_path).get_fdata() > 0.5
    b = nib.load(anat_dseg_in_bold_path).get_fdata() > 0.5
    if a.shape != b.shape:
        from spinalfmriprep.reportlets_common import stub_figure
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
