from __future__ import annotations

import getpass
import json
import platform
import time
from pathlib import Path


def _prov_path_for(target: str) -> Path:
    p = Path(target)
    if p.suffix in {".tsv", ".json"}:
        return p.with_suffix(p.suffix + ".prov.json")
    # .nii.gz -> .nii.gz.prov.json
    if p.name.endswith(".nii.gz"):
        return p.with_name(p.name + ".prov.json")
    return p.with_suffix(p.suffix + ".prov.json")


def write_prov(target: str, step: str, inputs: dict, params: dict, tools: dict) -> None:
    out = {
        "step": step,
        "target": str(target),
        "inputs": inputs,
        "params": params,
        "tools": tools,
        "time_end": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "host": platform.node(),
        "user": getpass.getuser(),
        "spineprep_version": "0.2.0",
    }
    pp = _prov_path_for(target)
    pp.parent.mkdir(parents=True, exist_ok=True)
    with open(pp, "w") as f:
        json.dump(out, f, indent=2)
