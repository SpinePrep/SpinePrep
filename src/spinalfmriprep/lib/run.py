"""Shared subprocess execution for external tools (SCT, FSL, ANTs)."""

from __future__ import annotations

import os
import subprocess


def run_command(
    cmd: list[str], timeout: int | None = None, cwd: str | os.PathLike | None = None,
) -> tuple[bool, str]:
    """Run a shell command and return (success, output).

    Enforces single-threaded execution for numerical libraries to avoid
    contention when called from parallel workers.

    ``cwd`` runs the command in a specific directory. This matters for SCT
    tools that drop working files (e.g. sct_straighten_spinalcord writes
    warp_curve2straight.nii.gz + straightening.cache into the *current*
    directory): without a private cwd, concurrent workers race on those
    shared filenames. Pass a per-run dir to isolate them.
    """
    try:
        env = os.environ.copy()
        env["OMP_NUM_THREADS"] = "1"
        env["NUMEXPR_MAX_THREADS"] = "1"
        env["MKL_NUM_THREADS"] = "1"
        result = subprocess.run(
            cmd,
            text=True,
            capture_output=True,
            check=True,
            env=env,
            timeout=timeout,
            cwd=cwd,
        )
    except FileNotFoundError:
        return False, f"Command not found: {cmd[0]}"
    except subprocess.CalledProcessError as err:
        output = "\n".join(part for part in [err.stdout, err.stderr] if part)
        return False, output.strip()
    except subprocess.TimeoutExpired:
        return False, f"Command timed out after {timeout}s: {' '.join(cmd[:3])}"
    output = "\n".join(part for part in [result.stdout, result.stderr] if part)
    return True, output.strip()


def is_command_not_found(message: str) -> bool:
    """Check if an error message indicates a missing command."""
    return "Command not found" in message or "not found" in message.lower()
