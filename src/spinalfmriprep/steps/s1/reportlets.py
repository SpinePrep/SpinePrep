"""S1 reportlet rendering — one self-contained HTML report per dataset.

S1 emits **pure tabular data**: file counts, PASS/WARN/FAIL check
statuses, subject×modality presence. There is no imaging visualization
to render, so PNG is the wrong format — rasterized text is
unsearchable, uncopyable, and locked to a single zoom level. This
matches the convention from fMRIPrep / MRIQC / nipreps: HTML for
tabular content, SVG/PNG only when the human is actually looking at
images.

The report is one self-contained ``.html`` file per dataset (inline
CSS, no external dependencies). Layout:

  ┌──────────────────────────────────────────────────────────────┐
  │  S1 input verify  •  <dataset_key>             [STATUS PILL] │
  ├──────────────────────────────────────────────────────────────┤
  │  [Subjects]  [Sessions]  [Cord func]  [Anat]  [FMaps]        │
  ├──────────────────────────────────────────────────────────────┤
  │  SUBJECT × MODALITY              │  CHECKS                   │
  │  ● sub-02  anat 1  func 9  ···   │  PASS  any_runs_present   │
  │  ● sub-…   …                     │  PASS  fmap_expected      │
  │                                  │  …                        │
  └──────────────────────────────────────────────────────────────┘

The same color palette as the dashboard so navigation feels seamless.
"""

from __future__ import annotations

import html
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np


_MODALITIES = ["anat", "func", "fmap", "physio"]

# Status palette — mirrors the dashboard CSS so banners and reports
# stay visually consistent across the chain.
_STATUS_CLASS = {
    "PASS": "pass",
    "WARN": "warn",
    "FAIL": "fail",
    "UNKNOWN": "unknown",
}


def _modality_grid(inventory: dict) -> tuple[list[str], np.ndarray]:
    """Build subject × modality count matrix from the raw inventory."""
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
        path = str(f.get("path", "")).lower()
        if "physio" in path:
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


def _subject_health(mat_row: np.ndarray) -> str:
    """Per-subject health: PASS if anat ≥ 1 and func ≥ 1, WARN if one
    missing, FAIL if both missing."""
    anat_ok = mat_row[0] > 0
    func_ok = mat_row[1] > 0
    if anat_ok and func_ok:
        return "PASS"
    if not anat_ok and not func_ok:
        return "FAIL"
    return "WARN"


