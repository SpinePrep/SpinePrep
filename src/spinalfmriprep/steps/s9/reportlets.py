"""S9 reportlet rendering — chain-wide visual standard (dark theme).

4 reportlets per run, matching the field-standard cord-fMRI primary-
derivative QC composition (Kaptan 2023 + CoSpine 2025 + Eippert 2017):

1. ``tsnr_map_axial`` — headline diagnostic: axial montage of the
   smoothed tSNR map with cord-median annotation in the subtitle.
2. ``tsnr_per_level`` — cord-specific signature: per-vertebral-level
   mean ± SD tSNR bars (Kaptan 2023 / CoSpine 2025 Fig 6).
3. ``smoothed_vs_unsmoothed_axial`` — visual confirmation of the
   smoothing operation: pre vs post mean BOLD side-by-side with
   cord contour.
4. ``smoothness_summary`` — measured residual FWHM per axis vs the
   policy tolerance band, color-coded PASS / WARN / FAIL per axis.

Audit reference: ``.claude/specs/s9-reportlet-set-audit.md``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import nibabel as nib
import numpy as np
import pandas as pd


# Visual-standard palette (mirrors reportlets_common to stay self-contained)
BG = "#0f1115"
TEXT = "#e6e8ec"
BORDER = "#374151"
MARKER_YELLOW = "#fbbf24"
EPI_CYAN = "#22d3ee"

_STATUS = {
    "PASS": ("#14532d", "#22c55e"),
    "WARN": ("#3a2f00", "#f59e0b"),
    "FAIL": ("#3a1010", "#ef4444"),
}

_PASS_COLOR = "#22c55e"
_WARN_COLOR = "#f59e0b"
_FAIL_COLOR = "#ef4444"


def _setup_dark_axes(ax) -> None:
    ax.set_facecolor(BG)
    ax.tick_params(colors=TEXT, labelsize=9)
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
    import matplotlib.patches as mpatches
    fig.patches.append(
        mpatches.Rectangle(
            (0.93, 0.94), 0.055, 0.04, transform=fig.transFigure,
            facecolor=fc, edgecolor="none", zorder=2,
        )
    )
    fig.text(0.957, 0.96, status,
             color=tc, fontsize=12, fontweight="bold",
             ha="center", va="center", family="monospace")


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


# ---------------------------------------------------------------------------
# Reportlet 1: tsnr_map_axial
# ---------------------------------------------------------------------------


def render_s9_tsnr_map_axial(
    tsnr_path: Path, cord_mask: Path, output_path: Path,
    n_slices: int = 9,
    status: str = "PASS",
    median_cord_tsnr: Optional[float] = None,
    tsnr_ratio: Optional[float] = None,
) -> None:
    """9-tile axial smoothed-tSNR map montage with cord contour overlay."""
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

    med = (float(np.median(grid[g_msk])) if g_msk.any()
           else (median_cord_tsnr or float("nan")))
    subtitle_parts = [f"cord median tSNR = {med:.1f}"]
    if tsnr_ratio is not None:
        subtitle_parts.append(f"ratio post/pre = {tsnr_ratio:.2f}×")
    subtitle = "  ·  ".join(subtitle_parts)

    fig = plt.figure(figsize=(10, 9), facecolor=BG)
    _draw_header(fig, "S9 — tSNR map (cord BOLD, smoothed)",
                 subtitle, status)
    ax = fig.add_axes((0.06, 0.06, 0.78, 0.80))
    _setup_dark_axes(ax)
    vmin, vmax = _safe_pct(grid, (2, 98))
    im = ax.imshow(grid, cmap="hot", vmin=vmin, vmax=vmax,
                   interpolation="nearest")
    if g_msk.any():
        ax.contour(g_msk, levels=[0.5], colors=[EPI_CYAN], linewidths=0.7)
    ax.set_xticks([]); ax.set_yticks([])

    cax = fig.add_axes((0.87, 0.20, 0.022, 0.50))
    cb = fig.colorbar(im, cax=cax)
    cb.set_label("tSNR", color=TEXT, fontsize=10)
    cb.ax.tick_params(colors=TEXT, labelsize=8)
    cb.outline.set_edgecolor(BORDER)

    fig.savefig(output_path, dpi=120, facecolor=BG, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Reportlet 2: tsnr_per_level
# ---------------------------------------------------------------------------


def render_s9_tsnr_per_level(
    per_level_tsv: Path, output_path: Path,
    status: str = "PASS",
    pass_threshold: float = 5.0,
    warn_threshold: float = 3.0,
) -> None:
    """Per-vertebral-level mean ± SD tSNR bars (Kaptan 2023 / CoSpine 2025).

    Bars color-coded green (≥pass_threshold) / amber (≥warn) / red
    (<warn) so the user can see at-a-glance which levels need
    extra-careful interpretation.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not per_level_tsv.exists():
        fig, ax = plt.subplots(figsize=(10, 4), facecolor=BG)
        _draw_header(fig, "S9 — tSNR by vertebral level", "no data", "WARN")
        ax.set_facecolor(BG); ax.axis("off")
        ax.text(0.5, 0.5, "per_level_tsnr TSV unavailable",
                transform=ax.transAxes, ha="center", va="center",
                color="#9ca3af")
        fig.savefig(output_path, dpi=120, facecolor=BG, bbox_inches="tight")
        plt.close(fig)
        return

    df = pd.read_csv(per_level_tsv, sep="\t")
    if df.empty:
        fig, ax = plt.subplots(figsize=(10, 4), facecolor=BG)
        _draw_header(fig, "S9 — tSNR by vertebral level",
                     "no PAM50 levels intersect cord in this run", "WARN")
        ax.set_facecolor(BG); ax.axis("off")
        fig.savefig(output_path, dpi=120, facecolor=BG, bbox_inches="tight")
        plt.close(fig)
        return

    x = df["level"].astype(int).to_numpy()
    y = df["mean_tsnr"].astype(float).to_numpy()
    err = df["std_tsnr"].astype(float).to_numpy()
    colors = [
        _PASS_COLOR if v >= pass_threshold
        else _WARN_COLOR if v >= warn_threshold
        else _FAIL_COLOR
        for v in y
    ]

    subtitle = (f"{len(df)} levels  ·  median {np.median(y):.1f}  "
                f"·  PASS ≥ {pass_threshold:.0f}")

    fig = plt.figure(figsize=(10, 4.8), facecolor=BG)
    _draw_header(fig, "S9 — tSNR by vertebral level (PAM50)",
                 subtitle, status)
    ax = fig.add_axes((0.08, 0.18, 0.88, 0.68))
    _setup_dark_axes(ax)

    ax.bar(x, y, yerr=err, color=colors, edgecolor=BORDER, linewidth=0.4,
           error_kw={"ecolor": "#9ca3af", "lw": 0.6})
    ax.axhline(pass_threshold, ls="--", color=_PASS_COLOR, lw=0.6,
               label=f"PASS ≥ {pass_threshold:.0f}")
    ax.axhline(warn_threshold, ls="--", color=_FAIL_COLOR, lw=0.6,
               label=f"FAIL < {warn_threshold:.0f}")
    ax.set_xticks(x)
    ax.set_xticklabels([f"L{lvl}" for lvl in x], color=TEXT, fontsize=10)
    ax.set_xlabel("PAM50 spinal level (1..20)", color=TEXT, fontsize=10)
    ax.set_ylabel("tSNR (mean ± SD)", color=TEXT, fontsize=10)
    leg = ax.legend(loc="upper right", fontsize=8, facecolor="#1a1d23",
                    edgecolor=BORDER, labelcolor=TEXT)
    for t in leg.get_texts():
        t.set_color(TEXT)
    ax.grid(axis="y", alpha=0.15, color=BORDER)
    ax.set_axisbelow(True)

    fig.savefig(output_path, dpi=120, facecolor=BG, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Reportlet 3: smoothed_vs_unsmoothed_axial
# ---------------------------------------------------------------------------


def render_s9_smoothed_vs_unsmoothed_axial(
    unsmoothed_bold: Path, smoothed_bold: Path, cord_mask: Path,
    output_path: Path, n_slices: int = 9,
    status: str = "PASS",
    tsnr_ratio: Optional[float] = None,
) -> None:
    """9-tile axial montage: unsmoothed (left) vs smoothed (right) mean BOLD."""
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

    subtitle_parts = []
    if tsnr_ratio is not None:
        subtitle_parts.append(f"tSNR ratio = {tsnr_ratio:.2f}×")
    subtitle = "  ·  ".join(subtitle_parts) if subtitle_parts else ""

    fig = plt.figure(figsize=(13, 7), facecolor=BG)
    _draw_header(fig, "S9 — Smoothed vs unsmoothed (mean BOLD)",
                 subtitle, status)

    vmin, vmax = _safe_pct(g_pre, (2, 98))
    for j, (grid, label) in enumerate(zip(
        [g_pre, g_post], ["Unsmoothed", "Smoothed"]
    )):
        ax = fig.add_axes((0.04 + j * 0.48, 0.07, 0.44, 0.80))
        _setup_dark_axes(ax)
        ax.imshow(grid, cmap="gray", vmin=vmin, vmax=vmax,
                  interpolation="nearest")
        if g_msk.any():
            ax.contour(g_msk, levels=[0.5], colors=[EPI_CYAN],
                       linewidths=0.6)
        ax.set_xticks([]); ax.set_yticks([])
        ax.set_title(label, color=TEXT, fontsize=12, fontweight="bold", pad=4)

    fig.savefig(output_path, dpi=120, facecolor=BG, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Reportlet 4: smoothness_summary — REDESIGNED with tolerance bands
# ---------------------------------------------------------------------------


def render_s9_smoothness_summary(
    requested: list[float],
    measured: dict[str, Optional[float]],
    output_path: Path,
    status: str = "PASS",
    tolerance_xy: float = 0.5,
    tolerance_xy_warn: float = 1.0,
    tolerance_z: float = 1.0,
    tolerance_z_warn: float = 2.0,
) -> None:
    """Per-axis FWHM bars (requested vs measured) with PASS / WARN / FAIL
    color coding + shaded tolerance window.

    Acceptance window per axis:
      PASS: |measured − requested| ≤ tolerance
      WARN: |measured − requested| ≤ tolerance_warn
      FAIL: otherwise

    Tolerances are wider on Z (S-I) than X/Y (R-L, A-P) because the
    sct_cord smoothing applies asymmetric kernel sigmas (cord-axis
    emphasis); the FWHM estimator's noise floor scales with the
    requested width.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    axes_lbl = ["X (R-L)", "Y (A-P)", "Z (S-I)"]
    req = list(requested) + [0.0] * (3 - len(requested))
    meas = [measured.get("x") or 0.0,
            measured.get("y") or 0.0,
            measured.get("z") or 0.0]
    tol_pass = [tolerance_xy, tolerance_xy, tolerance_z]
    tol_warn = [tolerance_xy_warn, tolerance_xy_warn, tolerance_z_warn]

    # Per-axis PASS/WARN/FAIL
    per_axis_status: list[str] = []
    for r, m, tp, tw in zip(req, meas, tol_pass, tol_warn):
        d = abs(m - r)
        if d <= tp:
            per_axis_status.append("PASS")
        elif d <= tw:
            per_axis_status.append("WARN")
        else:
            per_axis_status.append("FAIL")

    n_fail = sum(s == "FAIL" for s in per_axis_status)
    n_warn = sum(s == "WARN" for s in per_axis_status)
    n_pass = sum(s == "PASS" for s in per_axis_status)
    subtitle = (f"requested {req[0]:.1f}/{req[1]:.1f}/{req[2]:.1f} mm  ·  "
                f"measured {meas[0]:.1f}/{meas[1]:.1f}/{meas[2]:.1f} mm  ·  "
                f"{n_pass}P · {n_warn}W · {n_fail}F")

    fig = plt.figure(figsize=(10, 5.5), facecolor=BG)
    _draw_header(fig, "S9 — Spatial smoothness (requested vs measured)",
                 subtitle, status)
    ax = fig.add_axes((0.10, 0.13, 0.86, 0.72))
    _setup_dark_axes(ax)

    x = np.arange(3, dtype=float)
    w = 0.36

    # Shaded acceptance window around each requested value (PASS band
    # darker, WARN band lighter). Drawn behind the bars.
    for i in range(3):
        # PASS band
        ax.fill_betweenx(
            [req[i] - tol_pass[i], req[i] + tol_pass[i]],
            x[i] - 0.45, x[i] + 0.45,
            color="#14532d", alpha=0.30, zorder=0,
        )
        # WARN band (outside PASS)
        ax.fill_betweenx(
            [req[i] - tol_warn[i], req[i] - tol_pass[i]],
            x[i] - 0.45, x[i] + 0.45,
            color="#3a2f00", alpha=0.25, zorder=0,
        )
        ax.fill_betweenx(
            [req[i] + tol_pass[i], req[i] + tol_warn[i]],
            x[i] - 0.45, x[i] + 0.45,
            color="#3a2f00", alpha=0.25, zorder=0,
        )

    # Bars: requested (cyan) vs measured (color-coded)
    bars_req = ax.bar(x - w/2, req, width=w,
                      color="#7dcfff", edgecolor=BORDER, linewidth=0.4,
                      label="Requested FWHM")
    measured_colors = [
        _PASS_COLOR if s == "PASS"
        else _WARN_COLOR if s == "WARN"
        else _FAIL_COLOR
        for s in per_axis_status
    ]
    bars_meas = ax.bar(x + w/2, meas, width=w,
                       color=measured_colors, edgecolor=BORDER, linewidth=0.4,
                       label="Measured residual")

    # Number labels above each bar
    y_top = max(max(req), max(meas)) * 1.10
    for bar, val in zip(bars_req, req):
        ax.text(bar.get_x() + bar.get_width() / 2,
                val + y_top * 0.02, f"{val:.1f}",
                ha="center", color=TEXT, fontsize=10)
    for bar, val, st in zip(bars_meas, meas, per_axis_status):
        ax.text(bar.get_x() + bar.get_width() / 2,
                val + y_top * 0.02, f"{val:.1f}",
                ha="center",
                color=measured_colors[per_axis_status.index(st)],
                fontsize=10, fontweight="bold")

    ax.set_xticks(x)
    ax.set_xticklabels(axes_lbl, color=TEXT, fontsize=11)
    ax.set_ylabel("FWHM (mm)", color=TEXT, fontsize=11)
    ax.set_ylim(0, y_top * 1.05)

    # Legend for the bands (use proxy artists)
    import matplotlib.patches as mpatches
    pass_patch = mpatches.Patch(color="#14532d", alpha=0.30, label="PASS window")
    warn_patch = mpatches.Patch(color="#3a2f00", alpha=0.25, label="WARN window")
    leg = ax.legend(handles=[bars_req, bars_meas, pass_patch, warn_patch],
                    loc="upper left", fontsize=8, facecolor="#1a1d23",
                    edgecolor=BORDER, labelcolor=TEXT, ncol=2)
    for t in leg.get_texts():
        t.set_color(TEXT)
    ax.grid(axis="y", alpha=0.15, color=BORDER)
    ax.set_axisbelow(True)

    fig.savefig(output_path, dpi=120, facecolor=BG, bbox_inches="tight")
    plt.close(fig)
