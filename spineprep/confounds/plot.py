"""Motion QC plotting: create multi-panel PNG with trans/rot/FD/DVARS."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


def plot_motion_png(
    png_path: Path | str,
    motion_params: np.ndarray,
    fd: np.ndarray,
    dvars: np.ndarray,
) -> None:
    """
    Create a multi-panel motion QC plot.

    Generates a 4-panel figure:
    - Panel 1: Translations (x, y, z)
    - Panel 2: Rotations (x, y, z)
    - Panel 3: Framewise Displacement (FD)
    - Panel 4: DVARS

    Args:
        png_path: Output PNG file path
        motion_params: Array of shape (n_timepoints, 6)
        fd: Framewise displacement array (n_timepoints,)
        dvars: DVARS array (n_timepoints,)
    """
    png_path = Path(png_path)
    png_path.parent.mkdir(parents=True, exist_ok=True)

    n_timepoints = len(fd)
    timepoints = np.arange(n_timepoints)

    # Create figure with 4 subplots
    fig, axes = plt.subplots(4, 1, figsize=(10, 8), sharex=True)

    # Panel 1: Translations
    axes[0].plot(timepoints, motion_params[:, 0], label="X", linewidth=1.5, alpha=0.8)
    axes[0].plot(timepoints, motion_params[:, 1], label="Y", linewidth=1.5, alpha=0.8)
    axes[0].plot(timepoints, motion_params[:, 2], label="Z", linewidth=1.5, alpha=0.8)
    axes[0].set_ylabel("Translation (mm)")
    axes[0].set_title("Motion Parameters")
    axes[0].legend(loc="upper right", framealpha=0.9)
    axes[0].grid(True, alpha=0.3)

    # Panel 2: Rotations (convert radians to degrees for display)
    axes[1].plot(
        timepoints,
        np.rad2deg(motion_params[:, 3]),
        label="X (pitch)",
        linewidth=1.5,
        alpha=0.8,
    )
    axes[1].plot(
        timepoints,
        np.rad2deg(motion_params[:, 4]),
        label="Y (roll)",
        linewidth=1.5,
        alpha=0.8,
    )
    axes[1].plot(
        timepoints,
        np.rad2deg(motion_params[:, 5]),
        label="Z (yaw)",
        linewidth=1.5,
        alpha=0.8,
    )
    axes[1].set_ylabel("Rotation (degrees)")
    axes[1].legend(loc="upper right", framealpha=0.9)
    axes[1].grid(True, alpha=0.3)

    # Panel 3: Framewise Displacement
    axes[2].plot(timepoints, fd, linewidth=1.5, color="red", alpha=0.8)
    axes[2].axhline(y=0.5, color="orange", linestyle="--", linewidth=1, alpha=0.6)
    axes[2].set_ylabel("FD (mm)")
    axes[2].grid(True, alpha=0.3)

    # Panel 4: DVARS
    axes[3].plot(timepoints, dvars, linewidth=1.5, color="purple", alpha=0.8)
    axes[3].set_ylabel("DVARS")
    axes[3].set_xlabel("Timepoint")
    axes[3].grid(True, alpha=0.3)

    # Adjust layout and save
    plt.tight_layout()
    plt.savefig(png_path, dpi=100, bbox_inches="tight")
    plt.close(fig)


def plot_compcor_spectra_png(
    png_path: Path | str,
    acompcor_variance: np.ndarray | None = None,
    tcompcor_variance: np.ndarray | None = None,
) -> None:
    """
    Create CompCor variance explained spectra plot.

    Generates a 2-panel figure showing:
    - Panel 1: Per-component variance explained (bar plot)
    - Panel 2: Cumulative variance explained (line plot)

    Args:
        png_path: Output PNG file path
        acompcor_variance: Optional aCompCor variance explained array (n_components,)
        tcompcor_variance: Optional tCompCor variance explained array (n_components,)
    """
    png_path = Path(png_path)
    png_path.parent.mkdir(parents=True, exist_ok=True)

    # Determine if we have any data to plot
    has_acompcor = acompcor_variance is not None and len(acompcor_variance) > 0
    has_tcompcor = tcompcor_variance is not None and len(tcompcor_variance) > 0

    if not has_acompcor and not has_tcompcor:
        # Nothing to plot, create empty placeholder
        fig, ax = plt.subplots(1, 1, figsize=(8, 4))
        ax.text(
            0.5,
            0.5,
            "No CompCor components available",
            ha="center",
            va="center",
            fontsize=12,
        )
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")
        plt.tight_layout()
        plt.savefig(png_path, dpi=100, bbox_inches="tight")
        plt.close(fig)
        return

    # Create figure with 2 subplots
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))

    # Panel 1: Per-component variance explained (bar plot)
    ax1 = axes[0]
    x_offset = 0

    if has_acompcor:
        n_a = len(acompcor_variance)
        x_a = np.arange(n_a) + x_offset
        ax1.bar(
            x_a,
            acompcor_variance * 100,
            width=0.8,
            label="aCompCor",
            alpha=0.8,
            color="steelblue",
        )
        x_offset += n_a + 1

    if has_tcompcor:
        n_t = len(tcompcor_variance)
        x_t = np.arange(n_t) + x_offset
        ax1.bar(
            x_t,
            tcompcor_variance * 100,
            width=0.8,
            label="tCompCor",
            alpha=0.8,
            color="darkorange",
        )

    ax1.set_xlabel("Component")
    ax1.set_ylabel("Variance Explained (%)")
    ax1.set_title("Per-Component Variance")
    ax1.legend(loc="upper right", framealpha=0.9)
    ax1.grid(True, alpha=0.3, axis="y")

    # Panel 2: Cumulative variance explained (line plot)
    ax2 = axes[1]

    if has_acompcor:
        cumsum_a = np.cumsum(acompcor_variance) * 100
        ax2.plot(
            np.arange(1, len(cumsum_a) + 1),
            cumsum_a,
            marker="o",
            label="aCompCor",
            linewidth=2,
            alpha=0.8,
            color="steelblue",
        )

    if has_tcompcor:
        cumsum_t = np.cumsum(tcompcor_variance) * 100
        ax2.plot(
            np.arange(1, len(cumsum_t) + 1),
            cumsum_t,
            marker="s",
            label="tCompCor",
            linewidth=2,
            alpha=0.8,
            color="darkorange",
        )

    ax2.set_xlabel("Number of Components")
    ax2.set_ylabel("Cumulative Variance (%)")
    ax2.set_title("Cumulative Variance")
    ax2.legend(loc="lower right", framealpha=0.9)
    ax2.grid(True, alpha=0.3)
    ax2.set_ylim(0, 100)

    # Adjust layout and save
    plt.tight_layout()
    plt.savefig(png_path, dpi=100, bbox_inches="tight")
    plt.close(fig)
