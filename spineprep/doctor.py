from __future__ import annotations
import json, os, platform, shutil, subprocess
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Any, List, Optional
from .provenance import timestamp, ensure_dir

REQ_PAM50 = ["PAM50_t1.nii.gz", "PAM50_spinal_levels.nii.gz"]
PY_DEPS = ["numpy","nibabel","pandas","scipy","snakemake","jsonschema","jinja2"]

@dataclass
class DepStatus:
    found: bool
    version: Optional[str] = None
    path: Optional[str] = None
    files_ok: Optional[bool] = None

def _run(cmd: List[str], timeout=5) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return (r.stdout or r.stderr).strip()

def detect_sct() -> DepStatus:
    exe = shutil.which("sct_version")
    if not exe:
        return DepStatus(found=False)
    try:
        out = _run([exe])
        v = out.splitlines()[0].strip().split()[-1] if out else "unknown"
        return DepStatus(found=True, version=v, path=exe)
    except Exception:
        return DepStatus(found=False, path=exe)

def detect_pam50(explicit: Optional[Path]) -> DepStatus:
    candidates: List[Path] = []
    if explicit:
        candidates.append(explicit)
    sct_dir = os.environ.get("SCT_DIR")
    if sct_dir:
        candidates.append(Path(sct_dir) / "data" / "PAM50")
    for base in [Path.home()/".sct"/"data"/"PAM50", Path("/opt/spinalcordtoolbox/data/PAM50")]:
        candidates.append(base)
    for c in candidates:
        if c and c.is_dir():
            files_ok = all((c/f).exists() for f in REQ_PAM50)
            if files_ok:
                return DepStatus(found=True, path=str(c), files_ok=True)
    return DepStatus(found=False, files_ok=False)

def detect_python_deps() -> Dict[str,str]:
    out: Dict[str,str] = {}
    for m in PY_DEPS:
        try:
            mod = __import__(m)
            ver = getattr(mod, "__version__", "unknown")
            out[m] = str(ver)
        except Exception:
            out[m] = "MISSING"
    return out

def build_report(pam50_path: Optional[str]) -> Dict[str,Any]:
    plat = {
        "os": platform.system(),
        "kernel": platform.release(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count() or 1,
        "ram_gb": round((os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES'))/1e9, 1) if hasattr(os, "sysconf") else None,
    }
    sct = detect_sct()
    pam50 = detect_pam50(Path(pam50_path) if pam50_path else None)
    py = detect_python_deps()

    notes: List[str] = []
    status = "pass"
    if not sct.found:
        status = "fail"
        notes.append("SCT not found: sct_version not on PATH.")
    if not pam50.found:
        status = "fail"
        notes.append("PAM50 not found or incomplete.")
    if any(v=="MISSING" for v in py.values()):
        if status != "fail":
            status = "warn"
        notes.append("Optional Python packages missing.")

    return {
        "spineprep": {"version": "0.0.0"},
        "timestamp": _iso_now(),
        "status": status,
        "platform": plat,
        "deps": {
            "sct": asdict(sct),
            "pam50": asdict(pam50),
            "python": py
        },
        "notes": notes
    }

def _iso_now() -> str:
    import datetime as dt
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat()

def save_report(report: Dict[str,Any], out_dir: Path, explicit_json: Optional[Path]) -> Path:
    ensure_dir(out_dir / "provenance")
    art = out_dir / "provenance" / f"doctor-{timestamp()}.json"
    art.write_text(json.dumps(report, indent=2))
    if explicit_json:
        ensure_dir(explicit_json.parent)
        explicit_json.write_text(json.dumps(report, indent=2))
    return art

def cmd_doctor(out_dir: Path, pam50: Optional[str], json_path: Optional[Path], strict: bool) -> int:
    rep = build_report(pam50)
    art = save_report(rep, out_dir, json_path)
    banner = f"[doctor] {rep['status'].upper()}  →  {art}"
    print(banner)
    for n in rep["notes"]:
        print(f" - {n}")
    if rep["status"] == "fail":
        return 1
    if strict and rep["status"] == "warn":
        return 1
    return 2 if rep["status"] == "warn" else 0
