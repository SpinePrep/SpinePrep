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
