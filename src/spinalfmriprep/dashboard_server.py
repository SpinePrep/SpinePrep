"""Persistent QC dashboard web server for SpinalfMRIprep.

Serves pre-generated static dashboard HTML and reportlet images
from workfolders under WORK_ROOT. Listens on port 9002, accessible
externally via 271828.space/p2/.

Usage:
    python -m spinalfmriprep.dashboard_server
    # or: uvicorn spinalfmriprep.dashboard_server:app --port 9002
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response

WORK_ROOT = Path(os.environ.get("SFMRI_WORK_ROOT", "/mnt/ssd1/SpinalfMRIprep/work"))
VISIBLE_SCOPES: tuple[str, ...] = ("reg", "full")
DEFAULT_SCOPE = "reg"

# `redirect_slashes=False` is critical: Starlette's default trailing-
# slash auto-redirect emits an absolute `Location: /dashboard/` that
# drops the `/p2` reverse-proxy prefix, sending the browser to
# `271828.space/dashboard/` which falls through to the catch-all
# returning HTTP 401 "auth required". Handling bare and trailing-slash
# paths explicitly (no redirect) keeps the prefix intact.
app = FastAPI(
    title="SpinalfMRIprep QC Dashboard",
    docs_url=None, redoc_url=None,
    redirect_slashes=False,
)


def _list_workfolders() -> list[dict]:
    """Return workfolders sorted by modification time (newest first).

    `is_latest` prefers non-smoke (reg/full) workfolders over smoke.
    Smoke runs are sanity checks that often follow a reg pass; without
    this preference the dashboard's latest view flips to the smoke and
    hides the full reg set (recurring user-reported "only N images"
    symptom). Smoke can still be selected explicitly via the workfolder
    picker; it only loses the default-latest tiebreaker.
    """
    dirs = [d for d in WORK_ROOT.glob("wf_*") if d.is_dir()]
    dirs.sort(key=lambda d: d.stat().st_mtime, reverse=True)
    wfs = []
    for d in dirs:
        has_dashboard = (d / "dashboard" / "index.html").exists()
        wfs.append({
            "name": d.name,
            "path": d.name,
            "has_dashboard": has_dashboard,
            "is_latest": False,
        })

    def _is_smoke(name: str) -> bool:
        return name.startswith("wf_smoke_")

    # First pass: latest non-smoke with a dashboard.
    for wf in wfs:
        if wf["has_dashboard"] and not _is_smoke(wf["name"]):
            wf["is_latest"] = True
            return wfs
    # Fallback: latest smoke if no reg/full has a dashboard.
    for wf in wfs:
        if wf["has_dashboard"]:
            wf["is_latest"] = True
            break
    return wfs


def _latest_workfolder() -> Path | None:
    """Return path to the latest workfolder that has a dashboard."""
    for wf in _list_workfolders():
        if wf["is_latest"]:
            return WORK_ROOT / wf["name"]
    return None


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


@app.get("/__spinalfmriprep__/workfolders.json")
async def workfolders_json():
    return JSONResponse(_list_workfolders(), headers=_NO_CACHE_HEADERS)


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
@app.get("/{prefix}/dashboard/")
async def serve_dashboard_index(prefix: str):
    """Bare `/{prefix}/dashboard` — serves either a wf's per-wf
    dashboard (when prefix starts with ``wf_``) or the stitched
    per-scope dashboard (when prefix in VISIBLE_SCOPES). 404 otherwise."""
    if prefix.startswith("wf_"):
        index = WORK_ROOT / prefix / "dashboard" / "index.html"
        if not index.is_file():
            return Response(status_code=404)
        return _file_response(index)
    if prefix in VISIBLE_SCOPES:
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
    elif prefix in VISIBLE_SCOPES:
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
    elif prefix in VISIBLE_SCOPES:
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
