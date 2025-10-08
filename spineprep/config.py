from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, Optional
import copy, json, yaml
from jsonschema import validate

def _read_yaml(p: Path) -> Dict[str, Any]:
    return {} if not p.exists() else yaml.safe_load(p.read_text()) or {}

def _deep_merge(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(a)
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out

def load_schema() -> Dict[str, Any]:
    return json.loads(Path("schemas/config.schema.json").read_text())

def load_defaults() -> Dict[str, Any]:
    return _read_yaml(Path("configs/base.yaml"))

def resolve_config(
    bids_root: Optional[str],
    out_dir: Optional[str],
    yaml_path: Optional[Path],
    cli_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    cfg = load_defaults()
    if yaml_path:
        cfg = _deep_merge(cfg, _read_yaml(yaml_path))
    if bids_root is not None:
        cfg["bids_root"] = bids_root
    if out_dir is not None:
        cfg["output_dir"] = out_dir
    if cli_overrides:
        cfg = _deep_merge(cfg, cli_overrides)
    validate(instance=cfg, schema=load_schema())
    return cfg

def print_config(cfg: Dict[str, Any]) -> str:
    return yaml.safe_dump(cfg, sort_keys=False)
