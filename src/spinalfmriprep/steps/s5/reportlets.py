"""S5 reportlet rendering — CoSpine (Sci Data 2025) effectiveness metrics.

Two reportlets per run, both quantitative and per-slice:

1. ``slice_displacement`` — per-Z anteroposterior (Y-axis) cord-centerline
   displacement (mm) of the EPI cord vs the anat reference cord, Before
   and After distortion correction. Matches CoSpine Figure 3 / Methods
   §"Slice-by-slice Y-axis displacement". A perfectly corrected cord
   sits exactly on the anat centerline; remaining displacement is
   residual distortion (motion having already been removed in S4).
2. ``cord_dice_per_slice`` — per-Z 2D Dice between the EPI cord seg and
   the anat reference cord seg, Before and After. Matches CoSpine
   §"Spinal cord DSC". The 3D pooled Dice is also reported in the title.

Inputs are all in shared BOLD voxel geometry (S5 distortion correction
is in-grid). The anat reference is the S2 cord_dseg resampled into
BOLD space via FLIRT ``-applyxfm -usesqform`` with nearest-neighbour
interpolation (binary preserved). The EPI cord segs are computed by
``sct_deepseg_sc -c t2s`` on the mean BOLD (Before and After).

Both reportlets render a black-background figure with two panels:
left = per-slice trace (Z on Y-axis, metric on X-axis), right = summary
bar with mean ± SD across slices. Titles encode the distortion-
correction mode and the Δ (After − Before) summary.

When metrics cannot be computed (no anat reference, deepseg failure),
the renderers emit a placeholder figure explaining why; they never
raise.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


# ---------------------------------------------------------------------------
# Common helpers
# ---------------------------------------------------------------------------

_COLOR_BEFORE = "#888888"
_COLOR_AFTER = "#0086e6"


def _safe_mean(arr: Optional[np.ndarray]) -> Optional[float]:
    if arr is None:
        return None
    a = np.asarray(arr, dtype=float)
    if a.size == 0:
        return None
    finite = a[np.isfinite(a)]
    if finite.size == 0:
        return None
    return float(finite.mean())


def _safe_std(arr: Optional[np.ndarray]) -> Optional[float]:
    if arr is None:
        return None
    a = np.asarray(arr, dtype=float)
    finite = a[np.isfinite(a)]
    if finite.size < 2:
        return 0.0
    return float(finite.std(ddof=0))


def _placeholder(
    output_path: Path, title: str, reason: str
) -> None:
    """Emit a black placeholder PNG when metrics are unavailable."""
    fig, ax = plt.subplots(figsize=(9, 5), facecolor="black")
    ax.set_facecolor("black")
    ax.axis("off")
    ax.text(0.5, 0.55, title, ha="center", va="center",
            color="white", fontsize=13, fontweight="bold")
    ax.text(0.5, 0.40, reason, ha="center", va="center",
            color="#cccccc", fontsize=10, wrap=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=120, facecolor="black", bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Reportlet 1: slice_displacement
# ---------------------------------------------------------------------------

def render_s5_slice_displacement(
    metrics: dict[str, Any], output_path: Path, mode: str,
) -> None:
    """Render per-Z A–P cord-centerline displacement, Before vs After.

    ``metrics`` should carry:
      - ``per_slice_z``                : list[int]   (Z indices scored)
      - ``displacement_before_mm``     : list[float]
      - ``displacement_after_mm``      : list[float]
      - ``displacement_mean_before_mm``: float
      - ``displacement_mean_after_mm`` : float
      - ``displacement_delta_mm``      : float  (after − before)

    Missing keys → placeholder figure (never raises).
    """
    z = metrics.get("per_slice_z")
    db = metrics.get("displacement_before_mm")
    da = metrics.get("displacement_after_mm")
    if not z or db is None or da is None:
        reason = metrics.get("displacement_reason") or (
            "Cord A–P displacement not computed — anat reference unavailable.")
        _placeholder(output_path,
                     f"S5 slice-displacement — mode={mode}", reason)
        return

    z = np.asarray(z, dtype=int)
    db = np.asarray(db, dtype=float)
    da = np.asarray(da, dtype=float)
    mean_b = metrics.get("displacement_mean_before_mm")
    mean_a = metrics.get("displacement_mean_after_mm")
    delta = metrics.get("displacement_delta_mm")
    if mean_b is None:
        mean_b = _safe_mean(db)
    if mean_a is None:
        mean_a = _safe_mean(da)
    if delta is None and mean_b is not None and mean_a is not None:
        delta = mean_a - mean_b

    fig, axes = plt.subplots(
        1, 2, figsize=(11, 6),
        gridspec_kw={"width_ratios": [3, 1]},
        facecolor="black",
    )

    # Left: per-slice trace (Z on Y, displacement on X)
    ax = axes[0]
    ax.set_facecolor("black")
    ax.plot(db, z, "o-", color=_COLOR_BEFORE, label="Before",
            markersize=4, linewidth=1.4, alpha=0.95)
    ax.plot(da, z, "o-", color=_COLOR_AFTER, label="After",
            markersize=4, linewidth=1.6, alpha=0.95)
    ax.axvline(0.0, color="#444444", linestyle="--", linewidth=0.8)
    ax.set_xlabel("|cord A–P offset vs anat| (mm)", color="white")
    ax.set_ylabel("Z slice (BOLD)", color="white")
    ax.tick_params(colors="white")
    for spine in ax.spines.values():
        spine.set_color("#666666")
    ax.grid(alpha=0.2, color="#555555")
    leg = ax.legend(loc="best", facecolor="#222222", edgecolor="#444444",
                    labelcolor="white", framealpha=0.9)
    for t in leg.get_texts():
        t.set_color("white")

    # Right: summary bars
    ax = axes[1]
    ax.set_facecolor("black")
    xs = ["Before", "After"]
    ys = [mean_b if mean_b is not None else 0.0,
          mean_a if mean_a is not None else 0.0]
    es = [_safe_std(db) or 0.0, _safe_std(da) or 0.0]
    bars = ax.bar(xs, ys, yerr=es, color=[_COLOR_BEFORE, _COLOR_AFTER],
                  ecolor="#bbbbbb", capsize=4)
    for b, val in zip(bars, ys):
        ax.text(b.get_x() + b.get_width() / 2, val,
                f"{val:.2f}", ha="center", va="bottom",
                color="white", fontsize=10)
    ax.set_ylabel("mean displacement (mm)", color="white")
    ax.tick_params(colors="white")
    for spine in ax.spines.values():
        spine.set_color("#666666")
    ax.grid(alpha=0.2, color="#555555", axis="y")

    delta_str = f"{delta:+.2f}" if delta is not None else "n/a"
    fig.suptitle(
        f"Cord A–P displacement vs anat — mode={mode}, "
        f"Δmean = {delta_str} mm",
        color="white", fontsize=13,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=120, facecolor="black", bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Reportlet 2: cord_dice_per_slice
# ---------------------------------------------------------------------------

def render_s5_cord_dice_per_slice(
    metrics: dict[str, Any], output_path: Path, mode: str,
) -> None:
    """Render per-Z 2D Dice (EPI ∩ anat), Before vs After.

    ``metrics`` should carry:
      - ``per_slice_z``           : list[int]
      - ``dice_per_slice_before`` : list[float]
      - ``dice_per_slice_after``  : list[float]
      - ``dice_mean_before`` / ``dice_mean_after`` : float
      - ``dice_3d_before``   / ``dice_3d_after``   : float
      - ``dice_delta``                              : float

    Missing keys → placeholder figure.
    """
    z = metrics.get("per_slice_z")
    db = metrics.get("dice_per_slice_before")
    da = metrics.get("dice_per_slice_after")
    if not z or db is None or da is None:
        reason = metrics.get("dice_reason") or (
            "Cord Dice not computed — anat reference or EPI cord seg "
            "unavailable.")
        _placeholder(output_path,
                     f"S5 cord-Dice — mode={mode}", reason)
        return

    z = np.asarray(z, dtype=int)
    db = np.asarray(db, dtype=float)
    da = np.asarray(da, dtype=float)
    mean_b = metrics.get("dice_mean_before")
    mean_a = metrics.get("dice_mean_after")
    d3b = metrics.get("dice_3d_before")
    d3a = metrics.get("dice_3d_after")
    delta = metrics.get("dice_delta")
    if mean_b is None:
        mean_b = _safe_mean(db)
    if mean_a is None:
        mean_a = _safe_mean(da)
    if delta is None and mean_b is not None and mean_a is not None:
        delta = mean_a - mean_b

    fig, axes = plt.subplots(
        1, 2, figsize=(11, 6),
        gridspec_kw={"width_ratios": [3, 1]},
        facecolor="black",
    )

    ax = axes[0]
    ax.set_facecolor("black")
    ax.plot(db, z, "o-", color=_COLOR_BEFORE, label="Before",
            markersize=4, linewidth=1.4, alpha=0.95)
    ax.plot(da, z, "o-", color=_COLOR_AFTER, label="After",
            markersize=4, linewidth=1.6, alpha=0.95)
    ax.axvline(1.0, color="#444444", linestyle="--", linewidth=0.8)
    ax.set_xlim(0.0, 1.05)
    ax.set_xlabel("2D Dice (EPI cord ∩ anat cord)", color="white")
    ax.set_ylabel("Z slice (BOLD)", color="white")
    ax.tick_params(colors="white")
    for spine in ax.spines.values():
        spine.set_color("#666666")
    ax.grid(alpha=0.2, color="#555555")
    leg = ax.legend(loc="best", facecolor="#222222", edgecolor="#444444",
                    labelcolor="white", framealpha=0.9)
    for t in leg.get_texts():
        t.set_color("white")

    ax = axes[1]
    ax.set_facecolor("black")
    xs = ["Before", "After"]
    ys = [mean_b if mean_b is not None else 0.0,
          mean_a if mean_a is not None else 0.0]
    es = [_safe_std(db) or 0.0, _safe_std(da) or 0.0]
    bars = ax.bar(xs, ys, yerr=es, color=[_COLOR_BEFORE, _COLOR_AFTER],
                  ecolor="#bbbbbb", capsize=4)
    for b, val in zip(bars, ys):
        ax.text(b.get_x() + b.get_width() / 2, val,
                f"{val:.2f}", ha="center", va="bottom",
                color="white", fontsize=10)
    ax.set_ylim(0.0, 1.05)
    ax.set_ylabel("mean Dice", color="white")
    ax.tick_params(colors="white")
    for spine in ax.spines.values():
        spine.set_color("#666666")
    ax.grid(alpha=0.2, color="#555555", axis="y")

    delta_str = f"{delta:+.3f}" if delta is not None else "n/a"
    d3_str = ""
    if d3b is not None and d3a is not None:
        d3_str = f"  •  3D Dice: {d3b:.2f} → {d3a:.2f}"
    fig.suptitle(
        f"Cord Dice (EPI ∩ anat) — mode={mode}, "
        f"Δmean = {delta_str}{d3_str}",
        color="white", fontsize=13,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=120, facecolor="black", bbox_inches="tight")
    plt.close(fig)
