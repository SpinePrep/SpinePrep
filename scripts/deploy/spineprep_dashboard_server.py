#!/usr/bin/env python3
"""
SpinePrep Canonical Dashboard Server

Serves the latest workflow dashboard from the most recent run under a work root.
Exposes only on localhost; intended to be published via Tailscale Serve.
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
from dataclasses import dataclass
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class Config:
    work_root: Path
    host: str
    port: int
    refresh_seconds: float


def _env_path(name: str, default: str) -> Path:
    return Path(os.environ.get(name, default)).expanduser().resolve()


def _env_str(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except Exception:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except Exception:
        return default


def load_config() -> Config:
    return Config(
        work_root=_env_path("SPINEPREP_WORK_ROOT", "/mnt/ssd1/SpinePrep/work"),
        host=_env_str("SPINEPREP_DASH_HOST", "127.0.0.1"),
        port=_env_int("SPINEPREP_DASH_PORT", 17837),
        refresh_seconds=_env_float("SPINEPREP_DASH_REFRESH_SECONDS", 5.0),
    )


@dataclass
class LatestCache:
    latest_out: Optional[Path] = None
    latest_index: Optional[Path] = None
    checked_at: float = 0.0
    all_workfolders: Optional[list[tuple[str, Path, float]]] = None


def find_all_workfolders(work_root: Path) -> list[tuple[str, Path, float]]:
    """
    Find all workfolders with dashboard/index.html.
    
    Scans all canonical workfolder patterns:
    - wf_smoke_*/dashboard/index.html
    - wf_reg_*/dashboard/index.html
    - wf_full_*/dashboard/index.html
    
    Also supports legacy wf_*/dashboard/index.html pattern for backward compatibility.
    
    Returns list of (workfolder_name, workfolder_path, mtime) tuples,
    sorted by modification time (newest first).
    """
    if not work_root.exists():
        return []

    workfolders: list[tuple[str, Path, float]] = []
    
    # Scan all wf_* patterns (includes wf_smoke_*, wf_reg_*, wf_full_*, and legacy wf_*)
    # Pattern 1: wf_*/dashboard/index.html (flat structure)
    for index_path in work_root.glob("wf_*/dashboard/index.html"):
        try:
            st = index_path.stat()
        except FileNotFoundError:
            continue
        
        # Extract workfolder name from path: work_root/wf_smoke_008/dashboard/index.html -> wf_smoke_008
        try:
            workfolder_path = index_path.parent.parent  # <work_root>/wf_xxx/dashboard/index.html -> <work_root>/wf_xxx
            workfolder_name = workfolder_path.name
            if workfolder_name.startswith("wf_"):
                mtime = st.st_mtime
                workfolders.append((workfolder_name, workfolder_path, mtime))
        except Exception:
            continue
    
    # Pattern 2: wf_*/{dataset_key}/dashboard/index.html (nested dataset structure for regression runs)
    for index_path in work_root.glob("wf_*/*/dashboard/index.html"):
        try:
            st = index_path.stat()
        except FileNotFoundError:
            continue
        
        # Extract workfolder name: work_root/wf_reg_016/reg_xxx_subset/dashboard/index.html
        # Serve from the parent of dashboard (which contains dataset outputs)
        try:
            dataset_path = index_path.parent.parent  # <work_root>/wf_reg_016/reg_xxx_subset
            parent_wf_path = dataset_path.parent  # <work_root>/wf_reg_016
            parent_wf_name = parent_wf_path.name
            dataset_name = dataset_path.name
            # Create a composite name: wf_reg_016/reg_xxx_subset
            composite_name = f"{parent_wf_name}/{dataset_name}"
            if parent_wf_name.startswith("wf_"):
                mtime = st.st_mtime
                workfolders.append((composite_name, dataset_path, mtime))
        except Exception:
            continue
    
    # Sort by modification time (newest first)
    workfolders.sort(key=lambda x: x[2], reverse=True)
    return workfolders


def find_latest_out(work_root: Path) -> Optional[Path]:
    """
    Find the most recent workflow run by scanning for wf_*/dashboard/index.html.
    
    Scans all canonical workfolder patterns:
    - wf_smoke_*/dashboard/index.html
    - wf_reg_*/dashboard/index.html
    - wf_full_*/dashboard/index.html
    
    Also supports legacy wf_*/dashboard/index.html pattern for backward compatibility.
    
    Returns the <out> root directory (parent of dashboard/).
    """
    all_workfolders = find_all_workfolders(work_root)
    if not all_workfolders:
        return None
    
    # Return the first one (newest) - workfolder_path is already the <out> directory
    return all_workfolders[0][1]


def safe_join(root: Path, url_path: str) -> Optional[Path]:
    """
    Safely join a URL path to a root directory, preventing path traversal.
    Returns None if the path would escape the root.
    """
    url_path = url_path.lstrip("/")
    p = Path(url_path)

    # Reject any traversal components
    if any(part in ("..", "") for part in p.parts):
        return None

    candidate = (root / p).resolve()
    try:
        candidate.relative_to(root.resolve())
    except Exception:
        return None
    return candidate


class SpineprepDashboardHandler(SimpleHTTPRequestHandler):
    server_version = "SpinePrepDashboard/1.0"

    def do_GET(self) -> None:
        cfg: Config = self.server.cfg  # type: ignore[attr-defined]
        cache: LatestCache = self.server.cache  # type: ignore[attr-defined]

        # Refresh cache if needed
        now = time.time()
        if now - cache.checked_at >= cfg.refresh_seconds:
            all_workfolders = find_all_workfolders(cfg.work_root)
            latest_out = all_workfolders[0][1] if all_workfolders else None
            cache.latest_out = latest_out
            cache.latest_index = (latest_out / "dashboard" / "index.html") if latest_out else None
            cache.all_workfolders = all_workfolders
            cache.checked_at = now

        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path or "/"

        # Root redirects to dashboard (latest workfolder)
        if path == "/":
            if cache.all_workfolders and len(cache.all_workfolders) > 0:
                # Use the name from all_workfolders which is already a proper URL path component
                # (either "wf_smoke_008" for flat or "wf_reg_016/reg_xxx_subset" for nested)
                latest_wf_name = cache.all_workfolders[0][0]
                self.send_response(HTTPStatus.FOUND)
                self.send_header("Location", f"/{latest_wf_name}/dashboard/index.html")
            else:
                self.send_response(HTTPStatus.FOUND)
                self.send_header("Location", "/dashboard/index.html")
            self.end_headers()
            return

        # Workfolders API endpoint
        if path == "/__spineprep__/workfolders.json":
            if cache.all_workfolders is None:
                cache.all_workfolders = find_all_workfolders(cfg.work_root)
            
            # Find latest for marking
            latest_out = cache.latest_out
            latest_name = latest_out.name if latest_out else None
            
            workfolder_list = []
            for name, wf_path, mtime in (cache.all_workfolders or []):
                workfolder_list.append({
                    "name": name,
                    "path": name,  # URL path component
                    "mtime": mtime,
                    "is_latest": name == latest_name,
                })
            
            body = (json.dumps(workfolder_list, indent=2) + "\n").encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        # Status endpoint
        if path == "/__spineprep__/status.json":
            payload = {
                "work_root": str(cfg.work_root),
                "latest_out": str(cache.latest_out) if cache.latest_out else None,
                "latest_dashboard_index": str(cache.latest_index) if cache.latest_index else None,
                "checked_at_unix": cache.checked_at,
            }
            body = (json.dumps(payload, indent=2) + "\n").encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        # Check for workfolder-prefixed paths: /{workfolder_name}/dashboard/...
        target_workfolder: Optional[Path] = None
        remaining_path = path
        
        # Check if path starts with a workfolder name
        path_parts = path.strip("/").split("/")
        if path_parts and path_parts[0].startswith("wf_"):
            potential_wf_name = path_parts[0]
            potential_wf_path = cfg.work_root / potential_wf_name
            
            # Check for nested structure first: /wf_reg_016/dataset_key/dashboard/...
            if len(path_parts) >= 2 and potential_wf_path.exists():
                nested_path = potential_wf_path / path_parts[1]
                if nested_path.exists() and (nested_path / "dashboard" / "index.html").exists():
                    target_workfolder = nested_path
                    # Remove both wf_xxx and dataset_key from path
                    remaining_path = "/" + "/".join(path_parts[2:])
            
            # Fall back to flat structure: /wf_smoke_008/dashboard/...
            if target_workfolder is None and potential_wf_path.exists() and (potential_wf_path / "dashboard" / "index.html").exists():
                target_workfolder = potential_wf_path
                # Remove workfolder prefix from path: /wf_smoke_008/dashboard/index.html -> /dashboard/index.html
                remaining_path = "/" + "/".join(path_parts[1:])
        
        # Determine which workfolder to serve from
        if target_workfolder:
            serve_from = target_workfolder
        elif cache.latest_out:
            serve_from = cache.latest_out
        else:
            # No workfolders found
            body = (
                "<html><body style='font-family: sans-serif; background: #1a1a1a; color: #e6e6e6; padding: 20px;'>"
                "<h2>SpinePrep dashboard: no runs found</h2>"
                f"<p>Looked under: <code>{cfg.work_root}</code></p>"
                "<p>Expected: <code>wf_*/dashboard/index.html</code></p>"
                "<p>Canonical patterns: <code>wf_smoke_*</code>, <code>wf_reg_*</code>, <code>wf_full_*</code></p>"
                "<p>Generate a dashboard with: <code>spineprep qc --out &lt;out&gt;</code></p>"
                "</body></html>\n"
            ).encode("utf-8")
            self.send_response(HTTPStatus.NOT_FOUND)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        # Serve file from determined workfolder
        fs_path = safe_join(serve_from, remaining_path)
        if fs_path is None or not fs_path.exists():
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return

        # Temporarily set directory and path for SimpleHTTPRequestHandler
        self.directory = str(serve_from)
        # Save original path and modify it to the remaining path
        original_path = self.path
        self.path = remaining_path
        try:
            return super().do_GET()
        finally:
            # Restore original path
            self.path = original_path

    def log_message(self, format: str, *args: object) -> None:
        # Suppress default logging; can be enhanced later if needed
        pass


def main() -> int:
    cfg = load_config()
    cfg.work_root.mkdir(parents=True, exist_ok=True)

    httpd = ThreadingHTTPServer((cfg.host, cfg.port), SpineprepDashboardHandler)
    httpd.cfg = cfg  # type: ignore[attr-defined]
    httpd.cache = LatestCache()  # type: ignore[attr-defined]

    print(f"[spineprep-dashboard] serving latest wf under {cfg.work_root} on {cfg.host}:{cfg.port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[spineprep-dashboard] shutting down")
        httpd.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())



