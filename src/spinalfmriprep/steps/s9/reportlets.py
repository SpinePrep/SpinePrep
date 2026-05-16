"""S9 reportlet rendering — 4 PNGs per run."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import nibabel as nib
import numpy as np
import pandas as pd


def _crop_bbox(mask: np.ndarray, margin: int = 4) -> tuple[slice, slice, slice]:
    coords = np.argwhere(mask)
    if coords.size == 0:
        return slice(None), slice(None), slice(None)
    mn = coords.min(axis=0); mx = coords.max(axis=0)
    sl = []
    for ax, dim in enumerate(mask.shape):
        sl.append(slice(max(0, mn[ax] - margin), min(dim, mx[ax] + margin + 1)))
    return tuple(sl)


def _safe_pct(arr: np.ndarray, q: tuple[float, float]) -> tuple[float, float]:
    pool = arr[np.isfinite(arr) & (arr > 1e-6)]
    if pool.size == 0:
        return 0.0, 1.0
    lo, hi = np.percentile(pool, q)
    return float(lo), float(max(hi, lo + 1.0))


def render_s9_smoothed_vs_unsmoothed_axial(
    unsmoothed_bold: Path, smoothed_bold: Path, cord_mask: Path,
    output_path: Path, n_slices: int = 9,
) -> None:
    """9-slice axial montage comparing pre vs post smoothing (temporal means)."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pre = nib.load(unsmoothed_bold).get_fdata().astype(np.float32).mean(axis=3)
    post = nib.load(smoothed_bold).get_fdata().astype(np.float32).mean(axis=3)
    mask = nib.load(cord_mask).get_fdata() > 0.5
    bbx = _crop_bbox(mask)
    pre_c = pre[bbx]; post_c = post[bbx]; mask_c = mask[bbx]
    z_idx = np.where(mask_c.any(axis=(0, 1)))[0]
    if z_idx.size == 0:
        z_idx = np.arange(pre_c.shape[2])
    z_pick = np.linspace(z_idx.min(), z_idx.max(),
                         min(n_slices, max(1, z_idx.size)), dtype=int)
    rows = int(np.ceil(np.sqrt(len(z_pick))))
    cols = int(np.ceil(len(z_pick) / rows))
    th, tw = pre_c.shape[1], pre_c.shape[0]
    g_pre = np.zeros((rows * th, cols * tw), dtype=np.float32)
    g_post = np.zeros_like(g_pre)
    g_msk = np.zeros_like(g_pre, dtype=bool)
    for i, z in enumerate(z_pick):
        r, c = i // cols, i % cols
        g_pre[r*th:(r+1)*th, c*tw:(c+1)*tw] = np.rot90(pre_c[:, :, z])
        g_post[r*th:(r+1)*th, c*tw:(c+1)*tw] = np.rot90(post_c[:, :, z])
        g_msk[r*th:(r+1)*th, c*tw:(c+1)*tw] = np.rot90(mask_c[:, :, z]).astype(bool)
    fig, axes = plt.subplots(1, 2, figsize=(12, 6), facecolor="black")
    vmin, vmax = _safe_pct(g_pre, (2, 98))
    for ax, grid, label in zip(axes, [g_pre, g_post], ["Unsmoothed", "Smoothed"]):
        ax.imshow(grid, cmap="gray", vmin=vmin, vmax=vmax, interpolation="nearest")
        if g_msk.any():
            ax.contour(g_msk, levels=[0.5], colors=["#00d0ff"], linewidths=0.5)
        ax.set_title(f"{label}", color="white", fontsize=11)
        ax.axis("off")
    fig.tight_layout()
    fig.savefig(output_path, dpi=120, facecolor="black", bbox_inches="tight")
    plt.close(fig)


