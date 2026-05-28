"""S10 reportlet rendering — chain-wide visual standard (dark theme).

Three per-run reportlets + one per-subject reliability reportlet:

1. ``hemicord_timeseries`` — per-ROI timeseries grid, one curve per
   hemicord×segment ROI. Visual sanity for the extracted signals.
2. ``hemicord_connectivity`` — Fisher-z ROI×ROI heatmap, ROIs
   grouped by hemicord (VL/VR/DL/DR) so the 4-block structure is
   visible; column dividers between blocks.
3. ``reliability_icc`` — per-connection cross-session agreement bars
   with Cicchetti band lines. Fires only when subject has ≥2 sessions
   (Kaptan 2023 cord reliability standard).

DROPPED 2026-05-28:
- ``vertlvl_tsnr`` — duplicated S9's tsnr_per_level (same input + plot).

Audit reference: ``.claude/specs/s10-reportlet-set-audit.md``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


# Visual-standard palette (mirrors reportlets_common to stay self-contained)
BG = "#0f1115"
TEXT = "#e6e8ec"
BORDER = "#374151"

_STATUS = {
    "PASS": ("#14532d", "#22c55e"),
    "WARN": ("#3a2f00", "#f59e0b"),
    "FAIL": ("#3a1010", "#ef4444"),
}

# Per-hemicord color (ventral-left, ventral-right, dorsal-left, dorsal-right)
_HEMICORD_COLORS = {
    "VL": "#22c55e",
    "VR": "#7dcfff",
    "DL": "#f59e0b",
    "DR": "#c084fc",
}


def _setup_dark_axes(ax) -> None:
    ax.set_facecolor(BG)
    ax.tick_params(colors=TEXT, labelsize=8)
    for s in ax.spines.values():
        s.set_color(BORDER)


def _draw_header(fig, title: str, subtitle: str = "", status: str = "PASS") -> None:
    """Title + subtitle on the left, status pill on the right."""
    fig.text(0.02, 0.965, title,
             color=TEXT, fontsize=14, fontweight="bold",
             ha="left", va="top")
    if subtitle:
        fig.text(0.02, 0.93, subtitle,
                 color="#9ca3af", fontsize=10, family="monospace",
                 ha="left", va="top")
    fc, tc = _STATUS.get(status, _STATUS["WARN"])
    fig.patches.append(
        mpatches.Rectangle(
            (0.93, 0.94), 0.055, 0.04, transform=fig.transFigure,
            facecolor=fc, edgecolor="none", zorder=2,
        )
    )
    fig.text(0.957, 0.96, status,
             color=tc, fontsize=12, fontweight="bold",
             ha="center", va="center", family="monospace")


def _sort_by_hemicord(labels: list[str]) -> list[int]:
    """Return label indices reordered as VL_* → VR_* → DL_* → DR_* → other.

    Each block is internally sorted by segment label (segC2, segC3, …).
    """
    blocks = {"VL": [], "VR": [], "DL": [], "DR": [], "other": []}
    for i, lab in enumerate(labels):
        prefix = lab[:2] if len(lab) >= 2 else "?"
        bucket = "other"
        if prefix in blocks:
            bucket = prefix
        blocks[bucket].append((lab, i))
    order: list[int] = []
    for key in ("VL", "VR", "DL", "DR", "other"):
        for _, i in sorted(blocks[key]):
            order.append(i)
    return order


def _block_boundaries(labels: list[str]) -> list[int]:
    """Indices where the hemicord prefix changes (for divider lines)."""
    out: list[int] = []
    prev = None
    for i, lab in enumerate(labels):
        prefix = lab[:2] if len(lab) >= 2 else "?"
        if prev is not None and prefix != prev:
            out.append(i)
        prev = prefix
    return out


# ---------------------------------------------------------------------------
# Reportlet 1: hemicord_timeseries
# ---------------------------------------------------------------------------


def render_s10_hemicord_timeseries(
    ts_df: pd.DataFrame, output_path: Path,
    status: str = "PASS",
) -> None:
    """One panel per hemicord×segment ROI, color-coded by hemicord."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cols = list(ts_df.columns)
    n = len(cols)
    if n == 0:
        fig, ax = plt.subplots(figsize=(10, 4), facecolor=BG)
        _draw_header(fig, "S10 — Hemicord×segment timeseries",
                     "no ROIs extracted", "WARN")
        ax.set_facecolor(BG); ax.axis("off")
        fig.savefig(output_path, dpi=120, facecolor=BG, bbox_inches="tight")
        plt.close(fig)
        return

    # Reorder by hemicord block
    order = _sort_by_hemicord(cols)
    cols_ordered = [cols[i] for i in order]

    n_cols = 4
    rows = int(np.ceil(len(cols_ordered) / n_cols))
    fig = plt.figure(figsize=(14, 1.6 * rows + 1.2), facecolor=BG)
    _draw_header(fig, "S10 — Hemicord×segment timeseries (s8-regressed)",
                 f"{n} ROIs, ordered by hemicord (VL/VR/DL/DR)", status)

    grid_x0, grid_y0 = 0.05, 0.06
    grid_w, grid_h = 0.92, 0.80
    cell_w = grid_w / n_cols
    cell_h = grid_h / rows
    # Global y range so panels share scale
    all_vals = ts_df[cols_ordered].to_numpy()
    finite = all_vals[np.isfinite(all_vals)]
    ymin, ymax = (np.percentile(finite, 1), np.percentile(finite, 99)) if finite.size else (-1, 1)

    for i, c in enumerate(cols_ordered):
        r = i // n_cols
        col = i % n_cols
        ax = fig.add_axes((
            grid_x0 + col * cell_w + cell_w * 0.04,
            grid_y0 + (rows - 1 - r) * cell_h + cell_h * 0.18,
            cell_w * 0.92, cell_h * 0.72,
        ))
        _setup_dark_axes(ax)
        prefix = c[:2] if len(c) >= 2 else "?"
        color = _HEMICORD_COLORS.get(prefix, "#9ca3af")
        ax.plot(ts_df[c].to_numpy(), color=color, lw=0.6)
        ax.set_ylim(ymin, ymax)
        ax.set_title(c, color=TEXT, fontsize=8, fontweight="bold", pad=2)
        ax.tick_params(labelsize=6)
        ax.grid(alpha=0.10, color=BORDER)
        ax.set_axisbelow(True)

    fig.savefig(output_path, dpi=120, facecolor=BG, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Reportlet 2: hemicord_connectivity (Fisher-z heatmap, reordered)
# ---------------------------------------------------------------------------


def render_s10_hemicord_connectivity(
    mat: pd.DataFrame, output_path: Path,
    title: str = "Connectivity (Fisher-z)",
    vmin: float = -1.0, vmax: float = 1.0,
    status: str = "PASS",
    condition_number: Optional[float] = None,
    fc_mean_strength: Optional[float] = None,
    pct_significant: Optional[float] = None,
) -> None:
    """ROI×ROI Fisher-z heatmap, ROIs grouped by hemicord with dividers."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    labels = list(mat.columns)
    order = _sort_by_hemicord(labels)
    ord_labels = [labels[i] for i in order]
    arr = mat.iloc[order, order].to_numpy()
    n = len(ord_labels)

    subtitle_parts = []
    if fc_mean_strength is not None and np.isfinite(fc_mean_strength):
        subtitle_parts.append(f"mean |r| = {fc_mean_strength:.2f}")
    if pct_significant is not None and np.isfinite(pct_significant):
        subtitle_parts.append(f"|r|>0.1 = {pct_significant:.0%}")
    if condition_number is not None and np.isfinite(condition_number):
        subtitle_parts.append(f"CN = {condition_number:.0f}")
    subtitle = "  ·  ".join(subtitle_parts) if subtitle_parts else ""

    fig = plt.figure(figsize=(9, 8), facecolor=BG)
    _draw_header(fig, f"S10 — {title}", subtitle, status)
    ax = fig.add_axes((0.12, 0.07, 0.74, 0.80))
    _setup_dark_axes(ax)

    im = ax.imshow(arr, cmap="RdBu_r", vmin=vmin, vmax=vmax,
                   interpolation="nearest")

    # Hemicord block dividers
    for b in _block_boundaries(ord_labels):
        ax.axvline(b - 0.5, color=TEXT, linewidth=0.7, alpha=0.6)
        ax.axhline(b - 0.5, color=TEXT, linewidth=0.7, alpha=0.6)

    step = max(1, n // 30)
    tick_idx = list(range(0, n, step))
    ax.set_xticks(tick_idx)
    ax.set_yticks(tick_idx)
    ax.set_xticklabels([ord_labels[i] for i in tick_idx],
                       rotation=90, fontsize=7, color=TEXT)
    ax.set_yticklabels([ord_labels[i] for i in tick_idx],
                       fontsize=7, color=TEXT)

    cax = fig.add_axes((0.88, 0.20, 0.022, 0.50))
    cb = fig.colorbar(im, cax=cax)
    cb.set_label("Fisher-z", color=TEXT, fontsize=9)
    cb.ax.tick_params(colors=TEXT, labelsize=8)
    cb.outline.set_edgecolor(BORDER)

    fig.savefig(output_path, dpi=120, facecolor=BG, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Reportlet 3: reliability_icc (per-subject, multi-session)
# ---------------------------------------------------------------------------


def render_s10_reliability_icc(
    per_connection: list[dict[str, Any]],
    cicchetti_bands: dict,
    output_path: Path,
    status: str = "PASS",
    n_sessions: Optional[int] = None,
    pooled_icc: Optional[float] = None,
) -> None:
    """Per-connection cross-session agreement bars with Cicchetti bands.

    Bars are sorted descending and color-coded by Cicchetti band:
      excellent (> good): green
      good     (fair < r ≤ good): blue-green
      fair     (poor < r ≤ fair): amber
      poor     (≤ poor): red

    Kaptan 2023 reliability convention for cord rs-fMRI.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not per_connection:
        fig, ax = plt.subplots(figsize=(10, 4), facecolor=BG)
        _draw_header(fig, "S10 — Reliability (ICC across sessions)",
                     "single-session subject — reliability N/A",
                     "PASS")
        ax.set_facecolor(BG); ax.axis("off")
        ax.text(0.5, 0.5,
                "Multi-session reliability not applicable for this subject",
                transform=ax.transAxes, ha="center", va="center",
                color="#9ca3af", fontsize=11)
        fig.savefig(output_path, dpi=120, facecolor=BG, bbox_inches="tight")
        plt.close(fig)
        return

    df = pd.DataFrame(per_connection)
    if "icc" not in df.columns or df["icc"].dropna().empty:
        fig, ax = plt.subplots(figsize=(10, 4), facecolor=BG)
        _draw_header(fig, "S10 — Reliability (ICC across sessions)",
                     "no ICC values computed", "WARN")
        ax.set_facecolor(BG); ax.axis("off")
        fig.savefig(output_path, dpi=120, facecolor=BG, bbox_inches="tight")
        plt.close(fig)
        return

    poor_max = float(cicchetti_bands.get("poor", 0.40))
    fair_max = float(cicchetti_bands.get("fair", 0.59))
    good_max = float(cicchetti_bands.get("good", 0.74))

    df_sorted = df.sort_values("icc", ascending=False).reset_index(drop=True)
    vals = df_sorted["icc"].fillna(0).to_numpy()

    def _band_color(v):
        if v > good_max: return "#22c55e"
        if v > fair_max: return "#7dcfff"
        if v > poor_max: return "#f59e0b"
        return "#ef4444"
    colors = [_band_color(v) for v in vals]

    n_excellent = int((vals > good_max).sum())
    n_good = int(((vals > fair_max) & (vals <= good_max)).sum())
    n_fair = int(((vals > poor_max) & (vals <= fair_max)).sum())
    n_poor = int((vals <= poor_max).sum())

    subtitle_parts = []
    if n_sessions is not None:
        subtitle_parts.append(f"{n_sessions} sessions")
    if pooled_icc is not None and np.isfinite(pooled_icc):
        subtitle_parts.append(f"pooled ICC = {pooled_icc:.2f}")
    subtitle_parts.append(
        f"{n_excellent}E / {n_good}G / {n_fair}F / {n_poor}P"
    )
    subtitle = "  ·  ".join(subtitle_parts)

    fig = plt.figure(figsize=(11, 5), facecolor=BG)
    _draw_header(fig, "S10 — Reliability (ICC across sessions)",
                 subtitle, status)
    ax = fig.add_axes((0.07, 0.13, 0.90, 0.72))
    _setup_dark_axes(ax)

    ax.bar(range(len(vals)), vals, color=colors,
           edgecolor=BORDER, linewidth=0.3)
    # Cicchetti band lines
    for thr, label, color in (
        (good_max, "good",  "#22c55e"),
        (fair_max, "fair",  "#7dcfff"),
        (poor_max, "poor",  "#ef4444"),
    ):
        ax.axhline(thr, ls="--", color=color, lw=0.7,
                   label=f"{label} = {thr:.2f}")

    ax.set_xlabel("Connection (sorted by ICC)", color=TEXT, fontsize=10)
    ax.set_ylabel("ICC (cross-session)", color=TEXT, fontsize=10)
    ax.set_ylim(-0.2, 1.0)
    leg = ax.legend(loc="upper right", fontsize=8, facecolor="#1a1d23",
                    edgecolor=BORDER, labelcolor=TEXT)
    for t in leg.get_texts():
        t.set_color(TEXT)
    ax.grid(axis="y", alpha=0.15, color=BORDER)
    ax.set_axisbelow(True)

    fig.savefig(output_path, dpi=120, facecolor=BG, bbox_inches="tight")
    plt.close(fig)
