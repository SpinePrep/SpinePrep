"""Generic SCT (Spinal Cord Toolbox) command runner.

Thin wrapper for executing SCT commands with provenance tracking.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any


def get_sct_version() -> str:
    """
    Get installed SCT version.

    Returns:
        SCT version string (e.g., "6.0.0") or "unknown"
    """
    try:
        result = subprocess.run(
            ["sct_version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode == 0:
            # Parse first line of version output
            return result.stdout.strip().split("\n")[0]
    except Exception:
        pass
    return "unknown"


def run_sct_deepseg(
    t2w_path: str,
    out_mask: str,
    contrast: str = "t2",
) -> dict[str, Any]:
    """
    Run sct_deepseg_sc for spinal cord segmentation.

    Args:
        t2w_path: Path to input T2w image
        out_mask: Path to output mask
        contrast: Contrast type (default: "t2")

    Returns:
        Dictionary with:
        - success: bool
        - return_code: int
        - stdout: str
        - stderr: str
        - sct_version: str
        - cmd: str (full command executed)
    """
    # Get SCT version for provenance
    sct_version = get_sct_version()

    # Build command
    cmd = [
        "sct_deepseg_sc",
        "-i",
        t2w_path,
        "-c",
        contrast,
        "-o",
        out_mask,
    ]

    # Ensure output directory exists
    Path(out_mask).parent.mkdir(parents=True, exist_ok=True)

    # Run segmentation
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=600,  # 10 minute timeout
        )

        return {
            "success": result.returncode == 0,
            "return_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "sct_version": sct_version,
            "cmd": " ".join(cmd),
        }

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "return_code": -1,
            "stdout": "",
            "stderr": "sct_deepseg_sc timed out after 10 minutes",
            "sct_version": sct_version,
            "cmd": " ".join(cmd),
        }
    except Exception as e:
        return {
            "success": False,
            "return_code": -1,
            "stdout": "",
            "stderr": str(e),
            "sct_version": sct_version,
            "cmd": " ".join(cmd),
        }


def run_sct_command(
    cmd_args: list[str],
    timeout: int = 600,
) -> dict[str, Any]:
    """
    Generic SCT command runner with provenance.

    Args:
        cmd_args: Command arguments (e.g., ["sct_propseg", "-i", "..."])
        timeout: Timeout in seconds (default: 600)

    Returns:
        Dictionary with success, return_code, stdout, stderr, sct_version, cmd
    """
    sct_version = get_sct_version()

    try:
        result = subprocess.run(
            cmd_args,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )

        return {
            "success": result.returncode == 0,
            "return_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "sct_version": sct_version,
            "cmd": " ".join(cmd_args),
        }

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "return_code": -1,
            "stdout": "",
            "stderr": f"Command timed out after {timeout} seconds",
            "sct_version": sct_version,
            "cmd": " ".join(cmd_args),
        }
    except Exception as e:
        return {
            "success": False,
            "return_code": -1,
            "stdout": "",
            "stderr": str(e),
            "sct_version": sct_version,
            "cmd": " ".join(cmd_args),
        }
