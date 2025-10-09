"""Environment diagnostics for SpinePrep."""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from spineprep._version import __version__

# Required PAM50 files for basic validation
REQ_PAM50 = ["PAM50_t1.nii.gz", "PAM50_spinal_levels.nii.gz"]

# Python dependencies to check
PY_DEPS = ["numpy", "pandas", "scipy", "nibabel", "snakemake", "jsonschema", "jinja2"]


def detect_sct() -> dict[str, Any]:
    """
    Detect Spinal Cord Toolbox installation.

    Returns:
        Dictionary with 'found', 'version', and 'path' keys.
    """
    result = {"found": False, "version": "", "path": ""}

    # Try which first
    sct_bin = shutil.which("sct_version")
    if sct_bin:
        try:
            proc = subprocess.run(
                [sct_bin],
                capture_output=True,
                text=True,
                timeout=5,
            )
            output = (proc.stdout or proc.stderr).strip()
            version = output.splitlines()[0].strip() if output else "unknown"
            return {"found": True, "version": version, "path": sct_bin}
        except Exception:
            return {"found": False, "version": "", "path": sct_bin}

    # Try SCT_DIR environment variable
    sct_dir = os.environ.get("SCT_DIR")
    if sct_dir:
        sct_bin_candidate = Path(sct_dir) / "bin" / "sct_version"
        if sct_bin_candidate.exists():
            try:
                proc = subprocess.run(
                    [str(sct_bin_candidate)],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                output = (proc.stdout or proc.stderr).strip()
                version = output.splitlines()[0].strip() if output else "unknown"
                return {
                    "found": True,
                    "version": version,
                    "path": str(sct_bin_candidate),
                }
            except Exception:
                return {"found": False, "version": "", "path": str(sct_bin_candidate)}

    return result


def detect_pam50(explicit: str | None) -> dict[str, Any]:
    """
    Detect PAM50 template data.

    Args:
        explicit: Explicit path to PAM50 directory

    Returns:
        Dictionary with 'found', 'path', and 'files_ok' keys.
    """
    candidates: list[Path] = []

    if explicit:
        # If explicit path given, only check that
        explicit_path = Path(explicit)
        if explicit_path.is_dir():
            files_ok = all((explicit_path / f).exists() for f in REQ_PAM50)
            return {
                "found": True,
                "path": str(explicit_path),
                "files_ok": files_ok,
            }
        # Explicit path doesn't exist
        return {"found": False, "path": "", "files_ok": False}

    # No explicit path, check common locations
    sct_dir = os.environ.get("SCT_DIR")
    if sct_dir:
        candidates.append(Path(sct_dir) / "data" / "PAM50")

    # Common install locations
    candidates.extend(
        [
            Path.home() / ".sct" / "data" / "PAM50",
            Path("/opt/spinalcordtoolbox/data/PAM50"),
            Path("/usr/local/sct/data/PAM50"),
        ]
    )

    for candidate in candidates:
        if candidate and candidate.is_dir():
            files_ok = all((candidate / f).exists() for f in REQ_PAM50)
            return {
                "found": True,
                "path": str(candidate),
                "files_ok": files_ok,
            }

    return {"found": False, "path": "", "files_ok": False}


def detect_python_deps() -> dict[str, str]:
    """
    Detect Python package dependencies.

    Returns:
        Dictionary mapping package names to versions (or empty string if missing).
    """
    out: dict[str, str] = {}
    for pkg in PY_DEPS:
        try:
            mod = __import__(pkg)
            ver = getattr(mod, "__version__", "unknown")
            out[pkg] = str(ver)
        except ImportError:
            out[pkg] = ""
    return out


def detect_os_info() -> dict[str, Any]:
    """
    Detect OS and hardware information.

    Returns:
        Dictionary with platform details.
    """
    info = {
        "os": platform.system(),
        "kernel": platform.release(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count() or 1,
        "ram_gb": 0,
    }

    # Get RAM if available
    if hasattr(os, "sysconf"):
        try:
            info["ram_gb"] = round(
                (os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")) / 1e9, 1
            )
        except Exception:
            info["ram_gb"] = 0

    return info


def check_disk_space() -> int:
    """
    Check available disk space.

    Returns:
        Free bytes available on the filesystem containing cwd.
    """
    try:
        stat = os.statvfs(Path.cwd())
        return stat.f_bavail * stat.f_frsize
    except Exception:
        return 0


def check_writeable(path: Path) -> bool:
    """
    Check if a directory is writeable.

    Args:
        path: Directory to check

    Returns:
        True if writeable, False otherwise.
    """
    try:
        # Try to create a temporary file
        test_file = path / f".spineprep_test_{os.getpid()}"
        test_file.write_text("test")
        test_file.unlink()
        return True
    except Exception:
        return False


def generate_report(
    sct_info: dict[str, Any],
    pam50_info: dict[str, Any],
    python_deps: dict[str, str],
    os_info: dict[str, Any],
    disk_free: int,
    cwd_writeable: bool,
    tmp_writeable: bool,
    strict: bool = False,
) -> dict[str, Any]:
    """
    Generate a complete doctor report.

    Args:
        sct_info: SCT detection results
        pam50_info: PAM50 detection results
        python_deps: Python dependencies detection results
        os_info: OS information
        disk_free: Free disk space in bytes
        cwd_writeable: Whether cwd is writeable
        tmp_writeable: Whether /tmp is writeable
        strict: If True, warnings become failures

    Returns:
        Complete report dictionary matching ticket A1 format.
    """
    notes: list[str] = []
    status = "pass"

    # Check SCT (hard requirement)
    if not sct_info["found"]:
        status = "fail"
        notes.append(
            "HARD FAIL: SCT not found. Install from https://github.com/spinalcordtoolbox/spinalcordtoolbox"
        )
        notes.append(
            "Remediation: Use Docker (docker pull sctorg/sct:latest) or "
            "Apptainer/Singularity, or install locally via official installer."
        )

    # Check PAM50 (hard requirement)
    if not pam50_info["found"]:
        status = "fail"
        notes.append("HARD FAIL: PAM50 directory not found.")
    elif not pam50_info.get("files_ok", False):
        status = "fail"
        notes.append(
            f"HARD FAIL: PAM50 directory exists but required files are missing ({', '.join(REQ_PAM50)})."
        )

    # Check Python deps (soft requirement)
    missing_deps = [pkg for pkg, ver in python_deps.items() if not ver]
    if missing_deps:
        if status != "fail":
            status = "warn"
        notes.append(f"Missing optional Python packages: {', '.join(missing_deps)}")

    # Apply strict mode
    if strict and status == "warn":
        status = "fail"

    # Build report matching ticket A1 format
    return {
        "python": {"version": os_info["python"]},
        "spineprep": {"version": __version__},
        "platform": {
            "os": os_info["os"],
            "kernel": os_info.get("kernel", "unknown"),
            "cpu_count": os_info.get("cpu_count", 0),
            "ram_gb": os_info.get("ram_gb", 0),
        },
        "packages": python_deps,
        "sct": {
            "present": sct_info["found"],
            "version": sct_info.get("version", ""),
            "path": sct_info.get("path", ""),
        },
        "pam50": {
            "present": pam50_info["found"] and pam50_info.get("files_ok", False),
            "path": pam50_info.get("path", ""),
        },
        "disk": {"free_bytes": disk_free},
        "cwd_writeable": cwd_writeable,
        "tmp_writeable": tmp_writeable,
        "timestamp": datetime.now(timezone.utc).astimezone().isoformat(),
        "status": status,
        "notes": notes,
    }


def write_doctor_report(
    report: dict[str, Any],
    out_dir: Path,
    json_path: Path | str | None = None,
) -> Path:
    """
    Write doctor report to JSON file.

    Args:
        report: Report dictionary
        out_dir: Output directory for provenance files
        json_path: Optional custom JSON path for additional copy (Path or str, but not "-")

    Returns:
        Path to the main JSON report file.
    """
    # Ensure provenance directory exists
    prov_dir = out_dir / "provenance"
    prov_dir.mkdir(parents=True, exist_ok=True)

    # Generate timestamped filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    main_json = prov_dir / f"doctor-{timestamp}.json"

    # Write main report
    with open(main_json, "w") as f:
        json.dump(report, f, indent=2)

    # Write additional copy if requested
    if json_path and json_path != "-":
        json_p = Path(json_path) if isinstance(json_path, str) else json_path
        json_p.parent.mkdir(parents=True, exist_ok=True)
        with open(json_p, "w") as f:
            json.dump(report, f, indent=2)

    return main_json


def print_doctor_table(report: dict[str, Any]) -> None:
    """
    Print colorized doctor report table to stdout.

    Args:
        report: Report dictionary
    """
    # ANSI color codes
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    RESET = "\033[0m"
    BOLD = "\033[1m"

    status = report["status"]
    if status == "pass":
        status_color = GREEN
        status_symbol = "✓"
    elif status == "warn":
        status_color = YELLOW
        status_symbol = "⚠"
    else:
        status_color = RED
        status_symbol = "✗"

    # Print header
    print()
    print("=" * 70)
    print(f"  {BOLD}SpinePrep Doctor - Environment Diagnostics{RESET}")
    print("=" * 70)
    print(
        f"  Overall Status: [{status_color}{status_symbol}{RESET}] {status_color}{status.upper()}{RESET}"
    )
    print("=" * 70)
    print()

    # Platform info
    plat = report["platform"]
    py_ver = report["python"]["version"]
    print("Platform:")
    print(f"  OS:       {plat['os']} {plat.get('kernel', 'unknown')}")
    print(f"  Python:   {py_ver}")
    print(f"  CPU:      {plat['cpu_count']} cores")
    if plat.get("ram_gb"):
        print(f"  RAM:      {plat['ram_gb']} GB")
    print()

    # Dependencies
    print("Dependencies:")

    # SCT
    sct = report["sct"]
    if sct["present"]:
        print(f"  [{GREEN}✓{RESET}] SCT:")
        print(f"      Version: {sct.get('version', 'unknown')}")
        print(f"      Path:    {sct.get('path', 'unknown')}")
    else:
        print(f"  [{RED}✗{RESET}] SCT:")
        print("      Status:  NOT FOUND")

    # PAM50
    pam50 = report["pam50"]
    if pam50["present"]:
        print(f"  [{GREEN}✓{RESET}] PAM50:")
        print(f"      Path:    {pam50.get('path', 'unknown')}")
    else:
        print(f"  [{RED}✗{RESET}] PAM50:")
        if pam50.get("path"):
            print(f"      Path:    {pam50.get('path', 'unknown')}")
            print("      Status:  INCOMPLETE (missing required files)")
        else:
            print("      Status:  NOT FOUND")

    # Python packages
    py_deps = report.get("packages", {})
    if py_deps:
        missing = [pkg for pkg, ver in py_deps.items() if not ver]
        if not missing:
            print(f"  [{GREEN}✓{RESET}] Python Packages:")
        else:
            print(f"  [{YELLOW}⚠{RESET}] Python Packages:")
        for pkg, ver in sorted(py_deps.items()):
            if ver:
                print(f"      {pkg:15} {ver}")
            else:
                print(f"      {pkg:15} {RED}MISSING{RESET}")

    # Disk & permissions
    print()
    print("Disk & Permissions:")
    disk_gb = report["disk"]["free_bytes"] / 1e9
    print(f"  Disk free:    {disk_gb:.1f} GB")
    cwd_symbol = f"{GREEN}✓{RESET}" if report["cwd_writeable"] else f"{RED}✗{RESET}"
    tmp_symbol = f"{GREEN}✓{RESET}" if report["tmp_writeable"] else f"{RED}✗{RESET}"
    print(f"  CWD write:    [{cwd_symbol}]")
    print(f"  /tmp write:   [{tmp_symbol}]")

    # Notes
    if report["notes"]:
        print()
        print("Notes:")
        for note in report["notes"]:
            if "HARD FAIL" in note:
                print(f"  {RED}•{RESET} {note}")
            elif "Remediation" in note:
                print(f"  {YELLOW}•{RESET} {note}")
            elif "Missing" in note or "missing" in note:
                print(f"  {YELLOW}•{RESET} {note}")
            else:
                print(f"  • {note}")

    print()
    print("=" * 70)
    print()


def cmd_doctor(
    out_dir: Path,
    pam50: str | None,
    json_path: Path | str | None,
    strict: bool,
) -> int:
    """
    Run doctor diagnostics command.

    Args:
        out_dir: Output directory for provenance files
        pam50: Explicit PAM50 path (optional)
        json_path: Optional custom JSON path (Path object, "-" for stdout, or None)
        strict: Treat warnings as errors

    Returns:
        Exit code: 0 for pass, 1 for fail, 2 for warn.
    """
    # Detect all components
    sct_info = detect_sct()
    pam50_info = detect_pam50(pam50)
    python_deps = detect_python_deps()
    os_info = detect_os_info()
    disk_free = check_disk_space()
    cwd_writeable = check_writeable(Path.cwd())
    tmp_writeable = check_writeable(Path(tempfile.gettempdir()))

    # Generate report
    report = generate_report(
        sct_info,
        pam50_info,
        python_deps,
        os_info,
        disk_free,
        cwd_writeable,
        tmp_writeable,
        strict=strict,
    )

    # Handle JSON output
    if json_path:
        if str(json_path) == "-":
            # Output to stdout
            json.dump(report, sys.stdout, indent=2)
            sys.stdout.write("\n")
            return 0 if report["status"] == "pass" else 1
        else:
            # Write to specified file
            report_path = write_doctor_report(report, out_dir, json_path=json_path)
            print(f"Doctor report written to: {report_path}")
            if json_path:
                print(f"Additional copy written to: {json_path}")
            print()
    else:
        # Normal mode: write to provenance and print table
        report_path = write_doctor_report(report, out_dir, json_path=None)
        print_doctor_table(report)
        print(f"Doctor report written to: {report_path}")
        print()

    # Exit code based on status
    if report["status"] == "fail":
        return 1
    elif report["status"] == "warn":
        return 2
    return 0
