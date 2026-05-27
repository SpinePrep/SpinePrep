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


def _latest_dashboard_relative_url() -> str:
    """The URL to redirect to from `/`: a wf-name-prefixed path.

    Critical: the scope-banner chip hrefs in each dashboard are
    relative paths computed from the wf-specific location
    `work/<wf_name>/dashboard/index.html`. If we serve the latest
    dashboard at a shorter URL like `/dashboard/index.html`, the
    chip hrefs `../../wf_full_009/...` resolve UP one level too far
    and drop the `/p2` reverse-proxy prefix entirely — sending the
    browser to `271828.space/wf_full_009/...` which hits the 401
    catch-all. Always redirect to the wf-specific path so the
    relative-link depth matches.
    """
    wf = _latest_workfolder()
    if wf is None:
        return "dashboard/index.html"  # fallback (no wf found)
    return f"{wf.name}/dashboard/index.html"


@app.get("/")
async def root():
    """Unified entry point — redirects to the latest workfolder's
    wf-prefixed dashboard URL so the chip-link depth math is correct."""
    return RedirectResponse(url=_latest_dashboard_relative_url(),
                            headers=_NO_CACHE_HEADERS)


@app.get("/dashboard.html")
async def landing_page():
    """Legacy landing-page URL — redirect to the unified dashboard."""
    return RedirectResponse(url=_latest_dashboard_relative_url(),
                            headers=_NO_CACHE_HEADERS)


@app.get("/dashboard")
@app.get("/dashboard/")
async def latest_dashboard_index_redirect():
    """The old `/dashboard` shortcut now redirects to the wf-prefixed
    path (was serving the latest wf's index directly, which broke
    chip-link relative-path resolution under the /p2 reverse proxy)."""
    return RedirectResponse(url="../" + _latest_dashboard_relative_url(),
                            headers=_NO_CACHE_HEADERS)


@app.get("/__spinalfmriprep__/workfolders.json")
async def workfolders_json():
    return JSONResponse(_list_workfolders(), headers=_NO_CACHE_HEADERS)


@app.get("/{wf_name}/dashboard")
@app.get("/{wf_name}/dashboard/")
async def serve_wf_dashboard_index(wf_name: str):
    """Bare `/{wf}/dashboard` or `/{wf}/dashboard/` — serve index.html."""
    if not wf_name.startswith("wf_"):
        return Response(status_code=404)
    index = WORK_ROOT / wf_name / "dashboard" / "index.html"
    if not index.is_file():
        return Response(status_code=404)
    return _file_response(index)


@app.get("/{wf_name}/dashboard/{path:path}")
async def serve_wf_dashboard(wf_name: str, path: str):
    """Serve dashboard files from a specific workfolder."""
    if not wf_name.startswith("wf_"):
        return Response(status_code=404)
    wf_dir = WORK_ROOT / wf_name
    resolved = _safe_resolve(wf_dir / "dashboard", path)
    if resolved is None:
        return Response(status_code=404)
    return _file_response(resolved)


@app.get("/{wf_name}/derivatives/{path:path}")
async def serve_wf_derivatives(wf_name: str, path: str):
    """Serve derivative files (images) from a specific workfolder."""
    if not wf_name.startswith("wf_"):
        return Response(status_code=404)
    wf_dir = WORK_ROOT / wf_name
    resolved = _safe_resolve(wf_dir / "derivatives", path)
    if resolved is None:
        return Response(status_code=404)
    return _file_response(resolved)


@app.get("/dashboard/{path:path}")
async def latest_dashboard_passthrough(path: str):
    """`/dashboard/<file>` shortcut — redirect to the wf-prefixed
    equivalent so the chip-link relative-path math is correct under
    the `/p2` reverse proxy."""
    wf = _latest_workfolder()
    if wf is None:
        return Response("No workfolder with dashboard found", status_code=404)
    return RedirectResponse(
        url=f"../{wf.name}/dashboard/{path}", headers=_NO_CACHE_HEADERS)


@app.get("/derivatives/{path:path}")
async def latest_derivatives_passthrough(path: str):
    """Same redirect for the `/derivatives/<file>` shortcut."""
    wf = _latest_workfolder()
    if wf is None:
        return Response(status_code=404)
    return RedirectResponse(
        url=f"../{wf.name}/derivatives/{path}", headers=_NO_CACHE_HEADERS)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=9002, log_level="info")
