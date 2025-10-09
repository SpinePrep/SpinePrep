"""Per-subject QC HTML report generation with overlays, motion, and confounds."""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

# Inline CSS for self-contained HTML
CSS = """
body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    max-width: 1400px;
    margin: 0 auto;
    padding: 20px;
    background: #f5f5f5;
    color: #333;
}
h1, h2, h3 { color: #2c3e50; margin-top: 0; }
.header {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: white;
    padding: 30px;
    border-radius: 8px;
    margin-bottom: 20px;
}
.card {
    background: white;
    padding: 20px;
    margin: 15px 0;
    border-radius: 8px;
    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
}
.tabs {
    display: flex;
    gap: 10px;
    margin-bottom: 15px;
    border-bottom: 2px solid #e0e0e0;
}
.tab {
    padding: 10px 20px;
    cursor: pointer;
    background: #f0f0f0;
    border: none;
    border-radius: 4px 4px 0 0;
    font-size: 14px;
    transition: background 0.2s;
}
.tab:hover {
    background: #e0e0e0;
}
.tab.active {
    background: white;
    font-weight: 600;
    border-bottom: 2px solid #667eea;
}
.tab-content {
    display: none;
}
.tab-content.active {
    display: block;
}
.overlay-img {
    max-width: 100%;
    height: auto;
    border: 1px solid #ddd;
    border-radius: 4px;
    margin: 10px 0;
}
table {
    width: 100%;
    border-collapse: collapse;
    margin: 15px 0;
    font-size: 14px;
}
th, td {
    padding: 8px 12px;
    text-align: left;
    border-bottom: 1px solid #e0e0e0;
}
th {
    background: #f8f9fa;
    font-weight: 600;
    color: #555;
}
tr:hover {
    background: #f9f9f9;
}
.metric-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 15px;
    margin: 15px 0;
}
.metric-box {
    background: #f8f9fa;
    padding: 15px;
    border-radius: 6px;
    border-left: 4px solid #667eea;
}
.metric-label {
    font-size: 12px;
    color: #666;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}
.metric-value {
    font-size: 24px;
    font-weight: 600;
    color: #2c3e50;
    margin-top: 5px;
}
.status-good { color: #27ae60; font-weight: bold; }
.status-warn { color: #f39c12; font-weight: bold; }
.status-fail { color: #e74c3c; font-weight: bold; }
.footer {
    text-align: center;
    color: #7f8c8d;
    margin-top: 40px;
    padding-top: 20px;
    border-top: 1px solid #ddd;
    font-size: 14px;
}
"""

# Minimal JavaScript for tabs
TABS_JS = """
function switchTab(tabName) {
    // Hide all tab contents
    document.querySelectorAll('.tab-content').forEach(el => {
        el.classList.remove('active');
    });
    // Remove active class from all tabs
    document.querySelectorAll('.tab').forEach(el => {
        el.classList.remove('active');
    });
    // Show selected tab content
    const content = document.getElementById(tabName);
    if (content) {
        content.classList.add('active');
    }
    // Activate selected tab
    const tab = document.querySelector(`[data-tab="${tabName}"]`);
    if (tab) {
        tab.classList.add('active');
    }
}
// Activate first tab on load
document.addEventListener('DOMContentLoaded', () => {
    const firstTab = document.querySelector('.tab');
    if (firstTab) {
        const tabName = firstTab.getAttribute('data-tab');
        switchTab(tabName);
    }
});
"""


