"""Read a step's policy YAML, with an optional named preset laid over it.

A preset is a folder ``policy/presets/<name>/`` holding, per step, a YAML with only the
keys it changes. ``SPINEPREP_PRESET=<name>`` selects it; the defaults in ``policy/`` stay
as they are. Nested mappings merge key by key; any other value replaces the default.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml


def _merge(base: Any, over: Any) -> Any:
    if isinstance(base, dict) and isinstance(over, dict):
        out = dict(base)
        for k, v in over.items():
            out[k] = _merge(base.get(k), v)
        return out
    return over


def active_preset() -> str | None:
    name = os.environ.get("SPINEPREP_PRESET", "").strip()
    return name or None


def read_policy_yaml(path: Path) -> Any:
    """``yaml.safe_load`` of ``path``, with the active preset's file of the same name merged on top."""
    path = Path(path)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    name = active_preset()
    if name:
        preset_dir = path.parent / "presets" / name
        if not preset_dir.is_dir():
            raise ValueError(f"SPINEPREP_PRESET={name}: no folder {preset_dir}")
        over = preset_dir / path.name
        if over.exists():
            data = _merge(data or {}, yaml.safe_load(over.read_text(encoding="utf-8")) or {})
    return data
