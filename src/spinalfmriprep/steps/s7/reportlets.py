"""S7 reportlet rendering — PAM50 overlays on native func."""

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


def _safe_percentile(arr: np.ndarray, q: tuple[float, float]) -> tuple[float, float]:
    pool = arr[np.isfinite(arr) & (arr > 1e-5)]
    if pool.size == 0:
        return 0.0, 1.0
    lo, hi = np.percentile(pool, q)
    if hi <= lo:
        hi = lo + 1.0
    return float(lo), float(hi)


# ---------------------------------------------------------------------------
# Sagittal: funcref + PAM50_cord contour
# ---------------------------------------------------------------------------


def render_s7_pam50_overlay_sagittal(
    funcref_path: Path, pam50_cord_in_func_path: Path, output_path: Path,
) -> None:
    """Mid-sagittal funcref with PAM50_cord (warped to native func) contour."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fimg = nib.load(funcref_path)
    func = fimg.get_fdata()
    cord = nib.load(pam50_cord_in_func_path).get_fdata() > 0.5
    zooms = fimg.header.get_zooms()[:3]

    bbx = _crop_bbox(cord, margin=6)
    func_c = func[bbx]; cord_c = cord[bbx]

    x_mid = func_c.shape[0] // 2
    slc_func = np.rot90(func_c[x_mid, :, :])
    slc_cord = np.rot90(cord_c[x_mid, :, :])

    aspect = zooms[2] / zooms[1] if zooms[1] > 0 else 1.0
    fig, ax = plt.subplots(1, 1, figsize=(6, 8), facecolor="black")
    vmin, vmax = _safe_percentile(slc_func, (2, 98))
    ax.imshow(slc_func, cmap="gray", vmin=vmin, vmax=vmax,
              interpolation="nearest", aspect=aspect)
    if slc_cord.any():
        ax.contour(slc_cord, levels=[0.5], colors=["#00d0ff"], linewidths=0.8)
    ax.set_title("Funcref + PAM50 cord (cyan)", color="white", fontsize=11)
    ax.axis("off")
    fig.tight_layout()
    fig.savefig(output_path, dpi=120, facecolor="black", bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Axial 9-slice montage: funcref + PAM50_cord contour
# ---------------------------------------------------------------------------


def render_s7_pam50_overlay_axial(
    funcref_path: Path, pam50_cord_in_func_path: Path, output_path: Path,
    n_slices: int = 9,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    func = nib.load(funcref_path).get_fdata()
    cord = nib.load(pam50_cord_in_func_path).get_fdata() > 0.5

    bbx = _crop_bbox(cord)
    func_c = func[bbx]; cord_c = cord[bbx]

    z_idx = np.where(cord_c.any(axis=(0, 1)))[0]
    if z_idx.size == 0:
        z_idx = np.arange(func_c.shape[2])
    z_pick = np.linspace(z_idx.min(), z_idx.max(),
                         min(n_slices, max(1, z_idx.size)), dtype=int)

    rows = int(np.ceil(np.sqrt(len(z_pick))))
    cols = int(np.ceil(len(z_pick) / rows))
    th, tw = func_c.shape[1], func_c.shape[0]
    grid = np.zeros((rows * th, cols * tw), dtype=np.float32)
    cgrid = np.zeros_like(grid, dtype=bool)
    for i, z in enumerate(z_pick):
        r, c = i // cols, i % cols
        grid[r*th:(r+1)*th, c*tw:(c+1)*tw] = np.rot90(func_c[:, :, z])
        cgrid[r*th:(r+1)*th, c*tw:(c+1)*tw] = np.rot90(cord_c[:, :, z]).astype(bool)

    fig, ax = plt.subplots(figsize=(8, 8), facecolor="black")
    vmin, vmax = _safe_percentile(grid, (2, 98))
    ax.imshow(grid, cmap="gray", vmin=vmin, vmax=vmax, interpolation="nearest")
    if cgrid.any():
        ax.contour(cgrid, levels=[0.5], colors=["#00d0ff"], linewidths=0.5)
    ax.set_title("Funcref axial montage + PAM50 cord (cyan)",
                 color="white", fontsize=11)
    ax.axis("off")
    fig.tight_layout()
    fig.savefig(output_path, dpi=120, facecolor="black", bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Vertebral alignment: sagittal label overlay
# ---------------------------------------------------------------------------


def render_s7_vertebral_alignment(
    pam50_levels_in_func_path: Path,
    subject_labels_path: Optional[Path],
    output_path: Path,
) -> None:
    """Color-coded vertebral level overlay on a sagittal view.

    Always renders the warped PAM50 spinal_levels labels. If subject
    vertebral labels were provided (S2 derivative), they overlay on top
    as dashed contours so disagreement is visually obvious.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not Path(pam50_levels_in_func_path).exists():
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.text(0.5, 0.5, "PAM50 spinal_levels not available",
                ha="center", va="center")
        ax.axis("off")
        fig.savefig(output_path, dpi=120, bbox_inches="tight")
        plt.close(fig)
        return

    pam_img = nib.load(pam50_levels_in_func_path)
    pam = pam_img.get_fdata().astype(np.int32)
    zooms = pam_img.header.get_zooms()[:3]

    pam_mask = pam > 0
    if not pam_mask.any():
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.text(0.5, 0.5, "All-zero PAM50 spinal_levels", ha="center", va="center")
        ax.axis("off")
        fig.savefig(output_path, dpi=120, bbox_inches="tight")
        plt.close(fig)
        return

    bbx = _crop_bbox(pam_mask, margin=6)
    pam_c = pam[bbx]
    x_mid = pam_c.shape[0] // 2
    slc = np.rot90(pam_c[x_mid, :, :])

    aspect = zooms[2] / zooms[1] if zooms[1] > 0 else 1.0
    fig, ax = plt.subplots(figsize=(6, 8), facecolor="black")
    n_lvls = int(slc.max())
    cmap = plt.get_cmap("tab20", max(n_lvls + 1, 2))
    masked = np.ma.masked_where(slc == 0, slc)
    ax.imshow(masked, cmap=cmap, vmin=1, vmax=max(n_lvls, 1),
              interpolation="nearest", aspect=aspect)
    title = "PAM50 spinal levels"

    if subject_labels_path and Path(subject_labels_path).exists():
        try:
            sub = nib.load(subject_labels_path).get_fdata().astype(np.int32)
            if sub.shape == pam.shape:
                sub_c = sub[bbx]
                sub_slc = np.rot90(sub_c[x_mid, :, :])
                ax.contour(sub_slc > 0, levels=[0.5], colors=["white"],
                           linewidths=0.6, alpha=0.8, linestyles="dashed")
                title += " + subject labels (white dashed)"
        except Exception:
            pass

    ax.set_title(title, color="white", fontsize=10)
    ax.axis("off")
    fig.tight_layout()
    fig.savefig(output_path, dpi=120, facecolor="black", bbox_inches="tight")
    plt.close(fig)
