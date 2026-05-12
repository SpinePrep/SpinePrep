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

app = FastAPI(title="SpinalfMRIprep QC Dashboard", docs_url=None, redoc_url=None)


def _list_workfolders() -> list[dict]:
    """Return workfolders sorted by modification time (newest first)."""
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
    # Mark newest with a dashboard as latest
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


# --- Routes ---


@app.get("/")
async def root():
    # Relative target so the redirect resolves correctly when the server
    # is mounted under a reverse-proxy prefix (e.g. 271828.space/p2/).
    return RedirectResponse(url="dashboard/index.html")


@app.get("/__spinalfmriprep__/workfolders.json")
async def workfolders_json():
    return JSONResponse(_list_workfolders())


@app.get("/{wf_name}/dashboard/{path:path}")
async def serve_wf_dashboard(wf_name: str, path: str):
    """Serve dashboard files from a specific workfolder."""
    if not wf_name.startswith("wf_"):
        return Response(status_code=404)
    wf_dir = WORK_ROOT / wf_name
    resolved = _safe_resolve(wf_dir / "dashboard", path)
    if resolved is None:
        return Response(status_code=404)
    return FileResponse(resolved, media_type=_guess_media_type(resolved))


@app.get("/{wf_name}/derivatives/{path:path}")
async def serve_wf_derivatives(wf_name: str, path: str):
    """Serve derivative files (images) from a specific workfolder."""
    if not wf_name.startswith("wf_"):
        return Response(status_code=404)
    wf_dir = WORK_ROOT / wf_name
    resolved = _safe_resolve(wf_dir / "derivatives", path)
    if resolved is None:
        return Response(status_code=404)
    return FileResponse(resolved, media_type=_guess_media_type(resolved))


@app.get("/dashboard/{path:path}")
async def serve_latest_dashboard(path: str):
    """Serve dashboard files from the latest workfolder."""
    wf = _latest_workfolder()
    if wf is None:
        return Response("No workfolder with dashboard found", status_code=404)
    resolved = _safe_resolve(wf / "dashboard", path)
    if resolved is None:
        return Response(status_code=404)
    return FileResponse(resolved, media_type=_guess_media_type(resolved))


@app.get("/derivatives/{path:path}")
async def serve_latest_derivatives(path: str):
    """Serve derivative files from the latest workfolder."""
    wf = _latest_workfolder()
    if wf is None:
        return Response(status_code=404)
    resolved = _safe_resolve(wf / "derivatives", path)
    if resolved is None:
        return Response(status_code=404)
    return FileResponse(resolved, media_type=_guess_media_type(resolved))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=9002, log_level="info")
