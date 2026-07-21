"""Per-run, per-step timing for benchmarking.

Why this exists
---------------
Before 2026-07-21 the only timing field anywhere was S9's ``smoothing_runtime_s``,
and it read 0.0 on all 450 cohort runs because smoothing is disabled by default.
So the pipeline had, in effect, no timing data, and none could be recovered
retrospectively: S2, S3 and S7 write all nine dataset qc.json files in one burst,
so file mtimes show a 0.0-minute span for those steps.

What is recorded, and why each field
------------------------------------
``wall_s``
    Wall-clock for the run inside the step. The number a user actually waits.

``tool_s``
    Time spent inside external tools (SCT / FSL / ANTs subprocesses), accumulated
    by ``run_command``. Nearly all of SpinePrep's cost is these calls, so
    ``wall_s - tool_s`` is the pipeline's own overhead -- the honest measure of
    what the automation adds on top of the tools it integrates. Reporting only
    ``wall_s`` would let us take credit (or blame) for SCT's runtime.

``n_workers`` / ``gpu_slots`` / ``load_avg_start``
    A duration without its concurrency context is uninterpretable later. The
    reference cohort ran 12-way parallel under ``batch`` on a contended box:
    those numbers are valid for throughput and invalid for latency, and nothing
    in the output said so. ``load_avg_start`` lets an analysis separate the two
    after the fact rather than trusting a label.

``resumed``
    A resumed run reports near-zero time and would silently deflate any average.
    Analysis must exclude these; recording the flag makes that possible.

Timing is not a property of the software alone. Unlike the QC metrics it does
not reproduce across machines, so every record carries its host and core count
and no summary should be quoted without them.
"""

from __future__ import annotations

import contextlib
import os
import platform
import socket
import time
from contextvars import ContextVar
from typing import Any, Optional

# Accumulated external-tool seconds for the run currently being processed.
# A ContextVar rather than a plain global so this stays correct if a step is
# ever parallelised with threads instead of processes.
_TOOL_SECONDS: ContextVar[float] = ContextVar("spineprep_tool_seconds", default=0.0)
_TOOL_CALLS: ContextVar[int] = ContextVar("spineprep_tool_calls", default=0)


def add_tool_time(seconds: float) -> None:
    """Accumulate one external-tool call. Called by ``run_command``."""
    try:
        _TOOL_SECONDS.set(_TOOL_SECONDS.get() + max(0.0, float(seconds)))
        _TOOL_CALLS.set(_TOOL_CALLS.get() + 1)
    except Exception:
        pass


def _load_avg() -> Optional[float]:
    try:
        return round(os.getloadavg()[0], 2)
    except Exception:
        return None


def machine_context() -> dict[str, Any]:
    """Host facts a timing number is meaningless without."""
    ctx: dict[str, Any] = {
        "hostname": socket.gethostname(),
        "n_cores": os.cpu_count(),
        "platform": platform.platform(),
    }
    try:
        with open("/proc/meminfo") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    ctx["ram_gb"] = round(int(line.split()[1]) / 1024 / 1024, 1)
                    break
    except Exception:
        pass
    return ctx


def concurrency_context(n_workers: Optional[int] = None) -> dict[str, Any]:
    """How much else was running. Separates latency from throughput."""
    return {
        "n_workers": n_workers,
        "gpu_slots": int(os.environ.get("SPINEPREP_GPU_SLOTS", "0")) or None,
        "load_avg_start": _load_avg(),
        "benchmark_mode": os.environ.get("SPINEPREP_BENCHMARK") or None,
    }


@contextlib.contextmanager
def time_step(n_workers: Optional[int] = None):
    """Measure one run's wall-clock and its external-tool share.

    Yields a dict that is filled in on exit, so a caller can stash it in the
    run record before the block closes::

        with time_step(n_workers=w) as t:
            ...process the run...
        record["timing"] = t
    """
    out: dict[str, Any] = {}
    tok_s = _TOOL_SECONDS.set(0.0)
    tok_n = _TOOL_CALLS.set(0)
    t0 = time.perf_counter()
    try:
        yield out
    finally:
        wall = time.perf_counter() - t0
        tool = _TOOL_SECONDS.get()
        calls = _TOOL_CALLS.get()
        _TOOL_SECONDS.reset(tok_s)
        _TOOL_CALLS.reset(tok_n)
        # tool_s should be a subset of wall_s. If it exceeds it, the step ran
        # subprocesses concurrently, and "overhead = wall - tool" stops meaning
        # anything. Say so rather than clamping a nonsensical value to zero and
        # letting an analysis average it -- the same coercion that made S9
        # report an unmeasured FWHM as 0.
        concurrent_tools = tool > wall + 0.05
        out.update({
            "wall_s": round(wall, 3),
            "tool_s": round(tool, 3),
            # What the pipeline itself costs on top of the tools it calls.
            # None when it cannot be defined (see above).
            "overhead_s": None if concurrent_tools else round(max(0.0, wall - tool), 3),
            "concurrent_tool_calls": concurrent_tools,
            "n_tool_calls": calls,
            "resumed": False,
            **concurrency_context(n_workers),
            "load_avg_end": _load_avg(),
        })


def resumed_timing(n_workers: Optional[int] = None) -> dict[str, Any]:
    """Timing record for a run served from cache rather than computed.

    Marked so analysis can exclude it: a resumed run costs milliseconds and
    would otherwise deflate every summary it appears in.
    """
    return {
        "wall_s": 0.0, "tool_s": 0.0, "overhead_s": 0.0,
        "concurrent_tool_calls": False, "n_tool_calls": 0,
        "resumed": True,
        **concurrency_context(n_workers),
        "load_avg_end": _load_avg(),
    }


def timed_step(fn):
    """Decorator: record timing into the run record a step function returns.

    Applied to each ``run_S*`` entry point rather than at the call sites,
    because the dispatch style differs by step -- S2/S3/S4 submit to a
    ProcessPoolExecutor while S6-S9 loop serially. Timing inside the function
    is measured in whichever process does the work, so a pooled run records its
    own compute time and not the time it spent queued.

    A decorator also covers every early ``return`` (steps have many failure
    exits) without touching each one.

    Worker count is read from ``SPINEPREP_N_WORKERS``, exported by the
    orchestrator, because it is not visible inside the run function and env
    vars survive the fork into pool workers.
    """
    import functools

    @functools.wraps(fn)
    def _wrapped(*args, **kwargs):
        try:
            n_workers = int(os.environ.get("SPINEPREP_N_WORKERS", "") or 0) or None
        except Exception:
            n_workers = None
        with time_step(n_workers=n_workers) as t:
            res = fn(*args, **kwargs)
        if isinstance(res, dict):
            # setdefault: a step that already recorded its own timing wins.
            res.setdefault("timing", t)
        return res

    return _wrapped
