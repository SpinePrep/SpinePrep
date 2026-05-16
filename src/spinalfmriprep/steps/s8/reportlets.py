"""S8 reportlet rendering — 5 PNGs per run."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def render_s8_confound_columns(
    family_counts: dict[str, int], sidecar: dict[str, Any], output_path: Path,
) -> None:
    """Bar of column counts per family + total."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    families = ["motion", "outliers", "csf", "retroicor", "cosine", "spinalcompcor"]
    counts = [family_counts.get(f, 0) for f in families]
    total = sum(counts)
    fig, ax = plt.subplots(figsize=(8, 4))
    colors = ["#4477aa", "#cc6677", "#33aa77", "#ee8866", "#aaaaaa", "#bb55bb"]
    bars = ax.bar(families, counts, color=colors)
    for bar, c in zip(bars, counts):
        ax.text(bar.get_x() + bar.get_width() / 2, c + 0.5, str(c),
                ha="center", fontsize=10)
    ax.set_ylabel("Columns")
    ax.set_title(f"Confound regressor count by family (total = {total})")
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(output_path, dpi=120, bbox_inches="tight")
    plt.close(fig)


def render_s8_fd_dvars_outliers(
    fd: Optional[np.ndarray], dvars: Optional[np.ndarray],
    refrms: Optional[np.ndarray], n_outliers: int,
    output_path: Path,
) -> None:
    """FD + DVARS + refRMS time series, outlier frames highlighted."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(3, 1, figsize=(10, 6), sharex=True)
    for ax, vec, label, color in zip(
        axes,
        [fd, dvars, refrms],
        ["Framewise Displacement (mm)", "DVARS", "refRMS"],
        ["#0086e6", "#cc2222", "#dd8800"],
    ):
        if vec is None:
            ax.text(0.5, 0.5, "n/a", transform=ax.transAxes, ha="center")
            ax.set_ylabel(label)
            continue
        ax.plot(np.arange(vec.size), vec, color=color, lw=0.8)
        if vec is fd:
            ax.axhline(0.2, ls="--", color="#888", lw=0.6, label="0.2 mm")
            ax.legend(fontsize=7)
        elif vec is dvars or vec is refrms:
            mu = float(np.mean(vec)); sd = float(np.std(vec))
            ax.axhline(mu + 3 * sd, ls="--", color="#888", lw=0.6, label="μ + 3σ")
            ax.legend(fontsize=7)
        ax.set_ylabel(label, fontsize=9)
        ax.grid(alpha=0.3)
    axes[-1].set_xlabel("Volume")
    fig.suptitle(f"Motion + outliers ({n_outliers} flagged)", fontsize=11)
    fig.tight_layout()
    fig.savefig(output_path, dpi=120, bbox_inches="tight")
    plt.close(fig)


def render_s8_csf_variance(
    csf_meta: dict[str, Any], output_path: Path,
) -> None:
    """Per-slice CSF voxel count + which slices were kept."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    counts = csf_meta.get("slice_voxel_counts", []) or []
    skipped = set(csf_meta.get("skipped_slices", []) or [])
    if not counts:
        fig, ax = plt.subplots(figsize=(8, 3))
        ax.text(0.5, 0.5, "No CSF mask available", ha="center", va="center")
        ax.axis("off")
        fig.savefig(output_path, dpi=120, bbox_inches="tight")
        plt.close(fig)
        return
    n = len(counts)
    colors = ["#cc2222" if z in skipped else "#33aa77" for z in range(n)]
    fig, ax = plt.subplots(figsize=(10, 3.5))
    ax.bar(range(n), counts, color=colors)
    ax.axhline(5, ls="--", color="#888", lw=0.6, label="min 5 vox")
    ax.set_xlabel("Slice (Z index)")
    ax.set_ylabel("CSF voxels (eroded mask)")
    ax.set_title(f"CSF voxel count per slice — kept (green) / skipped (red): "
                 f"{n - len(skipped)} / {n}")
    ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(output_path, dpi=120, bbox_inches="tight")
    plt.close(fig)