def render_s9_tsnr_map_axial(
    tsnr_path: Path, cord_mask: Path, output_path: Path,
    n_slices: int = 9,
) -> None:
    """9-slice axial montage of the smoothed tSNR map."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tsnr = nib.load(tsnr_path).get_fdata().astype(np.float32)
    mask = nib.load(cord_mask).get_fdata() > 0.5
    bbx = _crop_bbox(mask)
    t_c = tsnr[bbx]; mask_c = mask[bbx]
    z_idx = np.where(mask_c.any(axis=(0, 1)))[0]
    if z_idx.size == 0:
        z_idx = np.arange(t_c.shape[2])
    z_pick = np.linspace(z_idx.min(), z_idx.max(),
                         min(n_slices, max(1, z_idx.size)), dtype=int)
    rows = int(np.ceil(np.sqrt(len(z_pick))))
    cols = int(np.ceil(len(z_pick) / rows))
    th, tw = t_c.shape[1], t_c.shape[0]
    grid = np.zeros((rows * th, cols * tw), dtype=np.float32)
    g_msk = np.zeros_like(grid, dtype=bool)
    for i, z in enumerate(z_pick):
        r, c = i // cols, i % cols
        grid[r*th:(r+1)*th, c*tw:(c+1)*tw] = np.rot90(t_c[:, :, z])
        g_msk[r*th:(r+1)*th, c*tw:(c+1)*tw] = np.rot90(mask_c[:, :, z]).astype(bool)
    fig, ax = plt.subplots(figsize=(8, 8), facecolor="black")
    vmin, vmax = _safe_pct(grid, (2, 98))
    im = ax.imshow(grid, cmap="hot", vmin=vmin, vmax=vmax, interpolation="nearest")
    if g_msk.any():
        ax.contour(g_msk, levels=[0.5], colors=["#00d0ff"], linewidths=0.5)
    cbar = fig.colorbar(im, ax=ax, shrink=0.7, label="tSNR")
    cbar.ax.tick_params(colors="white"); cbar.set_label("tSNR", color="white")
    median = float(np.median(grid[g_msk])) if g_msk.any() else float("nan")
    ax.set_title(f"Native tSNR (smoothed)  cord median = {median:.1f}",
                 color="white", fontsize=11)
    ax.axis("off")
    fig.tight_layout()
    fig.savefig(output_path, dpi=120, facecolor="black", bbox_inches="tight")
    plt.close(fig)


def render_s9_tsnr_per_level(per_level_tsv: Path, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not per_level_tsv.exists():
        fig, ax = plt.subplots(figsize=(8, 3))
        ax.text(0.5, 0.5, "per-level tSNR unavailable", ha="center", va="center")
        ax.axis("off")
        fig.savefig(output_path, dpi=120, bbox_inches="tight"); plt.close(fig)
        return
    df = pd.read_csv(per_level_tsv, sep="\t")
    if df.empty:
        fig, ax = plt.subplots(figsize=(8, 3))
        ax.text(0.5, 0.5, "no levels with cord voxels in this run",
                ha="center", va="center")
        ax.axis("off")
        fig.savefig(output_path, dpi=120, bbox_inches="tight"); plt.close(fig)
        return
    fig, ax = plt.subplots(figsize=(8, 4))
    x = df["level"].astype(int).to_numpy()
    y = df["mean_tsnr"].astype(float).to_numpy()
    err = df["std_tsnr"].astype(float).to_numpy()
    ax.bar(x, y, yerr=err, color="#0086e6", alpha=0.85,
           error_kw={"ecolor": "#444", "lw": 0.8})
    ax.set_xlabel("PAM50 spinal level")
    ax.set_ylabel("tSNR (mean ± SD)")
    ax.set_title(f"Per-vertebral-level tSNR ({len(df)} levels)")
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(output_path, dpi=120, bbox_inches="tight"); plt.close(fig)


def render_s9_smoothness_summary(
    requested: list[float], measured: dict[str, Optional[float]],
    output_path: Path,
) -> None:
    """Bar chart: requested FWHM vs measured FWHM per axis."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    axes_lbl = ["X (R-L)", "Y (A-P)", "Z (S-I)"]
    req = list(requested) + [0.0] * (3 - len(requested))
    meas = [measured.get("x") or 0.0,
            measured.get("y") or 0.0,
            measured.get("z") or 0.0]
    fig, ax = plt.subplots(figsize=(8, 4))
    x = np.arange(3)
    w = 0.35
    b1 = ax.bar(x - w/2, req, width=w, label="Requested FWHM",
                color="#0086e6", alpha=0.85)
    b2 = ax.bar(x + w/2, meas, width=w, label="Measured residual",
                color="#ff5500", alpha=0.85)
    for bars in (b1, b2):
        for bar in bars:
            h = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2, h + 0.2, f"{h:.1f}",
                    ha="center", fontsize=9)
    ax.set_xticks(x); ax.set_xticklabels(axes_lbl)
    ax.set_ylabel("FWHM (mm)")
    ax.set_title("Spatial smoothness — requested vs measured residual")
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(output_path, dpi=120, bbox_inches="tight"); plt.close(fig)
