"""
QC Dashboard generator for SpinalfMRIprep workflows.

Scans QC JSON files and generates HTML dashboard with reportlet galleries.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from spinalfmriprep.qc_dashboard_html import (
    REPORTLET_LABELS,
    REPORTLET_ORDER,
    _generate_index_html,
    _generate_reportlet_gallery_html,
    _generate_workfolder_dropdown_html,
    _get_reportlet_label,
    _relpath,
    _sort_reportlets,
)


def _extract_workfolder_name(out_dir: Path) -> Optional[str]:
    """
    Extract workfolder name from path, if present.

    Recognizes canonical patterns:
    - wf_smoke_XXX
    - wf_reg_XXX
    - wf_full_XXX

    Also supports legacy wf_XXX pattern (numeric) and any wf_* pattern for backward compatibility.
    """
    # Search all path components for wf_* pattern
    for part in out_dir.parts:
        if part.startswith("wf_") and len(part) > 3:
            # Prefer canonical patterns (wf_smoke_*, wf_reg_*, wf_full_*)
            if part.startswith(("wf_smoke_", "wf_reg_", "wf_full_")):
                return part
            # Fallback to legacy wf_* pattern (numeric) or any wf_* pattern
            elif re.match(r"wf_\d+$", part) or part.startswith("wf_"):
                return part
    return None


@dataclass
class DashboardResult:
    """Result of dashboard generation."""
    indexed_qc_files: int
    dashboard_dir: Path
    errors: list[str]


def generate_dashboard(out_dir: Path, chain_done_dirs: Optional[list[Path]] = None) -> DashboardResult:
    """
    Generate QC dashboard HTML from QC JSON files under out_dir/logs.

    Scans for qc.json files, collects reportlets, and generates:
    - out_dir/dashboard/index.html (step list with reportlet links)
    - out_dir/dashboard/reportlets/<STEP>/<REPORTLET>.html (galleries)

    Args:
        out_dir: Output directory containing logs/ with QC JSON files
        chain_done_dirs: Optional list of additional directories to scan for QC files.
                         Used in chain model to include S1/S2 outputs from done paths.

    Returns DashboardResult with counts and any errors.
    """
    out_dir = Path(out_dir)
    dashboard_dir = out_dir / "dashboard"
    dashboard_dir.mkdir(parents=True, exist_ok=True)

    # Extract workfolder name from path
    workfolder_name = _extract_workfolder_name(out_dir)

    # Collect all directories to scan: out_dir + chain_done_dirs
    dirs_to_scan = [out_dir]
    if chain_done_dirs:
        for chain_dir in chain_done_dirs:
            if chain_dir and Path(chain_dir).exists():
                dirs_to_scan.append(Path(chain_dir))

    # Scan for QC JSON files: support both structures
    # New structure: logs/<STEP>/<DATASET>/qc.json
    # Legacy structure: logs/<STEP>_qc.json
    # Also scan subdirectories: <DATASET_KEY>/logs/<STEP>_qc.json or <DATASET_KEY>/logs/<STEP>/<DATASET>/qc.json
    qc_files: list[tuple[Path, str, str, Path]] = []  # (qc_path, step_code, dataset_key, base_dir_for_paths)

    # Scan each directory (out_dir + chain_done_dirs)
    for scan_dir in dirs_to_scan:
        # First, scan top-level logs directory
        logs_dir = scan_dir / "logs"
        if logs_dir.exists():
            # New structure: logs/<STEP>/<DATASET>/qc.json
            for step_dir in logs_dir.iterdir():
                if not step_dir.is_dir():
                    continue
                # Skip evidence bundles (internal debugging, not for dashboard display)
                if step_dir.name.endswith("_evidence"):
                    continue
                for dataset_dir in step_dir.iterdir():
                    if not dataset_dir.is_dir():
                        continue
                    qc_path = dataset_dir / "qc.json"
                    if qc_path.exists():
                        step_code = step_dir.name
                        dataset_key = dataset_dir.name
                        qc_files.append((qc_path, step_code, dataset_key, scan_dir))

            # Legacy structure: logs/<STEP>_qc.json
            # Skip aggregate files if per-dataset QC files exist for this step
            for qc_file in logs_dir.glob("*_qc.json"):
                if qc_file.is_file():
                    # Extract step code from filename: S1_input_verify_qc.json -> S1_input_verify
                    step_code = qc_file.stem.replace("_qc", "")

                    # Check if per-dataset QC files exist for this step (preferred)
                    step_subdir = logs_dir / step_code
                    if step_subdir.exists() and step_subdir.is_dir():
                        # Per-dataset QC files exist; skip the aggregate file
                        # (they will be picked up by the new structure scan above)
                        continue

                    # Try to extract dataset_key from QC JSON content
                    try:
                        with open(qc_file, "r", encoding="utf-8") as f:
                            qc_data = json.load(f)
                        dataset_key = qc_data.get("dataset_key", "unknown")
                    except Exception:
                        dataset_key = "unknown"
                    qc_files.append((qc_file, step_code, dataset_key, scan_dir))

        # Also scan subdirectories (for datasets organized as scan_dir/{dataset_key}/logs/...)
        for item in scan_dir.iterdir():
            if not item.is_dir():
                continue
            # Skip common non-dataset directories
            if item.name in ("dashboard", "work", "logs", "derivatives"):
                continue

            # Check if this looks like a dataset subdirectory (contains logs/)
            sub_logs_dir = item / "logs"
            if not sub_logs_dir.exists():
                continue

            # Extract dataset_key from subdirectory name
            potential_dataset_key = item.name

            # Scan this subdirectory's logs for QC files
            # New structure: {dataset_key}/logs/<STEP>/<DATASET>/qc.json
            for step_dir in sub_logs_dir.iterdir():
                if not step_dir.is_dir():
                    continue
                if step_dir.name.endswith("_evidence"):
                    continue
                for dataset_dir in step_dir.iterdir():
                    if not dataset_dir.is_dir():
                        continue
                    qc_path = dataset_dir / "qc.json"
                    if qc_path.exists():
                        step_code = step_dir.name
                        dataset_key = dataset_dir.name
                        qc_files.append((qc_path, step_code, dataset_key, item))

            # Legacy structure: {dataset_key}/logs/<STEP>_qc.json
            for qc_file in sub_logs_dir.glob("*_qc.json"):
                if qc_file.is_file():
                    step_code = qc_file.stem.replace("_qc", "")
                    # Use subdirectory name as dataset_key, but also check QC JSON
                    try:
                        with open(qc_file, "r", encoding="utf-8") as f:
                            qc_data = json.load(f)
                        dataset_key = qc_data.get("dataset_key", potential_dataset_key)
                    except Exception:
                        dataset_key = potential_dataset_key
                    qc_files.append((qc_file, step_code, dataset_key, item))  # base_dir is the dataset subdirectory

    if not qc_files:
        return DashboardResult(
            indexed_qc_files=0,
            dashboard_dir=dashboard_dir,
            errors=[],
        )

    # Collect QC data: step -> dataset -> runs -> reportlets
    step_data: dict[str, dict[str, list[dict]]] = {}
    reportlet_index: dict[str, dict[str, list[dict]]] = {}  # step -> reportlet_key -> list of {dataset, subject, session, path}
    errors: list[str] = []

    seen_run_keys: dict[tuple[str, str], set[tuple[str, str, str]]] = {}  # (step, ds) -> set of (sub, ses, run_id)

    for qc_path, step_code, dataset_key, base_dir in qc_files:
        try:
            with open(qc_path, "r", encoding="utf-8") as f:
                qc = json.load(f)

            if step_code not in step_data:
                step_data[step_code] = {}
            if dataset_key not in step_data[step_code]:
                step_data[step_code][dataset_key] = []

            if (step_code, dataset_key) not in seen_run_keys:
                seen_run_keys[(step_code, dataset_key)] = set()

            raw_runs = qc.get("runs", [])
            unique_runs = []

            for run in raw_runs:
                subj = str(run.get("subject", "unknown"))
                sess = str(run.get("session", "None"))
                rid = str(run.get("run_id", "None"))
                run_key = (subj, sess, rid)

                if run_key in seen_run_keys[(step_code, dataset_key)]:
                    continue
                seen_run_keys[(step_code, dataset_key)].add(run_key)
                unique_runs.append(run)

            step_data[step_code][dataset_key].extend(unique_runs)

            # Index reportlets
            if step_code not in reportlet_index:
                reportlet_index[step_code] = {}

            for run in unique_runs:
                reportlets = run.get("reportlets", {})
                for reportlet_key, reportlet_path in reportlets.items():
                    if not reportlet_path:
                        continue
                    if reportlet_key not in reportlet_index[step_code]:
                        reportlet_index[step_code][reportlet_key] = []

                    # Resolve absolute path relative to base_dir (which may be a dataset subdirectory)
                    reportlet_abs = base_dir / reportlet_path
                    if not reportlet_abs.exists():
                        errors.append(f"Missing reportlet: {reportlet_abs}")
                        continue

                    # Store absolute path; we'll compute relative path later from the gallery file location
                    reportlet_abs_str = str(reportlet_abs)

                    reportlet_index[step_code][reportlet_key].append({
                        "dataset": dataset_key,
                        "subject": run.get("subject", "unknown"),
                        "session": run.get("session"),
                        "path_abs": reportlet_abs_str,
                        "path_rel": reportlet_path,  # Keep original relative path for display
                        # Prefer per-reportlet status (if present), fall back to run status.
                        "status": (
                            ((run.get("reportlets_detail") or {}).get(reportlet_key) or {}).get("status")
                            or run.get("status", "UNKNOWN")
                        ),
                    })
        except Exception as e:
            errors.append(f"Failed to process {qc_path}: {e}")

    # Generate index.html
    _generate_index_html(dashboard_dir, step_data, reportlet_index, workfolder_name)

    # Generate reportlet gallery pages
    for step_code, reportlets in reportlet_index.items():
        for reportlet_key, images in reportlets.items():
            _generate_reportlet_gallery_html(
                dashboard_dir, step_code, reportlet_key, images, workfolder_name
            )

    return DashboardResult(
        indexed_qc_files=len(qc_files),
        dashboard_dir=dashboard_dir,
        errors=errors,
    )


def generate_dashboard_safe(out_dir: Path, chain_done_dirs: Optional[list[Path]] = None) -> None:
    """
    Safely generate dashboard, catching and logging errors without failing the step.

    This should be called at the end of each step's run function.
    Dashboard generation failures are logged as warnings but do not affect step status.

    Args:
        out_dir: Output directory containing logs/ with QC JSON files
        chain_done_dirs: Optional list of additional directories to scan for QC files.
                         Used in chain model to include S1/S2 outputs from done paths.
    """
    try:
        result = generate_dashboard(out_dir, chain_done_dirs=chain_done_dirs)
        if result.errors:
            # Log warnings but don't fail
            import warnings
            for error in result.errors:
                warnings.warn(f"Dashboard generation warning: {error}", UserWarning)
    except Exception as e:
        # Log but don't fail the step
        import warnings
        warnings.warn(f"Dashboard generation failed (non-blocking): {e}", UserWarning)
