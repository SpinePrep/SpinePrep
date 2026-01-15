"""
QC Dashboard generator for SpinePrep workflows.

Scans QC JSON files and generates HTML dashboard with reportlet galleries.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# Explicit reportlet ordering per step (matching ROADMAP milestones)
REPORTLET_ORDER: dict[str, list[str]] = {
    "S2_anat_cordref": [
        "crop_box_sagittal",        # S2.1 - Discovery + Crop
        "centerline_montage",       # S2.2 - Center Line
        "cordmask_montage",         # S2.2 - Cord Mask
        "vertebral_labels_montage", # S2.3 - Vertebral labeling
        "rootlets_montage",         # S2.4 - Rootlets segmentation
        "pam50_reg_overlay",        # S2.5 - PAM50 registration
    ],
    "S3_func_init_and_crop": [
        "func_localization_crop",   # S3.1 - Discovery + Crop
        "frame_metrics",            # S3.2 - Outlier gating
        "crop_box_sagittal",        # S3.3 - Cord-focused crop
        "funcref_montage",          # S3.3 - Robust funcref
    ],
}

# Human-readable labels for reportlets (matching ROADMAP milestones)
REPORTLET_LABELS: dict[str, dict[str, str]] = {
    "S2_anat_cordref": {
        "crop_box_sagittal": "S2.1 - Discovery + Crop",
        "centerline_montage": "S2.2 - Center Line",
        "cordmask_montage": "S2.2 - Cord Mask",
        "vertebral_labels_montage": "S2.3 - Vertebral labeling",
        "rootlets_montage": "S2.4 - Rootlets segmentation",
        "pam50_reg_overlay": "S2.5 - PAM50 registration",
    },
    "S3_func_init_and_crop": {
        "func_localization_crop": "S3.1 - Discovery + Crop",
        "frame_metrics": "S3.2 - Frame Metrics (Outlier Gating)",
        "crop_box_sagittal": "S3.3 - Cord-focused Crop",
        "funcref_montage": "S3.3 - Robust Functional Reference",
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
        "  // Detect current workfolder from URL if not provided",
        "  let detectedWf = currentWf;",
        "  if (!detectedWf) {",
        "    const urlMatch = window.location.pathname.match(/^\\/(wf_[^/]+)\\//);",
        "    if (urlMatch) detectedWf = urlMatch[1];",
        "  }",
        "",
        "  // Determine current page path relative to dashboard root",
        "  function getCurrentPagePath() {",
        "    const path = window.location.pathname;",
        "    const wfMatch = path.match(/^\\/(wf_[^/]+)(\\/.*)$/);",
        "    if (wfMatch) {",
        "      // Already has workfolder prefix, extract dashboard path",
        "      return wfMatch[2];",
        "    }",
        "    // No workfolder prefix - should be /dashboard/...",
        "    // If path is just /, default to index",
        "    return path === '/' ? '/dashboard/index.html' : path;",
        "  }",
        "",
        "  // Fetch workfolder list",
        "  fetch('/__spineprep__/workfolders.json')",
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
        "      // Specific workfolder selected - prefix the path",
        "      targetUrl = '/' + selectedPath + currentPagePath;",
        "    } else {",
        "      // Latest selected - use path as-is (should already be /dashboard/...)",
        "      targetUrl = currentPagePath;",
        "    }",
        "",
        "    window.location.href = targetUrl;",
        "  });",
        "})();",
        "</script>",
    ]
    
    return (css_lines, html_lines, js_lines)


def _extract_workfolder_name(out_dir: Path) -> Optional[str]:
    """
    Extract workfolder name from path, if present.
    
    Recognizes canonical patterns:
    - wf_smoke_XXX
    - wf_reg_XXX
    - wf_full_XXX
    
    Also supports legacy wf_XXX pattern (numeric) and any wf_* pattern for backward compatibility.
    """
    # Search all path components for wf_* pattern
    for part in out_dir.parts:
        if part.startswith("wf_") and len(part) > 3:
            # Prefer canonical patterns (wf_smoke_*, wf_reg_*, wf_full_*)
            if part.startswith(("wf_smoke_", "wf_reg_", "wf_full_")):
                return part
            # Fallback to legacy wf_* pattern (numeric) or any wf_* pattern
            elif re.match(r"wf_\d+$", part) or part.startswith("wf_"):
                return part
    return None


@dataclass
class DashboardResult:
    """Result of dashboard generation."""
    indexed_qc_files: int
    dashboard_dir: Path
    errors: list[str]


def generate_dashboard(out_dir: Path) -> DashboardResult:
    """
    Generate QC dashboard HTML from QC JSON files under out_dir/logs.
    
    Scans for qc.json files, collects reportlets, and generates:
    - out_dir/dashboard/index.html (step list with reportlet links)
    - out_dir/dashboard/reportlets/<STEP>/<REPORTLET>.html (galleries)
    
    Returns DashboardResult with counts and any errors.
    """
    out_dir = Path(out_dir)
    dashboard_dir = out_dir / "dashboard"
    dashboard_dir.mkdir(parents=True, exist_ok=True)
    
    # Extract workfolder name from path
    workfolder_name = _extract_workfolder_name(out_dir)
    
    # Scan for QC JSON files: support both structures
    # New structure: logs/<STEP>/<DATASET>/qc.json
    # Legacy structure: logs/<STEP>_qc.json
    # Also scan subdirectories: <DATASET_KEY>/logs/<STEP>_qc.json or <DATASET_KEY>/logs/<STEP>/<DATASET>/qc.json
    qc_files: list[tuple[Path, str, str, Path]] = []  # (qc_path, step_code, dataset_key, base_dir_for_paths)
    
    # First, scan top-level logs directory
    logs_dir = out_dir / "logs"
    if logs_dir.exists():
        # New structure: logs/<STEP>/<DATASET>/qc.json
        for step_dir in logs_dir.iterdir():
            if not step_dir.is_dir():
                continue
            # Skip evidence bundles (internal debugging, not for dashboard display)
            if step_dir.name.endswith("_evidence"):
                continue
            for dataset_dir in step_dir.iterdir():
                if not dataset_dir.is_dir():
                    continue
                qc_path = dataset_dir / "qc.json"
                if qc_path.exists():
                    step_code = step_dir.name
                    dataset_key = dataset_dir.name
                    qc_files.append((qc_path, step_code, dataset_key, out_dir))
        
        # Legacy structure: logs/<STEP>_qc.json
        for qc_file in logs_dir.glob("*_qc.json"):
            if qc_file.is_file():
                # Extract step code from filename: S1_input_verify_qc.json -> S1_input_verify
                step_code = qc_file.stem.replace("_qc", "")
                # Try to extract dataset_key from QC JSON content
                try:
                    with open(qc_file, "r", encoding="utf-8") as f:
                        qc_data = json.load(f)
                    dataset_key = qc_data.get("dataset_key", "unknown")
                except Exception:
                    dataset_key = "unknown"
                qc_files.append((qc_file, step_code, dataset_key, out_dir))
    
    # Also scan subdirectories (for datasets organized as out_dir/{dataset_key}/logs/...)
    for item in out_dir.iterdir():
        if not item.is_dir():
            continue
        # Skip common non-dataset directories
        if item.name in ("dashboard", "work", "logs", "derivatives"):
            continue
        
        # Check if this looks like a dataset subdirectory (contains logs/)
        sub_logs_dir = item / "logs"
        if not sub_logs_dir.exists():
            continue
        
        # Extract dataset_key from subdirectory name
        potential_dataset_key = item.name
        
        # Scan this subdirectory's logs for QC files
        # New structure: {dataset_key}/logs/<STEP>/<DATASET>/qc.json
        for step_dir in sub_logs_dir.iterdir():
            if not step_dir.is_dir():
                continue
            if step_dir.name.endswith("_evidence"):
                continue
            for dataset_dir in step_dir.iterdir():
                if not dataset_dir.is_dir():
                    continue
                qc_path = dataset_dir / "qc.json"
                if qc_path.exists():
                    step_code = step_dir.name
                    dataset_key = dataset_dir.name
                    qc_files.append((qc_path, step_code, dataset_key, item))
        
        # Legacy structure: {dataset_key}/logs/<STEP>_qc.json
        for qc_file in sub_logs_dir.glob("*_qc.json"):
            if qc_file.is_file():
                step_code = qc_file.stem.replace("_qc", "")
                # Use subdirectory name as dataset_key, but also check QC JSON
                try:
                    with open(qc_file, "r", encoding="utf-8") as f:
                        qc_data = json.load(f)
                    dataset_key = qc_data.get("dataset_key", potential_dataset_key)
                except Exception:
                    dataset_key = potential_dataset_key
                qc_files.append((qc_file, step_code, dataset_key, item))  # base_dir is the dataset subdirectory
    
    if not qc_files:
        return DashboardResult(
            indexed_qc_files=0,
            dashboard_dir=dashboard_dir,
            errors=[],
        )
    
    # Collect QC data: step -> dataset -> runs -> reportlets
    step_data: dict[str, dict[str, list[dict]]] = {}
    reportlet_index: dict[str, dict[str, list[dict]]] = {}  # step -> reportlet_key -> list of {dataset, subject, session, path}
    errors: list[str] = []
    
    for qc_path, step_code, dataset_key, base_dir in qc_files:
        try:
            with open(qc_path, "r", encoding="utf-8") as f:
                qc = json.load(f)
            
            if step_code not in step_data:
                step_data[step_code] = {}
            if dataset_key not in step_data[step_code]:
                step_data[step_code][dataset_key] = []
            
            runs = qc.get("runs", [])
            step_data[step_code][dataset_key].extend(runs)
            
            # Index reportlets
            if step_code not in reportlet_index:
                reportlet_index[step_code] = {}
            
            for run in runs:
                reportlets = run.get("reportlets", {})
                for reportlet_key, reportlet_path in reportlets.items():
                    if not reportlet_path:
                        continue
                    if reportlet_key not in reportlet_index[step_code]:
                        reportlet_index[step_code][reportlet_key] = []
                    
                    # Resolve absolute path relative to base_dir (which may be a dataset subdirectory)
                    reportlet_abs = base_dir / reportlet_path
                    if not reportlet_abs.exists():
                        errors.append(f"Missing reportlet: {reportlet_abs}")
                        continue
                    
                    # Store absolute path; we'll compute relative path later from the gallery file location
                    reportlet_abs_str = str(reportlet_abs)
                    
                    reportlet_index[step_code][reportlet_key].append({
                        "dataset": dataset_key,
                        "subject": run.get("subject", "unknown"),
                        "session": run.get("session"),
                        "path_abs": reportlet_abs_str,
                        "path_rel": reportlet_path,  # Keep original relative path for display
                        # Prefer per-reportlet status (if present), fall back to run status.
                        "status": (
                            ((run.get("reportlets_detail") or {}).get(reportlet_key) or {}).get("status")
                            or run.get("status", "UNKNOWN")
                        ),
                    })
        except Exception as e:
            errors.append(f"Failed to process {qc_path}: {e}")
    
    # Generate index.html
    _generate_index_html(dashboard_dir, step_data, reportlet_index, workfolder_name)
    
    # Generate reportlet gallery pages
    for step_code, reportlets in reportlet_index.items():
        for reportlet_key, images in reportlets.items():
            _generate_reportlet_gallery_html(
                dashboard_dir, step_code, reportlet_key, images, workfolder_name
            )
    
    return DashboardResult(
        indexed_qc_files=len(qc_files),
        dashboard_dir=dashboard_dir,
        errors=errors,
    )


def _generate_index_html(
    dashboard_dir: Path,
    step_data: dict[str, dict[str, list[dict]]],
    reportlet_index: dict[str, dict[str, list[dict]]],
    workfolder_name: Optional[str],
) -> None:
    """Generate main index.html listing all steps and their reportlets."""
    # Get dropdown CSS, HTML, and JS
    dropdown_css, dropdown_html, dropdown_js = _generate_workfolder_dropdown_html(workfolder_name, True)
    
    lines = [
        "<!DOCTYPE html>",
        "<html>",
        "<head>",
        "<meta charset=\"utf-8\" />",
        "<title>SpinePrep QC Dashboard</title>",
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
    ]
    lines.extend(dropdown_css)
    lines.append("</style>")
    lines.append("</head>")
    lines.append("<body>")
    lines.append("<h1>SpinePrep QC Dashboard</h1>")
    lines.extend(dropdown_html)
    
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
            failed = total_runs - passed
            
            lines.append(f"<div class=\"step-card\">")
            lines.append(f"<h2>{step_code}</h2>")
            lines.append(f"<div class=\"status-summary\">")
            lines.append(f"Runs: {total_runs} total, {passed} passed, {failed} failed")
            lines.append(f"</div>")
            
            reportlets = reportlet_index.get(step_code, {})
            if reportlets:
                lines.append("<ul class=\"reportlet-list\">")
                for reportlet_key in _sort_reportlets(step_code, list(reportlets.keys())):
                    gallery_path = f"reportlets/{step_code}/{reportlet_key}.html"
                    label = _get_reportlet_label(step_code, reportlet_key)
                    count = len(reportlets[reportlet_key])
                    lines.append(
                        f"<li><a href=\"{gallery_path}\">{label}</a> ({count} images)</li>"
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
    """Generate a gallery page for a specific reportlet type."""
    gallery_dir = dashboard_dir / "reportlets" / step_code
    gallery_dir.mkdir(parents=True, exist_ok=True)
    gallery_file = gallery_dir / f"{reportlet_key}.html"
    
    label = _get_reportlet_label(step_code, reportlet_key)
    
    # Get dropdown CSS, HTML, and JS
    dropdown_css, dropdown_html, dropdown_js = _generate_workfolder_dropdown_html(workfolder_name, False)
    
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
        ".gallery { display: flex; flex-wrap: wrap; gap: 20px; }",
        ".card { border: 1px solid #333; padding: 12px; border-radius: 4px; background: #2a2a2a; max-width: 400px; }",
        ".card img { width: 100%; height: auto; border: 1px solid #222; }",
        ".card-info { margin-top: 8px; font-size: 0.9em; }",
        ".status-badge { display: inline-block; padding: 2px 6px; border-radius: 3px; font-size: 0.85em; margin-right: 8px; }",
        ".status-PASS { background: #14532d; }",
        ".status-FAIL { background: #7f1d1d; }",
        ".status-UNKNOWN { background: #333; }",
    ]
    lines.extend(dropdown_css)
    lines.append("</style>")
    lines.append("</head>")
    lines.append("<body>")
    lines.append(f"<h1>{step_code} / {label}</h1>")
    lines.extend(dropdown_html)
    
    lines.extend([
        "<p><a href=\"../../index.html\">Back to index</a></p>",
        f"<p>Showing {len(images)} image(s)</p>",
        "<div class=\"gallery\">",
    ])
    
    for img_info in images:
        dataset = img_info["dataset"]
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
        label_str = f"{dataset} / {subject}{session_str}"
        
        lines.append("<div class=\"card\">")
        # Get mtime for cache busting
        try:
             mtime = int(path_abs.stat().st_mtime)
        except OSError:
             mtime = 0
             
        lines.append(f"<img src=\"{reportlet_rel}?v={mtime}\" alt=\"{label_str}\" />")
        lines.append("<div class=\"card-info\">")
        lines.append(f"<span class=\"status-badge status-{status}\">{status}</span>")
        lines.append(f"<span>{label_str}</span><br/>")
        lines.append(f"<span style=\"color: #999; font-size: 0.85em;\">{path_rel_display}</span>")
        lines.append("</div>")
        lines.append("</div>")
    
    lines.extend(["</div>"])
    lines.extend(dropdown_js)
    lines.extend(["</body>", "</html>"])
    
    gallery_file = gallery_dir / f"{reportlet_key}.html"
    gallery_file.write_text("\n".join(lines), encoding="utf-8")


def _relpath(target: Path, base: Path) -> str:
    """Compute relative path from base to target."""
    try:
        return str(target.relative_to(base))
    except ValueError:
        # Fallback: compute manually
        target_parts = target.resolve().parts
        base_parts = base.resolve().parts
        
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


def generate_dashboard_safe(out_dir: Path) -> None:
    """
    Safely generate dashboard, catching and logging errors without failing the step.
    
    This should be called at the end of each step's run function.
    Dashboard generation failures are logged as warnings but do not affect step status.
    """
    try:
        result = generate_dashboard(out_dir)
        if result.errors:
            # Log warnings but don't fail
            import warnings
            for error in result.errors:
                warnings.warn(f"Dashboard generation warning: {error}", UserWarning)
    except Exception as e:
        # Log but don't fail the step
        import warnings
        warnings.warn(f"Dashboard generation failed (non-blocking): {e}", UserWarning)

