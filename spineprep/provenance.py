from __future__ import annotations
import datetime as _dt
from pathlib import Path

def timestamp() -> str:
    return _dt.datetime.now().strftime("%Y%m%d_%H%M%S")

def ensure_dir(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p