_CSS = """
:root {
  --bg: #0f1115; --card-bg: #1a1d23; --border: #2a2e36;
  --text: #e6e8ec; --muted: #9ca3af;
  --pass-bg: #14532d; --pass-fg: #22c55e;
  --warn-bg: #3a2f00; --warn-fg: #f59e0b;
  --fail-bg: #3a1010; --fail-fg: #ef4444;
  --unknown-bg: #1a1d23; --unknown-fg: #cccccc;
  --cell-bg: #1e3a5f; --cell-fg: #3b82f6;
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 24px;
  background: var(--bg); color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui,
               sans-serif;
  font-size: 14px;
}
code, .mono { font-family: "SF Mono", Menlo, Consolas, monospace; }
h1 { font-size: 22px; font-weight: 700; margin: 0 0 4px 0; }
h2 { font-size: 13px; font-weight: 700; margin: 0 0 12px 0;
     letter-spacing: 0.5px; text-transform: uppercase; color: var(--muted); }
.dataset-key { color: var(--muted); font-size: 13px; }
.header {
  display: flex; justify-content: space-between; align-items: center;
  padding-bottom: 18px; border-bottom: 1px solid var(--border);
  margin-bottom: 20px;
}
.pill {
  display: inline-block; padding: 5px 14px; border-radius: 999px;
  font-weight: 700; font-size: 11px; letter-spacing: 0.5px;
}
.pill-lg { padding: 8px 22px; font-size: 14px; }
.pill-pass    { background: var(--pass-bg); color: var(--pass-fg);
                border: 1px solid var(--pass-fg); }
.pill-warn    { background: var(--warn-bg); color: var(--warn-fg);
                border: 1px solid var(--warn-fg); }
.pill-fail    { background: var(--fail-bg); color: var(--fail-fg);
                border: 1px solid var(--fail-fg); }
.pill-unknown { background: var(--unknown-bg); color: var(--unknown-fg);
                border: 1px solid #666; }

.stats {
  display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px;
  margin-bottom: 24px;
}
.stat-card {
  background: var(--card-bg); border: 1px solid var(--border);
  border-radius: 8px; padding: 16px 12px; text-align: center;
}
.stat-card .value { font-size: 28px; font-weight: 700; color: var(--text); }
.stat-card.empty .value { color: var(--muted); }
.stat-card.warn  .value { color: var(--warn-fg); }
.stat-card.fail  .value { color: var(--fail-fg); }
.stat-card .label { font-size: 10px; font-weight: 700;
                    letter-spacing: 1px; color: var(--muted);
                    text-transform: uppercase; margin-top: 6px; }

.body { display: grid; grid-template-columns: 6fr 5fr; gap: 24px; }

table.matrix {
  width: 100%; border-collapse: separate; border-spacing: 6px;
  font-size: 13px;
}
table.matrix th {
  font-weight: 700; color: var(--muted); padding: 4px 8px;
  text-align: center; border-bottom: 1px solid var(--border);
}
table.matrix th.left { text-align: left; }
table.matrix td { padding: 4px 8px; text-align: center; }
table.matrix td.subj { text-align: left; color: var(--text); font-weight: 500; }
.dot {
  display: inline-block; width: 11px; height: 11px; border-radius: 50%;
  margin-right: 8px; vertical-align: middle;
}
.dot-pass { background: var(--pass-fg); }
.dot-warn { background: var(--warn-fg); }
.dot-fail { background: var(--fail-fg); }
.cell-pos {
  display: inline-block; min-width: 36px; padding: 4px 10px;
  background: var(--cell-bg); color: var(--text);
  border: 1px solid var(--cell-fg); border-radius: 6px;
  font-weight: 700;
}
.cell-zero { color: #4b5563; }

ul.checks { list-style: none; padding: 0; margin: 0; }
ul.checks li {
  display: grid; grid-template-columns: 64px 1fr;
  gap: 12px; align-items: center;
  padding: 10px 0; border-bottom: 1px solid var(--border);
}
ul.checks li:last-child { border-bottom: 0; }
ul.checks .check-name { font-weight: 700; color: var(--text); font-size: 13px; }
ul.checks .check-msg { color: var(--muted); font-size: 12px; margin-top: 2px; }

.footer {
  margin-top: 24px; padding-top: 16px; border-top: 1px solid var(--border);
  color: var(--muted); font-size: 11px; text-align: right;
}
""".strip()


def _esc(s: Any) -> str:
    return html.escape(str(s), quote=True)


def _pill(label: str, status: str, large: bool = False) -> str:
    cls = _STATUS_CLASS.get(status, "unknown")
    extra = " pill-lg" if large else ""
    return f'<span class="pill pill-{cls}{extra}">{_esc(label)}</span>'


