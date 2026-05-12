"""S5 reportlet rendering: before/after axial montage with cord contour."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import nibabel as nib
import numpy as np


def _slice_montage(
    vol: np.ndarray, mask: Optional[np.ndarray], n_slices: int = 9
) -> tuple[np.ndarray, np.ndarray]:
    """Return (data_montage, mask_montage) as 2D arrays.

    Picks `n_slices` axial slices uniformly within the cord-bearing Z range
    (or full Z if no mask). Stacks them in a square-ish grid.
    """
    if mask is not None and mask.any():
        z_idx = np.where(mask.any(axis=(0, 1)))[0]
        z_pick = np.linspace(z_idx.min(), z_idx.max(), n_slices,
                             dtype=int)
    else:
        z_pick = np.linspace(0, vol.shape[2] - 1, n_slices, dtype=int)

    rows = int(np.ceil(np.sqrt(n_slices)))
    cols = int(np.ceil(n_slices / rows))
    h, w = vol.shape[0], vol.shape[1]
    data_grid = np.zeros((rows * h, cols * w), dtype=np.float32)
    mask_grid = np.zeros_like(data_grid, dtype=bool) if mask is not None else None
    for i, z in enumerate(z_pick):
        r, c = i // cols, i % cols
        data_grid[r * h:(r + 1) * h, c * w:(c + 1) * w] = np.rot90(vol[:, :, z])
        if mask_grid is not None:
            mask_grid[r * h:(r + 1) * h, c * w:(c + 1) * w] = np.rot90(mask[:, :, z]).astype(bool)
    return data_grid, mask_grid


def render_s5_before_after(
    bold_before_path: Path,
    bold_after_path: Path,
    cord_mask_path: Optional[Path],
    output_path: Path,
    n_slices: int = 9,
) -> None:
    """Side-by-side axial montage of mean(before) and mean(after) BOLD,
    with cord contour overlay. Bright = signal; lit-up edges in BOTH panels
    means good registration; visible cord shift between panels = topup
    did something."""
    img_a = nib.load(bold_before_path)
    img_b = nib.load(bold_after_path)
    a = img_a.get_fdata()
    b = img_b.get_fdata()
    mean_a = a.mean(axis=3) if a.ndim == 4 else a
    mean_b = b.mean(axis=3) if b.ndim == 4 else b

    mask = None
    if cord_mask_path is not None and Path(cord_mask_path).exists():
        m = nib.load(cord_mask_path).get_fdata()
        if m.shape == mean_a.shape:
            mask = m > 0

    grid_a, mask_grid = _slice_montage(mean_a, mask, n_slices=n_slices)
    grid_b, _ = _slice_montage(mean_b, mask, n_slices=n_slices)

    pool = np.concatenate([grid_a[grid_a > 1e-5], grid_b[grid_b > 1e-5]])
    if pool.size > 0:
        vmin, vmax = np.percentile(pool, [2, 98])
    else:
        vmin, vmax = 0.0, 1.0

    fig, axes = plt.subplots(1, 2, figsize=(12, 6), facecolor="black")
    for ax, data, title in zip(axes, [grid_a, grid_b],
                                ["Before distortion correction",
                                 "After distortion correction"]):
        ax.imshow(data, cmap="gray", vmin=vmin, vmax=vmax, interpolation="nearest")
        if mask_grid is not None and mask_grid.any():
            ax.contour(mask_grid, levels=[0.5], colors=["#0086e6"],
                       linewidths=0.6, alpha=0.9)
        ax.set_title(title, color="white", fontsize=12)
        ax.axis("off")
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=120, facecolor="black", bbox_inches="tight")
    plt.close(fig)


def render_s5_mi_summary(
    metrics: dict, output_path: Path, mode: str
) -> None:
    """Single bar chart showing MI before vs after distortion correction."""
    mi_b = metrics.get("mi_before")
    mi_a = metrics.get("mi_after")
    fig, ax = plt.subplots(figsize=(6, 4))
    if mi_b is not None and mi_a is not None:
        ax.bar(["Before", "After"], [mi_b, mi_a],
               color=["#888", "#0086e6"])
        delta = metrics.get("mi_delta_pct")
        if delta is not None:
            ax.set_title(f"Mutual information vs anat (mode={mode}, Δ={delta:+.1f}%)")
        else:
            ax.set_title(f"Mutual information vs anat (mode={mode})")
        ax.set_ylabel("MI (nats)")
        ax.grid(alpha=0.3, axis="y")
    else:
        ax.text(0.5, 0.5, f"MI not computed (mode={mode})",
                ha="center", va="center")
        ax.axis("off")
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=120, bbox_inches="tight")
    plt.close(fig)
