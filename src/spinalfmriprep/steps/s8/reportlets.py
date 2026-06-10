"""S8 reportlet rendering — chain-wide visual standard (dark theme).

5 reportlets per run, following the field-standard for confound-matrix QC:

1. ``confound_columns`` — per-slice design bar chart of regressor counts
   per family (motion / outliers / CSF / RETROICOR / cosine / SpinalCompCor),
   PASS/WARN/FAIL status pill in the header. Quick health-of-the-
   confound-matrix view.
2. ``fd_dvars_outliers`` — 3-row time series (FD + DVARS + refRMS)
   with the outlier-flag bands shown as red x-marks. Power 2014 +
   Kaptan 2023 standard motion-and-noise diagnostic.
3. ``pnm_peaks`` — cardiac peak ticks + respiratory phase trace when
   physio exists; explicit "physio absent" placeholder otherwise.
4. ``correlation_heatmap`` — Pearson r matrix across all confound
   columns, color-coded for design-matrix multicollinearity.
5. ``carpet_plot`` — cord BOLD carpet (Power 2017) with FD/DVARS rails.

Dropped:
- ``csf_variance`` (2026-05-28) — implementation-detail per-slice voxel
  count; its info is in metrics.n_columns_csf + the correlation heatmap.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


BG = "#0f1115"
TEXT = "#e6e8ec"
BORDER = "#374151"

_STATUS = {
    "PASS": ("#14532d", "#22c55e"),
    "WARN": ("#3a2f00", "#f59e0b"),
    "FAIL": ("#3a1010", "#ef4444"),
}

_FAMILY_COLORS = {
    "motion": "#7dcfff",
    "outliers": "#ef4444",
    "csf": "#22c55e",
    "retroicor": "#f59e0b",
    "cosine": "#9ca3af",
    "spinalcompcor": "#c084fc",
}


def _setup_dark_axes(ax) -> None:
    ax.set_facecolor(BG)
    ax.tick_params(colors=TEXT, labelsize=9)
    for s in ax.spines.values():
        s.set_color(BORDER)


def _draw_header(fig, title: str, subtitle: str = "", status: str = "PASS") -> None:
    """Title + subtitle (left) and PASS/WARN/FAIL pill (right).
    Mirrors reportlets_common.add_header but light-dependency-only
    so S8 stays self-contained.
    """
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


# ---------------------------------------------------------------------------
# Reportlet 1: confound family counts + status pill
# ---------------------------------------------------------------------------


def render_s8_confound_columns(
    family_counts: dict[str, int],
    sidecar: dict[str, Any],
    output_path: Path,
    status: str = "PASS",
    n_columns_total: Optional[int] = None,
    condition_number: Optional[float] = None,
    csf_per_slice: Optional[int] = None,
    csf_n_slices: Optional[int] = None,
) -> None:
    """Per-family regressor count bar chart with status pill.

    The chart shows the **per-slice GLM design** — how many regressors each
    family contributes to a single slice's model. CSF aCompCor is slicewise, so
    its bar is the per-slice component count (e.g. 5), NOT the flat-TSV total
    (5 × N_slices); every other family is global (one set reused for all slices),
    so its per-slice count equals its column count. The flat-TSV column total is
    reported in the subtitle so the storage size stays discoverable.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    families = ["motion", "outliers", "csf", "retroicor", "cosine", "spinalcompcor"]
    flat_counts = {f: int(family_counts.get(f, 0)) for f in families}

    # Per-slice design: CSF collapses to its per-slice component count.
    show_per_slice = csf_per_slice is not None and flat_counts["csf"] > 0
    disp = dict(flat_counts)
    if show_per_slice:
        disp["csf"] = int(csf_per_slice)
    counts = [disp[f] for f in families]

    flat_total = (sum(flat_counts.values()) if n_columns_total is None
                  else int(n_columns_total))
    per_slice_total = sum(disp.values())

    subtitle_parts = []
    if show_per_slice:
        ns = f"×{int(csf_n_slices)} slices" if csf_n_slices else "per slice"
        subtitle_parts.append(f"per-slice design = {per_slice_total} regressors  "
                              f"(CSF {int(csf_per_slice)}/slice)")
        subtitle_parts.append(f"flat TSV = {flat_total} cols  "
                              f"(CSF {flat_counts['csf']} = {int(csf_per_slice)} {ns})")
    else:
        subtitle_parts.append(f"n_columns_total={flat_total}")
    if condition_number is not None and np.isfinite(condition_number):
        subtitle_parts.append(f"condition_number={condition_number:.1f}")
    subtitle = "  ·  ".join(subtitle_parts)

    fig, ax = plt.subplots(figsize=(10, 5), facecolor=BG)
    _draw_header(fig,
                 "S8 — Confound regressors per slice"
                 if show_per_slice else "S8 — Confound regressor families",
                 subtitle, status)
    _setup_dark_axes(ax)
    ax.set_position((0.08, 0.12, 0.88, 0.72))

    colors = [_FAMILY_COLORS[f] for f in families]
    bars = ax.bar(families, counts, color=colors, edgecolor=BORDER, linewidth=0.5)
    for f, bar, c in zip(families, bars, counts):
        label = str(c)
        if show_per_slice and f == "csf" and csf_n_slices:
            label = f"{c}/slice"
        ax.text(bar.get_x() + bar.get_width() / 2,
                c + max(counts) * 0.02,
                label, ha="center", color=TEXT, fontsize=11, fontweight="bold")
    ax.set_ylabel("Regressors in one slice's GLM" if show_per_slice
                  else "Regressor columns", color=TEXT, fontsize=11)
    ax.grid(axis="y", alpha=0.15, color=BORDER)
    ax.set_axisbelow(True)

    fig.savefig(output_path, dpi=120, facecolor=BG, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Reportlet 2: motion + outliers
# ---------------------------------------------------------------------------


def render_s8_fd_dvars_outliers(
    fd: Optional[np.ndarray], dvars: Optional[np.ndarray],
    refrms: Optional[np.ndarray], n_outliers: int,
    output_path: Path,
    status: str = "PASS",
    fd_thresh: float = 0.2,
    outlier_indices: Optional[np.ndarray] = None,
) -> None:
    """FD + DVARS + refRMS time series. Outlier frames marked across all panels."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    n_total = next((v.size for v in (fd, dvars, refrms) if v is not None), 0)
    subtitle = f"{n_outliers} flagged volumes / {n_total} total"

    fig = plt.figure(figsize=(11, 7), facecolor=BG)
    _draw_header(fig, "S8 — Motion + frame outliers", subtitle, status)
    axes = []
    for i, (vec, label, color) in enumerate(zip(
        [fd, dvars, refrms],
        ["Framewise Displacement (mm)", "DVARS", "refRMS"],
        ["#7dcfff", "#ef4444", "#f59e0b"],
    )):
        ax = fig.add_axes((0.08, 0.78 - i * 0.235, 0.88, 0.20))
        _setup_dark_axes(ax)
        axes.append(ax)
        if vec is None or vec.size == 0:
            ax.text(0.5, 0.5, "n/a", transform=ax.transAxes,
                    ha="center", color="#9ca3af", fontsize=11)
            ax.set_ylabel(label, color=TEXT, fontsize=9)
            continue
        x = np.arange(vec.size)
        ax.plot(x, vec, color=color, lw=1.0)
        # Outlier vertical lines
        if outlier_indices is not None and len(outlier_indices) > 0:
            for oi in outlier_indices:
                ax.axvline(oi, color="#ef4444", lw=0.4, alpha=0.35)
        # Threshold lines — FD uses caller-supplied threshold; DVARS/
        # refRMS use Tukey Q3 + 1.5·IQR (matches the actual gate).
        if i == 0:
            ax.axhline(fd_thresh, ls="--", color="#9ca3af", lw=0.6,
                       label=f"FD = {fd_thresh:.2f} mm")
        else:
            q1, q3 = np.percentile(vec, [25, 75])
            thr = q3 + 1.5 * (q3 - q1)
            ax.axhline(thr, ls="--", color="#9ca3af", lw=0.6,
                       label="Q3 + 1.5·IQR")
        leg = ax.legend(loc="upper right", fontsize=8, facecolor="#1a1d23",
                        edgecolor=BORDER, labelcolor=TEXT)
        for t in leg.get_texts():
            t.set_color(TEXT)
        ax.set_ylabel(label, color=TEXT, fontsize=9)
        ax.grid(alpha=0.15, color=BORDER)
        ax.set_axisbelow(True)
    axes[-1].set_xlabel("Volume", color=TEXT, fontsize=10)
    for ax in axes[:-1]:
        ax.tick_params(labelbottom=False)
    fig.savefig(output_path, dpi=120, facecolor=BG, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Reportlet 3: PNM physio cardiac + respiratory
# ---------------------------------------------------------------------------


def render_s8_pnm_peaks(
    work_dir: Path, physio_present: bool, output_path: Path,
    status: str = "PASS",
) -> None:
    """Cardiac peak ticks + respiratory phase trace, or "physio absent"
    placeholder. FSL popp output: popp_card.txt (cardiac peak times,
    seconds) and popp_resp.txt (per-sample respiratory phase).
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not physio_present:
        fig, ax = plt.subplots(figsize=(10, 4), facecolor=BG)
        _draw_header(fig, "S8 — RETROICOR (FSL PNM)",
                     "physio absent — RETROICOR skipped",
                     "WARN" if status == "PASS" else status)
        ax.set_facecolor(BG); ax.axis("off")
        ax.text(0.5, 0.45, "No BIDS physio TSV for this run",
                transform=ax.transAxes, ha="center", va="center",
                color="#9ca3af", fontsize=12)
        ax.text(0.5, 0.32,
                "The cosine basis + CSF + SpinalCompCor still capture "
                "physiological-band variance.",
                transform=ax.transAxes, ha="center", va="center",
                color="#6b7280", fontsize=9, family="monospace")
        fig.savefig(output_path, dpi=120, facecolor=BG, bbox_inches="tight")
        plt.close(fig)
        return

    pnm = work_dir / "pnm"
    card_path = pnm / "popp_card.txt"
    resp_path = pnm / "popp_resp.txt"

    bpm = None
    cpm = None
    try:
        if card_path.exists():
            card_times = np.loadtxt(card_path)
            if card_times.size > 1:
                bpm = 60.0 / float(np.median(np.diff(card_times)))
    except Exception:
        card_times = np.array([])
    else:
        card_times = card_times if card_path.exists() else np.array([])

    resp_t = np.array([])
    resp_ph = np.array([])
    try:
        if resp_path.exists():
            arr = np.loadtxt(resp_path)
            if arr.ndim == 2 and arr.shape[1] == 2:
                resp_t = arr[:, 0]
                resp_ph = arr[:, 1]
            elif arr.ndim == 1:
                resp_t = np.arange(arr.size) * 0.0025
                resp_ph = arr
            if resp_t.size > 1:
                phw = np.mod(resp_ph + np.pi, 2 * np.pi) - np.pi
                n_breaths = int(((np.diff(phw) < -np.pi).sum()))
                duration_s = float(resp_t[-1] - resp_t[0])
                cpm = 60.0 * n_breaths / max(duration_s, 1e-6)
    except Exception:
        pass

    subtitle_parts = []
    if bpm is not None:
        subtitle_parts.append(f"cardiac ~ {bpm:.0f} bpm")
    if cpm is not None:
        subtitle_parts.append(f"respiratory ~ {cpm:.0f} cpm")
    subtitle = "  ·  ".join(subtitle_parts) or "physio loaded"

    fig = plt.figure(figsize=(11, 5), facecolor=BG)
    _draw_header(fig, "S8 — RETROICOR (FSL PNM)", subtitle, status)

    # Cardiac peaks (top)
    ax1 = fig.add_axes((0.08, 0.54, 0.88, 0.30))
    _setup_dark_axes(ax1)
    if card_times.size > 0:
        ax1.vlines(card_times, 0, 1, color="#ef4444", lw=0.5)
    else:
        ax1.text(0.5, 0.5, "no cardiac peaks detected",
                 transform=ax1.transAxes, ha="center", color="#9ca3af")
    ax1.set_yticks([])
    ax1.set_ylabel("Cardiac peaks", color=TEXT, fontsize=9)
    ax1.tick_params(labelbottom=False)
    ax1.grid(axis="x", alpha=0.15, color=BORDER)

    # Respiratory phase (bottom)
    ax2 = fig.add_axes((0.08, 0.12, 0.88, 0.36))
    _setup_dark_axes(ax2)
    if resp_t.size > 0:
        phw_full = np.mod(resp_ph + np.pi, 2 * np.pi) - np.pi
        ax2.plot(resp_t, phw_full, color="#7dcfff", lw=0.4)
        ax2.set_ylim(-np.pi, np.pi)
    else:
        ax2.text(0.5, 0.5, "no respiratory phase",
                 transform=ax2.transAxes, ha="center", color="#9ca3af")
    ax2.set_xlabel("Time (s)", color=TEXT, fontsize=10)
    ax2.set_ylabel("Respiratory phase (rad)", color=TEXT, fontsize=9)
    ax2.grid(alpha=0.15, color=BORDER)

    fig.savefig(output_path, dpi=120, facecolor=BG, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Reportlet 4: confound matrix correlation heatmap
# ---------------------------------------------------------------------------


def render_s8_correlation_heatmap(
    df, output_path: Path, max_cols: int = 80,
    status: str = "PASS",
    condition_number: Optional[float] = None,
) -> None:
    """Pearson r heatmap across confound columns. Multicollinearity proxy.
    Downsamples columns when > max_cols to keep figure legible."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    subtitle_parts = []
    if condition_number is not None and np.isfinite(condition_number):
        subtitle_parts.append(f"condition_number={condition_number:.1f}")
    subtitle = "  ·  ".join(subtitle_parts)

    fig = plt.figure(figsize=(9, 8), facecolor=BG)
    _draw_header(fig, "S8 — Confound correlation matrix",
                 subtitle, status)
    ax = fig.add_axes((0.10, 0.07, 0.82, 0.80))
    _setup_dark_axes(ax)

    if df is None or df.empty or df.shape[1] < 2:
        ax.text(0.5, 0.5, "Insufficient columns for correlation",
                transform=ax.transAxes, ha="center", va="center",
                color="#9ca3af")
        ax.axis("off")
        fig.savefig(output_path, dpi=120, facecolor=BG, bbox_inches="tight")
        plt.close(fig)
        return

    cols = list(df.columns)
    if len(cols) > max_cols:
        idx = np.linspace(0, len(cols) - 1, max_cols).astype(int)
        cols = [cols[i] for i in idx]
    arr = df[cols].to_numpy(dtype=np.float64)
    sd = arr.std(axis=0)
    keep = sd > 1e-12
    arr = arr[:, keep]
    cols = [c for c, k in zip(cols, keep) if k]
    if arr.shape[1] < 2:
        ax.text(0.5, 0.5, "Insufficient non-zero columns",
                transform=ax.transAxes, ha="center", va="center",
                color="#9ca3af")
        ax.axis("off")
        fig.savefig(output_path, dpi=120, facecolor=BG, bbox_inches="tight")
        plt.close(fig)
        return
    arr_z = (arr - arr.mean(axis=0)) / arr.std(axis=0)
    corr = (arr_z.T @ arr_z) / max(arr_z.shape[0] - 1, 1)
    im = ax.imshow(corr, cmap="RdBu_r", vmin=-1, vmax=1, interpolation="nearest")
    cb = fig.colorbar(im, ax=ax, shrink=0.7)
    cb.set_label("Pearson r", color=TEXT, fontsize=9)
    cb.ax.tick_params(colors=TEXT, labelsize=8)
    cb.outline.set_edgecolor(BORDER)
    if len(cols) <= 40:
        ax.set_xticks(range(len(cols)))
        ax.set_yticks(range(len(cols)))
        ax.set_xticklabels(cols, rotation=90, fontsize=6, color=TEXT)
        ax.set_yticklabels(cols, fontsize=6, color=TEXT)
    else:
        ax.set_xticks([]); ax.set_yticks([])
        ax.set_xlabel(f"{len(cols)} columns (sampled to {max_cols})",
                      color=TEXT, fontsize=9)

    fig.savefig(output_path, dpi=120, facecolor=BG, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Reportlet 5: carpet plot (Power 2017 / fMRIPrep standard)
# ---------------------------------------------------------------------------


def render_s8_carpet_plot(
    bold_path,
    cord_mask_path,
    output_path: Path,
    fd: Optional[np.ndarray] = None,
    dvars: Optional[np.ndarray] = None,
    status: str = "PASS",
    fd_thresh: float = 0.2,
    outlier_indices: Optional[np.ndarray] = None,
) -> None:
    """Cord-restricted voxel × time BOLD intensity carpet, with FD/DVARS
    traces below. Power 2017 / fMRIPrep / Kaptan 2023 standard.

    Visualises WHERE in the cord (vertical axis = voxels sorted by
    mean intensity for stable striping) and WHEN (horizontal = volume
    index) the residual noise lives. Striped patterns indicate a
    confound the regressor model didn't capture; coherent bands
    align with FD spikes; speckled noise is acceptable.

    Voxels are intensity-normalised per row (mean-centered, std-
    divided) so the carpet visualises temporal variation, not
    absolute intensity. fMRIPrep convention.

    Parameters
    ----------
    bold_path : Path
        4D BOLD time series in native func space (post-S5/post-S6).
    cord_mask_path : Path
        Cord mask in BOLD geometry (S6 funccrop equivalent).
    fd, dvars : array-like
        Optional time series for the bottom traces.
    outlier_indices : array-like
        Volume indices to mark as red vertical bands across all axes.
    """
    import nibabel as nib

    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        bimg = nib.load(bold_path)
        bold = bimg.get_fdata()
        cord = nib.load(cord_mask_path).get_fdata() > 0.5
    except Exception as e:
        fig, ax = plt.subplots(figsize=(10, 5), facecolor=BG)
        _draw_header(fig, "S8 — Carpet plot", f"load failed: {e}", "WARN")
        ax.set_facecolor(BG); ax.axis("off")
        fig.savefig(output_path, dpi=120, facecolor=BG, bbox_inches="tight")
        plt.close(fig)
        return

    if bold.ndim != 4 or cord.shape != bold.shape[:3]:
        fig, ax = plt.subplots(figsize=(10, 5), facecolor=BG)
        _draw_header(fig, "S8 — Carpet plot",
                     f"shape mismatch: bold={bold.shape} cord={cord.shape}",
                     "WARN")
        ax.set_facecolor(BG); ax.axis("off")
        fig.savefig(output_path, dpi=120, facecolor=BG, bbox_inches="tight")
        plt.close(fig)
        return

    # Extract cord voxel timeseries: (V, T)
    cord_vox = bold[cord]
    n_vox, n_t = cord_vox.shape
    if n_vox < 5 or n_t < 5:
        fig, ax = plt.subplots(figsize=(10, 5), facecolor=BG)
        _draw_header(fig, "S8 — Carpet plot",
                     f"insufficient data: {n_vox} voxels × {n_t} volumes",
                     "WARN")
        ax.set_facecolor(BG); ax.axis("off")
        fig.savefig(output_path, dpi=120, facecolor=BG, bbox_inches="tight")
        plt.close(fig)
        return

    # Per-voxel mean-center + std-normalise (fMRIPrep convention).
    mu = cord_vox.mean(axis=1, keepdims=True)
    sd = cord_vox.std(axis=1, keepdims=True)
    sd[sd < 1e-6] = 1.0
    carpet = (cord_vox - mu) / sd

    # Sort voxels by mean intensity for stable banding patterns
    # (high-signal voxels = cord interior cluster at the top).
    order = np.argsort(mu.flatten())[::-1]
    carpet = carpet[order]

    # Color scale: ±2σ clipped — fMRIPrep convention.
    vmin, vmax = -2.0, 2.0

    has_fd = fd is not None and len(fd) == n_t
    has_dvars = dvars is not None and len(dvars) == n_t
    n_panels = 1 + int(has_fd) + int(has_dvars)

    subtitle = f"{n_vox} cord voxels × {n_t} volumes  ·  carpet ±{abs(vmin):.0f}σ"

    fig = plt.figure(figsize=(12, 7), facecolor=BG)
    _draw_header(fig, "S8 — Carpet plot (cord BOLD)",
                 subtitle, status)

    # Layout — carpet on top, traces below. Carpet has a dedicated
    # colorbar gutter to the RIGHT (cax) so the carpet's plot box
    # width equals the trace boxes (no auto-shrink from
    # `fig.colorbar(ax=ax_carpet)`). Volume-axis alignment requires
    # identical x-positions on all panels.
    plot_x0 = 0.08
    plot_w  = 0.80       # carpet + traces all this wide
    cbar_x0 = plot_x0 + plot_w + 0.012
    cbar_w  = 0.018

    if n_panels == 1:
        ax_carpet = fig.add_axes((plot_x0, 0.10, plot_w, 0.75))
        cax = fig.add_axes((cbar_x0, 0.10 + 0.75 * 0.18, cbar_w, 0.75 * 0.64))
        trace_axes: list = []
    else:
        carpet_h = 0.55
        trace_h_each = 0.20 / max(n_panels - 1, 1)
        ax_carpet = fig.add_axes((plot_x0, 0.30, plot_w, carpet_h))
        cax = fig.add_axes(
            (cbar_x0, 0.30 + carpet_h * 0.18, cbar_w, carpet_h * 0.64)
        )
        trace_axes = []
        next_y = 0.08
        for i in range(n_panels - 1):
            tax = fig.add_axes((plot_x0, next_y, plot_w, trace_h_each))
            trace_axes.append(tax)
            next_y += trace_h_each + 0.01

    _setup_dark_axes(ax_carpet)
    im = ax_carpet.imshow(
        carpet, cmap="RdBu_r", vmin=vmin, vmax=vmax,
        aspect="auto", interpolation="nearest",
        extent=(0, n_t, n_vox, 0),       # x in volume units (matches traces)
    )
    ax_carpet.set_xlim(0, n_t - 1)
    ax_carpet.set_ylabel(f"Cord voxels (sorted by mean, n={n_vox})",
                         color=TEXT, fontsize=9)
    if trace_axes:
        ax_carpet.tick_params(labelbottom=False)
    else:
        ax_carpet.set_xlabel("Volume", color=TEXT, fontsize=10)

    cb = fig.colorbar(im, cax=cax)
    cb.set_label("σ", color=TEXT, fontsize=9)
    cb.ax.tick_params(colors=TEXT, labelsize=8)
    cb.outline.set_edgecolor(BORDER)

    # Outlier markers across all axes
    all_axes = [ax_carpet] + trace_axes
    if outlier_indices is not None:
        for oi in outlier_indices:
            for ax in all_axes:
                ax.axvline(oi, color="#ef4444", lw=0.4, alpha=0.30)

    # Bottom traces
    trace_specs = []
    if has_fd:
        trace_specs.append((fd, "FD (mm)", "#7dcfff", fd_thresh,
                            f"FD = {fd_thresh:.2f} mm"))
    if has_dvars:
        # Match the actual DVARS gate (Tukey Q3 + 1.5·IQR), same as the
        # fd_dvars_outliers reportlet — not the abandoned μ+3σ rule.
        q1_d, q3_d = np.percentile(dvars, [25, 75])
        dvars_thr = float(q3_d + 1.5 * (q3_d - q1_d))
        trace_specs.append((dvars, "DVARS", "#ef4444",
                            dvars_thr, "DVARS Q3 + 1.5·IQR"))

    for ax, (vec, label, color, thr, thr_lbl) in zip(trace_axes, trace_specs):
        _setup_dark_axes(ax)
        x = np.arange(len(vec))
        ax.plot(x, vec, color=color, lw=0.9)
        ax.axhline(thr, ls="--", color="#9ca3af", lw=0.5, label=thr_lbl)
        leg = ax.legend(loc="upper right", fontsize=7, facecolor="#1a1d23",
                        edgecolor=BORDER, labelcolor=TEXT)
        for t in leg.get_texts():
            t.set_color(TEXT)
        ax.set_ylabel(label, color=TEXT, fontsize=8)
        ax.grid(alpha=0.15, color=BORDER)
        ax.set_axisbelow(True)
        ax.set_xlim(0, n_t - 1)        # match the carpet x extent exactly

    # X-label only on bottom-most panel
    if trace_axes:
        for ax in trace_axes[:-1]:
            ax.tick_params(labelbottom=False)
        trace_axes[-1].set_xlabel("Volume", color=TEXT, fontsize=10)

    fig.savefig(output_path, dpi=120, facecolor=BG, bbox_inches="tight")
    plt.close(fig)
