"""Persistent QC dashboard web server for SpinePrep.

Serves pre-generated static dashboard HTML and reportlet images
from workfolders under WORK_ROOT. Listens on port 9002, accessible
externally via 271828.space/p2/.

Usage:
    python -m spineprep.dashboard_server
    # or: uvicorn spineprep.dashboard_server:app --port 9002
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse, Response

WORK_ROOT = Path(os.environ.get("SFMRI_WORK_ROOT", "/mnt/ssd1/SpinePrep/work"))
# reg/smoke dev cohorts retired 2026-06-16; production scopes are the full
# per-dataset chains + the balgrist experiment. Any scope with a work/done/<scope>
# dir is served regardless (see _is_scope); this list is just the fast-path/default.
VISIBLE_SCOPES: tuple[str, ...] = ("exp", "cosmotor", "cospain", "handgrasp", "rest", "full")
DEFAULT_SCOPE = "exp"

# `redirect_slashes=False` is critical: Starlette's default trailing-
# slash auto-redirect emits an absolute `Location: /dashboard/` that
# drops the `/p2` reverse-proxy prefix, sending the browser to
# `271828.space/dashboard/` which falls through to the catch-all
# returning HTTP 401 "auth required". Handling bare and trailing-slash
# paths explicitly (no redirect) keeps the prefix intact.
app = FastAPI(
    title="SpinePrep QC Dashboard",
    docs_url=None, redoc_url=None,
    redirect_slashes=False,
)


def _safe_resolve(base: Path, rel: str) -> Path | None:
    """Resolve a relative path under base, preventing traversal escapes.

    The starting path must live under `base`, but the resolved file may sit
    anywhere under WORK_ROOT - chain workfolders create cross-workfolder
    symlinks (e.g. wf_smoke/derivatives/...  ->  wf_reg/derivatives/...).
    """
    unresolved = (base / rel)
    # First gate: the unresolved path must be under base (no `..` traversal)
    try:
        unresolved.relative_to(base)
    except ValueError:
        return None
    # Second gate: after symlink resolution, the file must still live in WORK_ROOT
    resolved = unresolved.resolve()
    work_root = WORK_ROOT.resolve()
    if not str(resolved).startswith(str(work_root)):
        return None
    if not resolved.is_file():
        return None
    return resolved


def _guess_media_type(path: Path) -> str:
    suffix = path.suffix.lower()
    return {
        ".html": "text/html",
        ".css": "text/css",
        ".js": "application/javascript",
        ".json": "application/json",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".svg": "image/svg+xml",
    }.get(suffix, "application/octet-stream")


# Cache-control headers applied to every response. The dashboard
# content can update at any moment (chain promotion, reportlet
# regen) and the user must always see the latest version.
_NO_CACHE_HEADERS = {
    "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}


def _file_response(path: Path, media_type: str | None = None) -> FileResponse:
    return FileResponse(
        path,
        media_type=media_type or _guess_media_type(path),
        headers=_NO_CACHE_HEADERS,
    )


# --- Routes ---

import re as _re
_SCOPE_RE = _re.compile(r"^[a-z0-9_]+$")


def _is_scope(prefix: str) -> bool:
    """A URL prefix is a stitched-view scope if it's a known scope OR any safe
    identifier with a work/done/<prefix> dir (per-dataset rollout scopes auto-
    served, no per-dataset code edit). The path-param can't contain '/', and the
    regex blocks '..'-style traversal."""
    if prefix in VISIBLE_SCOPES:
        return True
    return bool(_SCOPE_RE.match(prefix)) and (WORK_ROOT / "done" / prefix).is_dir()


def _build_stitched_view(scope: str) -> Path | None:
    """Rebuild the stitched view for ``scope`` and return its index.html
    path, or None if no steps are available.

    Called from each ``/{scope}/dashboard*`` route so the view is always
    fresh — the build is cheap (symlink creation + dashboard render of
    pre-existing qc.json files), and this avoids any "stale dashboard
    after a new mark_done" problem without a polling/inotify daemon.
    """
    from .dashboard_stitched import render_view
    try:
        return render_view(scope, WORK_ROOT)
    except Exception:
        # Don't let a stitched-view build error bring down the per-wf
        # routes; surface the failure as a 404 instead.
        return None


@app.get("/")
async def root():
    """Unified entry point — redirect to the default scope's stitched
    dashboard. The stitched view pulls each step from its approved
    (work/done/<scope>/Sn) wf, falling back to latest-wf-with-step for
    unapproved steps. One URL, always shows the latest meaningful
    state."""
    return RedirectResponse(
        url=f"{DEFAULT_SCOPE}/dashboard/index.html",
        headers=_NO_CACHE_HEADERS,
    )


@app.get("/dashboard.html")
@app.get("/dashboard")
@app.get("/dashboard/")
async def landing_page_legacy():
    """Legacy landing-page URLs — redirect to the default scope's
    stitched dashboard."""
    return RedirectResponse(
        url=f"../{DEFAULT_SCOPE}/dashboard/index.html",
        headers=_NO_CACHE_HEADERS,
    )


# Removed individual stitched routes — they collide with the wf routes
# below for the URL pattern /{prefix}/dashboard/{path}. The dispatcher
# at /{prefix}/dashboard/{path:path} handles both cases.


@app.get("/tutorial")
@app.get("/tutorial/")
async def tutorial_page():
    """Self-contained tutorial: one section per step + core concept
    reference (DVARS, DVARS-ref, Tukey rule, robust funcref, etc).
    The page is plain HTML using the dashboard's dark palette; no
    MathJax so it serves cleanly without external dependencies."""
    from .tutorial import render_tutorial_html
    return Response(
        content=render_tutorial_html(),
        media_type="text/html",
        headers=_NO_CACHE_HEADERS,
    )


@app.get("/{prefix}/dashboard")
async def redirect_dashboard_index(prefix: str):
    """Redirect the no-trailing-slash index to ``dashboard/``.

    The index links to reportlets relatively (``href="reportlets/..."``, no
    ``<base>`` tag). Served at ``/{prefix}/dashboard`` (no slash) the browser
    resolves those against ``/{prefix}/`` -> ``/{prefix}/reportlets/...`` (404).
    Redirect to the trailing-slash URL so they resolve under
    ``/{prefix}/dashboard/...``. The Location is RELATIVE (``dashboard/``) so the
    browser preserves the ``/p2`` reverse-proxy prefix — an absolute redirect
    would drop it (see the redirect_slashes note above)."""
    return RedirectResponse(url="dashboard/", status_code=307,
                            headers=_NO_CACHE_HEADERS)


@app.get("/{prefix}/dashboard/")
async def serve_dashboard_index(prefix: str):
    """Bare `/{prefix}/dashboard/` — serves either a wf's per-wf
    dashboard (when prefix starts with ``wf_``) or the stitched
    per-scope dashboard (when prefix in VISIBLE_SCOPES). 404 otherwise."""
    if prefix.startswith("wf_"):
        index = WORK_ROOT / prefix / "dashboard" / "index.html"
        if not index.is_file():
            return Response(status_code=404)
        return _file_response(index)
    if _is_scope(prefix):
        index = _build_stitched_view(prefix)
        if index is None or not index.is_file():
            return Response(
                "Scope has no done steps yet (run scripts/mark_done.py first).",
                status_code=404, media_type="text/plain")
        return _file_response(index)
    return Response(status_code=404)


@app.get("/{prefix}/dashboard/{path:path}")
async def serve_dashboard_file(prefix: str, path: str):
    """Static dashboard sub-resources for both wf and stitched views.

    Sub-resource fetches don't rebuild the stitched view (just serve
    from disk), since the bare-index hit already triggered a rebuild
    and the index references reportlet paths that already exist.
    """
    if prefix.startswith("wf_"):
        base = WORK_ROOT / prefix / "dashboard"
    elif _is_scope(prefix):
        base = WORK_ROOT / "done" / prefix / "_view" / "dashboard"
    else:
        return Response(status_code=404)
    resolved = _safe_resolve(base, path)
    if resolved is None:
        return Response(status_code=404)
    return _file_response(resolved)


@app.get("/{prefix}/derivatives/{path:path}")
async def serve_derivatives(prefix: str, path: str):
    """Reportlet PNGs etc. Routes through wf derivatives or the
    stitched view's derivatives dir (which resolves via per-step
    symlinks into the source wf)."""
    if prefix.startswith("wf_"):
        base = WORK_ROOT / prefix / "derivatives"
    elif _is_scope(prefix):
        base = WORK_ROOT / "done" / prefix / "_view" / "derivatives"
    else:
        return Response(status_code=404)
    resolved = _safe_resolve(base, path)
    if resolved is None:
        return Response(status_code=404)
    return _file_response(resolved)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=9002, log_level="info")
