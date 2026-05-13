"""S6 reportlet rendering."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import nibabel as nib
import numpy as np


def _crop_bbox(mask: np.ndarray, margin: int = 4) -> tuple[slice, slice, slice]:
    coords = np.argwhere(mask)
    if coords.size == 0:
        return slice(None), slice(None), slice(None)
    mn = coords.min(axis=0); mx = coords.max(axis=0)
    sl = []
    for ax, dim in enumerate(mask.shape):
        sl.append(slice(max(0, mn[ax] - margin), min(dim, mx[ax] + margin + 1)))
    return tuple(sl)


def render_s6_axial(
    bold_mean_path: Path, anat_in_bold_path: Path,
    cord_mask_path: Path, output_path: Path,
    n_slices: int = 9,
) -> None:
    """9-slice axial montage with BOLD-mean intensity + anat contour, cord-cropped."""
    bold = nib.load(bold_mean_path).get_fdata()
    anat = nib.load(anat_in_bold_path).get_fdata()
    mask = nib.load(cord_mask_path).get_fdata() > 0.5

    bbx = _crop_bbox(mask)
    bold_c = bold[bbx]; anat_c = anat[bbx]; mask_c = mask[bbx]

    # Pick cord-bearing Z slices
    z_idx = np.where(mask_c.any(axis=(0, 1)))[0]
    if z_idx.size == 0:
        z_idx = np.arange(bold_c.shape[2])
    z_pick = np.linspace(z_idx.min(), z_idx.max(),
                         min(n_slices, max(1, z_idx.size)), dtype=int)

    rows = int(np.ceil(np.sqrt(len(z_pick))))
    cols = int(np.ceil(len(z_pick) / rows))
    th, tw = bold_c.shape[1], bold_c.shape[0]
    grid_bold = np.zeros((rows * th, cols * tw), dtype=np.float32)
    grid_anat = np.zeros_like(grid_bold)
    grid_mask = np.zeros_like(grid_bold, dtype=bool)
    for i, z in enumerate(z_pick):
        r, c = i // cols, i % cols
        grid_bold[r*th:(r+1)*th, c*tw:(c+1)*tw] = np.rot90(bold_c[:, :, z])
        grid_anat[r*th:(r+1)*th, c*tw:(c+1)*tw] = np.rot90(anat_c[:, :, z])
        grid_mask[r*th:(r+1)*th, c*tw:(c+1)*tw] = np.rot90(mask_c[:, :, z]).astype(bool)

    fig, axes = plt.subplots(1, 2, figsize=(12, 6), facecolor="black")
    pool = grid_bold[grid_bold > 1e-5]
    if pool.size > 0:
        vmin_b, vmax_b = np.percentile(pool, [2, 98])
    else:
        vmin_b, vmax_b = 0.0, 1.0
    pool = grid_anat[grid_anat > 1e-5]
    if pool.size > 0:
        vmin_a, vmax_a = np.percentile(pool, [2, 98])
    else:
        vmin_a, vmax_a = 0.0, 1.0

    axes[0].imshow(grid_bold, cmap="gray", vmin=vmin_b, vmax=vmax_b, interpolation="nearest")
    if grid_mask.any():
        axes[0].contour(grid_mask, levels=[0.5], colors=["#0086e6"], linewidths=0.6)
    axes[0].set_title("Mean BOLD (cord-cropped)", color="white", fontsize=12)
    axes[0].axis("off")

    axes[1].imshow(grid_bold, cmap="gray", vmin=vmin_b, vmax=vmax_b, interpolation="nearest")
    axes[1].contour(grid_anat, levels=[float(np.percentile(grid_anat[grid_anat > 1e-5], 50))]
                     if (grid_anat > 1e-5).any() else [0.5],
                    colors=["#ff5500"], linewidths=0.5, alpha=0.7)
    if grid_mask.any():
        axes[1].contour(grid_mask, levels=[0.5], colors=["#0086e6"], linewidths=0.6)
    axes[1].set_title("BOLD + anat contour (orange) + cord seg (blue)",
                      color="white", fontsize=11)
    axes[1].axis("off")
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=120, facecolor="black", bbox_inches="tight")
    plt.close(fig)


def render_s6_sagittal(
    bold_mean_path: Path, anat_in_bold_path: Path,
    cord_mask_path: Path, output_path: Path,
) -> None:
    """Mid-sagittal overlay BOLD + anat-contour, aspect-corrected by voxel size."""
    bold_img = nib.load(bold_mean_path)
    bold = bold_img.get_fdata()
    anat = nib.load(anat_in_bold_path).get_fdata()
    mask = nib.load(cord_mask_path).get_fdata() > 0.5
    zooms = bold_img.header.get_zooms()[:3]

    bbx = _crop_bbox(mask, margin=6)
    bold_c = bold[bbx]; anat_c = anat[bbx]; mask_c = mask[bbx]

    # Mid-sagittal slice along X (axis 0)
    x_mid = bold_c.shape[0] // 2
    slc_bold = np.rot90(bold_c[x_mid, :, :])
    slc_anat = np.rot90(anat_c[x_mid, :, :])
    slc_mask = np.rot90(mask_c[x_mid, :, :])

    aspect = zooms[2] / zooms[1] if zooms[1] > 0 else 1.0
    fig, ax = plt.subplots(1, 1, figsize=(6, 8), facecolor="black")
    pool = slc_bold[slc_bold > 1e-5]
    if pool.size > 0:
        vmin, vmax = np.percentile(pool, [2, 98])
    else:
        vmin, vmax = 0.0, 1.0
    ax.imshow(slc_bold, cmap="gray", vmin=vmin, vmax=vmax,
              interpolation="nearest", aspect=aspect)
    if (slc_anat > 1e-5).any():
        ax.contour(slc_anat,
                   levels=[float(np.percentile(slc_anat[slc_anat > 1e-5], 50))],
                   colors=["#ff5500"], linewidths=0.6, alpha=0.8)
    if slc_mask.any():
        ax.contour(slc_mask, levels=[0.5], colors=["#0086e6"], linewidths=0.6)
    ax.set_title("Mid-sagittal: BOLD + anat (orange) + cord (blue)",
                 color="white", fontsize=11)
    ax.axis("off")
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=120, facecolor="black", bbox_inches="tight")
    plt.close(fig)


def render_s6_dice_per_slice(
    funccrop_mask_path: Path, anat_dseg_in_bold_path: Optional[Path],
    output_path: Path, thresholds: dict,
) -> None:
    """Per-slice cord Dice along Z, color-coded by PASS/WARN/FAIL band."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if anat_dseg_in_bold_path is None or not Path(anat_dseg_in_bold_path).exists():
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.text(0.5, 0.5, "No anat seg in BOLD geometry — Dice unavailable",
                ha="center", va="center")
        ax.axis("off")
        fig.savefig(output_path, dpi=120, bbox_inches="tight")
        plt.close(fig)
        return

    a = nib.load(funccrop_mask_path).get_fdata() > 0.5
    b = nib.load(anat_dseg_in_bold_path).get_fdata() > 0.5
    if a.shape != b.shape:
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.text(0.5, 0.5, f"Shape mismatch: {a.shape} vs {b.shape}",
                ha="center", va="center")
        ax.axis("off")
        fig.savefig(output_path, dpi=120, bbox_inches="tight")
        plt.close(fig)
        return

    pass_min = thresholds.get("pass_dice_min", 0.85)
    fail_below = thresholds.get("fail_dice_below", 0.65)

    dice_z: list[float] = []
    for z in range(a.shape[2]):
        az = a[:, :, z]; bz = b[:, :, z]
        n = az.sum() + bz.sum()
        dice_z.append(float(2 * (az & bz).sum() / n) if n > 0 else float("nan"))

    fig, ax = plt.subplots(figsize=(8, 4))
    colors = [("#22aa44" if (not np.isnan(d) and d >= pass_min)
               else "#dd8800" if (not np.isnan(d) and d >= fail_below)
               else "#cc2222") for d in dice_z]
    ax.bar(range(len(dice_z)), [0 if np.isnan(d) else d for d in dice_z],
           color=colors)
    ax.axhline(pass_min, linestyle="--", color="#22aa44", linewidth=0.8,
               label=f"PASS ≥ {pass_min}")
    ax.axhline(fail_below, linestyle="--", color="#cc2222", linewidth=0.8,
               label=f"FAIL < {fail_below}")
    ax.set_xlabel("Slice (Z)")
    ax.set_ylabel("Cord Dice")
    ax.set_ylim(0, 1.0)
    ax.set_title("Cord segmentation Dice by slice")
    ax.legend(loc="lower right", fontsize=8)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(output_path, dpi=120, bbox_inches="tight")
    plt.close(fig)
