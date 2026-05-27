"""S1 reportlet — one simple HTML page per dataset, just tables.

S1 emits pure tabular data: counts, subject×modality, checks. No
imaging viz, so the report is plain HTML tables with minimal CSS.
The dashboard gallery embeds these inline (one iframe per dataset).
"""

from __future__ import annotations

import html
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np


_MODALITIES = ["anat", "func", "fmap", "physio"]
_STATUS_CLASS = {"PASS": "pass", "WARN": "warn", "FAIL": "fail"}


def _modality_grid(inventory: dict) -> tuple[list[str], np.ndarray]:
    """Subject × modality count matrix from the raw inventory."""
    files = inventory.get("files", [])
    runs = inventory.get("runs", [])
    counts: dict[tuple[str, str], int] = defaultdict(int)
    subjects = set()
    for r in runs:
        sub = r.get("subject") or "unknown"
        mod = r.get("modality") or "other"
        subjects.add(sub)
        if mod in _MODALITIES:
            counts[(sub, mod)] += 1
    for f in files:
        sub = f.get("subject") or "unknown"
        if "physio" in str(f.get("path", "")).lower():
            subjects.add(sub)
            counts[(sub, "physio")] += 1
    subjects_sorted = sorted(s for s in subjects if s != "unknown") + (
        ["unknown"] if "unknown" in subjects else [])
    if not subjects_sorted:
        return [], np.zeros((0, len(_MODALITIES)), dtype=int)
    mat = np.zeros((len(subjects_sorted), len(_MODALITIES)), dtype=int)
    for i, sub in enumerate(subjects_sorted):
        for j, mod in enumerate(_MODALITIES):
            mat[i, j] = counts.get((sub, mod), 0)
    return subjects_sorted, mat


def _subject_health(row: np.ndarray) -> str:
    if row[0] > 0 and row[1] > 0:
        return "PASS"
    if row[0] == 0 and row[1] == 0:
        return "FAIL"
    return "WARN"


def _esc(s: Any) -> str:
    return html.escape(str(s), quote=True)


_CSS = """
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui,
                   sans-serif;
       background: #0f1115; color: #e6e8ec;
       margin: 0; padding: 14px 18px; font-size: 13px; }
h3 { margin: 0 0 4px 0; font-size: 14px; font-weight: 700; }
.dskey { font-family: "SF Mono", Menlo, Consolas, monospace;
         color: #9ca3af; font-size: 12px; }
.status { display: inline-block; padding: 1px 8px; border-radius: 3px;
          font-weight: 700; font-size: 11px; margin-left: 6px;
          vertical-align: middle; }
.status.pass { background: #14532d; color: #22c55e; }
.status.warn { background: #3a2f00; color: #f59e0b; }
.status.fail { background: #3a1010; color: #ef4444; }
table { border-collapse: collapse; margin: 8px 0 4px 0; }
th { color: #9ca3af; font-weight: 600; font-size: 10px;
     letter-spacing: 0.5px; text-transform: uppercase;
     text-align: left; padding: 4px 10px 4px 0;
     border-bottom: 1px solid #2a2e36; }
td { padding: 3px 10px 3px 0; border-bottom: 1px solid #1a1d23;
     vertical-align: middle; }
td.num { text-align: right; }
td.subj { font-family: "SF Mono", Menlo, Consolas, monospace; }
td.zero { color: #4b5563; }
td.pass { color: #22c55e; font-weight: 700; }
td.warn { color: #f59e0b; font-weight: 700; }
td.fail { color: #ef4444; font-weight: 700; }
.section { margin-top: 12px; }
.section h4 { margin: 0 0 4px 0; font-size: 11px; font-weight: 600;
              letter-spacing: 0.5px; text-transform: uppercase;
              color: #9ca3af; }
""".strip()


def render_s1_dataset_summary(
    inventory: dict, qc_summary: dict, output_path: Path,
) -> None:
    """Render one simple HTML page with three plain tables. Never raises."""
    try:
        subjects, mat = _modality_grid(inventory)
        checks = qc_summary.get("checks", []) or []
        counts = qc_summary.get("counts", {}) or {}
        metrics = qc_summary.get("metrics", {}) or {}
        dataset_key = qc_summary.get("dataset_key") or "(unknown)"
        status = qc_summary.get("status", "UNKNOWN")
        status_cls = _STATUS_CLASS.get(status, "")

        cls = counts.get("classification", {}) or {}
        count_rows = [
            ("files", counts.get("files", 0)),
            ("runs", counts.get("runs", 0)),
            ("subjects", counts.get("subjects", 0)),
            ("sessions", counts.get("sessions", 0)),
            ("cord-likely runs", cls.get("cord_likely", 0)),
            ("anat runs", metrics.get("n_anat_runs", 0)),
            ("fmap runs", metrics.get("n_fmap_runs", 0)),
        ]
        counts_tbl = (
            '<table><tbody>'
            + "".join(
                f'<tr><td>{_esc(k)}</td>'
                f'<td class="num">{_esc(v)}</td></tr>'
                for k, v in count_rows
            )
            + '</tbody></table>'
        )

        if subjects:
            rows = []
            for i, sub in enumerate(subjects):
                row = mat[i]
                health = _subject_health(row)
                cells = []
                for j in range(len(_MODALITIES)):
                    v = int(row[j])
                    cls_attr = "num zero" if v == 0 else "num"
                    cells.append(f'<td class="{cls_attr}">{v}</td>')
                rows.append(
                    f'<tr>'
                    f'<td class="subj">sub-{_esc(sub)}</td>'
                    + "".join(cells)
                    + f'<td class="{_STATUS_CLASS.get(health, "")}">{health}</td>'
                    + '</tr>'
                )
            modality_tbl = (
                '<table><thead><tr>'
                '<th>subject</th>'
                + "".join(f'<th>{m}</th>' for m in _MODALITIES)
                + '<th>status</th>'
                '</tr></thead><tbody>'
                + "".join(rows)
                + '</tbody></table>'
            )
        else:
            modality_tbl = '<p class="fail">No subjects detected.</p>'

        if checks:
            check_rows = []
            for c in checks:
                sev = c.get("severity", "")
                passed = c.get("passed", False)
                badge = "PASS" if passed else sev
                badge_cls = _STATUS_CLASS.get(badge, "")
                check_rows.append(
                    f'<tr>'
                    f'<td class="{badge_cls}">{_esc(badge)}</td>'
                    f'<td class="subj">{_esc(c.get("name", ""))}</td>'
                    f'<td>{_esc(c.get("message", ""))}</td>'
                    f'</tr>'
                )
            checks_tbl = (
                '<table><thead><tr>'
                '<th>status</th><th>check</th><th>message</th>'
                '</tr></thead><tbody>'
                + "".join(check_rows)
                + '</tbody></table>'
            )
        else:
            checks_tbl = '<p>No checks recorded.</p>'

        body = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>S1 — {_esc(dataset_key)}</title>
<style>{_CSS}</style>
</head>
<body>
<h3><span class="dskey">{_esc(dataset_key)}</span>
    <span class="status {status_cls}">{_esc(status)}</span></h3>

<div class="section"><h4>Counts</h4>{counts_tbl}</div>
<div class="section"><h4>Subject × modality</h4>{modality_tbl}</div>
<div class="section"><h4>Checks</h4>{checks_tbl}</div>
</body>
</html>
"""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(body, encoding="utf-8")
    except Exception:
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                "<!DOCTYPE html><html><body>"
                "<p>S1 reportlet render failed.</p></body></html>",
                encoding="utf-8",
            )
        except Exception:
            pass