def render_s8_pnm_peaks(
    work_dir: Path, physio_present: bool, output_path: Path,
) -> None:
    """Cardiac peaks (from popp_card.txt) + respiratory phase (from
    popp_resp.txt, 2-col time/phase) on a shared time axis.

    FSL popp output convention:
      popp_card.txt — cardiac peak times (one per line, seconds)
      popp_resp.txt — per-sample respiratory phase (time, phase) cols
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not physio_present:
        fig, ax = plt.subplots(figsize=(8, 3))
        ax.text(0.5, 0.5, "No BIDS physio for this run — RETROICOR skipped",
                ha="center", va="center")
        ax.axis("off")
        fig.savefig(output_path, dpi=120, bbox_inches="tight")
        plt.close(fig)
        return
    pnm = work_dir / "pnm"
    card_path = pnm / "popp_card.txt"
    resp_path = pnm / "popp_resp.txt"

    fig, axes = plt.subplots(2, 1, figsize=(10, 4), sharex=True)

    # Cardiac: peak times as vertical ticks
    ax = axes[0]
    if card_path.exists():
        try:
            card_times = np.loadtxt(card_path)
            if card_times.size > 1:
                bpm = 60.0 / float(np.median(np.diff(card_times)))
                ax.vlines(card_times, 0, 1, color="#cc2222", lw=0.4)
                ax.set_ylabel(f"Cardiac peaks\n({card_times.size} peaks, ~{bpm:.0f} bpm)",
                              fontsize=9)
            else:
                ax.text(0.5, 0.5, "Cardiac: <2 peaks detected",
                        transform=ax.transAxes, ha="center")
        except Exception as e:
            ax.text(0.5, 0.5, f"cardiac load failed: {e}",
                    transform=ax.transAxes, ha="center")
    else:
        ax.text(0.5, 0.5, "popp_card.txt missing", transform=ax.transAxes, ha="center")
    ax.set_yticks([])
    ax.grid(axis="x", alpha=0.3)

    # Respiratory: plot phase trace
    ax = axes[1]
    if resp_path.exists():
        try:
            arr = np.loadtxt(resp_path)
            if arr.ndim == 2 and arr.shape[1] == 2:
                t = arr[:, 0]; ph = arr[:, 1]
            else:
                t = np.arange(arr.size) * 0.0025  # 400Hz default
                ph = arr
            # Detect respiratory cycles via phase wraps (phase resets ~every breath)
            from scipy.signal import find_peaks
            # Phase is unwrapped (monotonically increasing-ish); wrap-modulo for cycle detection
            phw = np.mod(ph + np.pi, 2 * np.pi) - np.pi
            n_breaths = int(((np.diff(phw) < -np.pi).sum()))
            duration_s = float(t[-1] - t[0]) if t.size > 1 else 1.0
            cpm = 60.0 * n_breaths / max(duration_s, 1e-6)
            ax.plot(t, phw, color="#0086e6", lw=0.3)
            ax.set_ylabel(f"Respiratory phase\n(~{cpm:.0f} cpm)", fontsize=9)
        except Exception as e:
            ax.text(0.5, 0.5, f"respiratory load failed: {e}",
                    transform=ax.transAxes, ha="center")
    else:
        ax.text(0.5, 0.5, "popp_resp.txt missing", transform=ax.transAxes, ha="center")
    ax.grid(axis="x", alpha=0.3)
    axes[-1].set_xlabel("Time (s)")
    fig.suptitle("FSL PNM physio: cardiac peaks + respiratory phase", fontsize=11)
    fig.tight_layout()
    fig.savefig(output_path, dpi=120, bbox_inches="tight")
    plt.close(fig)


def render_s8_correlation_heatmap(
    df, output_path: Path, max_cols: int = 80,
) -> None:
    """Pearson correlation heatmap across the confound matrix.

    For large matrices (>80 cols), downsample column sampling to keep
    the figure legible.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if df is None or df.empty or df.shape[1] < 2:
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.text(0.5, 0.5, "Insufficient columns for correlation",
                ha="center", va="center")
        ax.axis("off")
        fig.savefig(output_path, dpi=120, bbox_inches="tight")
        plt.close(fig)
        return
    cols = list(df.columns)
    if len(cols) > max_cols:
        idx = np.linspace(0, len(cols) - 1, max_cols).astype(int)
        cols = [cols[i] for i in idx]
    arr = df[cols].to_numpy(dtype=np.float64)
    # Mask zero-variance columns
    sd = arr.std(axis=0)
    keep = sd > 1e-12
    arr = arr[:, keep]
    cols = [c for c, k in zip(cols, keep) if k]
    if arr.shape[1] < 2:
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.text(0.5, 0.5, "Insufficient non-zero columns",
                ha="center", va="center")
        ax.axis("off")
        fig.savefig(output_path, dpi=120, bbox_inches="tight")
        plt.close(fig)
        return
    arr_z = (arr - arr.mean(axis=0)) / arr.std(axis=0)
    corr = (arr_z.T @ arr_z) / max(arr_z.shape[0] - 1, 1)
    fig, ax = plt.subplots(figsize=(8, 7))
    im = ax.imshow(corr, cmap="RdBu_r", vmin=-1, vmax=1, interpolation="nearest")
    fig.colorbar(im, ax=ax, shrink=0.7, label="Pearson r")
    ax.set_title(f"Confound correlation ({len(cols)} cols shown)", fontsize=11)
    if len(cols) <= 40:
        ax.set_xticks(range(len(cols)))
        ax.set_yticks(range(len(cols)))
        ax.set_xticklabels(cols, rotation=90, fontsize=6)
        ax.set_yticklabels(cols, fontsize=6)
    else:
        ax.set_xticks([]); ax.set_yticks([])
    fig.tight_layout()
    fig.savefig(output_path, dpi=120, bbox_inches="tight")
    plt.close(fig)
