"""Stitched per-scope dashboard view.

One dashboard URL per scope (reg / full) that always shows the LATEST
state of the chain, with per-step locking:

- Approved step (work/done/<scope>/Sn symlink exists) → step card sources
  reportlets + qc from that pinned wf. Cannot change unless re-approved.
- Unapproved step (no done/Sn symlink) → step card sources from the most
  recent wf that has step Sn's data. Changes with every new run.

Implementation: build a "view" directory at ``work/done/<scope>/_view/``
whose ``logs/`` contains per-step symlinks into the source wf chosen by
the above rule. ``qc_dashboard.generate_dashboard`` already handles
chain symlinks (via ``_materialize_chain_reportlet``), so it renders
the stitched dashboard correctly. We thread the locked-step set into
the renderer so approved steps get a LOCKED pill.

This module is read-only with respect to the source wfs; the only files
it writes live under ``work/done/<scope>/_view/``.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

VISIBLE_SCOPES: tuple[str, ...] = ("reg", "full")
MAX_STEP = 11


def _step_logs_subdir(wf: Path, step_num: int) -> Optional[Path]:
    """Return ``wf/logs/S{n}_<name>`` if it exists and has qc.json, else None.

    Accepts both layouts:
      - per-dataset: ``S{n}_<name>/<dataset>/qc.json`` (S1–S10)
      - aggregate:  ``S{n}_<name>/qc.json``           (S11 release report)
    """
    logs = wf / "logs"
    if not logs.exists():
        return None
    prefix = f"S{step_num}_"
    candidates: list[Path] = []
    for entry in logs.iterdir():
        if not entry.name.startswith(prefix):
            continue
        if entry.name.endswith("_evidence"):
            continue
        try:
            real = entry.resolve()
        except Exception:
            continue
        if not real.is_dir():
            continue
        # Aggregate layout (S11) — qc.json sits directly under the step dir
        if (real / "qc.json").exists():
            candidates.append(entry)
            continue
        # Per-dataset layout — qc.json under a dataset subdir
        for sub in real.iterdir():
            if sub.is_dir() and (sub / "qc.json").exists():
                candidates.append(entry)
                break
    return candidates[0] if candidates else None


def _latest_wf_with_step(
    work_root: Path, step_num: int, scope: str,
) -> Optional[Path]:
    """Find the most recent ``wf_{scope}_*`` whose logs contain S{step_num}.

    Sort by the *step subdirectory's* mtime, not the wf root mtime —
    a wf's root mtime gets bumped by unrelated activity (symlink edits,
    chained downstream steps writing into the same wf), which would
    falsely promote a wf whose S{step_num} data is actually stale.
    """
    pattern = f"wf_{scope}_*"
    candidates: list[tuple[float, Path]] = []
    for wf in work_root.glob(pattern):
        if not wf.is_dir():
            continue
        step_dir = _step_logs_subdir(wf, step_num)
        if step_dir is None:
            continue
        try:
            mtime = step_dir.resolve().stat().st_mtime
        except OSError:
            continue
        candidates.append((mtime, wf))
    if not candidates:
        return None
    candidates.sort(key=lambda t: t[0], reverse=True)
    return candidates[0][1]


def _approved_wf(done_root: Path, step_num: int) -> Optional[Path]:
    """Resolve ``work/done/<scope>/S{n}`` if it points at a real wf."""
    link = done_root / f"S{step_num}"
    if not link.is_symlink():
        return None
    try:
        target = link.resolve()
    except Exception:
        return None
    return target if target.exists() and target.name.startswith("wf_") else None


def _clear_stale_step_links(view_logs: Path) -> None:
    """Remove ``S{n}_*`` symlinks under view_logs so we can rebuild cleanly."""
    if not view_logs.exists():
        return
    for entry in view_logs.iterdir():
        if not entry.is_symlink():
            continue
        if entry.name.startswith("S") and ("_" in entry.name or entry.name[1:].isdigit()):
            try:
                entry.unlink()
            except OSError:
                pass


def _link_cohort_deliverables(view_root: Path, source_wf: Path) -> None:
    """Symlink S11's cohort-level derivative *files* into the view.

    The S11 release banner in ``qc_dashboard_html`` looks for
    ``out_dir/derivatives/spinalfmriprep/release_report.html`` and
    ``group_qc_dashboard.html``. These live at the cohort tier of the S11
    source wf's derivatives tree (not under any subject). We symlink
    only the top-level FILES — not the per-subject subdirs, which would
    conflict with the per-step source wfs' contributions to those same
    subjects.
    """
    src_top = source_wf / "derivatives" / "spinalfmriprep"
    if not src_top.exists():
        return
    dest_top = view_root / "derivatives" / "spinalfmriprep"
    dest_top.mkdir(parents=True, exist_ok=True)
    for entry in src_top.iterdir():
        if not entry.is_file():
            continue
        dest = dest_top / entry.name
        if dest.is_symlink() or dest.exists():
            try:
                dest.unlink()
            except OSError:
                continue
        try:
            dest.symlink_to(entry.resolve())
        except OSError:
            pass


def build_view(scope: str, work_root: Path) -> tuple[Path, set[str], dict[str, str]]:
    """Build/refresh ``work/done/<scope>/_view/`` with per-step symlinks.

    Returns:
        (view_dir, locked_step_codes, source_wf_per_step)

    ``locked_step_codes`` is the set of full step codes (e.g.
    ``S5_func_distortion_correction``) that came from an approved
    done symlink; the renderer uses this for the LOCKED pill.
    ``source_wf_per_step`` maps step_code → source wf name (for the
    "source: wf_reg_NNN" line in the step card).
    """
    work_root = Path(work_root).resolve()
    done_root = work_root / "done" / scope
    view_root = done_root / "_view"
    view_logs = view_root / "logs"

    view_root.mkdir(parents=True, exist_ok=True)
    view_logs.mkdir(exist_ok=True)
    _clear_stale_step_links(view_logs)

    locked: set[str] = set()
    sources: dict[str, str] = {}

    for n in range(1, MAX_STEP + 1):
        approved = _approved_wf(done_root, n)
        source_wf = approved
        is_locked = approved is not None

        if source_wf is None:
            source_wf = _latest_wf_with_step(work_root, n, scope)
        if source_wf is None or not source_wf.exists():
            continue

        step_dir = _step_logs_subdir(source_wf, n)
        if step_dir is None:
            continue

        # Symlink the full step dir into the view's logs/ so chain
        # resolution in qc_dashboard works naturally.
        link_path = view_logs / step_dir.name
        try:
            if link_path.is_symlink() or link_path.exists():
                link_path.unlink()
        except OSError:
            pass
        try:
            link_path.symlink_to(step_dir.resolve())
        except OSError as e:
            logger.warning("Failed to symlink %s -> %s: %s",
                           link_path, step_dir, e)
            continue

        sources[step_dir.name] = source_wf.name
        if is_locked:
            locked.add(step_dir.name)

        # S11's release banner needs the cohort-tier deliverables
        # (release_report.html / group_qc_dashboard.html) reachable
        # via the dashboard's ``../derivatives/spinalfmriprep/`` path.
        if n == 11:
            _link_cohort_deliverables(view_root, source_wf)

    return view_root, locked, sources


def render_view(scope: str, work_root: Path) -> Optional[Path]:
    """Build view dir + render its dashboard. Returns path to index.html
    or None if no steps are available.
    """
    from .qc_dashboard import generate_dashboard
    view_root, locked, sources = build_view(scope, work_root)
    # Don't render if nothing landed
    if not any((view_root / "logs").iterdir()):
        return None
    result = generate_dashboard(
        view_root,
        locked_step_codes=locked,
        source_wf_per_step=sources,
        view_label=f"{scope} (stitched view)",
    )
    return view_root / "dashboard" / "index.html"


def view_dir(scope: str, work_root: Path) -> Path:
    """Path to the stitched view dir for a scope (does not build)."""
    return Path(work_root).resolve() / "done" / scope / "_view"