def render_s1_dataset_summary(
    inventory: dict,
    qc_summary: dict,
    output_path: Path,
) -> None:
    """Render the per-dataset S1 HTML report. Never raises."""
    try:
        subjects, mat = _modality_grid(inventory)
        checks = qc_summary.get("checks", []) or []
        counts = qc_summary.get("counts", {}) or {}
        metrics = qc_summary.get("metrics", {}) or {}
        dataset_key = qc_summary.get("dataset_key") or "(unknown)"
        status = qc_summary.get("status", "UNKNOWN")
        bids_root = qc_summary.get("bids_root", "")

        cls = counts.get("classification", {}) or {}
        cards = [
            ("Subjects", counts.get("subjects", 0), None),
            ("Sessions", counts.get("sessions", 0), None),
            ("Cord func",
             metrics.get("n_func_cord_runs", cls.get("cord_likely", 0)),
             "fail"),  # zero ⇒ FAIL accent
            ("Anat", metrics.get("n_anat_runs", 0), "warn"),
            ("FMaps", metrics.get("n_fmap_runs", 0), None),
        ]
        card_html_parts = []
        for label, value, zero_class in cards:
            card_cls = "stat-card"
            if value == 0:
                if zero_class:
                    card_cls += f" {zero_class}"
                else:
                    card_cls += " empty"
            card_html_parts.append(
                f'<div class="{card_cls}">'
                f'<div class="value">{_esc(value)}</div>'
                f'<div class="label">{_esc(label)}</div></div>'
            )
        stats_html = "\n      ".join(card_html_parts)

        # Subject × modality matrix
        if subjects:
            matrix_rows = []
            for i, sub in enumerate(subjects):
                row = mat[i]
                health = _subject_health(row)
                dot_cls = _STATUS_CLASS[health]
                cells = []
                for j, mod in enumerate(_MODALITIES):
                    v = int(row[j])
                    if v > 0:
                        cells.append(f'<td><span class="cell-pos">{v}</span></td>')
                    else:
                        cells.append('<td><span class="cell-zero">·</span></td>')
                matrix_rows.append(
                    f'<tr><td class="subj">'
                    f'<span class="dot dot-{dot_cls}"></span>'
                    f'<span class="mono">sub-{_esc(sub)}</span></td>'
                    + "".join(cells) + "</tr>"
                )
            matrix_html = (
                '<table class="matrix">'
                '<thead><tr>'
                '<th class="left">Subject</th>'
                + "".join(f'<th>{m}</th>' for m in _MODALITIES) +
                '</tr></thead>'
                '<tbody>' + "".join(matrix_rows) + '</tbody>'
                '</table>'
            )
        else:
            matrix_html = (
                '<p style="color: var(--fail-fg); font-weight: 700;">'
                'No subjects detected in the BIDS root.</p>'
            )

        # Checks list
        if checks:
            check_items = []
            for c in checks:
                sev = c.get("severity", "UNKNOWN")
                passed = c.get("passed", False)
                badge = "PASS" if passed else sev
                name = c.get("name", "?")
                msg = c.get("message", "")
                check_items.append(
                    f'<li>'
                    f'<div>{_pill(badge, badge)}</div>'
                    f'<div>'
                    f'<div class="check-name mono">{_esc(name)}</div>'
                    f'<div class="check-msg">{_esc(msg)}</div>'
                    f'</div>'
                    f'</li>'
                )
            checks_html = '<ul class="checks">' + "".join(check_items) + '</ul>'
        else:
            checks_html = (
                '<p style="color: var(--muted);">No checks recorded.</p>'
            )

        body = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>S1 input verify — {_esc(dataset_key)}</title>
<style>{_CSS}</style>
</head>
<body>
  <div class="header">
    <div>
      <h1>S1 input verify</h1>
      <code class="dataset-key">{_esc(dataset_key)}</code>
    </div>
    {_pill(status, status, large=True)}
  </div>

  <div class="stats">
      {stats_html}
  </div>

  <div class="body">
    <section>
      <h2>Subject × modality (file count)</h2>
      {matrix_html}
    </section>
    <section>
      <h2>Checks</h2>
      {checks_html}
    </section>
  </div>

  <div class="footer">
    BIDS root: <code class="mono">{_esc(bids_root)}</code>
  </div>
</body>
</html>
"""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(body, encoding="utf-8")
    except Exception:
        # Stub fallback — never let the reportlet fail S1.
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                "<!DOCTYPE html><html><body>"
                "<p>S1 reportlet render failed.</p>"
                "</body></html>",
                encoding="utf-8",
            )
        except Exception:
            pass