def load_confounds(confounds_tsv: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """
    Load confounds TSV file.

    Args:
        confounds_tsv: Path to confounds TSV

    Returns:
        Tuple of (rows as list of dicts, column names)
    """
    if not confounds_tsv.exists():
        return [], []

    rows: list[dict[str, Any]] = []
    cols: list[str] = []

    with confounds_tsv.open() as f:
        reader = csv.DictReader(f, delimiter="\t")
        rows = list(reader)  # type: ignore[assignment]
        cols = list(reader.fieldnames) if reader.fieldnames else []

    return rows, cols


def load_doctor_json(doctor_json: Path | None) -> dict[str, Any]:
    """
    Load doctor.json environment report.

    Args:
        doctor_json: Path to doctor JSON file

    Returns:
        Doctor report dictionary or empty dict if not found
    """
    if not doctor_json or not doctor_json.exists():
        return {}

    try:
        with doctor_json.open() as f:
            return json.load(f)
    except Exception:
        return {}


def build_motion_summary_html(rows: list[dict[str, Any]]) -> str:
    """Build motion summary metrics HTML."""
    if not rows:
        return "<p>No motion data available.</p>"

    # Compute summary stats
    fd_values = [float(r.get("fd", 0)) for r in rows if r.get("fd")]
    dvars_values = [float(r.get("dvars", 0)) for r in rows if r.get("dvars")]
    censored = sum(1 for r in rows if r.get("censor") == "1")

    max_fd = max(fd_values) if fd_values else 0
    mean_fd = sum(fd_values) / len(fd_values) if fd_values else 0
    max_dvars = max(dvars_values) if dvars_values else 0
    mean_dvars = sum(dvars_values) / len(dvars_values) if dvars_values else 0

    # Color coding
    fd_status = (
        "status-good"
        if max_fd < 0.5
        else "status-warn"
        if max_fd < 1.0
        else "status-fail"
    )
    censor_status = (
        "status-good"
        if censored == 0
        else "status-warn"
        if censored < len(rows) * 0.1
        else "status-fail"
    )

    html = f"""
    <div class="metric-grid">
        <div class="metric-box">
            <div class="metric-label">Max FD</div>
            <div class="metric-value {fd_status}">{max_fd:.3f} mm</div>
        </div>
        <div class="metric-box">
            <div class="metric-label">Mean FD</div>
            <div class="metric-value">{mean_fd:.3f} mm</div>
        </div>
        <div class="metric-box">
            <div class="metric-label">Max DVARS</div>
            <div class="metric-value">{max_dvars:.3f}</div>
        </div>
        <div class="metric-box">
            <div class="metric-label">Mean DVARS</div>
            <div class="metric-value">{mean_dvars:.3f}</div>
        </div>
        <div class="metric-box">
            <div class="metric-label">Censored Volumes</div>
            <div class="metric-value {censor_status}">{censored} / {len(rows)}</div>
        </div>
    </div>
    """

    return html


def build_acompcor_table_html(rows: list[dict[str, Any]], cols: list[str]) -> str:
    """Build aCompCor summary table HTML."""
    acompcor_cols = [c for c in cols if c.startswith("acompcor")]

    if not acompcor_cols or not rows:
        return "<p>No aCompCor components found.</p>"

    # Show first 10 timepoints
    html = ["<table>"]
    html.append("<tr><th>Timepoint</th>")
    for col in acompcor_cols:
        html.append(f"<th>{col}</th>")
    html.append("</tr>")

    for i, row in enumerate(rows[:10]):
        html.append(f"<tr><td>{i}</td>")
        for col in acompcor_cols:
            val = row.get(col, "N/A")
            if val != "N/A":
                try:
                    val = f"{float(val):.4f}"
                except ValueError:
                    pass
            html.append(f"<td>{val}</td>")
        html.append("</tr>")

    if len(rows) > 10:
        html.append(
            f"<tr><td colspan='{len(acompcor_cols) + 1}' style='text-align:center; color:#999;'>... ({len(rows) - 10} more timepoints)</td></tr>"
        )

    html.append("</table>")

    return "\n".join(html)


def build_environment_html(doctor_info: dict[str, Any]) -> str:
    """Build environment info HTML from doctor.json."""
    if not doctor_info:
        return "<p>No environment information available.</p>"

    platform = doctor_info.get("platform", {})
    deps = doctor_info.get("deps", {})
    status = doctor_info.get("status", "unknown")

    status_class = (
        f"status-{status}"
        if status in ["good", "pass"]
        else "status-warn"
        if status == "warn"
        else "status-fail"
    )

    html = [
        f"<p><strong>Status:</strong> <span class='{status_class}'>{status.upper()}</span></p>",
        "<table>",
        "<tr><th>Component</th><th>Value</th></tr>",
    ]

    # Platform info
    if platform:
        html.append(f"<tr><td>OS</td><td>{platform.get('os', 'unknown')}</td></tr>")
        html.append(
            f"<tr><td>Python</td><td>{platform.get('python', 'unknown')}</td></tr>"
        )
        html.append(
            f"<tr><td>CPU Cores</td><td>{platform.get('cpu_count', 'unknown')}</td></tr>"
        )

    # SCT
    sct = deps.get("sct", {})
    if sct.get("found"):
        html.append(f"<tr><td>SCT</td><td>✓ {sct.get('version', 'unknown')}</td></tr>")
    else:
        html.append("<tr><td>SCT</td><td class='status-fail'>✗ Not found</td></tr>")

    # PAM50
    pam50 = deps.get("pam50", {})
    if pam50.get("found"):
        html.append(f"<tr><td>PAM50</td><td>✓ {pam50.get('path', 'found')}</td></tr>")
    else:
        html.append("<tr><td>PAM50</td><td class='status-fail'>✗ Not found</td></tr>")

    html.append("</table>")

    return "\n".join(html)


def build_overlays_html(qc_dir: Path) -> str:
    """Build overlay images HTML with tabs."""
    # Look for common overlay PNGs
    overlays = []

    for pattern in [
        "overlay_epi_t2w.png",
        "overlay_t2w_template.png",
        "overlay_epi_template.png",
        "registration_*.png",
    ]:
        for img_path in qc_dir.glob(pattern):
            overlays.append(
                {
                    "name": img_path.stem.replace("overlay_", "")
                    .replace("_", " → ")
                    .title(),
                    "path": img_path.name,
                }
            )

    if not overlays:
        return "<p>No overlay images found. Run registration steps to generate overlays.</p>"

    # Build tabs
    html = ["<div class='tabs'>"]
    for i, overlay in enumerate(overlays):
        tab_id = f"overlay-{i}"
        html.append(
            f"<button class='tab' data-tab='{tab_id}' onclick='switchTab(\"{tab_id}\")'>{overlay['name']}</button>"
        )
    html.append("</div>")

    # Build tab contents
    for i, overlay in enumerate(overlays):
        tab_id = f"overlay-{i}"
        html.append(f"<div id='{tab_id}' class='tab-content'>")
        html.append(
            f"<img src='{overlay['path']}' alt='{overlay['name']}' class='overlay-img' />"
        )
        html.append("</div>")

    return "\n".join(html)


def write_qc(subject_dir: Path, assets: dict[str, Any]) -> Path:
    """
    Write per-subject QC HTML report.

    Args:
        subject_dir: Subject directory (e.g., out/sub-01)
        assets: Dictionary with keys:
            - confounds_tsv: Path to confounds TSV
            - doctor_json: Path to doctor.json (optional)
            - motion_png: Path to motion plot PNG (optional)

    Returns:
        Path to generated index.html
    """
    qc_dir = subject_dir / "qc"
    qc_dir.mkdir(parents=True, exist_ok=True)

    # Load assets
    confounds_tsv = assets.get("confounds_tsv")
    doctor_json = assets.get("doctor_json")

    rows, cols = load_confounds(confounds_tsv) if confounds_tsv else ([], [])
    doctor_info = load_doctor_json(doctor_json)

    subject_id = subject_dir.name

    # Build HTML parts
    html_parts = [
        "<!DOCTYPE html>",
        "<html lang='en'>",
        "<head>",
        "  <meta charset='UTF-8'>",
        "  <meta name='viewport' content='width=device-width, initial-scale=1.0'>",
        f"  <title>{subject_id} QC Report</title>",
        f"  <style>{CSS}</style>",
        "</head>",
        "<body>",
        "  <div class='header'>",
        f"    <h1>{subject_id} Quality Control Report</h1>",
        f"    <p>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>",
        "  </div>",
    ]

    # Registration overlays section
    html_parts.extend(
        [
            "  <div class='card'>",
            "    <h2>Registration Overlays</h2>",
            "    " + build_overlays_html(qc_dir),
            "  </div>",
        ]
    )

    # Motion section
    html_parts.extend(
        [
            "  <div class='card'>",
            "    <h2>Motion Summary</h2>",
            "    " + build_motion_summary_html(rows),
        ]
    )

    # Add motion plot if available
    motion_png = qc_dir / "motion_fd_dvars.png"
    if motion_png.exists():
        html_parts.append(
            "    <img src='motion_fd_dvars.png' alt='Motion FD/DVARS Plot' class='overlay-img' />"
        )

    html_parts.append("  </div>")

    # aCompCor section
    html_parts.extend(
        [
            "  <div class='card'>",
            "    <h2>aCompCor Components</h2>",
            "    " + build_acompcor_table_html(rows, cols),
            "  </div>",
        ]
    )

    # Environment section
    html_parts.extend(
        [
            "  <div class='card'>",
            "    <h2>Environment</h2>",
            "    " + build_environment_html(doctor_info),
            "  </div>",
        ]
    )

    # Footer
    html_parts.extend(
        [
            "  <div class='footer'>",
            "    <p>Generated by SpinePrep</p>",
            "  </div>",
            f"  <script>{TABS_JS}</script>",
            "</body>",
            "</html>",
        ]
    )

    # Write HTML
    html_path = qc_dir / "index.html"
    html_path.write_text("\n".join(html_parts))

    return html_path
