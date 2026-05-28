"""
HTML/CSS/JS template generation for SpinalfMRIprep QC dashboard.

Separated from qc_dashboard.py to keep each module under 500 lines.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional


# Explicit reportlet ordering per step (matching ROADMAP milestones)
REPORTLET_ORDER: dict[str, list[str]] = {
    "S1_input_verify": [
        "dataset_summary",          # S1 - per-dataset inventory + check summary
    ],
    "S2_anat_cordref": [
        "crop_box_sagittal",        # S2.1 - Discovery + Crop
        "cordmask_montage",         # S2.2 - Cord Segmentation (sct_deepseg spinalcord)
        "totalspineseg_montage",    # S2.2 - Spine Anatomy (TotalSpineSeg: vertebrae + discs + canal)
        "rootlets_montage",         # S2.3 - Rootlets segmentation
        "pam50_reg_overlay",        # S2.4 - PAM50 registration
    ],
    "S3_func_init_and_crop": [
        "func_localization",        # S3.1 - Func localization (coarse ref + cord seg)
        "frame_metrics",            # S3.2 - Outlier gating
        "crop_box_sagittal",        # S3.3 - Cord-focused crop
        "funcref_montage",          # S3.3 - Robust funcref
    ],
    "S4_func_motion_correction": [
        "S4_motion_traces",         # S4 - Motion parameter traces
        "S4_dvars_plot",            # S4 - DVARS timeseries
        "S4_tsnr_comparison",       # S4 - tSNR before/after (THE moco-quality reportlet)
    ],
    "S5_func_distortion_correction": [
        "slice_displacement",       # S5 - per-slice A–P cord displacement (CoSpine)
        "cord_dice_per_slice",      # S5 - per-slice 2D cord-Dice (CoSpine)
        "distortion_effectiveness", # S5 - visual Before/After + anat overlay
    ],
    "S6_func_to_anat_registration": [
        "bold_on_anat",             # S6 - composite: sagittal pair + axial montage (BOLD + Anat)
        "cord_dice_per_slice",      # S6 - per-slice cord Dice bars
    ],
    "S7_template_normalization": [
        "pam50_on_func",            # S7 - composite: sagittal pair + axial montage (funcref + PAM50 cord + EPI cord)
        "cord_dice_per_level",      # S7 - per-vertebral-level cord Dice bars
    ],
    "S8_confounds_and_physio_regressors": [
        "confound_columns",         # S8 - column counts per family
        "fd_dvars_outliers",        # S8 - FD/DVARS/refRMS with outlier highlights
        "pnm_peaks",                # S8 - FSL PNM cardiac/respiratory peak detection
        "correlation_heatmap",      # S8 - confound correlation matrix
    ],
    "S9_primary_functional_derivatives": [
        "smoothed_vs_unsmoothed_axial",  # S9 - axial montage before/after smoothing
        "tsnr_map_axial",                # S9 - tSNR map montage
        "tsnr_per_level",                # S9 - per-vertebral-level tSNR bars
        "smoothness_summary",            # S9 - requested vs measured FWHM
    ],
    "S10_roi_timeseries_and_connectivity": [
        "hemicord_timeseries",           # S10 - hemicord×seg ROI timeseries panels
        "hemicord_connectivity",         # S10 - Fisher-z connectivity heatmap
        "vertlvl_tsnr",                  # S10 - per-vertebral-level tSNR bars
        "reliability_icc",               # S10 - cross-session agreement bars
        "reliability_dice",              # S10 - spatial Dice per seed
    ],
}

# Human-readable labels for reportlets (matching ROADMAP milestones)
REPORTLET_LABELS: dict[str, dict[str, str]] = {
    "S1_input_verify": {
        "dataset_summary": "S1 - Inventory + Checks Summary",
    },
    "S2_anat_cordref": {
        "crop_box_sagittal": "S2.1 - Discovery + Crop",
        "cordmask_montage": "S2.2 - Cord Segmentation",
        "totalspineseg_montage": "S2.2 - Spine Anatomy (TSS)",
        "rootlets_montage": "S2.3 - Rootlets Segmentation",
        "pam50_reg_overlay": "S2.4 - PAM50 Registration",
    },
    "S3_func_init_and_crop": {
        "func_localization": "S3.1 - Func Localization",
        "frame_metrics": "S3.2 - Frame Metrics (Outlier Gating)",
        "crop_box_sagittal": "S3.3 - Cord-focused Crop",
        "funcref_montage": "S3.3 - Robust Functional Reference",
    },
    "S4_func_motion_correction": {
        "S4_motion_traces": "S4 - Motion Parameter Traces",
        "S4_dvars_plot": "S4 - DVARS Timeseries",
        "S4_tsnr_comparison": "S4 - tSNR Before/After",
    },
    "S5_func_distortion_correction": {
        "slice_displacement": "S5 - Cord A-P Displacement per Slice",
        "cord_dice_per_slice": "S5 - Cord Dice per Slice (EPI ∩ anat)",
        "distortion_effectiveness": "S5 - Distortion Correction (Before vs After)",
    },
    "S6_func_to_anat_registration": {
        "bold_on_anat": "S6 - BOLD on Anat (Composite)",
        "cord_dice_per_slice": "S6 - Cord Dice per Slice",
    },
    "S7_template_normalization": {
        "pam50_on_func": "S7 - PAM50 on Func (Composite)",
        "cord_dice_per_level": "S7 - Cord Dice per Vertebral Level",
    },
    "S8_confounds_and_physio_regressors": {
        "confound_columns":    "S8 - Confound Column Counts",
        "fd_dvars_outliers":   "S8 - FD / DVARS / refRMS with Outliers",
        "pnm_peaks":           "S8 - PNM Cardiac/Respiratory Peaks",
        "correlation_heatmap": "S8 - Confound Correlation Heatmap",
    },
    "S9_primary_functional_derivatives": {
        "smoothed_vs_unsmoothed_axial": "S9 - Smoothed vs Unsmoothed (Axial)",
        "tsnr_map_axial":               "S9 - Native tSNR Map (Axial)",
        "tsnr_per_level":               "S9 - tSNR per Vertebral Level",
        "smoothness_summary":           "S9 - Requested vs Measured FWHM",
    },
    "S10_roi_timeseries_and_connectivity": {
        "hemicord_timeseries":   "S10 - Hemicord ROI Timeseries",
        "hemicord_connectivity": "S10 - Hemicord Fisher-z Connectivity",
        "vertlvl_tsnr":          "S10 - Per-Vertebral-Level tSNR",
        "reliability_icc":       "S10 - Cross-Session ICC (multi-session)",
        "reliability_dice":      "S10 - Spatial Dice (multi-session)",
    },
}


def _sort_reportlets(step_code: str, reportlet_keys: list[str]) -> list[str]:
    """Sort reportlets by explicit order if defined, else alphabetically."""
    if step_code in REPORTLET_ORDER:
        order = REPORTLET_ORDER[step_code]
        # Sort by explicit order; unknown keys go to the end alphabetically
        def key_fn(k: str) -> tuple[int, int | str]:
            try:
                return (0, order.index(k))
            except ValueError:
                return (1, k)
        return sorted(reportlet_keys, key=key_fn)
    return sorted(reportlet_keys)


def _get_reportlet_label(step_code: str, reportlet_key: str) -> str:
    """Get display label for a reportlet, using explicit mapping if available."""
    if step_code in REPORTLET_LABELS and reportlet_key in REPORTLET_LABELS[step_code]:
        return REPORTLET_LABELS[step_code][reportlet_key]
    return reportlet_key.replace("_", " ").title()


def _generate_index_html(
    dashboard_dir: Path,
    step_data: dict[str, dict[str, list[dict]]],
    reportlet_index: dict[str, dict[str, list[dict]]],
    workfolder_name: Optional[str],
    out_dir: Optional[Path] = None,
    locked_step_codes: Optional[set[str]] = None,
    source_wf_per_step: Optional[dict[str, str]] = None,
    view_label: Optional[str] = None,
) -> None:
    """Generate main index.html listing all steps and their reportlets.

    If `out_dir` is provided and S11 has produced a release report, a banner
    is prepended linking to it (S11 emits no per-run reportlets so it would
    otherwise not appear).

    ``locked_step_codes`` marks steps whose source was pinned via the
    work/done/<scope>/Sn symlink — renders a LOCKED pill on the step card.
    ``source_wf_per_step`` puts a small "src: wf_..." caption under each
    step card so the user can see which wf each step came from.
    ``view_label`` overrides the topbar wf chip with a scope-view label
    (e.g. "reg view"); used by the stitched dashboard.
    """
    locked_step_codes = locked_step_codes or set()
    source_wf_per_step = source_wf_per_step or {}
    lines = [
        "<!DOCTYPE html>",
        "<html>",
        "<head>",
        "<meta charset=\"utf-8\" />",
        "<meta http-equiv=\"Cache-Control\" content=\"no-cache, no-store, must-revalidate\" />",
        "<meta http-equiv=\"Pragma\" content=\"no-cache\" />",
        "<meta http-equiv=\"Expires\" content=\"0\" />",
        "<title>SpinalfMRIprep QC</title>",
        "<style>",
        # Page base
        "body { background: #0f1115; color: #e6e8ec;"
        " font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;"
        " margin: 0; padding: 18px 24px; font-size: 13px; }",
        "a { color: #7dcfff; text-decoration: none; }",
        "a:hover { text-decoration: underline; }",
        "code { font-family: 'SF Mono', Menlo, Consolas, monospace; }",
        # Title row
        ".topbar { display: flex; align-items: baseline; gap: 12px;"
        " padding-bottom: 12px; border-bottom: 1px solid #2a2e36;"
        " margin-bottom: 14px; }",
        ".topbar h1 { font-size: 15px; font-weight: 700; margin: 0;"
        " color: #e6e8ec; letter-spacing: 0.3px; }",
        ".topbar .wf { font-family: 'SF Mono', Menlo, Consolas, monospace;"
        " background: #1a1d23; border: 1px solid #2a2e36;"
        " padding: 2px 8px; border-radius: 3px; color: #9ca3af;"
        " font-size: 12px; }",
        ".topbar .tutorial-chip { margin-left: auto; }",
        ".topbar .tutorial-link { background: #1a1d23;"
        " border: 1px solid #2a2e36; padding: 2px 10px;"
        " border-radius: 3px; color: #7dcfff; font-size: 12px; }",
        ".topbar .tutorial-link:hover { background: #2a2e36;"
        " text-decoration: none; }",
        # Step rows
        ".step { display: grid; grid-template-columns: 220px 1fr;"
        " gap: 16px; padding: 10px 0; border-bottom: 1px solid #1a1d23;"
        " align-items: center; }",
        ".step:last-child { border-bottom: 0; }",
        ".step .name { font-family: 'SF Mono', Menlo, Consolas, monospace;"
        " font-weight: 700; color: #e6e8ec; font-size: 13px; }",
        ".step .badges { font-size: 11px; color: #6b7280;"
        " margin-top: 3px; }",
        ".badges .pill { display: inline-block; padding: 1px 7px;"
        " border-radius: 3px; font-weight: 700; margin-right: 4px; }",
        ".badges .pill.pass { background: #14532d; color: #22c55e; }",
        ".badges .pill.warn { background: #3a2f00; color: #f59e0b; }",
        ".badges .pill.fail { background: #3a1010; color: #ef4444; }",
        ".badges .pill.lock { background: #1f2a3f; color: #93c5fd;"
        " border: 1px solid #3b4a6a; font-size: 10px;"
        " padding: 1px 6px; margin-right: 4px; }",
        ".step .src { font-family: 'SF Mono', Menlo, Consolas, monospace;"
        " color: #6b7280; font-size: 10px; margin-top: 2px; }",
        ".step .links { display: flex; flex-wrap: wrap; gap: 6px; }",
        ".step .links a { display: inline-block; padding: 3px 10px;"
        " background: #1a1d23; border: 1px solid #2a2e36;"
        " border-radius: 3px; font-size: 12px; }",
        ".step .links a:hover { background: #2a2e36; }",
        ".step .empty { color: #6b7280; font-style: italic;"
        " font-size: 12px; }",
        # S11 release banner (compact)
        ".release { background: #14301e; border: 1px solid #2a623d;"
        " border-radius: 4px; padding: 10px 14px; margin: 6px 0 14px 0;"
        " display: flex; gap: 16px; align-items: center;"
        " flex-wrap: wrap; }",
        ".release b { color: #7dcfff; font-size: 13px; }",
        ".release .stat { color: #9ca3af; font-size: 12px; }",
        ".release .stat code { background: #1a1d23; padding: 1px 5px;"
        " border-radius: 2px; color: #e6e8ec; }",
        ".release-status { padding: 2px 8px; border-radius: 3px;"
        " font-weight: 700; font-size: 11px; }",
        ".release-status.status-PASS { background: #14532d; color: #22c55e; }",
        ".release-status.status-WARN { background: #3a2f00; color: #f59e0b; }",
        ".release-status.status-FAIL { background: #3a1010; color: #ef4444; }",
        "</style>",
        "</head>",
        "<body>",
    ]

    # Topbar: single line — "QC · <wf_name_chip> · tutorial link".
    # The tutorial link is mounted-prefix-aware: when served via the
    # /p2 reverse proxy the absolute /p2/tutorial path is required;
    # we compute it from window.location at click time via a tiny
    # inline onclick so the same generated HTML works when opened
    # directly off disk (file://...) too.
    if view_label:
        wf_chip = f"<code class=\"wf\">{view_label}</code>"
    else:
        wf_chip = f"<code class=\"wf\">{workfolder_name}</code>" if workfolder_name else ""
    tutorial_link = (
        "<a href=\"#\" class=\"tutorial-link\""
        " onclick=\"event.preventDefault();"
        " var m = window.location.pathname.match(/^(.*?)(?:\\/wf_[^/]+)?\\/dashboard/);"
        " window.location.href = (m ? m[1] : '') + '/tutorial';\""
        " title=\"Algorithms + metrics reference\">tutorial</a>"
    )
    lines.append(
        f"<div class=\"topbar\"><h1>SpinalfMRIprep QC</h1>"
        f"{wf_chip}<span class=\"tutorial-chip\">{tutorial_link}</span>"
        f"</div>"
    )

    # Compact scope banner — only the current scope's card; other
    # scopes collapse to a chip row.
    #
    # Two cases:
    # (a) stitched view  (out_dir = work/done/<scope>/_view/) — emit
    #     URL-relative scope buttons that work under the FastAPI
    #     ``/{scope}/dashboard/`` routes.
    # (b) per-wf dashboard (out_dir = work/wf_*/) — fall back to the
    #     legacy filesystem-relative banner from dashboard_latest.
    if out_dir is not None:
        stitched_scope = _stitched_scope_of(out_dir)
        if stitched_scope is not None:
            lines.append(_render_stitched_scope_buttons(stitched_scope))
        else:
            try:
                from .dashboard_latest import render_scope_banner
                cursor = Path(out_dir).resolve()
                for _ in range(4):
                    if cursor.name == "work":
                        current_scope = _infer_scope_from_wfname(workfolder_name)
                        lines.append(render_scope_banner(
                            cursor, dashboard_dir,
                            current_scope=current_scope,
                        ))
                        break
                    cursor = cursor.parent
            except Exception:
                pass

    # Compact S11 release banner — single row instead of header + list.
    if out_dir is not None:
        s11_qc_path = out_dir / "logs" / "S11_qc_aggregation_and_release" / "qc.json"
        rel_report = out_dir / "derivatives" / "spinalfmriprep" / "release_report.html"
        if s11_qc_path.exists() and rel_report.exists():
            try:
                s11_qc = json.loads(s11_qc_path.read_text(encoding="utf-8"))
            except Exception:
                s11_qc = {}
            status = s11_qc.get("status", "UNKNOWN")
            metrics = s11_qc.get("metrics", {}) or {}
            rel_link = _relpath(rel_report, dashboard_dir).replace("\\", "/")
            deliv = s11_qc.get("deliverables", {}) or {}
            group_link = deliv.get("group_dashboard")
            group_html = ""
            if group_link:
                gd_abs = out_dir / group_link
                if gd_abs.exists():
                    group_html = (
                        f"&nbsp;·&nbsp;<a href=\"{_relpath(gd_abs, dashboard_dir).replace(chr(92), '/')}\">"
                        "group</a>"
                    )
            stats = []
            n_sub = metrics.get("n_subjects_aggregated")
            n_runs = metrics.get("n_runs_aggregated")
            n_ds = metrics.get("n_datasets")
            frac = metrics.get("subject_report_fraction")
            if n_sub is not None and n_runs is not None and n_ds is not None:
                stats.append(
                    f"<span class=\"stat\"><code>{n_sub}</code> subj &middot; "
                    f"<code>{n_runs}</code> runs &middot; <code>{n_ds}</code> ds</span>"
                )
            if frac is not None:
                stats.append(
                    f"<span class=\"stat\">reports <code>{frac * 100:.0f}%</code></span>"
                )
            lines.append(
                f"<div class=\"release\">"
                f"<b>S11 release</b>"
                f"<span class=\"release-status status-{status}\">{status}</span>"
                f"<a href=\"{rel_link}\">open report</a>{group_html}"
                f"{''.join(stats)}"
                f"</div>"
            )

    if not step_data:
        lines.append("<p style=\"color:#6b7280;\">No QC data found.</p>")
    else:
        for step_code in sorted(step_data.keys(), key=_step_sort_key):
            datasets = step_data[step_code]
            passed = sum(
                sum(1 for r in runs if r.get("status") == "PASS")
                for runs in datasets.values()
            )
            warned = sum(
                sum(1 for r in runs if r.get("status") == "WARN")
                for runs in datasets.values()
            )
            failed = sum(
                sum(1 for r in runs if r.get("status") == "FAIL")
                for runs in datasets.values()
            )

            badges = []
            if step_code in locked_step_codes:
                badges.append(
                    "<span class=\"pill lock\" title=\"Approved via "
                    "scripts/mark_done.py; source wf is pinned\">LOCKED</span>"
                )
            if passed:
                badges.append(f"<span class=\"pill pass\">{passed}</span>")
            if warned:
                badges.append(f"<span class=\"pill warn\">{warned}</span>")
            if failed:
                badges.append(f"<span class=\"pill fail\">{failed}</span>")

            reportlets = reportlet_index.get(step_code, {})
            links_html: list[str] = []
            for reportlet_key in _sort_reportlets(step_code, list(reportlets.keys())):
                gallery_path = f"reportlets/{step_code}/{reportlet_key}.html"
                label = _get_reportlet_label(step_code, reportlet_key)
                links_html.append(f"<a href=\"{gallery_path}\">{label}</a>")

            src_wf = source_wf_per_step.get(step_code)
            src_html = (f"<div class=\"src\">src: {src_wf}</div>"
                        if src_wf else "")

            lines.append("<div class=\"step\">")
            lines.append(
                f"<div><div class=\"name\">{step_code}</div>"
                f"<div class=\"badges\">{''.join(badges) if badges else '<span class=\"empty\">—</span>'}</div>"
                f"{src_html}</div>"
            )
            if links_html:
                lines.append(
                    f"<div class=\"links\">{''.join(links_html)}</div>"
                )
            else:
                lines.append("<div class=\"empty\">no reportlets</div>")
            lines.append("</div>")

    lines.extend(["</body>", "</html>"])
    (dashboard_dir / "index.html").write_text("\n".join(lines), encoding="utf-8")


def _stitched_scope_of(out_dir: Path) -> Optional[str]:
    """If ``out_dir`` is a stitched scope view (``work/done/<scope>/_view``),
    return the scope name; else None."""
    try:
        parts = Path(out_dir).resolve().parts
    except Exception:
        return None
    if "done" in parts and "_view" in parts:
        i = parts.index("done")
        if i + 1 < len(parts) and parts[i + 1] in ("reg", "full"):
            return parts[i + 1]
    return None


def _render_stitched_scope_buttons(current_scope: str) -> str:
    """Two-button scope row (reg / full) for the stitched dashboard.

    Emits URL-relative hrefs that resolve correctly under the
    ``/{scope}/dashboard/`` FastAPI routes (and under the ``/p2/``
    Caddy reverse proxy). The current scope is highlighted; the
    other scope links to its stitched view."""
    css = (
        "<style>"
        ".sfp-scope-buttons { display: flex; gap: 8px; margin: 0 0 14px 0; }"
        ".sfp-scope-buttons a, .sfp-scope-buttons span {"
        " display: inline-block; padding: 4px 14px; border-radius: 4px;"
        " font-family: 'SF Mono', Menlo, Consolas, monospace;"
        " font-size: 12px; font-weight: 700; letter-spacing: 1px;"
        " text-transform: uppercase; }"
        ".sfp-scope-buttons a {"
        " background: #1a1d23; border: 1px solid #2a2e36;"
        " color: #9ca3af; text-decoration: none; }"
        ".sfp-scope-buttons a:hover { background: #2a2e36; color: #e6e8ec; }"
        ".sfp-scope-buttons .active {"
        " background: #14532d; color: #22c55e;"
        " border: 1px solid #2a623d; }"
        "</style>"
    )
    cells: list[str] = []
    for scope in ("reg", "full"):
        if scope == current_scope:
            cells.append(f'<span class="active">{scope}</span>')
        else:
            cells.append(
                f'<a href="../../{scope}/dashboard/index.html">{scope}</a>'
            )
    return css + (
        f'<div class="sfp-scope-buttons">{"".join(cells)}</div>'
    )


def _infer_scope_from_wfname(workfolder_name: Optional[str]) -> Optional[str]:
    """Map `wf_reg_071` → "reg", `wf_smoke_045` → "smoke", etc."""
    if not workfolder_name or not workfolder_name.startswith("wf_"):
        return None
    rest = workfolder_name[3:]
    if "_" in rest:
        return rest.split("_", 1)[0]
    return None


def _step_sort_key(step_code: str) -> tuple[int, str]:
    """Numeric-aware sort: S1 < S2 < … < S9 < S10 < S11. Falls back to
    a high sentinel + lexicographic for unrecognised codes."""
    if step_code.startswith("S") and len(step_code) > 1:
        head = step_code[1:].split("_", 1)[0]
        if head.isdigit():
            return (int(head), step_code)
    return (10**6, step_code)


def _generate_reportlet_gallery_html(
    dashboard_dir: Path,
    step_code: str,
    reportlet_key: str,
    images: list[dict],
    workfolder_name: Optional[str],
) -> None:
    """Generate a gallery page for a specific reportlet type, grouped by dataset."""
    gallery_dir = dashboard_dir / "reportlets" / step_code
    gallery_dir.mkdir(parents=True, exist_ok=True)
    gallery_file = gallery_dir / f"{reportlet_key}.html"

    label = _get_reportlet_label(step_code, reportlet_key)

    # Group images by dataset
    images_by_dataset: dict[str, list[dict]] = {}
    for img_info in images:
        dataset = img_info["dataset"]
        if dataset not in images_by_dataset:
            images_by_dataset[dataset] = []
        images_by_dataset[dataset].append(img_info)

    # Sort datasets alphabetically
    sorted_datasets = sorted(images_by_dataset.keys())
    num_datasets = len(sorted_datasets)

    lines = [
        "<!DOCTYPE html>",
        "<html>",
        "<head>",
        "<meta charset=\"utf-8\" />",
        # Force the browser to never cache the dashboard HTML — image
        # cache-bust (?v=mtime) alone is useless if the HTML referencing
        # them is itself served from cache.
        "<meta http-equiv=\"Cache-Control\" content=\"no-cache, no-store, must-revalidate\" />",
        "<meta http-equiv=\"Pragma\" content=\"no-cache\" />",
        "<meta http-equiv=\"Expires\" content=\"0\" />",
        f"<title>{step_code} / {label}</title>",
        "<style>",
        "body { background: #1a1a1a; color: #e6e6e6; font-family: Arial, sans-serif; margin: 20px; }",
        "a { color: #7dcfff; text-decoration: none; }",
        "a:hover { text-decoration: underline; }",
        ".dataset-section { margin: 24px 0; padding: 16px; border: 1px solid #444; border-radius: 6px; background: #222; }",
        ".dataset-header { font-size: 1.1em; font-weight: bold; margin-bottom: 12px; color: #7dcfff; border-bottom: 1px solid #444; padding-bottom: 8px; }",
        ".gallery { display: flex; flex-wrap: wrap; gap: 20px; }",
        ".card { border: 1px solid #333; padding: 12px; border-radius: 4px; background: #2a2a2a; max-width: 400px; }",
        ".card img { width: 100%; height: auto; border: 1px solid #222; }",
        ".card-info { margin-top: 8px; font-size: 0.9em; }",
        ".status-badge { display: inline-block; padding: 2px 6px; border-radius: 3px; font-size: 0.85em; margin-right: 8px; }",
        ".status-PASS { background: #14532d; }",
        ".status-FAIL { background: #7f1d1d; }",
        ".status-UNKNOWN { background: #333; }",
        ".summary-bar { background: #2a2a2a; padding: 12px; border-radius: 4px; margin-bottom: 16px; }",
    ]
    lines.append("</style>")
    lines.append("</head>")
    lines.append("<body>")
    lines.append(f"<h1>{step_code} / {label}</h1>")

    lines.extend([
        "<p><a href=\"../../index.html\">Back to index</a></p>",
        f"<div class=\"summary-bar\">Showing {len(images)} image(s) from {num_datasets} dataset(s)</div>",
    ])

    # Render each dataset section
    for dataset in sorted_datasets:
        dataset_images = images_by_dataset[dataset]

        lines.append(f"<div class=\"dataset-section\">")
        lines.append(f"<div class=\"dataset-header\">{dataset} ({len(dataset_images)} images)</div>")
        lines.append("<div class=\"gallery\">")

        for img_info in dataset_images:
            subject = img_info["subject"]
            session = img_info.get("session")
            path_abs = Path(img_info["path_abs"])
            path_rel_display = img_info.get("path_rel", "")
            status = img_info.get("status", "UNKNOWN")

            # Compute relative path from gallery file's parent directory to reportlet
            reportlet_rel = _relpath(path_abs, gallery_file.parent)
            # Ensure forward slashes for web compatibility
            reportlet_rel = reportlet_rel.replace("\\", "/")

            session_str = f" / {session}" if session else ""
            label_str = f"{subject}{session_str}"

            try:
                 mtime = int(path_abs.stat().st_mtime)
            except OSError:
                 mtime = 0

            # HTML reportlets (e.g. S1 dataset_summary) embed inline as
            # an iframe at full width — the report is just plain tables,
            # no reason to constrain to a 400px image card.
            is_html = str(path_abs).lower().endswith((".html", ".htm"))
            if is_html:
                lines.append(
                    f"<div style=\"flex:1 1 100%;max-width:100%;\">"
                    f"<iframe src=\"{reportlet_rel}?v={mtime}\" "
                    f"style=\"width:100%;height:420px;border:1px solid #333;"
                    f"border-radius:4px;background:#0f1115;\"></iframe>"
                    f"</div>"
                )
            else:
                lines.append("<div class=\"card\">")
                lines.append(f"<img src=\"{reportlet_rel}?v={mtime}\" alt=\"{dataset} / {label_str}\" />")
                lines.append("<div class=\"card-info\">")
                lines.append(f"<span class=\"status-badge status-{status}\">{status}</span>")
                lines.append(f"<span>{label_str}</span><br/>")
                lines.append(f"<span style=\"color: #999; font-size: 0.85em;\">{path_rel_display}</span>")
                lines.append("</div>")
                lines.append("</div>")

        lines.append("</div>")  # Close gallery
        lines.append("</div>")  # Close dataset-section

    lines.extend(["</body>", "</html>"])

    gallery_file = gallery_dir / f"{reportlet_key}.html"
    gallery_file.write_text("\n".join(lines), encoding="utf-8")


def _relpath(target: Path, base: Path) -> str:
    """Compute relative path from base to target by pure path arithmetic.

    Must NOT follow symlinks - chain reportlets are materialised as symlinks
    inside the workfolder and the browser URL needs to address them at their
    in-workfolder path, not at their resolved location in the upstream
    workfolder.
    """
    try:
        return str(target.relative_to(base))
    except ValueError:
        # Fallback: use absolute (NOT resolved) parts so symlinks stay symbolic
        target_parts = target.absolute().parts
        base_parts = base.absolute().parts

        # Find common prefix
        common_len = 0
        for i in range(min(len(target_parts), len(base_parts))):
            if target_parts[i] == base_parts[i]:
                common_len += 1
            else:
                break

        # Build relative path
        up_levels = len(base_parts) - common_len
        rel_parts = [".."] * up_levels + list(target_parts[common_len:])
        return "/".join(rel_parts)
