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

_SCOPE_CSS = """
.sfp-scope-banner { margin-bottom: 24px; }
.sfp-scope-banner h2 { font-size: 13px; font-weight: 700; margin: 0 0 10px 0;
                       letter-spacing: 1px; text-transform: uppercase;
                       color: #9ca3af; }
.sfp-scopes { display: grid; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
              gap: 12px; }
.sfp-card { background: #1a1d23; border: 1px solid #2a2e36; border-radius: 8px;
            padding: 14px 16px; }
.sfp-card .sfp-scope-name { font-size: 11px; letter-spacing: 1px;
                             text-transform: uppercase; color: #9ca3af;
                             margin-bottom: 4px; font-weight: 700; }
.sfp-card .sfp-wf { font-family: "SF Mono", Menlo, Consolas, monospace;
                     font-weight: 700; font-size: 15px; color: #e6e8ec; }
.sfp-card .sfp-meta { color: #9ca3af; font-size: 11px; margin: 4px 0 10px 0; }
.sfp-card .sfp-links { display: flex; flex-wrap: wrap; gap: 6px; }
.sfp-card .sfp-links a { display: inline-block; padding: 4px 10px;
                          background: #2a2e36; color: #7dcfff;
                          text-decoration: none; border-radius: 3px;
                          font-size: 12px; }
.sfp-card .sfp-links a:hover { background: #3a3e46; }
.sfp-card .sfp-links a.sfp-primary { background: #14532d; color: #22c55e;
                                       font-weight: 700; }
.sfp-card .sfp-links a.sfp-primary:hover { background: #1a6638; }
.sfp-empty { color: #6b7280; font-style: italic; }
"""

_CSS = _SCOPE_CSS + """
body { background: #0f1115; color: #e6e8ec;
       font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
       margin: 0; padding: 32px; }
h1 { font-size: 22px; margin: 0 0 6px 0; }
.muted { color: #9ca3af; font-size: 12px; }
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


def _scope_card_html(work_root: Path, scope: str, links_from: Path) -> str:
    """Render one scope card. Links are computed relative to `links_from`."""
    latest_wf, all_targets = _latest_wf_for_scope(work_root, scope)
    if latest_wf is None:
        return (
            f'<div class="sfp-card">'
            f'<div class="sfp-scope-name">{scope}</div>'
            f'<div class="sfp-empty">No done steps yet.</div></div>'
        )
    rel_to_latest = os.path.relpath(
        latest_wf / "dashboard" / "index.html", links_from)
    mtime = _fmt_mtime(latest_wf)
    latest_step = _latest_step_name(work_root, scope)
    n_steps = len({t for t in all_targets})

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
        rel = os.path.relpath(tgt / "dashboard" / "index.html", links_from)
        step_links_html.append(f'<a href="{rel}">{entry.name}</a>')

    latest_wf_name = latest_wf.name
    return f"""
<div class="sfp-card">
  <div class="sfp-scope-name">{scope}</div>
  <div class="sfp-wf">{latest_wf_name}</div>
  <div class="sfp-meta">latest step: <b>{latest_step}</b>  •
                        {n_steps} done  •  {mtime}</div>
  <div class="sfp-links">
    <a class="sfp-primary" href="{rel_to_latest}">Open latest →</a>
    {" ".join(step_links_html)}
  </div>
</div>
""".strip()


def render_scope_banner(work_root: Path, links_from: Path) -> str:
    """Return the unified scope-summary banner as an HTML fragment with
    inline <style>. Embed at the top of a dashboard page; links resolve
    relative to ``links_from``."""
    work_root = Path(work_root).resolve()
    links_from = Path(links_from).resolve()
    done_root = work_root / "done"
    scopes = sorted(
        d.name for d in done_root.iterdir() if d.is_dir()
    ) if done_root.exists() else ["reg"]
    if not scopes:
        scopes = ["reg"]
    cards = "\n".join(
        _scope_card_html(work_root, s, links_from) for s in scopes)
    return f"""
<style>{_SCOPE_CSS}</style>
<div class="sfp-scope-banner">
  <h2>Latest runs</h2>
  <div class="sfp-scopes">
{cards}
  </div>
</div>
""".strip()


def write_latest_landing(work_root: Path) -> Path:
    """Write `<work_root>/dashboard.html` — a minimal standalone landing
    page that redirects to the latest dashboard. Kept as a fallback for
    cases where no wf dashboard exists yet (e.g. fresh repo)."""
    work_root = Path(work_root).resolve()
    done_root = work_root / "done"
    scopes = sorted(
        d.name for d in done_root.iterdir() if d.is_dir()
    ) if done_root.exists() else ["reg"]
    if not scopes:
        scopes = ["reg"]

    # Find any latest wf (across all scopes) to redirect to
    target = None
    for s in scopes:
        wf, _ = _latest_wf_for_scope(work_root, s)
        if wf is not None:
            target = wf
            break
    out = work_root / "dashboard.html"
    if target is not None:
        rel = os.path.relpath(target / "dashboard" / "index.html", work_root)
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
{_NO_CACHE}
<meta http-equiv="refresh" content="0; url={rel}" />
<title>SpinalfMRIprep dashboard</title>
</head>
<body>
<p>Redirecting to <a href="{rel}">{rel}</a>…</p>
</body>
</html>"""
    else:
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
{_NO_CACHE}
<title>SpinalfMRIprep dashboard</title>
</head>
<body>
<p>No workfolder dashboards available yet.</p>
</body>
</html>"""
    out.write_text(html, encoding="utf-8")
    return out
