"""Project-root "latest" dashboard landing page.

A single stable URL — `work/dashboard.html` — that always points to
the dashboard of the latest chain workfolder for each scope. The user
bookmarks ONE URL; the file is rewritten on every chain promotion.

Layout: one card per scope (reg / cohort / ad-hoc), each linking to
that scope's most recently promoted workfolder dashboard. The cards
include the wf name, mtime, and the latest step done so the user can
tell at a glance which chain step they're inspecting.
"""

from __future__ import annotations

import datetime
import os
from pathlib import Path


_NO_CACHE = (
    '<meta http-equiv="Cache-Control" '
    'content="no-cache, no-store, must-revalidate" />\n'
    '<meta http-equiv="Pragma" content="no-cache" />\n'
    '<meta http-equiv="Expires" content="0" />'
)

_CSS = """
body { background: #0f1115; color: #e6e8ec;
       font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
       margin: 0; padding: 32px; }
h1 { font-size: 22px; margin: 0 0 6px 0; }
.muted { color: #9ca3af; font-size: 12px; }
.scopes { display: grid; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
          gap: 16px; margin-top: 24px; }
.card { background: #1a1d23; border: 1px solid #2a2e36; border-radius: 8px;
        padding: 18px; }
.card h2 { margin: 0 0 8px 0; font-size: 14px; letter-spacing: 0.5px;
           text-transform: uppercase; color: #9ca3af; }
.card .wf { font-family: "SF Mono", Menlo, Consolas, monospace;
            font-weight: 700; font-size: 16px; color: #e6e8ec; }
.card .meta { color: #9ca3af; font-size: 12px; margin: 6px 0 14px 0; }
.card .links { display: flex; flex-wrap: wrap; gap: 8px; }
.card .links a { display: inline-block; padding: 6px 12px;
                 background: #2a2e36; color: #7dcfff;
                 text-decoration: none; border-radius: 4px; font-size: 13px; }
.card .links a:hover { background: #3a3e46; }
.empty { color: #6b7280; font-style: italic; }
.footer { color: #6b7280; font-size: 11px; margin-top: 32px; text-align: right; }
"""


def _latest_wf_for_scope(work_root: Path, scope: str) -> tuple[Path | None, list[Path]]:
    """Find the workfolder for the latest-done step in a scope.

    Returns (latest_wf, all_done_step_targets). ``latest_wf`` is the
    target of the highest-numbered S{n} symlink under work/done/<scope>/.
    Falls back to None when the scope has no done steps.
    """
    done_root = work_root / "done" / scope
    if not done_root.exists():
        return None, []
    step_links = []
    for entry in done_root.iterdir():
        if not entry.is_symlink():
            continue
        name = entry.name
        if not (name.startswith("S") and name[1:].isdigit()):
            continue
        try:
            target = entry.resolve()
            step_num = int(name[1:])
            step_links.append((step_num, name, target))
        except Exception:
            continue
    step_links.sort()
    if not step_links:
        return None, []
    return step_links[-1][2], [t for _, _, t in step_links]


def _fmt_mtime(p: Path) -> str:
    try:
        ts = datetime.datetime.fromtimestamp(p.stat().st_mtime)
        return ts.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "?"


def _latest_step_name(work_root: Path, scope: str) -> str:
    done_root = work_root / "done" / scope
    if not done_root.exists():
        return "—"
    steps = sorted(
        e.name for e in done_root.iterdir()
        if e.is_symlink() and e.name.startswith("S") and e.name[1:].isdigit()
    )
    return steps[-1] if steps else "—"


def _scope_card_html(work_root: Path, scope: str) -> str:
    latest_wf, all_targets = _latest_wf_for_scope(work_root, scope)
    if latest_wf is None:
        return (
            f'<div class="card"><h2>{scope}</h2>'
            f'<div class="empty">No done steps yet.</div></div>'
        )
    rel_wf = os.path.relpath(latest_wf, work_root)
    rel_dashboard = f"{rel_wf}/dashboard/index.html"
    mtime = _fmt_mtime(latest_wf)
    latest_step = _latest_step_name(work_root, scope)
    n_steps = len({t for t in all_targets})
    # Build links to each step's dashboard (deduped by target wf)
    seen = set()
    step_links_html: list[str] = []
    done_root = work_root / "done" / scope
    for entry in sorted(done_root.iterdir(), key=lambda p: p.name):
        if not entry.is_symlink():
            continue
        if not (entry.name.startswith("S") and entry.name[1:].isdigit()):
            continue
        try:
            tgt = entry.resolve()
        except Exception:
            continue
        if tgt in seen:
            continue
        seen.add(tgt)
        rel = os.path.relpath(tgt, work_root)
        step_links_html.append(
            f'<a href="{rel}/dashboard/index.html">{entry.name}</a>'
        )

    return f"""
<div class="card">
  <h2>{scope}</h2>
  <div class="wf">{rel_wf}</div>
  <div class="meta">latest step: <b>{latest_step}</b>  •
                    {n_steps} done  •  {mtime}</div>
  <div class="links">
    <a href="{rel_dashboard}"><b>Open latest dashboard →</b></a>
    {" ".join(step_links_html)}
  </div>
</div>
""".strip()


def write_latest_landing(work_root: Path) -> Path:
    """Write `<work_root>/dashboard.html` linking to the latest chain
    dashboards. Returns the written path."""
    work_root = Path(work_root)
    scope_dirs = []
    done_root = work_root / "done"
    if done_root.exists():
        scope_dirs = sorted(
            d.name for d in done_root.iterdir() if d.is_dir()
        )
    if not scope_dirs:
        scope_dirs = ["reg"]

    scope_cards = "\n".join(_scope_card_html(work_root, s) for s in scope_dirs)
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
{_NO_CACHE}
<title>SpinalfMRIprep — Latest dashboards</title>
<style>{_CSS}</style>
</head>
<body>
<h1>SpinalfMRIprep — Latest dashboards</h1>
<div class="muted">Project-root entry point. Bookmark this URL — each
card auto-refreshes after every chain promotion and links to the
latest workfolder per scope.</div>
<div class="scopes">
{scope_cards}
</div>
<div class="footer">generated {now}</div>
</body>
</html>
"""
    out = work_root / "dashboard.html"
    out.write_text(html, encoding="utf-8")
    return out
