"""Spinal Cord Toolbox (SCT) wrapper for EPI→PAM50 registration."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


def build_sct_register_cmd(
    src_image: str,
    dest_image: str,
    out_warp: str,
    out_resampled: str | None = None,
    param: str | None = None,
) -> list[str]:
    """
    Build sct_register_multimodal command.

    Args:
        src_image: Source image path (e.g., EPI reference)
        dest_image: Destination/template image path (e.g., PAM50)
        out_warp: Output warp field path
        out_resampled: Output resampled image path (optional)
        param: Registration parameters (default: rigid+affine)

    Returns:
        Command list for subprocess.run()
    """
    if param is None:
        # Conservative defaults: rigid + affine only (no deformable)
        param = "step=1,type=im,algo=rigid:step=2,type=im,algo=affine"

    cmd = [
        "sct_register_multimodal",
        "-i",
        src_image,
        "-d",
        dest_image,
        "-owarp",
        out_warp,
        "-param",
        param,
    ]

    if out_resampled:
        cmd.extend(["-o", out_resampled])

    return cmd


def run_sct_register(
    src_image: str,
    dest_image: str,
    out_warp: str,
    out_resampled: str | None = None,
    param: str | None = None,
) -> dict[str, Any]:
    """
    Run SCT registration with error handling.

    Args:
        src_image: Source image path
        dest_image: Destination image path
        out_warp: Output warp path
        out_resampled: Output resampled image path (optional)
        param: Custom registration parameters (optional)

    Returns:
        Dictionary with:
        - success: bool
        - return_code: int
        - stdout: str
        - stderr: str
        - sct_version: str
        - command: str
    """
    # Get SCT version for provenance
    sct_version = "unknown"
    try:
        version_proc = subprocess.run(
            ["sct_version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if version_proc.returncode == 0:
            # Parse version from output (first line typically)
            sct_version = version_proc.stdout.strip().split("\n")[0]
    except Exception:
        pass

    # Build command
    cmd = build_sct_register_cmd(src_image, dest_image, out_warp, out_resampled, param)

    # Ensure output directories exist
    Path(out_warp).parent.mkdir(parents=True, exist_ok=True)
    if out_resampled:
        Path(out_resampled).parent.mkdir(parents=True, exist_ok=True)

    # Run registration
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
            "command": " ".join(cmd),
        }

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "return_code": -1,
            "stdout": "",
            "stderr": "Registration timed out after 10 minutes",
            "sct_version": sct_version,
            "command": " ".join(cmd),
        }
    except Exception as e:
        return {
            "success": False,
            "return_code": -1,
            "stdout": "",
            "stderr": str(e),
            "sct_version": sct_version,
            "command": " ".join(cmd),
        }


def check_doctor_status(doctor_json_path: str) -> None:
    """
    Check doctor JSON for SCT and PAM50 availability.

    Args:
        doctor_json_path: Path to doctor.json file

    Raises:
        FileNotFoundError: If doctor.json doesn't exist
        RuntimeError: If required checks are not green
    """
    doctor_path = Path(doctor_json_path)
    if not doctor_path.exists():
        raise FileNotFoundError(
            f"Doctor report not found at {doctor_json_path}. "
            "Run 'spineprep doctor' first to verify SCT installation."
        )

    try:
        with open(doctor_path) as f:
            doctor_data = json.load(f)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Invalid doctor JSON: {e}") from e

    checks = doctor_data.get("checks", {})

    # Check for SCT-related statuses
    required_checks = ["sct_installed", "pam50_available"]
    failed = []

    for check_name in required_checks:
        if check_name in checks:
            status = checks[check_name].get("status", "unknown")
            if status != "green":
                msg = checks[check_name].get("message", "No details")
                failed.append(f"{check_name}: {status} ({msg})")

    if failed:
        raise RuntimeError(
            "Doctor checks failed for SCT/PAM50 (red status):\n"
            + "\n".join(f"  - {f}" for f in failed)
            + "\n\nRun 'spineprep doctor' to diagnose and fix."
        )


def map_sct_error(return_code: int, stderr: str) -> str:
    """
    Map SCT error to actionable message.

    Args:
        return_code: Process return code
        stderr: Standard error output

    Returns:
        Actionable error message
    """
    stderr_lower = stderr.lower()

    if "command not found" in stderr_lower or "no such file" in stderr_lower:
        return (
            "SCT command not found. Please ensure Spinal Cord Toolbox is installed "
            "and available in PATH. See: https://spinalcordtoolbox.com/user_section/installation.html"
        )

    if "cannot open" in stderr_lower or "does not exist" in stderr_lower:
        return (
            "SCT cannot open input file. Check that image paths are correct "
            "and files exist."
        )

    if "template" in stderr_lower or "pam50" in stderr_lower:
        return (
            "SCT cannot find PAM50 template. Ensure SCT_DIR environment variable "
            "is set and templates are installed."
        )

    if "registration failed" in stderr_lower or "convergence" in stderr_lower:
        return (
            "Registration did not converge. Input images may have poor contrast, "
            "misaligned orientations, or insufficient overlap."
        )

    # Generic error
    return f"SCT registration failed (exit {return_code}): {stderr[:200]}"


def create_output_paths(
    subject: str,
    task: str,
    out_dir: str,
    session: str | None = None,
) -> dict[str, str]:
    """
    Create BIDS-compliant output paths for registration derivatives.

    Args:
        subject: Subject ID (e.g., 'sub-01')
        task: Task name (e.g., 'rest')
        out_dir: Output derivatives directory
        session: Optional session ID (e.g., 'ses-01')

    Returns:
        Dictionary of output paths:
        - warp: transformation file
        - registered: registered BOLD reference in PAM50 space
        - metrics: metrics JSON
        - mosaic_before: before mosaic PNG
        - mosaic_after: after mosaic PNG
    """
    # Build base path
    base = Path(out_dir) / "spineprep" / subject
    if session:
        base = base / session

    # Construct BIDS entities
    entities = subject
    if session:
        entities += f"_{session}"
    entities += f"_task-{task}"

    # Output paths
    xfm_dir = base / "xfm"
    func_dir = base / "func"
    qc_dir = base / "qc" / "registration"

    return {
        "warp": str(xfm_dir / f"{entities}_from-epi_to-PAM50_desc-sct_xfm.nii.gz"),
        "registered": str(func_dir / f"{entities}_space-PAM50_desc-ref_bold.nii.gz"),
        "metrics": str(qc_dir / f"{entities}_desc-registration_metrics.json"),
        "mosaic_before": str(qc_dir / f"{entities}_desc-before_mosaic.png"),
        "mosaic_after": str(qc_dir / f"{entities}_desc-after_mosaic.png"),
    }
