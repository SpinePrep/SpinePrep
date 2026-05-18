"""S10 reportlet rendering."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def render_s10_hemicord_timeseries(ts_df: pd.DataFrame, output_path: Path) -> None:
    """One panel per hemicord×seg ROI; shared y-axis."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cols = list(ts_df.columns)
    n = len(cols)
    if n == 0:
        fig, ax = plt.subplots(figsize=(8, 3))
        ax.text(0.5, 0.5, "No hemicord ROIs", ha="center", va="center")
        ax.axis("off")
        fig.savefig(output_path, dpi=120, bbox_inches="tight"); plt.close(fig)
        return
    rows = int(np.ceil(n / 4))
    fig, axes = plt.subplots(rows, 4, figsize=(14, 1.5 * rows + 1),
                             sharex=True, sharey=True)
    axes = np.atleast_2d(axes)
    for i, c in enumerate(cols):
        ax = axes[i // 4, i % 4]
        ax.plot(ts_df[c].to_numpy(), color="#0086e6", lw=0.5)
        ax.set_title(c, fontsize=8)
        ax.grid(alpha=0.3)
        ax.tick_params(labelsize=6)
    for j in range(n, rows * 4):
        axes[j // 4, j % 4].axis("off")
    fig.suptitle(f"Hemicord × segmental timeseries (s8-regressed) — {n} ROIs",
                 fontsize=11)
    fig.tight_layout()
    fig.savefig(output_path, dpi=120, bbox_inches="tight"); plt.close(fig)


def render_s10_hemicord_connectivity(
    mat: pd.DataFrame, output_path: Path, title: str = "Connectivity",
    vmin: float = -1.0, vmax: float = 1.0,
) -> None:
    """ROI×ROI heatmap with row/col labels."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    arr = mat.to_numpy()
    labels = list(mat.columns)
    n = len(labels)
    fig, ax = plt.subplots(figsize=(max(6, n * 0.25 + 2), max(6, n * 0.25 + 2)))
    im = ax.imshow(arr, cmap="RdBu_r", vmin=vmin, vmax=vmax,
                   interpolation="nearest")
    fig.colorbar(im, ax=ax, shrink=0.7, label="value")
    step = max(1, n // 24)
    ax.set_xticks(range(0, n, step))
    ax.set_yticks(range(0, n, step))
    ax.set_xticklabels([labels[i] for i in range(0, n, step)],
                       rotation=90, fontsize=7)
    ax.set_yticklabels([labels[i] for i in range(0, n, step)], fontsize=7)
    ax.set_title(title)
    fig.tight_layout()
    fig.savefig(output_path, dpi=120, bbox_inches="tight"); plt.close(fig)


def render_s10_vertlvl_tsnr(
    tsnr_per_label: dict[str, float], output_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    labels = list(tsnr_per_label.keys())
    vals = [tsnr_per_label[k] for k in labels]
    fig, ax = plt.subplots(figsize=(max(6, len(labels) * 0.4 + 2), 4))
    ax.bar(labels, vals, color="#0086e6", alpha=0.85)
    ax.set_ylabel("Median tSNR")
    ax.set_xlabel("Vertebral level")
    ax.set_title(f"Per-vertebral-level tSNR ({len(labels)} levels)")
    ax.grid(axis="y", alpha=0.3)
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right")
    fig.tight_layout()
    fig.savefig(output_path, dpi=120, bbox_inches="tight"); plt.close(fig)


def render_s10_reliability_icc(
    per_connection: list[dict[str, Any]], cicchetti_bands: dict,
    output_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not per_connection:
        fig, ax = plt.subplots(figsize=(8, 3))
        ax.text(0.5, 0.5, "Reliability not applicable (< 2 sessions)",
                ha="center", va="center")
        ax.axis("off")
        fig.savefig(output_path, dpi=120, bbox_inches="tight"); plt.close(fig)
        return
    df = pd.DataFrame(per_connection)
    if "icc" not in df.columns:
        fig, ax = plt.subplots(figsize=(8, 3))
        ax.text(0.5, 0.5, "No ICC data", ha="center", va="center")
        ax.axis("off")
        fig.savefig(output_path, dpi=120, bbox_inches="tight"); plt.close(fig)
        return
    df_sorted = df.sort_values("icc", ascending=False).reset_index(drop=True)
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.bar(range(len(df_sorted)), df_sorted["icc"].fillna(0).to_numpy(),
           color="#33aa77", alpha=0.85)
    for band_name, thr in cicchetti_bands.items():
        ax.axhline(thr, ls="--", color="#888", lw=0.6,
                   label=f"{band_name}={thr}")
    ax.set_xlabel("Connection (sorted)")
    ax.set_ylabel("Cross-session agreement (r)")
    ax.set_title(f"Per-connection cross-session agreement ({len(df_sorted)} connections)")
    ax.legend(fontsize=7, loc="upper right")
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(output_path, dpi=120, bbox_inches="tight"); plt.close(fig)


def render_s10_reliability_dice(
    dice_per_seed: dict[str, float], output_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not dice_per_seed:
        fig, ax = plt.subplots(figsize=(8, 3))
        ax.text(0.5, 0.5, "Spatial Dice not computed", ha="center", va="center")
        ax.axis("off")
        fig.savefig(output_path, dpi=120, bbox_inches="tight"); plt.close(fig)
        return
    labels = list(dice_per_seed.keys())
    vals = [dice_per_seed[k] for k in labels]
    fig, ax = plt.subplots(figsize=(max(6, len(labels) * 0.3 + 2), 4))
    ax.bar(labels, vals, color="#ff5500", alpha=0.85)
    ax.set_ylabel("Spatial Dice")
    ax.set_xlabel("Seed")
    ax.set_title("Cross-session spatial Dice (Kaptan 2023 reliability metric)")
    ax.axhline(0.7, ls="--", color="#888", lw=0.6, label="0.7 threshold")
    ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=0.3)
    plt.setp(ax.get_xticklabels(), rotation=90)
    fig.tight_layout()
    fig.savefig(output_path, dpi=120, bbox_inches="tight"); plt.close(fig)
