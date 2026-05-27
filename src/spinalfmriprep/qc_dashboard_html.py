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
        "func_localization_crop",   # S3.1 - Discovery + Crop
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
    ],
    "S6_func_to_anat_registration": [
        "bold_on_anat_axial",       # S6 - axial overlay BOLD + anat contour + cord seg
        "bold_on_anat_sagittal",    # S6 - mid-sagittal overlay
        "cord_dice_per_slice",      # S6 - per-slice cord Dice bars
    ],
    "S7_template_normalization": [
        "pam50_overlay_sagittal",   # S7 - funcref + PAM50 cord contour (mid-sagittal)
        "pam50_overlay_axial",      # S7 - funcref + PAM50 cord contour (axial montage)
        "vertebral_alignment",      # S7 - vertebral level overlay
    ],
    "S8_confounds_and_physio_regressors": [
        "confound_columns",         # S8 - column counts per family
        "fd_dvars_outliers",        # S8 - FD/DVARS/refRMS with outlier highlights
        "csf_variance",             # S8 - per-slice CSF voxel count
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
        "func_localization_crop": "S3.1 - Discovery + Crop",
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
    },
    "S6_func_to_anat_registration": {
        "bold_on_anat_axial": "S6 - BOLD on Anat (Axial)",
        "bold_on_anat_sagittal": "S6 - BOLD on Anat (Sagittal)",
        "cord_dice_per_slice": "S6 - Cord Dice per Slice",
    },
    "S7_template_normalization": {
        "pam50_overlay_sagittal": "S7 - PAM50 Overlay (Sagittal)",
        "pam50_overlay_axial": "S7 - PAM50 Overlay (Axial)",
        "vertebral_alignment": "S7 - Vertebral Level Alignment",
    },
    "S8_confounds_and_physio_regressors": {
        "confound_columns":    "S8 - Confound Column Counts",
        "fd_dvars_outliers":   "S8 - FD / DVARS / refRMS with Outliers",
        "csf_variance":        "S8 - CSF Voxel Count per Slice",
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


def _generate_workfolder_dropdown_html(workfolder_name: Optional[str], is_index_page: bool) -> tuple[list[str], list[str], list[str]]:
    """
    Generate HTML, CSS, and JavaScript for workfolder dropdown selector.

    Args:
        workfolder_name: Current workfolder name (if known)
        is_index_page: True if generating for index page, False for gallery pages

    Returns:
        Tuple of (css_lines, html_lines, js_lines)
    """
    # CSS styles
    css_lines = [
        ".workfolder-selector { margin: 16px 0; display: flex; align-items: center; gap: 12px; }",
        ".workfolder-selector label { color: #999; font-size: 0.9em; }",
        ".workfolder-selector select {",
        "  background: #2a2a2a;",
        "  color: #e6e6e6;",
        "  border: 1px solid #555;",
        "  padding: 6px 12px;",
        "  border-radius: 4px;",
        "  font-size: 0.9em;",
        "  cursor: pointer;",
        "}",
        ".workfolder-selector select:hover { border-color: #7dcfff; }",
        ".workfolder-selector select:focus { outline: none; border-color: #7dcfff; }",
    ]

    # HTML dropdown markup
    workfolder_label = f"Workfolder: {workfolder_name}" if workfolder_name else "Workfolder:"
    html_lines = [
        "<div class=\"workfolder-selector\">",
        f"<label for=\"workfolder-select\">{workfolder_label}</label>",
        "<select id=\"workfolder-select\">",
        "<option value=\"\" disabled selected>Loading...</option>",
        "</select>",
        "</div>",
    ]

    # JavaScript for dropdown functionality
    js_lines = [
        "<script>",
        "(function() {",
        "  const select = document.getElementById('workfolder-select');",
        "  const currentWf = " + (f"'{workfolder_name}'" if workfolder_name else "null") + ";",
        "",
        "  // Detect mount prefix (e.g. '' on :9002, '/p2' behind a reverse proxy)",
        "  function getMountPrefix() {",
        "    const m = window.location.pathname.match(/^(.*?)(?:\\/wf_[^/]+)?\\/dashboard(?:\\/|$)/);",
        "    return m ? m[1] : '';",
        "  }",
        "  const BASE = getMountPrefix();",
        "",
        "  // Detect current workfolder from URL if not provided",
        "  let detectedWf = currentWf;",
        "  if (!detectedWf) {",
        "    const sub = window.location.pathname.slice(BASE.length);",
        "    const urlMatch = sub.match(/^\\/(wf_[^/]+)\\//);",
        "    if (urlMatch) detectedWf = urlMatch[1];",
        "  }",
        "",
        "  // Determine current page path relative to dashboard root (no BASE)",
        "  function getCurrentPagePath() {",
        "    const sub = window.location.pathname.slice(BASE.length);",
        "    const wfMatch = sub.match(/^\\/(wf_[^/]+)(\\/.*)$/);",
        "    if (wfMatch) {",
        "      // Already has workfolder prefix, extract dashboard path",
        "      return wfMatch[2];",
        "    }",
        "    // No workfolder prefix - should be /dashboard/...",
        "    // If path is just /, default to index",
        "    return sub === '/' || sub === '' ? '/dashboard/index.html' : sub;",
        "  }",
        "",
        "  // Fetch workfolder list",
        "  fetch(BASE + '/__spinalfmriprep__/workfolders.json')",
        "    .then(response => response.json())",
        "    .then(workfolders => {",
        "      select.innerHTML = '';",
        "",
      "      // Add 'Latest' option first",
      "      const latestWf = workfolders.find(wf => wf.is_latest);",
      "      if (latestWf) {",
      "        const option = document.createElement('option');",
      "        option.value = ''; // Empty value means latest (no prefix)",
      "        option.textContent = latestWf.name + ' (latest)';",
      "        if (!detectedWf || detectedWf === latestWf.name) option.selected = true;",
      "        select.appendChild(option);",
      "      }",
      "",
      "      // Add all workfolders (excluding the latest one to avoid duplication)",
      "      workfolders.forEach(wf => {",
      "        if (wf.is_latest) return; // Skip latest - already shown as special option",
      "        const option = document.createElement('option');",
      "        option.value = wf.path;",
      "        option.textContent = wf.name;",
      "        if (detectedWf === wf.name) option.selected = true;",
      "        select.appendChild(option);",
      "      });",
        "    })",
        "    .catch(err => {",
        "      select.innerHTML = '<option value=\"\">Error loading workfolders</option>';",
        "      console.error('Failed to load workfolders:', err);",
        "    });",
        "",
        "  // Handle selection change",
        "  select.addEventListener('change', function() {",
        "    const selectedPath = this.value;",
        "    const currentPagePath = getCurrentPagePath();",
        "",
        "    let targetUrl;",
        "    if (selectedPath) {",
        "      // Specific workfolder selected - prefix the path with BASE + wf name",
        "      targetUrl = BASE + '/' + selectedPath + currentPagePath;",
        "    } else {",
        "      // Latest selected - keep BASE but drop any wf segment",
        "      targetUrl = BASE + currentPagePath;",
        "    }",
        "",
        "    window.location.href = targetUrl;",
        "  });",
        "})();",
        "</script>",
    ]

    return (css_lines, html_lines, js_lines)


def _generate_index_html(
    dashboard_dir: Path,
    step_data: dict[str, dict[str, list[dict]]],
    reportlet_index: dict[str, dict[str, list[dict]]],
    workfolder_name: Optional[str],
    out_dir: Optional[Path] = None,
) -> None:
    """Generate main index.html listing all steps and their reportlets.

    If `out_dir` is provided and S11 has produced a release report, a banner
    is prepended linking to it (S11 emits no per-run reportlets so it would
    otherwise not appear).
    """
    # Get dropdown CSS, HTML, and JS
    dropdown_css, dropdown_html, dropdown_js = _generate_workfolder_dropdown_html(workfolder_name, True)

    lines = [
        "<!DOCTYPE html>",
        "<html>",
        "<head>",
        "<meta charset=\"utf-8\" />",
        "<title>SpinalfMRIprep QC Dashboard</title>",
        "<style>",
        "body { background: #1a1a1a; color: #e6e6e6; font-family: Arial, sans-serif; margin: 20px; }",
        "a { color: #7dcfff; text-decoration: none; }",
        "a:hover { text-decoration: underline; }",
        ".step-card { border: 1px solid #333; padding: 16px; margin: 16px 0; border-radius: 4px; }",
        ".step-card h2 { margin-top: 0; }",
        ".reportlet-list { list-style: none; padding-left: 0; }",
        ".reportlet-list li { margin: 8px 0; }",
        ".reportlet-list a { display: inline-block; padding: 4px 8px; background: #2a2a2a; border-radius: 3px; }",
        ".reportlet-list a:hover { background: #3a3a3a; }",
        ".status-summary { color: #999; font-size: 0.9em; margin-top: 8px; }",
        ".release-banner { border: 1px solid #2a623d; background: #14301e; padding: 16px; margin: 16px 0; border-radius: 6px; }",
        ".release-banner h2 { margin: 0 0 8px 0; color: #7dcfff; }",
        ".release-banner .release-status { display: inline-block; padding: 2px 10px; border-radius: 3px; font-weight: bold; margin-right: 8px; }",
        ".release-banner .status-PASS { background: #14532d; }",
        ".release-banner .status-WARN { background: #7c5e00; }",
        ".release-banner .status-FAIL { background: #7f1d1d; }",
        ".release-banner ul { margin: 12px 0 0 0; padding-left: 20px; }",
        ".release-banner code { background: #222; padding: 1px 4px; border-radius: 2px; }",
    ]
    lines.extend(dropdown_css)
    lines.append("</style>")
    lines.append("</head>")
    lines.append("<body>")
    lines.append("<h1>SpinalfMRIprep QC Dashboard</h1>")
    lines.extend(dropdown_html)

    # S11 release banner — only when S11 has produced artifacts.
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
                        f" &middot; <a href=\"{_relpath(gd_abs, dashboard_dir).replace(chr(92), '/')}\">"
                        "Group QC dashboard</a>"
                    )
            lines.append("<div class=\"release-banner\">")
            lines.append("<h2>S11 — Release Readiness</h2>")
            lines.append(
                f"<span class=\"release-status status-{status}\">{status}</span> "
                f"<a href=\"{rel_link}\">Open release_report.html</a>{group_html}"
            )
            n_sub = metrics.get("n_subjects_aggregated")
            n_runs = metrics.get("n_runs_aggregated")
            n_ds = metrics.get("n_datasets")
            frac = metrics.get("subject_report_fraction")
            issues = metrics.get("sidecar_audit_issues")
            parts = []
            if n_sub is not None:
                parts.append(f"<code>{n_sub}</code> subject(s)")
            if n_runs is not None:
                parts.append(f"<code>{n_runs}</code> run(s)")
            if n_ds is not None:
                parts.append(f"<code>{n_ds}</code> dataset(s)")
            if frac is not None:
                parts.append(f"per-subject reports: <code>{frac * 100:.0f}%</code>")
            if issues is not None:
                parts.append(f"sidecar issues: <code>{issues}</code>")
            if parts:
                lines.append("<ul>")
                for p in parts:
                    lines.append(f"<li>{p}</li>")
                lines.append("</ul>")
            lines.append("</div>")

    if not step_data:
        lines.append("<p>No QC data found.</p>")
    else:
        for step_code in sorted(step_data.keys()):
            datasets = step_data[step_code]
            total_runs = sum(len(runs) for runs in datasets.values())
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
            other = total_runs - passed - warned - failed

            parts = [f"{total_runs} total", f"{passed} passed"]
            if warned:
                parts.append(f"{warned} warned")
            if failed:
                parts.append(f"{failed} failed")
            if other:
                parts.append(f"{other} unknown")

            lines.append(f"<div class=\"step-card\">")
            lines.append(f"<h2>{step_code}</h2>")
            lines.append(f"<div class=\"status-summary\">")
            lines.append("Runs: " + ", ".join(parts))
            lines.append(f"</div>")

            reportlets = reportlet_index.get(step_code, {})
            if reportlets:
                lines.append("<ul class=\"reportlet-list\">")
                for reportlet_key in _sort_reportlets(step_code, list(reportlets.keys())):
                    gallery_path = f"reportlets/{step_code}/{reportlet_key}.html"
                    label = _get_reportlet_label(step_code, reportlet_key)
                    items = reportlets[reportlet_key]
                    count = len(items)
                    # Detect HTML vs image reportlets for accurate label
                    any_html = any(
                        str(it.get("path_abs", "")).lower().endswith((".html", ".htm"))
                        for it in items
                    )
                    noun = "reports" if any_html else "images"
                    lines.append(
                        f"<li><a href=\"{gallery_path}\">{label}</a> ({count} {noun})</li>"
                    )
                lines.append("</ul>")
            else:
                lines.append("<p style=\"color: #999;\">No reportlets available.</p>")
            lines.append("</div>")

    lines.extend(dropdown_js)
    lines.extend(["</body>", "</html>"])
    (dashboard_dir / "index.html").write_text("\n".join(lines), encoding="utf-8")


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

    # Get dropdown CSS, HTML, and JS
    dropdown_css, dropdown_html, dropdown_js = _generate_workfolder_dropdown_html(workfolder_name, False)

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
    lines.extend(dropdown_css)
    lines.append("</style>")
    lines.append("</head>")
    lines.append("<body>")
    lines.append(f"<h1>{step_code} / {label}</h1>")
    lines.extend(dropdown_html)

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

    lines.extend(dropdown_js)
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
