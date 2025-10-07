"""Config loading and path resolution for SpinePrep."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

try:
    import yaml  # type: ignore
except Exception as e:  # pragma: no cover
    raise SystemExit("PyYAML is required: pip install PyYAML") from e


def _abs(p: str) -> str:
    return os.path.abspath(os.path.expanduser(p))


def _normalize_slashes(x: str) -> str:
    return os.path.normpath(x)


def _resolve_paths(paths: Dict[str, Any]) -> Dict[str, str]:
    """
    Resolve templated paths with multi-pass formatting and ensure required keys exist.

    Supported placeholders: any key in `paths`, e.g., {root}, {deriv_dir}, etc.
    Strategy:
      1) Seed defaults if missing: bids_dir, deriv_dir, work_dir, logs_dir.
      2) Run multi-pass str.format() with the current dict until stable or 5 iterations.
      3) Absolutize and normalize.

    Raises:
      ValueError if 'root' is missing or empty.
    """
    if "root" not in paths or not str(paths["root"]).strip():
        raise ValueError("paths.root is required")

    # Seed defaults if missing
    p: Dict[str, str] = {
        k: str(v) for k, v in paths.items() if isinstance(v, (str, int, float))
    }
    p.setdefault("bids_dir", "{root}/bids")
    p.setdefault("deriv_dir", "{root}/derivatives/spineprep")
    p.setdefault("work_dir", "{root}/work/spineprep")
    p.setdefault("logs_dir", "{deriv_dir}/logs")

    # Multi-pass resolution using the dict itself
    for _ in range(5):
        before = dict(p)
        for k, v in list(p.items()):
            try:
                p[k] = str(v).format(**p)
            except KeyError:
                # Leave unresolved; may resolve in later passes
                pass
        if p == before:
            break

    # Absolutize & normalize
    for k, v in list(p.items()):
        p[k] = _normalize_slashes(_abs(v))

    return p


def load_config(cfg_path: str, schema_path: Optional[str] = None) -> Dict[str, Any]:
    """Load YAML config, optionally validate with JSON Schema, and resolve paths."""
    cfg_path = _abs(cfg_path)
    with open(cfg_path, "r") as f:
        cfg = yaml.safe_load(f)

    if schema_path:
        try:
            import jsonschema  # type: ignore
        except Exception:
            print("[WARN] jsonschema not installed; skipping schema validation")
        else:
            with open(schema_path, "r") as sf:
                schema = json.load(sf)
            jsonschema.validate(cfg, schema)

    if "paths" not in cfg:
        raise ValueError("Missing top-level 'paths' in config")

    cfg["paths"] = _resolve_paths(cfg["paths"])
    return cfg
