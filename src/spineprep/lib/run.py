"""Shared subprocess execution for external tools (SCT, FSL, ANTs)."""

from __future__ import annotations

import contextlib
import fcntl
import os
import subprocess
import time


@contextlib.contextmanager
def _gpu_slot():
    """Cross-process cap on concurrent GPU (``sct_deepseg``) calls.

    A shared/limited GPU (e.g. one partly used by other users' workloads) can
    only host a few nnU-Net models at once, but the pipeline may run many CPU
    workers in parallel. This gates GPU calls to ``SPINEPREP_GPU_SLOTS`` at a
    time across ALL processes via ``flock`` on N slot files, so wide CPU
    parallelism never OOMs the GPU. A crashed holder frees its slot
    automatically (fd closes on process death). No-op when the env var is unset
    or <= 0.
    """
    n = int(os.environ.get("SPINEPREP_GPU_SLOTS", "0"))
    if n <= 0:
        yield
        return
    slot_dir = os.environ.get("SPINEPREP_GPU_SLOT_DIR", "/tmp/spineprep_gpu_slots")
    os.makedirs(slot_dir, exist_ok=True)
    while True:
        for i in range(n):
            f = open(os.path.join(slot_dir, f"slot{i}.lock"), "w")
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                f.close()
                continue
            try:
                yield
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                f.close()
            return
        time.sleep(0.4)


def _is_gpu_cmd(cmd: list[str]) -> bool:
    return bool(cmd) and os.path.basename(str(cmd[0])) == "sct_deepseg"


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
        with (_gpu_slot() if _is_gpu_cmd(cmd) else contextlib.nullcontext()):
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
