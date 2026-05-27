"""S3 unified reportlets — implements the chain-wide visual standard.

Uses shared helpers from `spinalfmriprep.reportlets_common`. The visual
language is documented in
`.claude/specs/reportlet-visual-standard.md`. Replaces the legacy
PIL+ImageMagick renderers (`reportlets.py`, `localize_viz.py`).

Four S3 reportlets:
  S3.1 func_localization       Discovery cord on coarse functional reference
  S3.2 frame_metrics           DVARS + DVARS-ref + outlier markers
  S3.3 crop_box_sagittal       Cord-cropped funcref sagittal + montage
  S3.3 funcref_montage         Robust funcref with cord contour overlay
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from spinalfmriprep.reportlets_common import (
    BG, BORDER, MARKER_YELLOW, MUTED, SEMANTIC, TEXT,
    add_footer, add_header, cord_zrange, intensity_window,
    load_canonical, midcord_sagittal_slice, per_slice_centered_crop,
    render_axial_tile, render_sagittal, render_sagittal_plus_montage,
    stub_figure, uniform_z_picks,
)


# ---------------------------------------------------------------------------
# S3.1 — func_localization
# ---------------------------------------------------------------------------

def render_func_localization(
    output_path: Path,
    func_ref_fast_path: Path,      # quick mean BOLD (S3.1, full FOV)
    discovery_seg_path: Path,      # cord seg in func_ref_fast geometry
    subject: str = "?",
    dataset_key: str = "?",
    status: str = "UNKNOWN",
) -> None:
    """Sagittal + axial of the full-FOV functional reference with the
    discovery cord contour. The operator can see whether the cord
    localization picked the right region (and didn't drift into the
    brain or muscle)."""
    try:
        if not func_ref_fast_path.exists() or not discovery_seg_path.exists():
            stub_figure(output_path, "funcref or discovery seg missing")
            return
        funcref, _, zooms = load_canonical(func_ref_fast_path)
        disc, _, _ = load_canonical(discovery_seg_path)
        if funcref.shape != disc.shape:
            stub_figure(output_path, "shape mismatch funcref vs seg")
            return
        disc_mask = disc > 0
        if not disc_mask.any():
            stub_figure(output_path, "discovery seg empty (drift gate)")
            return

        x_mid = midcord_sagittal_slice(disc_mask)
        sag_overlays: list[tuple[np.ndarray, str, float, float]] = [
            (disc_mask[x_mid, :, :], SEMANTIC["discovery"], 0.0, 2.6),
        ]

        def axial_overlays(z):
            return [(disc_mask[:, :, z], SEMANTIC["discovery"], 2.6, 0.0)]

        z_with = np.where(disc_mask.any(axis=(0, 1)))[0]
        metric = f"{z_with.size} cord slices" if z_with.size else ""

        render_sagittal_plus_montage(
            output_path=output_path,
            title="S3.1 — Func localization",
            subtitle=f"sub-{subject} • {dataset_key}",
            status=status, metric_header=metric,
            anat=funcref, cord_mask=disc_mask,
            sag_overlays=sag_overlays,
            axial_overlays_factory=axial_overlays,
            legend_items=[(SEMANTIC["discovery"], "discovery cord")],
            metric_lines=[],
            axial_window_vox=(28, 28),
            zooms=zooms,
            intensity_pct=(1.0, 99.0),  # tighter for funcref (bright fat else dominates)
        )
    except Exception as e:
        stub_figure(output_path, f"func_localization render failed: {e}")


# ---------------------------------------------------------------------------
# S3.2 — frame_metrics (time-series plot, dark theme)
# ---------------------------------------------------------------------------

def render_frame_metrics(
    output_path: Path,
    frame_metrics_tsv: Path,
    outlier_mask_json: Optional[Path],
    subject: str = "?",
    dataset_key: str = "?",
    status: str = "UNKNOWN",
) -> None:
    """DVARS + refRMS line plot with threshold + outlier markers.

    Dark theme matching the chain's visual language. Header carries
    outlier_fraction; footer shows total frame + outlier counts. The
    plot itself preserves the diagnostic value of the old matplotlib
    line plot but with proper chrome.
    """
    try:
        if not frame_metrics_tsv.exists():
            stub_figure(output_path, "frame_metrics.tsv missing")
            return

        # Parse TSV (columns: frame, dvars, ref_rms, outlier)
        rows = []
        with open(frame_metrics_tsv) as f:
            header_line = f.readline().strip().split("\t")
            for line in f:
                parts = line.strip().split("\t")
                if len(parts) < 4:
                    continue
                rows.append(parts)
        arr = np.array(rows, dtype=float)
        if arr.size == 0:
            stub_figure(output_path, "frame_metrics empty")
            return
        frames = arr[:, 0].astype(int)
        dvars = arr[:, 1]
        refrms = arr[:, 2]
        outlier_mask = arr[:, 3].astype(bool)

        # Outlier thresholds + counts from JSON
        dvars_thr = None
        refrms_thr = None
        outlier_frac = None
        n_outliers = None
        if outlier_mask_json and outlier_mask_json.exists():
            try:
                meta = json.loads(outlier_mask_json.read_text(encoding="utf-8"))
                thr = meta.get("thresholds", {}) or {}
                dvars_thr = thr.get("dvars")
                refrms_thr = thr.get("ref_rms")
                outlier_frac = meta.get("outlier_fraction")
                n_outliers = meta.get("outlier_count")
            except Exception:
                pass

        fig = plt.figure(figsize=(14.0, 7.0), facecolor=BG)
        fig.patch.set_facecolor(BG)
        metric_header = ""
        if outlier_frac is not None:
            metric_header = f"outliers {outlier_frac * 100:.1f}%"
        add_header(
            fig, "S3.2 — Frame metrics & outliers",
            f"sub-{subject} • {dataset_key}", status, metric_header)

        # Two stacked panels for DVARS + refRMS
        gs = fig.add_gridspec(2, 1, hspace=0.15,
                               left=0.08, right=0.98, top=0.86, bottom=0.14)

        def _setup_axes(ax, ylabel: str):
            ax.set_facecolor(BG)
            ax.set_ylabel(ylabel, color=TEXT, fontsize=12)
            ax.tick_params(colors=TEXT, labelsize=10)
            ax.grid(True, alpha=0.2, color=BORDER, linewidth=0.5)
            for spine in ax.spines.values():
                spine.set_color(BORDER)

        # DVARS panel
        ax1 = fig.add_subplot(gs[0])
        _setup_axes(ax1, "DVARS")
        ax1.plot(frames, dvars, color="#22d3ee", linewidth=1.4)
        if dvars_thr is not None:
            ax1.axhline(dvars_thr, color="#facc15", linestyle="--",
                        linewidth=1.0, alpha=0.8, label=f"threshold {dvars_thr:.1f}")
            out_idx = np.where(dvars > dvars_thr)[0]
            if out_idx.size:
                ax1.scatter(out_idx, dvars[out_idx], color="#ef4444",
                            s=40, marker="x", linewidths=2, zorder=5,
                            label=f"{out_idx.size} outliers")
            leg = ax1.legend(loc="upper right", facecolor=BG,
                              edgecolor=BORDER, labelcolor=TEXT, fontsize=10)
            if leg:
                for t in leg.get_texts():
                    t.set_color(TEXT)
        ax1.tick_params(labelbottom=False)

        # refRMS panel
        ax2 = fig.add_subplot(gs[1], sharex=ax1)
        _setup_axes(ax2, "refRMS")
        ax2.plot(frames, refrms, color="#22c55e", linewidth=1.4)
        if refrms_thr is not None:
            ax2.axhline(refrms_thr, color="#facc15", linestyle="--",
                        linewidth=1.0, alpha=0.8, label=f"threshold {refrms_thr:.1f}")
            out_idx = np.where(refrms > refrms_thr)[0]
            if out_idx.size:
                ax2.scatter(out_idx, refrms[out_idx], color="#ef4444",
                            s=40, marker="x", linewidths=2, zorder=5,
                            label=f"{out_idx.size} outliers")
            leg = ax2.legend(loc="upper right", facecolor=BG,
                              edgecolor=BORDER, labelcolor=TEXT, fontsize=10)
            if leg:
                for t in leg.get_texts():
                    t.set_color(TEXT)
        ax2.set_xlabel("Frame (after dummy drop)", color=TEXT, fontsize=12)

        # Footer with frame totals + outlier counts
        metric_lines = [f"{len(frames)} frames"]
        if n_outliers is not None:
            metric_lines.append(f"{n_outliers} outliers")
        add_footer(
            fig,
            legend_items=[
                ("#22d3ee", "DVARS"),
                ("#22c55e", "refRMS"),
                ("#facc15", "threshold"),
                ("#ef4444", "outlier"),
            ],
            metric_lines=metric_lines,
        )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path, dpi=130, facecolor=BG,
                    bbox_inches="tight", pad_inches=0.05)
        plt.close(fig)
    except Exception as e:
        stub_figure(output_path, f"frame_metrics render failed: {e}")


# ---------------------------------------------------------------------------
# S3.3 — crop_box_sagittal (cord-focused crop on funcref)
# ---------------------------------------------------------------------------

def render_crop_box_sagittal_s3(
    output_path: Path,
    func_ref_fast_path: Path,        # full-FOV functional reference
    discovery_seg_path: Path,         # discovery cord seg (func space)
    func_ref_cropped_path: Path,      # post-crop functional reference (smaller shape)
    subject: str = "?",
    dataset_key: str = "?",
    status: str = "UNKNOWN",
) -> None:
    """S3.3 cord-focused crop. Shows full-FOV funcref with discovery
    cord contour + an amber rectangle marking the cropped bbox (derived
    from the cropped funcref's size aligned to the cord centroid)."""
    try:
        if not func_ref_fast_path.exists() or not discovery_seg_path.exists():
            stub_figure(output_path, "funcref or discovery seg missing")
            return
        funcref, _, zooms = load_canonical(func_ref_fast_path)
        disc, _, _ = load_canonical(discovery_seg_path)
        if funcref.shape != disc.shape:
            stub_figure(output_path, "shape mismatch funcref vs seg")
            return
        disc_mask = disc > 0
        if not disc_mask.any():
            stub_figure(output_path, "discovery seg empty (drift gate)")
            return

        # Build the crop-bbox indicator in funcref geometry: a box
        # whose XY extent matches the cropped funcref's voxel shape,
        # centered on the cord centroid in XY, spanning the cord-bearing
        # Z range. This mirrors what S3.3 actually does.
        crop_mask = np.zeros_like(disc_mask)
        nx, ny, nz = disc_mask.shape
        if func_ref_cropped_path.exists():
            cropped, _, _ = load_canonical(func_ref_cropped_path)
            cw, ch, _ = cropped.shape
        else:
            cw = ch = max(20, min(nx, ny))
        xs, ys, zs = np.nonzero(disc_mask)
        cx, cy = int(round(float(xs.mean()))), int(round(float(ys.mean())))
        x0 = max(0, cx - cw // 2); x1 = min(nx, x0 + cw); x0 = max(0, x1 - cw)
        y0 = max(0, cy - ch // 2); y1 = min(ny, y0 + ch); y0 = max(0, y1 - ch)
        z0, z1 = int(zs.min()), int(zs.max())
        crop_mask[x0:x1, y0:y1, z0:z1 + 1] = True

        x_mid = midcord_sagittal_slice(disc_mask)
        sag_overlays: list[tuple[np.ndarray, str, float, float]] = [
            (disc_mask[x_mid, :, :], SEMANTIC["discovery"], 0.0, 2.4),
            (crop_mask[x_mid, :, :], SEMANTIC["crop_box"], 0.15, 2.8),
        ]

        def axial_overlays(z):
            return [
                (crop_mask[:, :, z], SEMANTIC["crop_box"], 2.6, 0.0),
                (disc_mask[:, :, z], SEMANTIC["discovery"], 2.4, 0.0),
            ]

        dx_mm = (x1 - x0) * float(zooms[0])
        dy_mm = (y1 - y0) * float(zooms[1])
        dz_mm = (z1 - z0 + 1) * float(zooms[2])
        metric = f"crop {dx_mm:.0f}×{dy_mm:.0f}×{dz_mm:.0f} mm"

        render_sagittal_plus_montage(
            output_path=output_path,
            title="S3.3 — Cord-focused crop",
            subtitle=f"sub-{subject} • {dataset_key}",
            status=status, metric_header=metric,
            anat=funcref, cord_mask=disc_mask,
            sag_overlays=sag_overlays,
            axial_overlays_factory=axial_overlays,
            legend_items=[
                (SEMANTIC["discovery"], "discovery cord"),
                (SEMANTIC["crop_box"], "crop bbox"),
            ],
            metric_lines=[],
            axial_window_vox=(40, 40),
            zooms=zooms,
            intensity_pct=(1.0, 99.0),
        )
    except Exception as e:
        stub_figure(output_path, f"crop_box_sagittal render failed: {e}")


# ---------------------------------------------------------------------------
# S3.3 — funcref_montage (robust functional reference)
# ---------------------------------------------------------------------------

def render_funcref_montage(
    output_path: Path,
    func_ref_path: Path,           # robust funcref (mean of non-outlier vols)
    cord_mask_path: Optional[Path],  # cord mask if available (often the crop ROI ≠ tight seg)
    subject: str = "?",
    dataset_key: str = "?",
    status: str = "UNKNOWN",
    metrics: Optional[dict] = None,
) -> None:
    """Robust funcref view — verify cord signal sanity (no banding,
    no dropouts). Cropped-func data is already centered on the cord,
    so no cord-mask overlay is needed; the operator inspects the
    grayscale image directly for signal uniformity."""
    try:
        if not func_ref_path.exists():
            stub_figure(output_path, "funcref missing")
            return
        funcref, _, zooms = load_canonical(func_ref_path)

        # Use intensity to find the cord-bearing Z range without needing
        # a per-voxel cord seg (which isn't reliably available in
        # cropped func geometry).
        bright = funcref > np.percentile(funcref[funcref > 0], 50) \
            if (funcref > 0).any() else np.ones_like(funcref, dtype=bool)
        # Treat the full cropped FOV as the "cord ROI" — the funcref is
        # already a cord crop. Pass `bright` to the layout helpers as a
        # proxy for the cord centerline; render NO overlay (the funcref
        # itself is the content).
        proxy_mask = bright if bright.any() else np.ones_like(funcref, dtype=bool)

        sag_overlays: list[tuple[np.ndarray, str, float, float]] = []
        def axial_overlays(z):
            return []

        m = metrics or {}
        metric_header = ""
        funcref_mean = m.get("funcref_in_cord_mean")
        funcref_std = m.get("funcref_in_cord_std")
        if funcref_mean is not None:
            metric_header = f"cord signal μ={funcref_mean:.0f}"
            if funcref_std is not None:
                metric_header += f"  σ={funcref_std:.0f}"

        n_volumes = m.get("n_frames_total") or m.get("n_volumes")
        metric_lines = [f"{n_volumes} volumes"] if n_volumes else []

        render_sagittal_plus_montage(
            output_path=output_path,
            title="S3.3 — Robust functional reference",
            subtitle=f"sub-{subject} • {dataset_key}",
            status=status, metric_header=metric_header,
            anat=funcref, cord_mask=proxy_mask,
            sag_overlays=sag_overlays,
            axial_overlays_factory=axial_overlays,
            legend_items=[],
            metric_lines=metric_lines,
            axial_window_vox=None,
            zooms=zooms,
            intensity_pct=(1.0, 99.0),
        )
    except Exception as e:
        stub_figure(output_path, f"funcref_montage render failed: {e}")


# ---------------------------------------------------------------------------
# Single regen helper — called by session.py after the substeps complete
# ---------------------------------------------------------------------------

def regenerate_s3_reportlets(
    run_id: str,
    subject: str,
    session: Optional[str],
    dataset_key: str,
    status: str,
    metrics: dict,
    figures_dir: Path,
    cordref_std_path: Optional[Path],
    func_ref_fast_path: Optional[Path],
    func_ref_path: Optional[Path],
    discovery_seg_path: Optional[Path],
    cord_mask_path: Optional[Path],
    crop_mask_path: Optional[Path],
    frame_metrics_tsv: Optional[Path],
    outlier_mask_json: Optional[Path],
) -> dict[str, Path]:
    """Run all 4 S3 unified renderers, overwriting the standard
    reportlet paths in `figures_dir`. Returns {key: path} for the
    paths actually emitted.

    Inputs are optional — missing inputs cause that specific reportlet
    to emit a stub (and the path is still returned so the dashboard
    has something to display).
    """
    figures_dir.mkdir(parents=True, exist_ok=True)
    out: dict[str, Path] = {}

    # S3.1 — func_localization (full-FOV func space, coarse reference)
    if func_ref_fast_path and discovery_seg_path:
        p = figures_dir / f"{run_id}_desc-S3_func_localization.png"
        render_func_localization(
            p, func_ref_fast_path, discovery_seg_path,
            subject=subject, dataset_key=dataset_key, status=status,
        )
        out["func_localization"] = p

    # S3.2 — frame_metrics
    if frame_metrics_tsv:
        p = figures_dir / f"{run_id}_desc-S3_frame_metrics.png"
        render_frame_metrics(
            p, frame_metrics_tsv, outlier_mask_json,
            subject=subject, dataset_key=dataset_key, status=status,
        )
        out["frame_metrics"] = p

    # S3.3 — crop_box_sagittal (full-FOV func + crop bbox indicator)
    if func_ref_fast_path and discovery_seg_path and func_ref_path:
        p = figures_dir / f"{run_id}_desc-S3_crop_box_sagittal.png"
        render_crop_box_sagittal_s3(
            p, func_ref_fast_path, discovery_seg_path, func_ref_path,
            subject=subject, dataset_key=dataset_key, status=status,
        )
        out["crop_box_sagittal"] = p

    # S3.3 — funcref_montage
    if func_ref_path:
        p = figures_dir / f"{run_id}_desc-S3_funcref_montage.png"
        render_funcref_montage(
            p, func_ref_path, cord_mask_path,
            subject=subject, dataset_key=dataset_key, status=status,
            metrics=metrics,
        )
        out["funcref_montage"] = p

    return out
