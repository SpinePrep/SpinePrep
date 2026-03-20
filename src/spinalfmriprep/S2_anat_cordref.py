"""
S2_anat_cordref: cord reference selection, standardization, cropping, and segmentation.
"""

from __future__ import annotations

import csv
import json
import os
import subprocess
from concurrent.futures import ProcessPoolExecutor, as_completed
from functools import partial
from shutil import copy2
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, cast

import nibabel as nib
import numpy as np
import yaml
from jsonschema import Draft7Validator
from PIL import Image, ImageDraw


@dataclass
class StepResult:
    status: str
    failure_message: Optional[str]
    runs_path: Optional[Path] = None
    qc_path: Optional[Path] = None


def run_S2_anat_cordref(
    dataset_key: Optional[str],
    datasets_local: Optional[Path],
    bids_root: Optional[Path],
    out: Optional[Path],
) -> StepResult:
    command_line = _format_command_line(dataset_key, datasets_local, bids_root, out)
    if out is None:
        return StepResult(status="FAIL", failure_message="--out is required for S2_anat_cordref")

    # Per-dataset inventory path (matches S1 output structure)
    ds_key = dataset_key or "ad_hoc"
    inventory_path = Path(out) / "work" / "S1_input_verify" / ds_key / "bids_inventory.json"
    if not inventory_path.exists():
        return StepResult(
            status="FAIL",
            failure_message=f"Missing required inventory: {inventory_path}",
            runs_path=Path(out) / "logs" / "S2_anat_cordref" / ds_key / "runs.jsonl",
            qc_path=Path(out) / "logs" / "S2_anat_cordref" / ds_key / "qc.json",
        )

    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))

    policy_path = Path("policy") / "S2_anat_cordref.yaml"
    try:
        policy = _load_policy(policy_path)
    except ValueError as err:
        return StepResult(status="FAIL", failure_message=str(err))

    bids_root_path = Path(inventory["bids_root"])
    if bids_root and bids_root_path.resolve() != bids_root.resolve():
        return StepResult(status="FAIL", failure_message="Inventory bids_root mismatch.")

    runs_path = Path(out) / "logs" / "S2_anat_cordref_runs.jsonl"
    qc_path = Path(out) / "logs" / "S2_anat_cordref_qc.json"
    runs_path.parent.mkdir(parents=True, exist_ok=True)

    candidates = _collect_anat_candidates(inventory)
    sessions = _collect_subject_sessions(inventory)

    # Always process subjects sequentially within a dataset (1 worker)
    # Parallelization happens at dataset level, not subject level
    max_workers = 1

    # Process subjects sequentially
    runs = []
    sorted_sessions = sorted(sessions)

    if len(sorted_sessions) == 1 or max_workers == 1:
        # Sequential processing for single subject or when workers=1
        for key in sorted_sessions:
            subject, session = key
            run = _process_session(
                subject=subject,
                session=session,
                candidates=candidates.get(key, []),
                bids_root=bids_root_path,
                out_root=Path(out),
                policy=policy,
            )
            run["command_line"] = command_line
            runs.append(run)
    else:
        # Parallel processing
        # Convert Path objects to strings for pickling
        # Also ensure candidates dict has string paths
        candidates_str = {}
        for key, cand_list in candidates.items():
            candidates_str[key] = []
            for cand in cand_list:
                cand_copy = cand.copy()
                if "path" in cand_copy and isinstance(cand_copy["path"], Path):
                    cand_copy["path"] = str(cand_copy["path"])
                candidates_str[key].append(cand_copy)

        # Create a partial function with fixed arguments (all Paths converted to strings)
        _process_session_partial = partial(
            _process_session_worker,
            candidates=candidates_str,
            bids_root=str(bids_root_path),
            out_root=str(Path(out)),
            policy=policy,
        )

        # Track order of submission
        future_to_key = {}
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            for key in sorted_sessions:
                subject, session = key
                future = executor.submit(
                    _process_session_partial,
                    subject=subject,
                    session=session,
                )
                future_to_key[future] = key

            # Collect results as they complete, but maintain order
            results_dict = {}
            for future in as_completed(future_to_key):
                key = future_to_key[future]
                try:
                    run = future.result()
                    run["command_line"] = command_line
                    results_dict[key] = run
                except Exception as e:  # noqa: BLE001
                    # If worker crashes, create a failed run record
                    subject, session = key
                    run_id = _format_run_id(subject, session)
                    results_dict[key] = {
                        "subject": subject,
                        "session": session,
                        "status": "FAIL",
                        "failure_message": f"Parallel processing error: {e}",
                        "run_id": run_id,
                        "command_line": command_line,
                    }

        # Reconstruct runs in original order
        runs = [results_dict[key] for key in sorted_sessions]

    runs = _render_reportlets_for_runs(
        runs=runs,
        out_root=Path(out),
        dataset_key=dataset_key or inventory.get("dataset_key") or "ad_hoc",
    )

    _write_runs_jsonl(runs_path, runs)

    qc = _summarise_runs(inventory, policy_path, runs)
    _write_json(qc_path, qc)

    status = qc.get("status", "FAIL")
    failure_message = qc.get("failure_message")

    metrics_path = Path(out) / "logs" / "metrics" / "summary.jsonl"
    _append_metrics(metrics_path, inventory.get("dataset_key"), runs)

    evidence_dir = Path(out) / "logs" / "S2_evidence" / (dataset_key or inventory.get("dataset_key") or "ad_hoc")
    _write_evidence(
        evidence_dir=evidence_dir,
        qc_path=qc_path,
        runs_path=runs_path,
        runs=runs,
        status=status,
        command_line=command_line,
        out_root=Path(out),
    )

    # Generate dashboard (non-blocking)
    from spinalfmriprep.qc_dashboard import generate_dashboard_safe
    generate_dashboard_safe(Path(out))

    return StepResult(status=status, failure_message=failure_message, runs_path=runs_path, qc_path=qc_path)


def check_S2_anat_cordref(
    dataset_key: Optional[str],
    datasets_local: Optional[Path],
    bids_root: Optional[Path],
    out: Optional[Path],
) -> StepResult:
    if out is None:
        return StepResult(status="FAIL", failure_message="--out is required for S2_anat_cordref")

    runs_path = Path(out) / "logs" / "S2_anat_cordref_runs.jsonl"
    qc_path = Path(out) / "logs" / "S2_anat_cordref_qc.json"

    required = (runs_path, qc_path)
    missing = [p for p in required if not p.exists() or p.stat().st_size == 0]
    if missing:
        return StepResult(
            status="FAIL",
            failure_message=f"Missing required artifact(s): {', '.join(str(p) for p in missing)}",
            runs_path=runs_path,
            qc_path=qc_path,
        )

    try:
        qc = json.loads(qc_path.read_text(encoding="utf-8"))
    except Exception as err:  # noqa: BLE001
        return StepResult(status="FAIL", failure_message=f"Failed to read QC JSON: {err}")

    if dataset_key and qc.get("dataset_key") != dataset_key:
        return StepResult(status="FAIL", failure_message="QC dataset_key mismatch.")

    if bids_root and qc.get("bids_root") != str(bids_root.resolve()):
        return StepResult(status="FAIL", failure_message="QC bids_root mismatch.")

    try:
        _validate_json(qc_path, Path("schemas/qc_S2_anat_cordref.schema.json"))
    except ValueError as err:
        return StepResult(status="FAIL", failure_message=str(err))

    try:
        runs = _read_runs_jsonl(runs_path)
    except ValueError as err:
        return StepResult(status="FAIL", failure_message=str(err))

    missing_outputs = []
    missing_reportlets = []
    for run in runs:
        if run.get("status") != "PASS":
            continue
        for key in ("cordref_path", "cordmask_path"):
            rel = run.get(key)
            if not rel:
                missing_outputs.append(f"{key} missing for {run.get('subject')}/{run.get('session')}")
                continue
            path = Path(out) / rel if not Path(rel).is_absolute() else Path(rel)
            if not path.exists() or path.stat().st_size == 0:
                missing_outputs.append(str(path))
        labels_info = run.get("labels") or {}
        labels_status = labels_info.get("status", "PASS")
        if labels_status == "PASS":
            rel = run.get("vertebral_labels_path")
            if not rel:
                missing_outputs.append(f"vertebral_labels_path missing for {run.get('subject')}/{run.get('session')}")
            else:
                path = Path(out) / rel if not Path(rel).is_absolute() else Path(rel)
                if not path.exists() or path.stat().st_size == 0:
                    missing_outputs.append(str(path))

        rootlets_info = run.get("rootlets", {})
        if rootlets_info.get("status") == "PASS":
            rel = run.get("rootlets_path")
            if not rel:
                missing_outputs.append(f"rootlets_path missing for {run.get('subject')}/{run.get('session')}")
            else:
                path = Path(out) / rel if not Path(rel).is_absolute() else Path(rel)
                if not path.exists() or path.stat().st_size == 0:
                    missing_outputs.append(str(path))

        xfm_info = run.get("xfm") or {}
        for key in ("warp_to_template", "warp_to_cordref"):
            rel = xfm_info.get(key)
            if not rel:
                missing_outputs.append(f"{key} missing for {run.get('subject')}/{run.get('session')}")
                continue
            path = Path(out) / rel if not Path(rel).is_absolute() else Path(rel)
            if not path.exists() or path.stat().st_size == 0:
                missing_outputs.append(str(path))

        reportlets = run.get("reportlets", {})
        required_reportlets = [
            "cordmask_montage",
            "totalspineseg_montage",
            "pam50_reg_overlay",
        ]
        for key in required_reportlets:
            rel = reportlets.get(key)
            if not rel:
                missing_reportlets.append(f"{key} missing for {run.get('subject')}/{run.get('session')}")
                continue
            path = Path(out) / rel if not Path(rel).is_absolute() else Path(rel)
            if not path.exists() or path.stat().st_size == 0:
                missing_reportlets.append(str(path))

        rootlets_info = run.get("rootlets", {})
        if rootlets_info.get("status") == "PASS":
            for key in ("rootlets_montage",):
                rel = reportlets.get(key)
                if not rel:
                    missing_reportlets.append(f"{key} missing for {run.get('subject')}/{run.get('session')}")
                    continue
                path = Path(out) / rel if not Path(rel).is_absolute() else Path(rel)
                if not path.exists() or path.stat().st_size == 0:
                    missing_reportlets.append(str(path))

    if missing_outputs:
        return StepResult(
            status="FAIL",
            failure_message=f"Missing required outputs: {', '.join(missing_outputs)}",
            runs_path=runs_path,
            qc_path=qc_path,
        )
    if missing_reportlets:
        return StepResult(
            status="FAIL",
            failure_message=f"Missing required reportlets: {', '.join(missing_reportlets)}",
            runs_path=runs_path,
            qc_path=qc_path,
        )

    return StepResult(status="PASS", failure_message=None, runs_path=runs_path, qc_path=qc_path)


def run_S2_anat_cordref_reportlets_only(
    dataset_key: Optional[str],
    datasets_local: Optional[Path],
    bids_root: Optional[Path],
    out: Optional[Path],
) -> StepResult:
    """Regenerate only QC reportlets from existing step outputs, skipping all processing."""
    if out is None:
        return StepResult(status="FAIL", failure_message="--out is required for S2_anat_cordref")

    # Per-dataset paths
    ds_key = dataset_key or "ad_hoc"
    runs_path = Path(out) / "logs" / "S2_anat_cordref" / ds_key / "runs.jsonl"
    qc_path = Path(out) / "logs" / "S2_anat_cordref" / ds_key / "qc.json"

    # Check that runs.jsonl exists and is non-empty
    if not runs_path.exists() or runs_path.stat().st_size == 0:
        return StepResult(
            status="FAIL",
            failure_message=f"Missing or empty runs.jsonl: {runs_path}. Run the full step first.",
            runs_path=runs_path,
            qc_path=qc_path,
        )

    # Load inventory to get dataset_key (per-dataset path)
    inventory_path = Path(out) / "work" / "S1_input_verify" / ds_key / "bids_inventory.json"
    if not inventory_path.exists():
        return StepResult(
            status="FAIL",
            failure_message=f"Missing required inventory: {inventory_path}",
            runs_path=runs_path,
            qc_path=qc_path,
        )

    try:
        inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    except Exception as err:  # noqa: BLE001
        return StepResult(
            status="FAIL",
            failure_message=f"Failed to read inventory: {err}",
            runs_path=runs_path,
            qc_path=qc_path,
        )

    # Load policy (needed for _summarise_runs)
    policy_path = Path("policy") / "S2_anat_cordref.yaml"
    try:
        policy = _load_policy(policy_path)
    except ValueError as err:
        return StepResult(status="FAIL", failure_message=str(err))

    # Read existing runs
    try:
        runs = _read_runs_jsonl(runs_path)
    except Exception as err:  # noqa: BLE001
        return StepResult(
            status="FAIL",
            failure_message=f"Failed to read runs.jsonl: {err}",
            runs_path=runs_path,
            qc_path=qc_path,
        )

    if not runs:
        return StepResult(
            status="FAIL",
            failure_message=f"runs.jsonl is empty: {runs_path}",
            runs_path=runs_path,
            qc_path=qc_path,
        )

    # Regenerate reportlets
    resolved_dataset_key = dataset_key or inventory.get("dataset_key") or "ad_hoc"
    runs = _render_reportlets_for_runs(
        runs=runs,
        out_root=Path(out),
        dataset_key=resolved_dataset_key,
    )

    # Update runs.jsonl with new reportlet paths
    _write_runs_jsonl(runs_path, runs)

    # Regenerate QC JSON
    qc = _summarise_runs(inventory, policy_path, runs)
    _write_json(qc_path, qc)

    # Determine overall status
    status = qc.get("status", "FAIL")
    failure_message = qc.get("failure_message")

    return StepResult(status=status, failure_message=failure_message, runs_path=runs_path, qc_path=qc_path)


def run_S2_anat_cordref_reportlets_only_batch(
    dataset_keys: list[str],
    out_base: Path,
) -> dict[str, StepResult]:
    """
    Regenerate only QC reportlets for multiple datasets, skipping all processing.
    
    This is the batch version of run_S2_anat_cordref_reportlets_only.
    Useful for updating visualizations without re-running expensive SCT processing.
    
    Reads from the aggregate runs.jsonl and filters runs by dataset_key.
    
    Args:
        dataset_keys: List of dataset keys to regenerate reportlets for
        out_base: Base output directory containing existing step outputs
        
    Returns:
        Dictionary mapping dataset_key to StepResult
    """
    results: dict[str, StepResult] = {}
    
    # Read the aggregate runs.jsonl
    aggregate_runs_path = out_base / "logs" / "S2_anat_cordref_runs.jsonl"
    if not aggregate_runs_path.exists():
        # Fall back to trying per-dataset runs.jsonl
        for ds_key in dataset_keys:
            result = run_S2_anat_cordref_reportlets_only(
                dataset_key=ds_key,
                datasets_local=None,
                bids_root=None,
                out=out_base,
            )
            results[ds_key] = result
        from spinalfmriprep.qc_dashboard import generate_dashboard_safe
        generate_dashboard_safe(out_base)
        return results
    
    # Read all runs from aggregate file
    try:
        all_runs = _read_runs_jsonl(aggregate_runs_path)
    except Exception as err:
        for ds_key in dataset_keys:
            results[ds_key] = StepResult(
                status="FAIL",
                failure_message=f"Failed to read aggregate runs.jsonl: {err}",
            )
        return results
    
    # Load policy
    policy_path = Path("policy") / "S2_anat_cordref.yaml"
    try:
        policy = _load_policy(policy_path)
    except ValueError as err:
        for ds_key in dataset_keys:
            results[ds_key] = StepResult(status="FAIL", failure_message=str(err))
        return results
    
    # Process each dataset
    for ds_key in dataset_keys:
        # Filter runs for this dataset
        dataset_runs = [r for r in all_runs if r.get("dataset_key") == ds_key]
        
        if not dataset_runs:
            results[ds_key] = StepResult(
                status="FAIL",
                failure_message=f"No runs found for dataset_key={ds_key} in {aggregate_runs_path}",
            )
            continue
        
        # Regenerate reportlets for this dataset's runs
        dataset_runs = _render_reportlets_for_runs(
            runs=dataset_runs,
            out_root=out_base,
            dataset_key=ds_key,
        )
        
        # Load inventory for QC summary
        inventory_path = out_base / "work" / "S1_input_verify" / ds_key / "bids_inventory.json"
        if inventory_path.exists():
            try:
                inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
            except Exception:
                inventory = {"dataset_key": ds_key, "bids_root": "unknown"}
        else:
            inventory = {"dataset_key": ds_key, "bids_root": "unknown"}
        
        # Regenerate per-dataset QC JSON
        qc_path = out_base / "logs" / "S2_anat_cordref" / ds_key / "qc.json"
        qc_path.parent.mkdir(parents=True, exist_ok=True)
        qc = _summarise_runs(inventory, policy_path, dataset_runs)
        _write_json(qc_path, qc)
        
        results[ds_key] = StepResult(
            status=qc.get("status", "PASS"),
            failure_message=qc.get("failure_message"),
            qc_path=qc_path,
        )
    
    # Update aggregate runs.jsonl with new reportlet paths
    # Merge updated runs back into all_runs
    updated_runs = []
    processed_keys = set(dataset_keys)
    for run in all_runs:
        if run.get("dataset_key") not in processed_keys:
            updated_runs.append(run)
    # Add the regenerated runs
    for ds_key in dataset_keys:
        dataset_runs = [r for r in all_runs if r.get("dataset_key") == ds_key]
        # Re-render and add back
        dataset_runs = _render_reportlets_for_runs(
            runs=dataset_runs,
            out_root=out_base,
            dataset_key=ds_key,
        )
        updated_runs.extend(dataset_runs)
    
    _write_runs_jsonl(aggregate_runs_path, updated_runs)
    
    # Regenerate dashboard
    from spinalfmriprep.qc_dashboard import generate_dashboard_safe
    generate_dashboard_safe(out_base)
    
    return results


def run_S2_anat_cordref_batch(
    dataset_keys: list[str],
    datasets_local: Optional[Path],
    out_base: Path,
    max_workers: int = 32,
    s1_base: Optional[Path] = None,
) -> dict[str, StepResult]:
    """
    Run S2_anat_cordref on multiple datasets, with parallelism at SESSION level.

    All (subject, session) pairs from all datasets are processed in parallel.
    Results are grouped back by dataset for QC and reportlet generation.

    Args:
        dataset_keys: List of dataset keys to process
        datasets_local: Path to datasets_local.yaml
        out_base: Base output directory (each dataset gets out_base/{dataset_key})
        max_workers: Number of sessions to process in parallel (default: 32)
        s1_base: Base path for S1 outputs (chain model). If None, uses out_base.
                 For chain model, pass work/done/{scope}/S1/ to read S1 outputs.

    Returns:
        Dictionary mapping dataset_key to StepResult
    """
    from concurrent.futures import ProcessPoolExecutor, as_completed

    # Chain model: read S1 outputs from s1_base if provided, else from out_base
    inventory_base = s1_base if s1_base else out_base

    # Collect all sessions from all datasets
    all_sessions = []  # List of session info dicts
    dataset_inventories = {}

    for dataset_key in dataset_keys:
        # Per-dataset inventory path (chain model: read from S1 done path)
        inventory_path = inventory_base / "work" / "S1_input_verify" / dataset_key / "bids_inventory.json"

        if not inventory_path.exists():
            continue  # Skip if inventory doesn't exist

        inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
        dataset_inventories[dataset_key] = inventory

        bids_root_path = Path(inventory["bids_root"])
        candidates = _collect_anat_candidates(inventory)
        sessions = _collect_subject_sessions(inventory)

        for subject, session in sessions:
            key = (subject, session)
            all_sessions.append({
                "dataset_key": dataset_key,
                "subject": subject,
                "session": session,
                "bids_root": str(bids_root_path),  # Convert to string for pickling
                "out_root": str(out_base),  # Shared output root for all datasets
                "candidates": candidates.get(key, []),
            })

    if not all_sessions:
        # No sessions found in any dataset
        return {
            key: StepResult(
                status="FAIL",
                failure_message="No sessions found in any dataset",
            )
            for key in dataset_keys
        }

    # Convert candidates paths to strings for pickling
    for sess in all_sessions:
        candidates_str = []
        for cand in sess["candidates"]:
            cand_copy = cand.copy()
            if "path" in cand_copy and isinstance(cand_copy["path"], Path):
                cand_copy["path"] = str(cand_copy["path"])
            candidates_str.append(cand_copy)
        sess["candidates"] = candidates_str

    # Process all sessions in parallel
    all_runs = {}  # dataset_key -> list of runs
    all_runs_flat = []  # Flat list of all runs with dataset_key for shared JSONL
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        future_to_session = {
            executor.submit(_process_single_session_batch_worker, sess): sess
            for sess in all_sessions
        }

        for future in as_completed(future_to_session):
            sess = future_to_session[future]
            try:
                dataset_key, subject, session, run = future.result()
                # Add dataset_key to run record for dashboard grouping
                run["dataset_key"] = dataset_key
                run["command_line"] = _format_command_line(
                    dataset_key=dataset_key,
                    datasets_local=datasets_local,
                    bids_root=None,
                    out=out_base,
                )
                if dataset_key not in all_runs:
                    all_runs[dataset_key] = []
                all_runs[dataset_key].append(run)
                all_runs_flat.append(run)
            except Exception as e:  # noqa: BLE001
                import traceback
                dataset_key = sess["dataset_key"]
                error_msg = f"Session processing error: {e}"
                error_trace = traceback.format_exc()
                run = {
                    "dataset_key": dataset_key,
                    "subject": sess["subject"],
                    "session": sess["session"],
                    "status": "FAIL",
                    "failure_message": error_msg,
                    "error_traceback": error_trace,
                    "run_id": _format_run_id(sess["subject"], sess["session"]),
                }
                if dataset_key not in all_runs:
                    all_runs[dataset_key] = []
                all_runs[dataset_key].append(run)
                all_runs_flat.append(run)

    # Render reportlets for all runs (shared output structure)
    # Update runs in all_runs dict with reportlet paths
    policy_path = Path("policy") / "S2_anat_cordref.yaml"
    
    for dataset_key in list(all_runs.keys()):
        runs = all_runs[dataset_key]
        runs = _render_reportlets_for_runs(
            runs=runs,
            out_root=out_base,
            dataset_key=dataset_key,
        )
        all_runs[dataset_key] = runs
    
    # Rebuild all_runs_flat with updated reportlet info
    all_runs_flat = []
    for dataset_key in dataset_keys:
        if dataset_key in all_runs:
            all_runs_flat.extend(all_runs[dataset_key])

    # Write shared runs.jsonl (all datasets together)
    runs_path = out_base / "logs" / "S2_anat_cordref_runs.jsonl"
    runs_path.parent.mkdir(parents=True, exist_ok=True)
    _write_runs_jsonl(runs_path, all_runs_flat)

    # Generate per-dataset QC files and results
    results = {}
    for dataset_key in dataset_keys:
        if dataset_key not in all_runs:
            results[dataset_key] = StepResult(
                status="FAIL",
                failure_message="No sessions processed for this dataset",
            )
            continue

        runs = all_runs[dataset_key]

        if dataset_key not in dataset_inventories:
            results[dataset_key] = StepResult(
                status="FAIL",
                failure_message="Inventory not found for this dataset",
            )
            continue

        inventory = dataset_inventories[dataset_key]

        # Write per-dataset QC file in new structure
        qc_dir = out_base / "logs" / "S2_anat_cordref" / dataset_key
        qc_dir.mkdir(parents=True, exist_ok=True)
        qc_path = qc_dir / "qc.json"

        qc = _summarise_runs(inventory, policy_path, runs)
        qc["dataset_key"] = dataset_key
        _write_json(qc_path, qc)

        # Append metrics
        metrics_path = out_base / "logs" / "metrics" / "summary.jsonl"
        _append_metrics(metrics_path, dataset_key, runs)

        status = qc.get("status", "FAIL")
        failure_message = qc.get("failure_message")

        results[dataset_key] = StepResult(
            status=status,
            failure_message=failure_message,
            runs_path=runs_path,
            qc_path=qc_path,
        )

    # Write combined QC summary
    combined_qc_path = out_base / "logs" / "S2_anat_cordref_qc.json"
    combined_qc = {
        "step": "S2_anat_cordref",
        "datasets": list(dataset_keys),
        "total_runs": len(all_runs_flat),
        "passed": sum(1 for r in all_runs_flat if r.get("status") == "PASS"),
        "failed": sum(1 for r in all_runs_flat if r.get("status") == "FAIL"),
        "runs": all_runs_flat,
    }
    _write_json(combined_qc_path, combined_qc)

    # Generate dashboard for batch (non-blocking)
    from spinalfmriprep.qc_dashboard import generate_dashboard_safe
    generate_dashboard_safe(out_base)

    return results


def _format_command_line(
    dataset_key: Optional[str],
    datasets_local: Optional[Path],
    bids_root: Optional[Path],
    out: Optional[Path],
) -> str:
    parts = ["poetry", "run", "spinalfmriprep", "run", "S2_anat_cordref"]
    if dataset_key:
        parts.extend(["--dataset-key", str(dataset_key)])
    if datasets_local:
        parts.extend(["--datasets-local", str(datasets_local)])
    if bids_root:
        parts.extend(["--bids-root", str(bids_root)])
    if out:
        parts.extend(["--out", str(out)])
    return " ".join(parts)


def _load_policy(path: Path) -> dict:
    if not path.exists():
        raise ValueError(f"Policy not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("S2_anat_cordref policy must be a mapping.")
    version = raw.get("version")
    if not isinstance(version, int):
        raise ValueError("S2_anat_cordref policy missing integer 'version'.")
    selection = raw.get("selection", {})
    preference = selection.get("preference", ["T2w", "T1w"])
    if not isinstance(preference, list) or not all(isinstance(p, str) for p in preference):
        raise ValueError("S2_anat_cordref policy selection.preference must be a list of strings.")
    standardize = raw.get("standardize", {})
    orientation = standardize.get("orientation", "RPI")
    
    # Discovery parameters (for discovery segmentation before crop)
    discover = raw.get("discover", {})
    discover_method = discover.get("method", "sct_deepseg_sc")
    if not isinstance(discover_method, str):
        raise ValueError("S2_anat_cordref policy discover.method must be a string.")
    discover_task = discover.get("task")  # Optional, used when method="deepseg"
    if discover_task is not None and not isinstance(discover_task, str):
        raise ValueError("S2_anat_cordref policy discover.task must be a string or null.")
    discover_contrast_map = discover.get("contrast_map", {"T2w": "t2", "T1w": "t1"})
    if not isinstance(discover_contrast_map, dict):
        raise ValueError("S2_anat_cordref policy discover.contrast_map must be a mapping.")
    discover_min_z_slices = discover.get("min_z_slices", 20)
    if not isinstance(discover_min_z_slices, int) or discover_min_z_slices < 1:
        raise ValueError("S2_anat_cordref policy discover.min_z_slices must be a positive integer.")
    
    # Crop parameters (for mask-based cropping)
    crop = raw.get("crop", {})
    # Backward compatibility: keep size_vox and z_full but deprecated
    size_vox = crop.get("size_vox", [96, 96])
    if (
        not isinstance(size_vox, list)
        or len(size_vox) != 2
        or not all(isinstance(v, int) and v > 0 for v in size_vox)
    ):
        raise ValueError("S2_anat_cordref policy crop.size_vox must be [x, y] positive ints.")
    mask_diameter_mm = crop.get("mask_diameter_mm", 30)
    if not isinstance(mask_diameter_mm, (int, float)) or mask_diameter_mm <= 0:
        raise ValueError("S2_anat_cordref policy crop.mask_diameter_mm must be a positive number.")
    dilate_xyz = crop.get("dilate_xyz", [0, 0, 0])
    if (
        not isinstance(dilate_xyz, list)
        or len(dilate_xyz) != 3
        or not all(isinstance(v, int) for v in dilate_xyz)
    ):
        raise ValueError("S2_anat_cordref policy crop.dilate_xyz must be [x, y, z] integers.")
    crop_min_z_slices = crop.get("min_z_slices", 20)
    if not isinstance(crop_min_z_slices, int) or crop_min_z_slices < 1:
        raise ValueError("S2_anat_cordref policy crop.min_z_slices must be a positive integer.")
    
    segmentation = raw.get("segmentation", {})
    contrast_map = segmentation.get("contrast_map", {"T2w": "t2", "T1w": "t1"})
    if not isinstance(contrast_map, dict):
        raise ValueError("S2_anat_cordref policy segmentation.contrast_map must be a mapping.")
    # Cord segmentation method: contrast_agnostic (default) or totalspineseg
    cord_method = segmentation.get("cord_method", "contrast_agnostic")
    if cord_method not in ("contrast_agnostic", "totalspineseg"):
        raise ValueError("S2_anat_cordref policy segmentation.cord_method must be 'contrast_agnostic' or 'totalspineseg'.")
    labeling = raw.get("labeling", {})
    # Labeling method: totalspineseg (default) or sct_label_vertebrae
    labeling_method = labeling.get("method", "totalspineseg")
    if labeling_method not in ("totalspineseg", "sct_label_vertebrae"):
        raise ValueError("S2_anat_cordref policy labeling.method must be 'totalspineseg' or 'sct_label_vertebrae'.")
    clean_labels = labeling.get("clean_labels", 1)
    if not isinstance(clean_labels, int):
        raise ValueError("S2_anat_cordref policy labeling.clean_labels must be an int.")
    initcenter = labeling.get("initcenter")
    if initcenter is not None and not isinstance(initcenter, int):
        raise ValueError("S2_anat_cordref policy labeling.initcenter must be an int or null.")
    # TotalSpineSeg QC thresholds
    qc_thresholds = labeling.get("qc_thresholds", {})
    tss_min_levels = qc_thresholds.get("min_vertebral_levels", 5)
    tss_min_coverage = qc_thresholds.get("min_coverage_ratio", 0.8)
    tss_max_gap = qc_thresholds.get("max_inter_level_gap_mm", 15)
    tss_min_confidence = qc_thresholds.get("min_confidence", 0.7)
    rootlets = raw.get("rootlets", {})
    rootlets_enabled = bool(rootlets.get("enabled", False))
    eligible_modalities = rootlets.get("eligible_modalities", ["T2w"])
    if not isinstance(eligible_modalities, list) or not all(
        isinstance(mod, str) for mod in eligible_modalities
    ):
        raise ValueError("S2_anat_cordref policy rootlets.eligible_modalities must be a list of strings.")
    registration = raw.get("registration", {})
    prefer_rootlets = bool(registration.get("prefer_rootlets", True))
    return {
        "version": version,
        "preference": preference,
        "orientation": orientation,
        # Discovery parameters
        "discover_method": discover_method,
        "discover_task": discover_task,
        "discover_contrast_map": discover_contrast_map,
        "discover_min_z_slices": discover_min_z_slices,
        # Crop parameters
        "size_vox": size_vox,  # Deprecated, kept for backward compat
        "z_full": bool(crop.get("z_full", True)),  # Deprecated, kept for backward compat
        "mask_diameter_mm": mask_diameter_mm,
        "dilate_xyz": dilate_xyz,
        "crop_min_z_slices": crop_min_z_slices,
        # Segmentation parameters
        "contrast_map": contrast_map,
        "cord_method": cord_method,
        # Labeling parameters
        "labeling_method": labeling_method,
        "clean_labels": clean_labels,
        "initcenter": initcenter,
        # TotalSpineSeg QC thresholds
        "tss_min_levels": tss_min_levels,
        "tss_min_coverage": tss_min_coverage,
        "tss_max_gap": tss_max_gap,
        "tss_min_confidence": tss_min_confidence,
        # Rootlets parameters
        "rootlets_enabled": rootlets_enabled,
        "rootlets_modalities": eligible_modalities,
        # Registration parameters
        "prefer_rootlets": prefer_rootlets,
    }


def _collect_anat_candidates(inventory: dict) -> dict[tuple[str, Optional[str]], list[dict]]:
    candidates: dict[tuple[str, Optional[str]], list[dict]] = {}
    for entry in inventory.get("files", []):
        path = entry.get("path")
        if not path or not isinstance(path, str):
            continue
        path_lower = path.lower()
        if "/anat/" not in path_lower:
            continue
        if not (path_lower.endswith(".nii") or path_lower.endswith(".nii.gz")):
            continue
        if "t1w" not in path_lower and "t2w" not in path_lower:
            continue
        modality = "T2w" if "t2w" in path_lower else "T1w"
        subject = entry.get("subject")
        session = entry.get("session")
        if not subject:
            continue
        key = (subject, session)
        candidates.setdefault(key, []).append(
            {
                "path": path,
                "modality": modality,
            }
        )
    return candidates


def _collect_subject_sessions(inventory: dict) -> set[tuple[str, Optional[str]]]:
    sessions: set[tuple[str, Optional[str]]] = set()
    for entry in inventory.get("files", []):
        subject = entry.get("subject")
        if not subject:
            continue
        sessions.add((subject, entry.get("session")))
    return sessions


def _process_session_worker(
    subject: str,
    session: Optional[str],
    candidates: dict,
    bids_root: str,
    out_root: str,
    policy: dict,
) -> dict:
    """Worker function for parallel processing - unpacks candidates dict and converts strings to Paths."""
    key = (subject, session)
    candidate_list = candidates.get(key, [])
    # Convert string paths back to Path objects in candidates
    candidate_list_paths = []
    for cand in candidate_list:
        cand_copy = cand.copy()
        if "path" in cand_copy and isinstance(cand_copy["path"], str):
            cand_copy["path"] = Path(cand_copy["path"])
        candidate_list_paths.append(cand_copy)

    return _process_session(
        subject=subject,
        session=session,
        candidates=candidate_list_paths,
        bids_root=Path(bids_root),
        out_root=Path(out_root),
        policy=policy,
    )


def _process_single_session_batch_worker(session_info: dict) -> tuple[str, str, Optional[str], dict]:
    """
    Worker function for batch processing - processes one (subject, session) from any dataset.

    This is a module-level function (not nested) so it can be pickled for multiprocessing.
    Derivatives are stored with dataset_key prefix: derivatives/spinalfmriprep/{dataset_key}/sub-XX/
    """
    # Convert string paths back to Path objects
    candidates_paths = []
    for cand in session_info["candidates"]:
        cand_copy = cand.copy()
        if "path" in cand_copy and isinstance(cand_copy["path"], str):
            cand_copy["path"] = Path(cand_copy["path"])
        candidates_paths.append(cand_copy)

    # Load policy (needs to be done in worker since policy dict may not be picklable)
    policy_path = Path("policy") / "S2_anat_cordref.yaml"
    policy = _load_policy(policy_path)

    dataset_key = session_info["dataset_key"]

    run = _process_session(
        subject=session_info["subject"],
        session=session_info["session"],
        candidates=candidates_paths,
        bids_root=Path(session_info["bids_root"]),
        out_root=Path(session_info["out_root"]),
        policy=policy,
        dataset_key=dataset_key,  # Pass dataset_key for derivatives prefix
    )

    return (
        dataset_key,
        session_info["subject"],
        session_info["session"],
        run,
    )


def _process_session(
    subject: str,
    session: Optional[str],
    candidates: list[dict],
    bids_root: Path,
    out_root: Path,
    policy: dict,
    dataset_key: Optional[str] = None,
) -> dict:
    selection = _select_cordref(candidates, policy["preference"])
    run_id = _format_run_id(subject, session)
    if selection is None:
        return {
            "subject": subject,
            "session": session,
            "status": "FAIL",
            "failure_message": "No eligible T1w/T2w anatomy found for cordref selection.",
            "run_id": run_id,
        }

    source_rel = selection["path"]
    source_path = bids_root / source_rel
    if not source_path.exists():
        return {
            "subject": subject,
            "session": session,
            "status": "FAIL",
            "failure_message": f"Selected anatomy not found: {source_path}",
            "run_id": run_id,
        }

    work_dir = out_root / "work" / "S2_anat_cordref" / run_id
    work_dir.mkdir(parents=True, exist_ok=True)

    standard_path = work_dir / "cordref_std.nii.gz"
    ok, message = _standardize_orientation(source_path, standard_path, policy["orientation"])
    if not ok:
        return _fail_run(subject, session, run_id, f"Header standardization failed: {message}")

    # Discovery segmentation: find cord location before cropping (SCT best practice)
    discovery_seg_path = work_dir / "cordmask_discovery.nii.gz"
    discover_contrast = policy["discover_contrast_map"].get(selection["modality"], "t2")
    ok, message = _run_discovery_segmentation(
        standard_path=standard_path,
        discovery_seg_path=discovery_seg_path,
        contrast=discover_contrast,
        min_z_slices=policy["discover_min_z_slices"],
        method=policy["discover_method"],
        task=policy.get("discover_task"),
    )
    if not ok:
        return _fail_run(subject, session, run_id, f"Discovery segmentation failed: {message}")

    # Crop based on discovered cord using mask (SCT best practice)
    cropped_path = work_dir / "cordref_crop.nii.gz"
    crop_mask_path = work_dir / "crop_mask.nii.gz"
    ok, message = _crop_based_on_mask(
        standard_path=standard_path,
        discovery_seg_path=discovery_seg_path,
        cropped_path=cropped_path,
        crop_mask_path=crop_mask_path,
        mask_diameter_mm=policy["mask_diameter_mm"],
        dilate_xyz=policy["dilate_xyz"],
        min_z_slices=policy["crop_min_z_slices"],
    )
    if not ok:
        return _fail_run(subject, session, run_id, f"Cropping failed: {message}")

    derivatives_dir = _derivatives_anat_dir(out_root, subject, session, dataset_key)
    derivatives_dir.mkdir(parents=True, exist_ok=True)

    cordref_name = _format_derivative_name(subject, session, "desc-cordref", selection["modality"])
    cordref_path = derivatives_dir / cordref_name
    _copy_nifti(cropped_path, cordref_path)

    # Cord segmentation based on policy cord_method
    seg_path = derivatives_dir / _format_derivative_name(
        subject, session, "desc-cord_dseg", selection["modality"]
    )
    contrast = policy["contrast_map"].get(selection["modality"], "t2")
    cord_method = policy.get("cord_method", "contrast_agnostic")
    
    if cord_method == "contrast_agnostic":
        # Use contrast-agnostic model (optimized for CSA consistency)
        # Task name is "spinalcord" in SCT 7.x
        ok, message = _run_command(
            [
                "sct_deepseg",
                "spinalcord",
                "-i",
                str(cordref_path),
                "-o",
                str(seg_path),
            ]
        )
    else:
        # Use legacy sct_deepseg_sc with contrast (for backward compat or if TSS cord preferred)
        ok, message = _run_command(
            [
                "sct_deepseg_sc",
                "-i",
                str(cordref_path),
                "-c",
                str(contrast),
                "-o",
                str(seg_path),
            ]
        )
    if not ok:
        return _fail_run(subject, session, run_id, f"Cord segmentation failed: {message}")

    try:
        metrics = _compute_segmentation_metrics(seg_path)
    except ValueError as err:
        return _fail_run(subject, session, run_id, f"Metric computation failed: {err}")

    # Run TotalSpineSeg for vertebrae, discs, and canal segmentation
    tss_info = _run_totalspineseg(
        cordref_path=cordref_path,
        work_dir=work_dir,
    )
    if tss_info["status"] == "FAIL":
        return _fail_run(subject, session, run_id, tss_info["failure_message"])

    # Save TSS outputs to derivatives
    vertebral_labels_path = None
    disc_labels_path = None
    canal_path = None
    tss_vertebrae_path = None
    tss_discs_path = None
    tss_output_path = None
    
    if tss_info["status"] == "PASS":
        # SCT-compatible vertebral labels (for registration)
        vertebral_labels_path = derivatives_dir / _format_derivative_name(
            subject, session, "desc-vertebral_labels", selection["modality"]
        )
        _copy_file(Path(tss_info["vertebral_labels_path"]), vertebral_labels_path)
        
        # SCT-compatible disc labels (for registration)
        disc_labels_path = derivatives_dir / _format_derivative_name(
            subject, session, "desc-disc_labels", selection["modality"]
        )
        _copy_file(Path(tss_info["disc_labels_path"]), disc_labels_path)
        
        # Canal segmentation (new from TSS)
        canal_path = derivatives_dir / _format_derivative_name(
            subject, session, "desc-canal_dseg", selection["modality"]
        )
        _copy_file(Path(tss_info["canal_path"]), canal_path)
        
        # Full TSS output with original labels (for visualization)
        tss_output_path = derivatives_dir / _format_derivative_name(
            subject, session, "desc-totalspineseg_dseg", selection["modality"]
        )
        _copy_file(Path(tss_info["tss_output_path"]), tss_output_path)
        
        # TSS vertebrae with original labels (for visualization)
        tss_vertebrae_path = derivatives_dir / _format_derivative_name(
            subject, session, "desc-tss_vertebrae_dseg", selection["modality"]
        )
        _copy_file(Path(tss_info["vertebrae_path"]), tss_vertebrae_path)
        
        # TSS discs with original labels (for visualization)
        tss_discs_path = derivatives_dir / _format_derivative_name(
            subject, session, "desc-tss_discs_dseg", selection["modality"]
        )
        _copy_file(Path(tss_info["discs_path"]), tss_discs_path)
    
    # Create label_info dict for backward compatibility
    label_info = {
        "status": tss_info["status"],
        "failure_message": tss_info.get("failure_message"),
        "vertebral_labels_path": str(vertebral_labels_path) if vertebral_labels_path else None,
        "disc_labels_path": str(disc_labels_path) if disc_labels_path else None,
        "metrics": tss_info.get("metrics", {}),
    }

    rootlets_info = _run_rootlets_segmentation(
        cordref_path=cordref_path,
        work_dir=work_dir,
        enabled=policy["rootlets_enabled"],
        eligible=selection["modality"] in policy["rootlets_modalities"],
    )
    rootlets_path = None
    if rootlets_info.get("status") == "PASS" and rootlets_info.get("rootlets_path"):
        rootlets_path = derivatives_dir / _format_derivative_name(
            subject, session, "desc-rootlets_dseg", selection["modality"]
        )
        _copy_file(Path(rootlets_info["rootlets_path"]), rootlets_path)

    # Registration policy:
    # - Rootlet registration is the default (when rootlets are available).
    # - Disc registration is always attempted, recorded for reference, but is non-gating.
    # - If rootlets are missing/unavailable, fall back to disc registration for outputs.
    reg_rootlet: Optional[dict] = None

    # 1) Rootlet registration first (default when available)
    if rootlets_path is not None and policy["rootlets_enabled"]:
        reg_rootlet = _run_register_to_template(
            cordref_path=cordref_path,
            seg_path=seg_path,
            disc_labels_path=disc_labels_path,
            rootlets_path=rootlets_path,
            contrast=contrast,
            work_dir=work_dir / "reg_rootlet",
        )

    # 2) Disc registration always attempted (reference-only; never gates PASS if rootlet succeeded)
    reg_disc: dict = _run_register_to_template(
        cordref_path=cordref_path,
        seg_path=seg_path,
        disc_labels_path=disc_labels_path,
        rootlets_path=None,
        contrast=contrast,
        work_dir=work_dir / "reg_disc",
    )

    # 3) Choose warp for downstream outputs:
    # - Use rootlet warp if it succeeded (default).
    # - Else fall back to disc warp if it succeeded.
    # - Fail only if neither succeeded.
    selected_variant: str
    selected_reg: dict
    if reg_rootlet and reg_rootlet.get("status") == "PASS":
        selected_variant = "rootlet"
        selected_reg = reg_rootlet
    elif reg_disc and reg_disc.get("status") == "PASS":
        selected_variant = "disc"
        selected_reg = reg_disc
    else:
        if reg_rootlet and reg_rootlet.get("status") == "FAIL":
            msg = reg_rootlet.get("failure_message") or "rootlet registration failed."
            return _fail_run(subject, session, run_id, str(msg))
        return _fail_run(
            subject,
            session,
            run_id,
            str(reg_disc.get("failure_message") or "Registration failed."),
        )

    xfm_dir = _derivatives_xfm_dir(out_root, subject, session)
    xfm_dir.mkdir(parents=True, exist_ok=True)
    warp_to_template = xfm_dir / _format_xfm_name(subject, session, "from-cordref_to-PAM50_warp")
    warp_to_cordref = xfm_dir / _format_xfm_name(subject, session, "from-PAM50_to-cordref_warp")
    _copy_file(Path(selected_reg["warp_anat2template"]), warp_to_template)
    _copy_file(Path(selected_reg["warp_template2anat"]), warp_to_cordref)

    sct_version = _get_sct_version()

    return {
        "subject": subject,
        "session": session,
        "status": "PASS",
        "failure_message": None,
        "run_id": run_id,
        "source_path": source_rel,
        "cordref_modality": selection["modality"],
        "cordref_path": _relpath(cordref_path, out_root),
        "cordmask_path": _relpath(seg_path, out_root),
        "vertebral_labels_path": _relpath(vertebral_labels_path, out_root),
        "disc_labels_path": _relpath(disc_labels_path, out_root),
        "canal_path": _relpath(canal_path, out_root) if canal_path else None,
        "tss_output_path": _relpath(tss_output_path, out_root) if tss_output_path else None,
        "tss_vertebrae_path": _relpath(tss_vertebrae_path, out_root) if tss_vertebrae_path else None,
        "tss_discs_path": _relpath(tss_discs_path, out_root) if tss_discs_path else None,
        "rootlets_path": _relpath(rootlets_path, out_root) if rootlets_path else None,
        "metrics": metrics,
        "labels": label_info,
        "tss": tss_info,
        "rootlets": rootlets_info,
        "registration": {
            "selected": selected_variant,
            "disc": reg_disc,
            "rootlet": reg_rootlet,
        },
        "xfm": {
            "warp_to_template": _relpath(warp_to_template, out_root),
            "warp_to_cordref": _relpath(warp_to_cordref, out_root),
        },
        "provenance": {"sct_version": sct_version},
    }


def _select_cordref(candidates: list[dict], preference: list[str]) -> Optional[dict]:
    if not candidates:
        return None
    by_modality: dict[str, list[dict]] = {}
    for cand in candidates:
        by_modality.setdefault(cand["modality"], []).append(cand)
    for modality in preference:
        if modality in by_modality:
            return sorted(by_modality[modality], key=lambda c: c["path"])[0]
    return sorted(candidates, key=lambda c: c["path"])[0]


def _standardize_orientation(source: Path, dest: Path, orientation: str) -> tuple[bool, str]:
    return _run_command(["sct_image", "-i", str(source), "-setorient", orientation, "-o", str(dest)])


def _run_discovery_segmentation(
    standard_path: Path,
    discovery_seg_path: Path,
    contrast: str,
    min_z_slices: int,
    method: str,
    task: Optional[str] = None,
) -> tuple[bool, str]:
    """
    Run discovery segmentation on standardized image to find cord location.
    
    Args:
        standard_path: Path to standardized input image
        discovery_seg_path: Path to output discovery segmentation
        contrast: Contrast string (e.g., "t2", "t1") - used for sct_deepseg_sc
        min_z_slices: Minimum number of z-slices required in segmentation
        method: Discovery method ("sct_deepseg_sc" or "deepseg")
        task: Task name for deepseg method (e.g., "spinalcord") - required when method="deepseg"
        
    Returns:
        (success, error_message) tuple
    """
    if method == "deepseg":
        # Use sct_deepseg with task parameter (contrast-agnostic)
        if not task:
            return False, "discover.task is required when discover.method='deepseg'"
        cmd = [
            "sct_deepseg",
            str(task),
            "-i",
            str(standard_path),
            "-o",
            str(discovery_seg_path),
        ]
    elif method == "sct_deepseg_sc":
        # Use sct_deepseg_sc with contrast parameter
        cmd = [
            "sct_deepseg_sc",
            "-i",
            str(standard_path),
            "-c",
            str(contrast),
            "-o",
            str(discovery_seg_path),
        ]
    else:
        return False, f"Unknown discovery method: {method}"
    
    ok, message = _run_command(cmd)
    if not ok:
        return False, f"Discovery segmentation failed: {message}"
    
    # Validate min_z_slices requirement
    if not discovery_seg_path.exists():
        return False, "Discovery segmentation output not found"
    
    try:
        img = cast(Any, nib.load(discovery_seg_path))
        data = img.get_fdata()
        if data.ndim > 3:
            data = data[..., 0]
        mask = data > 0
        slice_counts = mask.sum(axis=(0, 1))
        slice_present = slice_counts > 0
        num_slices = int(slice_present.sum())
        
        if num_slices < min_z_slices:
            return False, (
                f"Discovery segmentation has {num_slices} slices, "
                f"but minimum {min_z_slices} slices required"
            )
    except Exception as e:
        return False, f"Failed to validate discovery segmentation: {e}"
    
    return True, ""


def _crop_centered(source: Path, dest: Path, size_vox: list[int], z_full: bool) -> None:
    img = cast(Any, nib.load(source))
    data = img.get_fdata()
    if data.ndim > 3:
        data = data[..., 0]
    shape = data.shape
    if len(shape) != 3:
        raise ValueError(f"Expected 3D image, got shape {shape}")

    size_x, size_y = size_vox
    center = (shape[0] // 2, shape[1] // 2, shape[2] // 2)
    x0 = max(0, center[0] - size_x // 2)
    y0 = max(0, center[1] - size_y // 2)
    x1 = min(shape[0], x0 + size_x)
    y1 = min(shape[1], y0 + size_y)
    x0 = max(0, x1 - size_x)
    y0 = max(0, y1 - size_y)

    if z_full:
        z0, z1 = 0, shape[2]
    else:
        z0 = 0
        z1 = shape[2]

    cropped = data[x0:x1, y0:y1, z0:z1]
    affine = img.affine.copy()
    shift = np.array([x0, y0, z0], dtype=float)
    affine[:3, 3] = affine[:3, 3] + affine[:3, :3] @ shift
    new_img = nib.Nifti1Image(cropped.astype(img.get_data_dtype()), affine, img.header)
    nib.save(new_img, dest)


def _crop_based_on_mask(
    standard_path: Path,
    discovery_seg_path: Path,
    cropped_path: Path,
    crop_mask_path: Path,
    mask_diameter_mm: float,
    dilate_xyz: list[int],
    min_z_slices: int,
) -> tuple[bool, str]:
    """
    Crop standardized image based on discovered cord segmentation using SCT tools.
    
    This follows SCT best practice:
    1. Create a cylindrical mask centered on the cord centerline
    2. Crop the image using the mask
    
    Args:
        standard_path: Path to standardized input image
        discovery_seg_path: Path to discovery segmentation (used for centerline)
        cropped_path: Path to output cropped image
        crop_mask_path: Path to output crop mask (work dir, for QC)
        mask_diameter_mm: Diameter of the cylindrical mask in mm
        dilate_xyz: Dilation margins in voxels [x, y, z]
        min_z_slices: Minimum number of z-slices required in cropped image
        
    Returns:
        (success, error_message) tuple
    """
    # Step 1: Create crop mask using sct_create_mask with centerline method
    ok, message = _run_command(
        [
            "sct_create_mask",
            "-i",
            str(standard_path),
            "-p",
            f"centerline,{discovery_seg_path}",
            "-size",
            f"{mask_diameter_mm}mm",
            "-f",
            "cylinder",
            "-o",
            str(crop_mask_path),
        ]
    )
    if not ok:
        return False, f"Crop mask creation failed: {message}"
    
    if not crop_mask_path.exists():
        return False, "Crop mask output not found"
    
    # Step 2: Crop image using sct_crop_image with the mask
    dilate_str = f"{dilate_xyz[0]}x{dilate_xyz[1]}x{dilate_xyz[2]}"
    ok, message = _run_command(
        [
            "sct_crop_image",
            "-i",
            str(standard_path),
            "-m",
            str(crop_mask_path),
            "-dilate",
            dilate_str,
            "-o",
            str(cropped_path),
        ]
    )
    if not ok:
        return False, f"Image cropping failed: {message}"
    
    if not cropped_path.exists():
        return False, "Cropped image output not found"
    
    # Step 3: Validate min_z_slices requirement
    try:
        img = cast(Any, nib.load(cropped_path))
        data = img.get_fdata()
        if data.ndim > 3:
            data = data[..., 0]
        num_z_slices = data.shape[2]
        
        if num_z_slices < min_z_slices:
            return False, (
                f"Cropped image has {num_z_slices} z-slices, "
                f"but minimum {min_z_slices} slices required"
            )
    except Exception as e:
        return False, f"Failed to validate cropped image: {e}"
    
    return True, ""


def _compute_segmentation_metrics(seg_path: Path) -> dict:
    img = cast(Any, nib.load(seg_path))
    data = img.get_fdata()
    if data.ndim > 3:
        data = data[..., 0]
    mask = data > 0
    voxels = int(mask.sum())
    zooms = img.header.get_zooms()[:3]
    voxel_volume = float(zooms[0] * zooms[1] * zooms[2])
    volume = float(voxels * voxel_volume)
    slice_counts = mask.sum(axis=(0, 1))
    slice_present = slice_counts > 0
    slice_area = slice_counts * (zooms[0] * zooms[1])
    length_mm = float(slice_present.sum() * zooms[2])
    if slice_present.any():
        stats = {
            "csa_mean_mm2": float(slice_area[slice_present].mean()),
            "csa_min_mm2": float(slice_area[slice_present].min()),
            "csa_max_mm2": float(slice_area[slice_present].max()),
        }
    else:
        stats = {"csa_mean_mm2": 0.0, "csa_min_mm2": 0.0, "csa_max_mm2": 0.0}
    return {
        "voxels": voxels,
        "voxel_volume_mm3": voxel_volume,
        "cord_volume_mm3": volume,
        "cord_length_mm": length_mm,
        **stats,
    }


def _run_vertebral_labeling(
    cordref_path: Path,
    seg_path: Path,
    contrast: str,
    work_dir: Path,
    clean_labels: int,
    initcenter: Optional[int],
) -> dict:
    label_dir = work_dir / "labels"
    label_dir.mkdir(parents=True, exist_ok=True)
    attempts = []
    first_ok, message = _run_command(
        _label_cmd(
            cordref_path=cordref_path,
            seg_path=seg_path,
            contrast=contrast,
            clean_labels=clean_labels,
            out_dir=label_dir,
            initcenter=None,
        )
    )
    attempts.append({"method": "auto", "ok": first_ok, "message": message})

    vertebral_labels = _find_first(label_dir, "*_labeled.nii.gz")
    disc_labels = _find_first(label_dir, "*_labeled_discs.nii.gz")

    if (not first_ok or vertebral_labels is None or disc_labels is None) and initcenter is not None:
        retry_dir = work_dir / "labels_initcenter"
        retry_dir.mkdir(parents=True, exist_ok=True)
        retry_ok, retry_message = _run_command(
            _label_cmd(
                cordref_path=cordref_path,
                seg_path=seg_path,
                contrast=contrast,
                clean_labels=clean_labels,
                out_dir=retry_dir,
                initcenter=initcenter,
            )
        )
        attempts.append(
            {"method": "initcenter", "ok": retry_ok, "message": retry_message, "initcenter": initcenter}
        )
        if retry_ok:
            candidate_labels = _find_first(retry_dir, "*_labeled.nii.gz")
            candidate_discs = _find_first(retry_dir, "*_labeled_discs.nii.gz")
            if candidate_labels is not None and candidate_discs is not None:
                vertebral_labels = candidate_labels
                disc_labels = candidate_discs

    if vertebral_labels is None or disc_labels is None:
        if any(_is_command_not_found(attempt["message"]) for attempt in attempts):
            return {
                "status": "FAIL",
                "failure_message": "sct_label_vertebrae command not found.",
                "attempts": attempts,
            }
        return {
            "status": "NOT_FEASIBLE",
            "failure_message": "Vertebral labeling outputs not found.",
            "attempts": attempts,
        }

    metrics = _compute_label_metrics(vertebral_labels)
    disc_metrics = _compute_label_metrics(disc_labels)
    metrics["disc_label_count"] = disc_metrics["label_count"]

    return {
        "status": "PASS",
        "failure_message": None,
        "vertebral_labels_path": str(vertebral_labels),
        "disc_labels_path": str(disc_labels),
        "metrics": metrics,
        "attempts": attempts,
    }


# TotalSpineSeg label mapping (from https://github.com/neuropoly/totalspineseg)
TSS_LABELS = {
    "spinal_cord": 1,
    "spinal_canal": 2,
    # Vertebrae: C1-C7 (11-17), T1-T12 (21-32), L1-L5 (41-45), Sacrum (50)
    "vertebrae": {
        "C1": 11, "C2": 12, "C3": 13, "C4": 14, "C5": 15, "C6": 16, "C7": 17,
        "T1": 21, "T2": 22, "T3": 23, "T4": 24, "T5": 25, "T6": 26,
        "T7": 27, "T8": 28, "T9": 29, "T10": 30, "T11": 31, "T12": 32,
        "L1": 41, "L2": 42, "L3": 43, "L4": 44, "L5": 45,
        "S": 50,
    },
    # Discs: C2-C3 to C6-C7 (63-67), C7-T1 to T11-T12 (71-82), T12-L1 to L4-L5 (91-95), L5-S (100)
    "discs": {
        "C2/C3": 63, "C3/C4": 64, "C4/C5": 65, "C5/C6": 66, "C6/C7": 67,
        "C7/T1": 71, "T1/T2": 72, "T2/T3": 73, "T3/T4": 74, "T4/T5": 75,
        "T5/T6": 76, "T6/T7": 77, "T7/T8": 78, "T8/T9": 79, "T9/T10": 80,
        "T10/T11": 81, "T11/T12": 82,
        "T12/L1": 91, "L1/L2": 92, "L2/L3": 93, "L3/L4": 94, "L4/L5": 95,
        "L5/S": 100,
    },
}

# Reverse mappings for label -> name
TSS_VERTEBRA_NAMES = {v: k for k, v in TSS_LABELS["vertebrae"].items()}
TSS_DISC_NAMES = {v: k for k, v in TSS_LABELS["discs"].items()}


def _run_totalspineseg(
    cordref_path: Path,
    work_dir: Path,
) -> dict:
    """
    Run TotalSpineSeg segmentation on the cordref image.
    
    TotalSpineSeg outputs a single NIfTI with multiple label values:
    - 1: spinal cord
    - 2: spinal canal
    - 11-50: vertebrae (C1-S)
    - 63-100: intervertebral discs
    
    Args:
        cordref_path: Path to cropped anatomical reference
        work_dir: Working directory for outputs
        
    Returns:
        Dict with status, paths to extracted components, and metrics
    """
    tss_dir = work_dir / "totalspineseg"
    tss_dir.mkdir(parents=True, exist_ok=True)
    
    # Run TotalSpineSeg
    # Syntax: sct_deepseg totalspineseg -i input.nii.gz -o output.nii.gz
    # SCT adds suffixes: _step2_output, _step1_cord, _step1_canal, etc.
    output_path = tss_dir / "tss.nii.gz"
    ok, message = _run_command(
        [
            "sct_deepseg",
            "totalspineseg",
            "-i",
            str(cordref_path),
            "-o",
            str(output_path),
        ]
    )
    # TotalSpineSeg outputs: tss_step2_output.nii.gz, tss_step1_cord.nii.gz, etc.
    tss_output = tss_dir / "tss_step2_output.nii.gz"
    tss_cord = tss_dir / "tss_step1_cord.nii.gz"
    tss_canal = tss_dir / "tss_step1_canal.nii.gz"
    
    if not tss_output.exists():
        # List what files were actually created for debugging
        created_files = list(tss_dir.rglob("*.nii.gz"))
        if not ok:
            return {
                "status": "FAIL",
                "failure_message": f"TotalSpineSeg failed: {message}",
            }
        return {
            "status": "FAIL",
            "failure_message": f"TotalSpineSeg output not found. Created files: {[str(f.relative_to(tss_dir)) for f in created_files[:10]]}",
        }
    
    # Load TSS output and extract components
    try:
        tss_img = cast(Any, nib.load(tss_output))
        tss_data = tss_img.get_fdata()
        if tss_data.ndim > 3:
            tss_data = tss_data[..., 0]
        affine = tss_img.affine
        header = tss_img.header
    except Exception as e:
        return {
            "status": "FAIL",
            "failure_message": f"Failed to load TotalSpineSeg output: {e}",
        }
    
    # Use TSS's own cord and canal outputs if available (more accurate)
    cord_path = tss_cord if tss_cord.exists() else tss_dir / "cord.nii.gz"
    canal_path = tss_canal if tss_canal.exists() else tss_dir / "canal.nii.gz"
    
    # If TSS didn't provide separate cord/canal files, extract from main output
    if not tss_cord.exists():
        cord_mask = (tss_data == TSS_LABELS["spinal_cord"]).astype(np.uint8)
        nib.save(nib.Nifti1Image(cord_mask, affine, header), cord_path)
    
    if not tss_canal.exists():
        canal_mask = (tss_data == TSS_LABELS["spinal_canal"]).astype(np.uint8)
        nib.save(nib.Nifti1Image(canal_mask, affine, header), canal_path)
    
    # Extract vertebrae (labels 11-50) - keep original labels for visualization
    vertebrae_labels = list(TSS_LABELS["vertebrae"].values())
    vertebrae_mask = np.isin(tss_data, vertebrae_labels).astype(np.uint8)
    vertebrae_data = np.where(vertebrae_mask, tss_data, 0).astype(np.uint8)
    vertebrae_path = tss_dir / "vertebrae.nii.gz"
    nib.save(nib.Nifti1Image(vertebrae_data, affine, header), vertebrae_path)
    
    # Extract discs (labels 63-100) - keep original labels
    disc_labels = list(TSS_LABELS["discs"].values())
    discs_mask = np.isin(tss_data, disc_labels).astype(np.uint8)
    discs_data = np.where(discs_mask, tss_data, 0).astype(np.uint8)
    discs_path = tss_dir / "discs.nii.gz"
    nib.save(nib.Nifti1Image(discs_data, affine, header), discs_path)
    
    # Create SCT-compatible vertebral labels (convert TSS labels to SCT convention)
    # SCT uses: C1=1, C2=2, ..., C7=7, T1=8, ..., T12=19, L1=20, ..., L5=24
    sct_vertebral_data = np.zeros_like(tss_data, dtype=np.uint8)
    for name, tss_label in TSS_LABELS["vertebrae"].items():
        if name == "S":
            continue  # Skip sacrum for SCT compat
        mask = tss_data == tss_label
        if name.startswith("C"):
            sct_label = int(name[1:])  # C1=1, C7=7
        elif name.startswith("T"):
            sct_label = int(name[1:]) + 7  # T1=8, T12=19
        elif name.startswith("L"):
            sct_label = int(name[1:]) + 19  # L1=20, L5=24
        else:
            continue
        sct_vertebral_data[mask] = sct_label
    sct_vertebral_path = tss_dir / "vertebral_labels_sct.nii.gz"
    nib.save(nib.Nifti1Image(sct_vertebral_data, affine, header), sct_vertebral_path)
    
    # Create SCT-compatible disc labels (point labels at disc centers)
    # SCT uses: disc below C2 = 3, disc below C3 = 4, etc.
    sct_disc_data = np.zeros_like(tss_data, dtype=np.uint8)
    for name, tss_label in TSS_LABELS["discs"].items():
        mask = tss_data == tss_label
        if not mask.any():
            continue
        # Get centroid of disc
        coords = np.argwhere(mask)
        centroid = coords.mean(axis=0).astype(int)
        # Convert disc name to SCT label (disc C2/C3 = 3, C3/C4 = 4, etc.)
        upper, lower = name.split("/")
        if upper.startswith("C"):
            sct_label = int(upper[1:]) + 1  # C2/C3 = 3
        elif upper.startswith("T"):
            sct_label = int(upper[1:]) + 8  # T1/T2 = 9
        elif upper.startswith("L"):
            sct_label = int(upper[1:]) + 20  # L1/L2 = 21
        else:
            continue
        # Place single voxel at centroid
        sct_disc_data[tuple(centroid)] = sct_label
    sct_disc_path = tss_dir / "disc_labels_sct.nii.gz"
    nib.save(nib.Nifti1Image(sct_disc_data, affine, header), sct_disc_path)
    
    # Compute metrics
    present_vertebrae = sorted([TSS_VERTEBRA_NAMES[int(v)] for v in np.unique(vertebrae_data) if v > 0])
    present_discs = sorted([TSS_DISC_NAMES[int(v)] for v in np.unique(discs_data) if v > 0])
    
    # Load cord/canal for volume metrics
    try:
        cord_vol_data = nib.load(cord_path).get_fdata()
        cord_volume_vox = int(np.sum(cord_vol_data > 0))
    except Exception:
        cord_volume_vox = 0
    try:
        canal_vol_data = nib.load(canal_path).get_fdata()
        canal_volume_vox = int(np.sum(canal_vol_data > 0))
    except Exception:
        canal_volume_vox = 0
    
    return {
        "status": "PASS",
        "failure_message": None,
        "tss_output_path": str(tss_output),
        "cord_path": str(cord_path),
        "canal_path": str(canal_path),
        "vertebrae_path": str(vertebrae_path),
        "discs_path": str(discs_path),
        "vertebral_labels_path": str(sct_vertebral_path),  # SCT-compatible
        "disc_labels_path": str(sct_disc_path),  # SCT-compatible
        "metrics": {
            "vertebrae_count": len(present_vertebrae),
            "disc_count": len(present_discs),
            "present_vertebrae": present_vertebrae,
            "present_discs": present_discs,
            "cord_volume_vox": cord_volume_vox,
            "canal_volume_vox": canal_volume_vox,
        },
    }


def _run_rootlets_segmentation(
    cordref_path: Path,
    work_dir: Path,
    enabled: bool,
    eligible: bool,
) -> dict:
    if not enabled:
        return {"status": "SKIP", "eligible": eligible, "enabled": False}
    if not eligible:
        return {"status": "SKIP", "eligible": False, "enabled": True}

    rootlets_dir = work_dir / "rootlets"
    rootlets_dir.mkdir(parents=True, exist_ok=True)
    output_base = rootlets_dir / "rootlets.nii.gz"
    ok, message = _run_command(
        [
            "sct_deepseg",
            "rootlets",
            "-i",
            str(cordref_path),
            "-o",
            str(output_base),
        ]
    )
    if not ok:
        return {"status": "FAIL", "eligible": True, "enabled": True, "failure_message": message}

    rootlets_path = _find_rootlets_output(rootlets_dir, output_base)
    if rootlets_path is None:
        return {
            "status": "FAIL",
            "eligible": True,
            "enabled": True,
            "failure_message": "Rootlets output not found.",
        }
    return {
        "status": "PASS",
        "eligible": True,
        "enabled": True,
        "rootlets_path": str(rootlets_path),
    }


def _run_register_to_template(
    cordref_path: Path,
    seg_path: Path,
    disc_labels_path: Optional[Path],
    rootlets_path: Optional[Path],
    contrast: str,
    work_dir: Path,
) -> dict:
    work_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "sct_register_to_template",
        "-i",
        str(cordref_path),
        "-s",
        str(seg_path),
        "-c",
        str(contrast),
        "-ofolder",
        str(work_dir),
    ]
    if disc_labels_path is not None:
        cmd.extend(["-ldisc", str(disc_labels_path)])
    if rootlets_path is not None:
        cmd.extend(["-lrootlet", str(rootlets_path)])
    ok, message = _run_command(cmd)
    if not ok:
        variant = "rootlet" if rootlets_path is not None else "disc"
        return {
            "status": "FAIL",
            "failure_message": f"{variant} registration failed: {message}",
        }

    warp_anat2template = work_dir / "warp_anat2template.nii.gz"
    warp_template2anat = work_dir / "warp_template2anat.nii.gz"
    anat2template = work_dir / "anat2template.nii.gz"
    template2anat = work_dir / "template2anat.nii.gz"
    if not warp_anat2template.exists() or not warp_template2anat.exists():
        return {
            "status": "FAIL",
            "failure_message": "Registration warps not found in output folder.",
        }

    return {
        "status": "PASS",
        "failure_message": None,
        "warp_anat2template": str(warp_anat2template),
        "warp_template2anat": str(warp_template2anat),
        "anat2template": str(anat2template) if anat2template.exists() else None,
        "template2anat": str(template2anat) if template2anat.exists() else None,
    }


def _render_crop_box_sagittal(
    qc_root: Path,
    cordref_std_path: Optional[Path],
    cordref_crop_path: Optional[Path],
    discovery_seg_path: Optional[Path],
    crop_mask_path: Optional[Path],
) -> Optional[Path]:
    """
    Render S2.1 crop box sagittal figure showing discovery and crop region.
    
    Shows the standardized anatomical reference with:
    - Blue contour: cord mask (discovery segmentation in std space)
    - Red contour: crop box region (from crop mask in std space)
    
    Args:
        qc_root: QC output directory
        cordref_std_path: Path to standardized anatomical reference (before crop)
        cordref_crop_path: Path to cropped anatomical reference (after crop)
        discovery_seg_path: Path to discovery segmentation (in std space, for blue overlay)
        crop_mask_path: Path to crop mask (in std space, for red overlay)
        
    Returns:
        Path to output PNG or None on failure
    """
    if cordref_std_path is None:
        return None
    if not cordref_std_path.exists():
        return None
    
    qc_root.mkdir(parents=True, exist_ok=True)
    
    try:
        # Load standardized image
        std_img = nib.as_closest_canonical(nib.load(cordref_std_path))
        std_data = std_img.get_fdata()
        
        if std_data.ndim > 3:
            std_data = std_data[..., 0]
        
        std_shape = std_data.shape
        
        # Load discovery segmentation (in std space)
        discovery_seg_data = None
        if discovery_seg_path and discovery_seg_path.exists():
            try:
                discovery_seg_img = nib.as_closest_canonical(nib.load(discovery_seg_path))
                discovery_seg_data = discovery_seg_img.get_fdata()
                if discovery_seg_data.ndim > 3:
                    discovery_seg_data = discovery_seg_data[..., 0]
                # Ensure shapes match
                if discovery_seg_data.shape != std_shape:
                    discovery_seg_data = None
            except Exception:
                discovery_seg_data = None
        
        # Load crop mask (in std space)
        crop_mask_data = None
        if crop_mask_path and crop_mask_path.exists():
            try:
                crop_mask_img = nib.as_closest_canonical(nib.load(crop_mask_path))
                crop_mask_data = crop_mask_img.get_fdata()
                if crop_mask_data.ndim > 3:
                    crop_mask_data = crop_mask_data[..., 0]
                # Ensure shapes match
                if crop_mask_data.shape != std_shape:
                    crop_mask_data = None
                else:
                    crop_mask_data = crop_mask_data > 0
            except Exception:
                crop_mask_data = None
        
        # If crop mask not available, fall back to computing from cropped image
        if crop_mask_data is None and cordref_crop_path and cordref_crop_path.exists():
            try:
                crop_img = nib.as_closest_canonical(nib.load(cordref_crop_path))
                crop_data = crop_img.get_fdata()
                if crop_data.ndim > 3:
                    crop_data = crop_data[..., 0]
                # Use a simple heuristic: find where crop_data fits in std_data
                crop_shape = crop_data.shape
                size_x, size_y = crop_shape[0], crop_shape[1]
                center = (std_shape[0] // 2, std_shape[1] // 2, std_shape[2] // 2)
                x0 = max(0, center[0] - size_x // 2)
                y0 = max(0, center[1] - size_y // 2)
                x1 = min(std_shape[0], x0 + size_x)
                y1 = min(std_shape[1], y0 + size_y)
                x0 = max(0, x1 - size_x)
                y0 = max(0, y1 - size_y)
                z0, z1 = 0, std_shape[2]
                
                crop_mask_data = np.zeros(std_shape, dtype=bool)
                crop_mask_data[x0:x1, y0:y1, z0:z1] = True
            except Exception:
                crop_mask_data = None
        
        # Find center slice for sagittal view
        # Prefer using discovery segmentation center, otherwise use crop mask center
        if discovery_seg_data is not None:
            coords = np.argwhere(discovery_seg_data > 0)
        elif crop_mask_data is not None:
            coords = np.argwhere(crop_mask_data)
        else:
            coords = np.array([[std_shape[0] // 2, std_shape[1] // 2, std_shape[2] // 2]])
        
        if coords.size == 0:
            return None
        x_index = int(np.median(coords[:, 0]))
        x_index = max(0, min(x_index, std_shape[0] - 1))
        
        # Extract sagittal slice
        img_slice = std_data[x_index, :, :]
        
        # Extract discovery segmentation slice (in std space)
        discovery_slice_2d = None
        if discovery_seg_data is not None:
            discovery_slice_2d = discovery_seg_data[x_index, :, :] > 0
        
        # Extract crop mask slice (in std space)
        crop_slice = None
        if crop_mask_data is not None:
            crop_slice = crop_mask_data[x_index, :, :]
        
        if img_slice.ndim != 2:
            return None
        
        # Display with superior at the top: z-axis becomes vertical after transpose
        img_slice = np.flipud(img_slice.T)
        if crop_slice is not None:
            crop_slice = np.flipud(crop_slice.T)
        if discovery_slice_2d is not None:
            discovery_slice_2d = np.flipud(discovery_slice_2d.T)
        
        # Normalize image
        vmin, vmax = np.percentile(img_slice, [1, 99])
        if vmax <= vmin:
            vmin, vmax = float(img_slice.min()), float(img_slice.max())
        if vmax <= vmin:
            vmax = vmin + 1.0
        
        normalized = np.clip((img_slice - vmin) / (vmax - vmin), 0, 1)
        base = (normalized * 255).astype(np.uint8)
        base_rgb = np.repeat(base[..., np.newaxis], 3, axis=2)
        
        # Create RGBA overlay for overlays
        overlay_img = Image.fromarray(base_rgb, mode="RGB").convert("RGBA")
        
        # Draw discovery segmentation as solid transparent overlay (blue) - if available
        if discovery_slice_2d is not None:
            # Create mask overlay: fill actual cord mask pixels with blue transparency
            # discovery_slice_2d is already (y, z) shape after transpose/flip
            mask_array = discovery_slice_2d.astype(np.uint8) * 180  # Alpha for ~70% opacity
            blue_overlay = np.zeros((*discovery_slice_2d.shape, 4), dtype=np.uint8)
            blue_overlay[:, :, 0] = 0      # R
            blue_overlay[:, :, 1] = 100    # G
            blue_overlay[:, :, 2] = 200    # B
            blue_overlay[:, :, 3] = mask_array  # A (alpha - only where mask is True)
            
            # Convert to PIL Image
            mask_img = Image.fromarray(blue_overlay, mode="RGBA")
            
            # Composite onto overlay (only where mask is True)
            overlay_img = Image.alpha_composite(overlay_img, mask_img)
        
        # Draw crop box as thin rectangular border (red) - if available
        if crop_slice is not None:
            # Compute bounding box of crop mask
            coords = np.argwhere(crop_slice)
            if coords.size > 0:
                y_min, z_min = coords.min(axis=0)
                y_max, z_max = coords.max(axis=0)
                
                # Draw thin rectangular border (1px thick)
                draw = ImageDraw.Draw(overlay_img)
                # Draw rectangle outline only (no fill)
                draw.rectangle(
                    [(z_min, y_min), (z_max + 1, y_max + 1)],
                    outline=(255, 0, 0, 255),  # Red
                    width=1,  # Thin border (1 pixel)
                )
        
        # Convert back to RGB
        final_rgb = np.array(overlay_img.convert("RGB"), dtype=np.uint8)
        
        # Save as PPM, resize with ImageMagick
        output = qc_root / "crop_box_sagittal.png"
        ppm_path = qc_root / "crop_box_sagittal.ppm"
        _write_ppm(ppm_path, final_rgb)
        
        ok, _ = _run_command(
            [
                "convert",
                str(ppm_path),
                "-filter",
                "Lanczos",
                "-resize",
                "1200x",
                str(output),
            ]
        )
        
        # Clean up PPM
        if ppm_path.exists():
            ppm_path.unlink()
        
        return output if ok else None
        
    except Exception:  # noqa: BLE001
        return None


def _binary_erode_2d(mask: np.ndarray) -> np.ndarray:
    """3x3 erosion without scipy; edges are treated as False."""
    if mask.ndim != 2:
        raise ValueError("mask must be 2D")
    h, w = mask.shape
    if h < 3 or w < 3:
        return np.zeros_like(mask, dtype=bool)
    eroded = np.ones_like(mask, dtype=bool)
    core = mask[1:-1, 1:-1]
    eroded[1:-1, 1:-1] = core.copy()
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            eroded[1:-1, 1:-1] &= mask[1 + dy : h - 1 + dy, 1 + dx : w - 1 + dx]
    eroded[0, :] = False
    eroded[-1, :] = False
    eroded[:, 0] = False
    eroded[:, -1] = False
    return eroded


def _mask_contour_2d(mask: np.ndarray) -> np.ndarray:
    """Return a thin contour mask from a 2D boolean mask."""
    mask = mask.astype(bool)
    eroded = _binary_erode_2d(mask)
    return mask & (~eroded)


def _draw_thick_contour(
    overlay: Image.Image,
    contour_mask: np.ndarray,
    color: tuple[int, int, int, int],
    thickness: int = 2,
    outline_color: Optional[tuple[int, int, int, int]] = (0, 0, 0, 255),
) -> None:
    """Draw a thick contour on an RGBA overlay image with optional dark outline for contrast."""
    yy, xx = np.where(contour_mask)
    if outline_color is not None:
        # Draw outline first (1px wider on all sides)
        for y, x in zip(yy.tolist(), xx.tolist()):
            for dy in range(-thickness - 1, thickness + 2):
                for dx in range(-thickness - 1, thickness + 2):
                    if dx * dx + dy * dy > (thickness + 1) ** 2:
                        continue
                    px = x + dx
                    py = y + dy
                    if 0 <= px < overlay.width and 0 <= py < overlay.height:
                        overlay.putpixel((px, py), outline_color)
    
    # Draw main border
    for y, x in zip(yy.tolist(), xx.tolist()):
        for dy in range(-thickness, thickness + 1):
            for dx in range(-thickness, thickness + 1):
                if dx * dx + dy * dy > thickness ** 2:
                    continue
                px = x + dx
                py = y + dy
                if 0 <= px < overlay.width and 0 <= py < overlay.height:
                    overlay.putpixel((px, py), color)


def _render_reportlets_for_runs(runs: list[dict], out_root: Path, dataset_key: str) -> list[dict]:
    updated = []
    for run in runs:
        if run.get("status") != "PASS":
            updated.append(run)
            continue
        reportlets, error = _render_reportlets(run, out_root, dataset_key)
        if error:
            run["status"] = "FAIL"
            run["failure_message"] = error
        run["reportlets"] = reportlets
        updated.append(run)
    return updated


def _render_reportlets(run: dict, out_root: Path, dataset_key: str) -> tuple[dict, Optional[str]]:
    subject = run.get("subject")
    session = run.get("session")
    # Use dataset_key from run record if present, otherwise use passed dataset_key
    run_dataset_key = run.get("dataset_key", dataset_key)
    figures_dir = _derivatives_figures_dir(out_root, subject, session, run_dataset_key)
    figures_dir.mkdir(parents=True, exist_ok=True)

    cordref_path = _abs_path(out_root, run.get("cordref_path"))
    cordmask_path = _abs_path(out_root, run.get("cordmask_path"))
    vertebral_labels_path = _abs_path(out_root, run.get("vertebral_labels_path"))
    disc_labels_path = _abs_path(out_root, run.get("disc_labels_path"))
    canal_path = _abs_path(out_root, run.get("canal_path"))
    tss_output_path = _abs_path(out_root, run.get("tss_output_path"))
    rootlets_path = _abs_path(out_root, run.get("rootlets_path"))
    reg_selected = run.get("registration", {}).get(run.get("registration", {}).get("selected", "disc"), {})
    template2anat = reg_selected.get("template2anat")
    if template2anat:
        template2anat = Path(template2anat)
    warp_template2anat = reg_selected.get("warp_template2anat")
    if warp_template2anat:
        warp_template2anat = Path(warp_template2anat)

    reportlets: dict[str, Optional[str]] = {}
    qc_root = out_root / "work" / "S2_anat_cordref" / run.get("run_id", "unknown") / "qc"
    work_dir = out_root / "work" / "S2_anat_cordref" / run.get("run_id", "unknown")
    
    # S2.1: Discovery + Crop sagittal figure
    cordref_std_path = work_dir / "cordref_std.nii.gz"
    cordref_crop_path = work_dir / "cordref_crop.nii.gz"
    discovery_seg_path = work_dir / "cordmask_discovery.nii.gz"
    crop_mask_path = work_dir / "crop_mask.nii.gz"
    crop_box_sagittal = _render_crop_box_sagittal(
        qc_root=qc_root / "crop_box_sagittal",
        cordref_std_path=cordref_std_path if cordref_std_path.exists() else None,
        cordref_crop_path=cordref_crop_path if cordref_crop_path.exists() else None,
        discovery_seg_path=discovery_seg_path if discovery_seg_path.exists() else None,
        crop_mask_path=crop_mask_path if crop_mask_path.exists() else None,
    )
    reportlets["crop_box_sagittal"] = _copy_reportlet(
        crop_box_sagittal,
        figures_dir / _format_reportlet_name(subject, session, "S2_crop_box_sagittal"),
        out_root,
    )

    cordmask_montage = _render_cordmask_montage(
        qc_root=qc_root / "cordmask_montage",
        image=cordref_path,
        cordmask=cordmask_path,
    )
    reportlets["cordmask_montage"] = _copy_reportlet(
        cordmask_montage,
        figures_dir / _format_reportlet_name(subject, session, "S2_cordmask_montage"),
        out_root,
    )

    # TotalSpineSeg comprehensive visualization (vertebrae + discs + cord + canal)
    tss_info = run.get("tss") or run.get("labels") or {}
    tss_status = tss_info.get("status", "PASS")
    if tss_status == "PASS" and tss_output_path is not None:
        tss_montage_png = _render_totalspineseg_montage(
            qc_root=qc_root / "totalspineseg_montage",
            image=cordref_path,
            tss_output_path=tss_output_path,
            cord_path=cordmask_path,  # Use the contrast-agnostic cord segmentation
            canal_path=canal_path,
        )
        reportlets["totalspineseg_montage"] = _copy_reportlet(
            tss_montage_png,
            figures_dir / _format_reportlet_name(subject, session, "S2_totalspineseg_montage"),
            out_root,
        )
    else:
        reportlets["totalspineseg_montage"] = _write_not_available_panel(
            figures_dir / _format_reportlet_name(subject, session, "S2_totalspineseg_montage"),
            out_root,
            "TotalSpineSeg not available",
        )

    reg_gif = None
    if template2anat and warp_template2anat:
        reg_gif = _render_pam50_reg_overlay_gif(
            qc_root=qc_root / "pam50_reg_overlay",
            subject_image=cordref_path,
            pam50_in_s2=template2anat,
            subject_cordmask=cordmask_path,
            warp_template2anat=warp_template2anat,
            subject_label=subject,
            session_label=session,
            vertebral_labels_path=vertebral_labels_path,
        )
    reportlets["pam50_reg_overlay"] = _copy_reportlet(
        reg_gif,
        figures_dir / _format_reportlet_name(subject, session, "S2_pam50_reg_overlay", ext="gif"),
        out_root,
    )

    rootlets_info = run.get("rootlets", {})
    if rootlets_info.get("status") == "PASS" and rootlets_path:
        rootlets_montage = _render_rootlets_montage(
            qc_root=qc_root / "rootlets_montage",
            image=cordref_path,
            rootlets=rootlets_path,
            vertebral_labels=vertebral_labels_path,
            cordmask=cordmask_path,
        )
        if rootlets_montage is not None:
            reportlets["rootlets_montage"] = _copy_reportlet(
                rootlets_montage,
                figures_dir / _format_reportlet_name(subject, session, "S2_rootlets_montage", ext="gif"),
                out_root,
            )
        else:
            reportlets["rootlets_montage"] = _write_not_available_panel(
                figures_dir / _format_reportlet_name(subject, session, "S2_rootlets_montage"),
                out_root,
                "Rootlets montage not available",
            )
    else:
        reportlets["rootlets_montage"] = _write_not_available_panel(
            figures_dir / _format_reportlet_name(subject, session, "S2_rootlets_montage"),
            out_root,
            "Rootlets not available",
        )

    required = [
        "cordmask_montage",
        "totalspineseg_montage",
        "pam50_reg_overlay",
    ]
    missing = [key for key in required if not reportlets.get(key)]
    if rootlets_info.get("status") == "PASS":
        if not reportlets.get("rootlets_montage"):
            missing.append("rootlets_montage")
    if missing:
        return reportlets, f"Reportlet generation failed: {', '.join(missing)}"
    return reportlets, None


def _label_cmd(
    cordref_path: Path,
    seg_path: Path,
    contrast: str,
    clean_labels: int,
    out_dir: Path,
    initcenter: Optional[int],
) -> list[str]:
    cmd = [
        "sct_label_vertebrae",
        "-i",
        str(cordref_path),
        "-s",
        str(seg_path),
        "-c",
        str(contrast),
        "-clean-labels",
        str(clean_labels),
        "-ofolder",
        str(out_dir),
    ]
    if initcenter is not None:
        cmd.extend(["-initcenter", str(initcenter)])
    return cmd


def _summarise_runs(inventory: dict, policy_path: Path, runs: list[dict]) -> dict:
    total = len(runs)
    passed = sum(1 for run in runs if run.get("status") == "PASS")
    failed = sum(1 for run in runs if run.get("status") == "FAIL")
    status = "PASS" if failed == 0 and total > 0 else "FAIL"
    failure_message = None if status == "PASS" else "One or more runs failed in S2_anat_cordref."
    return {
        "dataset_key": inventory.get("dataset_key"),
        "bids_root": inventory.get("bids_root"),
        "status": status,
        "failure_message": failure_message,
        "policy_path": str(policy_path),
        "counts": {"runs": total, "passed": passed, "failed": failed},
        "runs": runs,
    }


def _write_runs_jsonl(path: Path, runs: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for run in runs:
            f.write(json.dumps(run, default=str))
            f.write("\n")


def _read_runs_jsonl(path: Path) -> list[dict]:
    runs = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            runs.append(json.loads(line))
    return runs


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")


def _append_metrics(path: Path, dataset_key: Optional[str], runs: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for run in runs:
            record = _metrics_record(dataset_key, run)
            if record is None:
                continue
            f.write(json.dumps(record))
            f.write("\n")


def _metrics_record(dataset_key: Optional[str], run: dict) -> Optional[dict]:
    metrics = run.get("metrics") or {}
    labels_info = run.get("labels") or {}
    label_metrics = labels_info.get("metrics") or {}
    if not metrics:
        return None
    return {
        "step": "S2_anat_cordref",
        "dataset_key": dataset_key,
        "subject": run.get("subject"),
        "session": run.get("session"),
        "status": run.get("status"),
        "cordref_modality": run.get("cordref_modality"),
        "cord_length_mm": metrics.get("cord_length_mm"),
        "cord_volume_mm3": metrics.get("cord_volume_mm3"),
        "csa_mean_mm2": metrics.get("csa_mean_mm2"),
        "csa_min_mm2": metrics.get("csa_min_mm2"),
        "csa_max_mm2": metrics.get("csa_max_mm2"),
        "label_count": label_metrics.get("label_count"),
        "disc_label_count": label_metrics.get("disc_label_count"),
        "rootlets_status": (run.get("rootlets") or {}).get("status"),
        "registration_selected": (run.get("registration") or {}).get("selected"),
    }


def _run_command(cmd: list[str]) -> tuple[bool, str]:
    try:
        result = subprocess.run(cmd, text=True, capture_output=True, check=True)
    except FileNotFoundError:
        return False, f"Command not found: {cmd[0]}"
    except subprocess.CalledProcessError as err:
        output = "\n".join(part for part in [err.stdout, err.stderr] if part)
        return False, output.strip()
    output = "\n".join(part for part in [result.stdout, result.stderr] if part)
    return True, output.strip()


def _is_command_not_found(message: str) -> bool:
    return "Command not found" in message or "not found" in message.lower()


def _get_sct_version() -> Optional[str]:
    ok, output = _run_command(["sct_version"])
    if not ok:
        return None
    return output.strip() or None


def _derivatives_anat_dir(out_root: Path, subject: str, session: Optional[str], dataset_key: Optional[str] = None) -> Path:
    """
    Return the derivatives anat directory path.
    
    If dataset_key is provided, includes it in the path for multi-dataset workflows:
    out_root/derivatives/spinalfmriprep/{dataset_key}/sub-XX/[ses-XX/]anat
    
    If dataset_key is None, uses the traditional path:
    out_root/derivatives/spinalfmriprep/sub-XX/[ses-XX/]anat
    """
    if dataset_key:
        base = out_root / "derivatives" / "spinalfmriprep" / dataset_key / f"sub-{subject}"
    else:
        base = out_root / "derivatives" / "spinalfmriprep" / f"sub-{subject}"
    
    if session:
        return base / f"ses-{session}" / "anat"
    return base / "anat"


def _format_derivative_name(subject: str, session: Optional[str], desc: str, suffix: str) -> str:
    if session:
        return f"sub-{subject}_ses-{session}_{desc}_{suffix}.nii.gz"
    return f"sub-{subject}_{desc}_{suffix}.nii.gz"


def _format_run_id(subject: str, session: Optional[str]) -> str:
    if session:
        return f"sub-{subject}_ses-{session}"
    return f"sub-{subject}_ses-none"


def _copy_nifti(source: Path, dest: Path) -> None:
    img = nib.load(source)
    nib.save(img, dest)


def _copy_file(source: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    copy2(source, dest)


def _fail_run(subject: str, session: Optional[str], run_id: str, message: str) -> dict:
    return {
        "subject": subject,
        "session": session,
        "status": "FAIL",
        "failure_message": message,
        "run_id": run_id,
    }


def _relpath(path: Optional[Path], out_root: Path) -> Optional[str]:
    if path is None:
        return None
    try:
        return str(path.relative_to(out_root))
    except ValueError:
        return str(path)


def _derivatives_figures_dir(out_root: Path, subject: Optional[str], session: Optional[str], dataset_key: Optional[str] = None) -> Path:
    """
    Return the derivatives figures directory path.
    
    If dataset_key is provided, includes it in the path for multi-dataset workflows:
    out_root/derivatives/spinalfmriprep/{dataset_key}/sub-XX/[ses-XX/]figures
    
    If dataset_key is None, uses the traditional path:
    out_root/derivatives/spinalfmriprep/sub-XX/[ses-XX/]figures
    """
    if dataset_key:
        if session:
            return out_root / "derivatives" / "spinalfmriprep" / dataset_key / f"sub-{subject}" / f"ses-{session}" / "figures"
        return out_root / "derivatives" / "spinalfmriprep" / dataset_key / f"sub-{subject}" / "figures"
    else:
        if session:
            return out_root / "derivatives" / "spinalfmriprep" / f"sub-{subject}" / f"ses-{session}" / "figures"
        return out_root / "derivatives" / "spinalfmriprep" / f"sub-{subject}" / "figures"


def _format_reportlet_name(
    subject: Optional[str],
    session: Optional[str],
    desc: str,
    ext: str = "png",
) -> str:
    if session:
        return f"sub-{subject}_ses-{session}_desc-{desc}.{ext}"
    return f"sub-{subject}_desc-{desc}.{ext}"


def _abs_path(out_root: Path, rel: Optional[str]) -> Optional[Path]:
    if rel is None:
        return None
    path = Path(rel)
    if path.is_absolute():
        return path
    return out_root / rel


def _qc_overlay(
    qc_root: Path,
    image: Optional[Path],
    seg: Optional[Path],
    process: str,
    dataset_key: str,
    subject: Optional[str],
    dest: Optional[Path] = None,
) -> Optional[Path]:
    if image is None or seg is None:
        return None
    qc_root.mkdir(parents=True, exist_ok=True)
    cmd = [
        "sct_qc",
        "-i",
        str(image),
        "-s",
        str(seg),
        "-p",
        process,
        "-qc",
        str(qc_root),
        "-qc-dataset",
        dataset_key,
        "-qc-subject",
        subject or "unknown",
    ]
    if dest is not None:
        cmd.extend(["-d", str(dest)])
    ok, _ = _run_command(cmd)
    if not ok:
        return None
    overlay = _find_qc_overlay(qc_root)
    if overlay is None:
        return None
    background = _find_qc_background(qc_root)
    if background is None:
        return overlay
    composed = overlay.parent / "composite_img.png"
    if _compose_overlay(background, overlay, composed):
        return composed
    return overlay


def _resolve_pam50_dir() -> Optional[Path]:
    """Resolve PAM50 template directory from environment/SCT conventions."""
    candidates: list[Path] = []
    env_path = os.environ.get("PAM50_PATH")
    if env_path:
        candidates.append(Path(env_path))
    sct_dir = os.environ.get("SCT_DIR")
    if sct_dir:
        candidates.append(Path(sct_dir) / "data" / "PAM50")
    candidates.append(Path.home() / "sct_7.1" / "data" / "PAM50")
    for p in candidates:
        if p.exists():
            return p
    return None


def _find_pam50_cord_mask(pam50_dir: Path) -> Optional[Path]:
    """Find PAM50 cord mask template file."""
    for name in ("PAM50_cord.nii.gz", "PAM50_cordseg.nii.gz", "PAM50_cord_mask.nii.gz"):
        for candidate in (pam50_dir / "template" / name, pam50_dir / name):
            if candidate.exists():
                return candidate
    return None


def _ensure_rpi_orientation(image_path: Path, work_dir: Path) -> Optional[Path]:
    """Ensure image is in RPI orientation using sct_image.

    Checks orientation using sct_image -header, and if not RPI, uses sct_image -setorient RPI.
    Returns path to properly oriented image (may be original if already RPI).

    Args:
        image_path: Path to input image
        work_dir: Working directory for output if reorientation needed

    Returns:
        Path to RPI-oriented image, or None if orientation check/set fails
    """
    work_dir.mkdir(parents=True, exist_ok=True)

    # Check current orientation
    ok, output = _run_command(["sct_image", "-i", str(image_path), "-header"])
    if not ok:
        return None

    # Parse orientation from header output (look for "orientation" or "qform" info)
    # sct_image -header typically shows orientation in the output
    # If output contains "RPI" or orientation is already correct, return original
    if "RPI" in output.upper() or "orientation.*RPI" in output:
        return image_path

    # Reorient to RPI
    rpi_path = work_dir / f"{image_path.stem}_rpi{image_path.suffix}"
    ok, _ = _run_command([
        "sct_image",
        "-i", str(image_path),
        "-setorient", "RPI",
        "-o", str(rpi_path),
    ])
    if not ok or not rpi_path.exists():
        return None

    return rpi_path


def _extract_centerline_csv(cord_mask_path: Path, work_dir: Path) -> Optional[Path]:
    """Extract centerline CSV using sct_get_centerline.

    Runs sct_get_centerline -i <cord_mask> -method fitseg and returns path to CSV.
    CSV contains float centerline coordinates in RPI orientation (x, y, z in mm).
    sct_get_centerline automatically outputs CSV with same base name as output image.

    Args:
        cord_mask_path: Path to cord mask image
        work_dir: Working directory for centerline output

    Returns:
        Path to centerline CSV file, or None if extraction fails
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    centerline_img = work_dir / "centerline.nii.gz"
    centerline_csv = work_dir / "centerline.csv"  # sct_get_centerline outputs CSV with same base name

    ok, _ = _run_command([
        "sct_get_centerline",
        "-i", str(cord_mask_path),
        "-method", "fitseg",
        "-o", str(centerline_img),
    ])

    if not ok:
        return None

    # sct_get_centerline outputs CSV automatically with same base name as output image
    # Check primary location first
    if centerline_csv.exists():
        return centerline_csv

    # Also check alternative locations (in case output goes to input directory)
    csv_candidates = [
        centerline_img.parent / f"{centerline_img.stem}.csv",
        cord_mask_path.parent / f"{cord_mask_path.stem}_centerline.csv",
        cord_mask_path.parent / f"{centerline_img.stem}.csv",
    ]

    for csv_path in csv_candidates:
        if csv_path.exists():
            return csv_path

    # If CSV not found, return None (diagnostics will be skipped)
    return None


def _compute_si_mismatch_from_centerlines(subj_csv: Path, pam_csv: Path) -> dict:
    """Compute SI (superior-inferior) mismatch metrics from centerline CSVs.

    Reads centerline CSV files (assumes RPI orientation, columns include z in mm),
    computes z-ranges, coverage, overlap, and SI shift.
    Detects shift type: systematic z-translation vs scaling/nonlinear mismatch.

    Args:
        subj_csv: Path to subject centerline CSV
        pam_csv: Path to PAM50 centerline CSV

    Returns:
        Diagnostic dict with keys:
        - subj_z_min_mm, subj_z_max_mm: Subject z-range in mm
        - pam_z_min_mm, pam_z_max_mm: PAM50 z-range in mm
        - subj_range_mm, pam_range_mm: Range lengths
        - coverage_pct: pam_range_mm / subj_range_mm * 100
        - overlap_min_mm, overlap_max_mm: Overlap z-range
        - overlap_mm: Overlap length
        - overlap_pct: Overlap percentage of subject range
        - si_shift_mm: Mean(z_pam - z_subj) over overlapping portion
        - shift_type: "systematic" if constant, "scaling" if varying, "none" if zero
        - warnings: List of warning messages
    """
    diagnostics = {
        "subj_z_min_mm": None,
        "subj_z_max_mm": None,
        "pam_z_min_mm": None,
        "pam_z_max_mm": None,
        "subj_range_mm": None,
        "pam_range_mm": None,
        "coverage_pct": None,
        "overlap_min_mm": None,
        "overlap_max_mm": None,
        "overlap_mm": None,
        "overlap_pct": None,
        "si_shift_mm": None,
        "shift_type": "unknown",
        "warnings": [],
    }

    try:
        # Read subject centerline CSV
        # sct_get_centerline CSV format: x,y,z (no header, comma-separated floats)
        subj_z_values = []
        with subj_csv.open("r", encoding="utf-8") as f:
            # Try reading as headerless CSV first (x,y,z format)
            reader = csv.reader(f)
            first_line = next(reader, None)
            if first_line is None:
                diagnostics["warnings"].append("Subject CSV is empty")
                return diagnostics

            # Check if first line looks like header (non-numeric) or data (numeric)
            try:
                float(first_line[0])
                # First line is data, no header - format is x,y,z
                z_col_idx = 2  # z is third column (0-indexed: x=0, y=1, z=2)
                # Process first line
                if len(first_line) > z_col_idx:
                    try:
                        subj_z_values.append(float(first_line[z_col_idx]))
                    except (ValueError, IndexError):
                        pass
                # Process remaining lines
                for row in reader:
                    if len(row) > z_col_idx:
                        try:
                            subj_z_values.append(float(row[z_col_idx]))
                        except (ValueError, IndexError):
                            continue
            except ValueError:
                # First line is header - use DictReader
                f.seek(0)
                reader_dict = csv.DictReader(f)
                for row in reader_dict:
                    # Look for z column (case-insensitive)
                    z_key = None
                    for key in row.keys():
                        if key.lower() == "z":
                            z_key = key
                            break
                    if z_key is None:
                        diagnostics["warnings"].append(f"Subject CSV missing z column: {list(row.keys())}")
                        return diagnostics
                    try:
                        z_val = float(row[z_key])
                        subj_z_values.append(z_val)
                    except (ValueError, KeyError):
                        continue

        if not subj_z_values:
            diagnostics["warnings"].append("Subject centerline CSV has no valid z values")
            return diagnostics

        # Read PAM50 centerline CSV (same format as subject)
        pam_z_values = []
        with pam_csv.open("r", encoding="utf-8") as f:
            reader = csv.reader(f)
            first_line = next(reader, None)
            if first_line is None:
                diagnostics["warnings"].append("PAM50 CSV is empty")
                return diagnostics

            try:
                float(first_line[0])
                # First line is data, no header - format is x,y,z
                z_col_idx = 2  # z is third column
                # Process first line
                if len(first_line) > z_col_idx:
                    try:
                        pam_z_values.append(float(first_line[z_col_idx]))
                    except (ValueError, IndexError):
                        pass
                # Process remaining lines
                for row in reader:
                    if len(row) > z_col_idx:
                        try:
                            pam_z_values.append(float(row[z_col_idx]))
                        except (ValueError, IndexError):
                            continue
            except ValueError:
                # First line is header - use DictReader
                f.seek(0)
                reader_dict = csv.DictReader(f)
                for row in reader_dict:
                    z_key = None
                    for key in row.keys():
                        if key.lower() == "z":
                            z_key = key
                            break
                    if z_key is None:
                        diagnostics["warnings"].append(f"PAM50 CSV missing z column: {list(row.keys())}")
                        return diagnostics
                    try:
                        z_val = float(row[z_key])
                        pam_z_values.append(z_val)
                    except (ValueError, KeyError):
                        continue

        if not pam_z_values:
            diagnostics["warnings"].append("PAM50 centerline CSV has no valid z values")
            return diagnostics

        # Compute z-ranges
        subj_z_min = float(min(subj_z_values))
        subj_z_max = float(max(subj_z_values))
        pam_z_min = float(min(pam_z_values))
        pam_z_max = float(max(pam_z_values))

        subj_range = subj_z_max - subj_z_min
        pam_range = pam_z_max - pam_z_min

        diagnostics["subj_z_min_mm"] = subj_z_min
        diagnostics["subj_z_max_mm"] = subj_z_max
        diagnostics["pam_z_min_mm"] = pam_z_min
        diagnostics["pam_z_max_mm"] = pam_z_max
        diagnostics["subj_range_mm"] = subj_range
        diagnostics["pam_range_mm"] = pam_range

        # Compute coverage
        if subj_range > 0:
            diagnostics["coverage_pct"] = (pam_range / subj_range) * 100.0
        else:
            diagnostics["warnings"].append("Subject z-range is zero")

        # Compute overlap
        overlap_min = max(subj_z_min, pam_z_min)
        overlap_max = min(subj_z_max, pam_z_max)
        overlap = max(0.0, overlap_max - overlap_min)

        diagnostics["overlap_min_mm"] = overlap_min
        diagnostics["overlap_max_mm"] = overlap_max
        diagnostics["overlap_mm"] = overlap

        if subj_range > 0:
            diagnostics["overlap_pct"] = (overlap / subj_range) * 100.0

        # Compute SI shift over overlapping portion
        # Match z values in overlap region and compute mean difference
        if overlap > 0:
            # Find overlapping z values (interpolate if needed, or use nearest)
            # For simplicity, compute mean shift from all points in overlap
            subj_overlap = [z for z in subj_z_values if overlap_min <= z <= overlap_max]
            pam_overlap = [z for z in pam_z_values if overlap_min <= z <= overlap_max]

            if subj_overlap and pam_overlap:
                # Sort both for matching
                subj_overlap_sorted = sorted(subj_overlap)
                pam_overlap_sorted = sorted(pam_overlap)

                # Compute mean shift (simple approach: mean of differences)
                # For more accuracy, could interpolate to match positions
                min_len = min(len(subj_overlap_sorted), len(pam_overlap_sorted))
                if min_len > 0:
                    # Take corresponding points (assuming similar sampling)
                    shifts = [
                        pam_overlap_sorted[i] - subj_overlap_sorted[i]
                        for i in range(min_len)
                    ]
                    mean_shift = float(np.mean(shifts))
                    diagnostics["si_shift_mm"] = mean_shift

                    # Detect shift type
                    if abs(mean_shift) < 0.1:  # Less than 0.1mm
                        diagnostics["shift_type"] = "none"
                    else:
                        # Check if shift is constant (systematic) vs varying (scaling/nonlinear)
                        shift_std = float(np.std(shifts))
                        if shift_std < abs(mean_shift) * 0.1:  # Low variation relative to mean
                            diagnostics["shift_type"] = "systematic"
                        else:
                            diagnostics["shift_type"] = "scaling_or_nonlinear"
                else:
                    diagnostics["warnings"].append("No matching points in overlap region for SI shift computation")
            else:
                diagnostics["warnings"].append("No z values in overlap region")
        else:
            diagnostics["warnings"].append("No overlap between subject and PAM50 z-ranges")
            diagnostics["shift_type"] = "no_overlap"

        # Add warnings for significant issues
        if diagnostics.get("coverage_pct") is not None and diagnostics["coverage_pct"] < 80:
            diagnostics["warnings"].append(f"PAM50 coverage is only {diagnostics['coverage_pct']:.1f}% of subject range")

        if diagnostics.get("overlap_pct") is not None and diagnostics["overlap_pct"] < 50:
            diagnostics["warnings"].append(f"Overlap is only {diagnostics['overlap_pct']:.1f}% of subject range")

        if diagnostics.get("si_shift_mm") is not None and abs(diagnostics["si_shift_mm"]) > 5.0:
            diagnostics["warnings"].append(f"Large SI shift detected: {diagnostics['si_shift_mm']:.2f}mm")

    except Exception as err:  # noqa: BLE001
        diagnostics["warnings"].append(f"Error computing SI mismatch: {err}")

    return diagnostics


def _binary_erode_2d(mask: np.ndarray) -> np.ndarray:
    """3x3 erosion without scipy; edges are treated as False."""
    if mask.ndim != 2:
        raise ValueError("mask must be 2D")
    h, w = mask.shape
    if h < 3 or w < 3:
        return np.zeros_like(mask, dtype=bool)
    eroded = np.ones_like(mask, dtype=bool)
    core = mask[1:-1, 1:-1]
    eroded[1:-1, 1:-1] = core.copy()
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            eroded[1:-1, 1:-1] &= mask[1 + dy : h - 1 + dy, 1 + dx : w - 1 + dx]
    eroded[0, :] = False
    eroded[-1, :] = False
    eroded[:, 0] = False
    eroded[:, -1] = False
    return eroded


def _mask_contour_2d(mask: np.ndarray) -> np.ndarray:
    """Return a thin contour mask from a 2D boolean mask."""
    mask = mask.astype(bool)
    eroded = _binary_erode_2d(mask)
    return mask & (~eroded)


def _draw_thick_contour(
    overlay: Image.Image,
    contour_mask: np.ndarray,
    color: tuple[int, int, int, int],
    x_offset: int = 0,
    y_offset: int = 0,
    thickness: int = 2,
    outline_color: Optional[tuple[int, int, int, int]] = (0, 0, 0, 255),
) -> None:
    """Draw a thick contour on an RGBA overlay image with optional dark outline for contrast.

    Args:
        overlay: RGBA Image to draw on
        contour_mask: 2D boolean mask of contour pixels
        color: RGBA color tuple for main border
        x_offset: X offset for drawing position
        y_offset: Y offset for drawing position
        thickness: Border thickness in pixels (default 2)
        outline_color: Optional RGBA color for outline (default black). If None, no outline.
    """
    yy, xx = np.where(contour_mask)
    if outline_color is not None:
        # Draw outline first (1px wider on all sides)
        for y, x in zip(yy.tolist(), xx.tolist()):
            for dy in range(-thickness - 1, thickness + 2):
                for dx in range(-thickness - 1, thickness + 2):
                    if dx * dx + dy * dy > (thickness + 1) ** 2:
                        continue
                    px = x_offset + x + dx
                    py = y_offset + y + dy
                    if 0 <= px < overlay.width and 0 <= py < overlay.height:
                        overlay.putpixel((px, py), outline_color)

    # Draw main border
    for y, x in zip(yy.tolist(), xx.tolist()):
        for dy in range(-thickness, thickness + 1):
            for dx in range(-thickness, thickness + 1):
                if dx * dx + dy * dy > thickness ** 2:
                    continue
                px = x_offset + x + dx
                py = y_offset + y + dy
                if 0 <= px < overlay.width and 0 <= py < overlay.height:
                    overlay.putpixel((px, py), color)


def _scale_to_rgb(slice2d: np.ndarray) -> np.ndarray:
    """Scale a 2D slice to uint8 RGB using robust percentiles."""
    vmin, vmax = np.percentile(slice2d, [1, 99])
    if vmax <= vmin:
        vmin, vmax = float(slice2d.min()), float(slice2d.max())
    if vmax <= vmin:
        vmax = vmin + 1.0
    normalized = np.clip((slice2d - vmin) / (vmax - vmin), 0, 1)
    base = (normalized * 255).astype(np.uint8)
    return np.repeat(base[..., np.newaxis], 3, axis=2)


def _resize_rgb(rgb: np.ndarray, width: int, height: int) -> np.ndarray:
    img = Image.fromarray(rgb, mode="RGB")
    img = img.resize((int(width), int(height)), resample=2)  # 2 == BILINEAR
    return np.array(img, dtype=np.uint8)


def _resize_mask(mask: np.ndarray, width: int, height: int) -> np.ndarray:
    img = Image.fromarray((mask.astype(np.uint8) * 255), mode="L")
    img = img.resize((int(width), int(height)), resample=0)  # 0 == NEAREST
    return (np.array(img, dtype=np.uint8) > 0)


def _cover_resize_and_crop_rgb(rgb: np.ndarray, width: int, height: int) -> np.ndarray:
    """Resize to cover (width,height) preserving aspect, then center-crop."""
    img = Image.fromarray(rgb, mode="RGB")
    src_w, src_h = img.size
    if src_w <= 0 or src_h <= 0:
        return np.zeros((height, width, 3), dtype=np.uint8)
    scale = max(width / src_w, height / src_h)
    new_w = int(np.ceil(src_w * scale))
    new_h = int(np.ceil(src_h * scale))
    resized = img.resize((new_w, new_h), resample=2)  # 2 == BILINEAR
    left = max(0, (new_w - width) // 2)
    top = max(0, (new_h - height) // 2)
    cropped = resized.crop((left, top, left + width, top + height))
    return np.array(cropped, dtype=np.uint8)


def _cover_resize_and_crop_mask(mask: np.ndarray, width: int, height: int) -> np.ndarray:
    """Resize to cover (width,height) preserving aspect, then center-crop (nearest)."""
    img = Image.fromarray((mask.astype(np.uint8) * 255), mode="L")
    src_w, src_h = img.size
    if src_w <= 0 or src_h <= 0:
        return np.zeros((height, width), dtype=bool)
    scale = max(width / src_w, height / src_h)
    new_w = int(np.ceil(src_w * scale))
    new_h = int(np.ceil(src_h * scale))
    resized = img.resize((new_w, new_h), resample=0)  # 0 == NEAREST
    left = max(0, (new_w - width) // 2)
    top = max(0, (new_h - height) // 2)
    cropped = resized.crop((left, top, left + width, top + height))
    return (np.array(cropped, dtype=np.uint8) > 0)


def _fit_resize_and_paste_rgb(rgb: np.ndarray, width: int, height: int) -> np.ndarray:
    """Resize to fit within (width,height) preserving aspect, then paste on black background."""
    img = Image.fromarray(rgb, mode="RGB")
    src_w, src_h = img.size
    if src_w <= 0 or src_h <= 0:
        return np.zeros((height, width, 3), dtype=np.uint8)
    # Scale to fit (use min instead of max)
    scale = min(width / src_w, height / src_h)
    new_w = int(np.ceil(src_w * scale))
    new_h = int(np.ceil(src_h * scale))
    resized = img.resize((new_w, new_h), resample=2)  # 2 == BILINEAR
    # Paste on black background, centered
    canvas = Image.new("RGB", (width, height), (0, 0, 0))  # type: ignore[arg-type]
    left = (width - new_w) // 2
    top = (height - new_h) // 2
    canvas.paste(resized, (left, top))
    return np.array(canvas, dtype=np.uint8)


def _fit_resize_and_paste_mask(mask: np.ndarray, width: int, height: int) -> np.ndarray:
    """Resize to fit within (width,height) preserving aspect, then paste on black background."""
    img = Image.fromarray((mask.astype(np.uint8) * 255), mode="L")
    src_w, src_h = img.size
    if src_w <= 0 or src_h <= 0:
        return np.zeros((height, width), dtype=bool)
    # Scale to fit (use min instead of max)
    scale = min(width / src_w, height / src_h)
    new_w = int(np.ceil(src_w * scale))
    new_h = int(np.ceil(src_h * scale))
    resized = img.resize((new_w, new_h), resample=0)  # 0 == NEAREST
    # Paste on black background, centered
    canvas = Image.new("L", (width, height), 0)  # type: ignore[arg-type]
    left = (width - new_w) // 2
    top = (height - new_h) // 2
    canvas.paste(resized, (left, top))
    return (np.array(canvas, dtype=np.uint8) > 0)


def _render_pam50_reg_overlay_gif(
    qc_root: Path,
    subject_image: Optional[Path],
    pam50_in_s2: Optional[Path],
    subject_cordmask: Optional[Path],
    warp_template2anat: Optional[Path],
    subject_label: Optional[str],
    session_label: Optional[str],
    vertebral_labels_path: Optional[Path] = None,
    canvas_size: tuple[int, int] = (2400, 1200),
    mosaic_cols: int = 6,
    mosaic_rows: int = 4,
    frame_delay_ms: int = 900,
    crossfade_steps: int = 10,
) -> Optional[Path]:
    """Render flicker/crossfade GIF: subject underlay vs PAM50-in-S2 underlay, with identical cord contours."""
    if (
        subject_image is None
        or pam50_in_s2 is None
        or subject_cordmask is None
        or warp_template2anat is None
    ):
        return None
    qc_root.mkdir(parents=True, exist_ok=True)

    try:
        subj_img = nib.as_closest_canonical(nib.load(subject_image))
        pam_img = nib.as_closest_canonical(nib.load(pam50_in_s2))
        seg_img = nib.as_closest_canonical(nib.load(subject_cordmask))
    except Exception:
        return None

    subj = subj_img.get_fdata()
    pam = pam_img.get_fdata()
    seg = seg_img.get_fdata()
    if subj.ndim > 3:
        subj = subj[..., 0]
    if pam.ndim > 3:
        pam = pam[..., 0]
    if seg.ndim > 3:
        seg = seg[..., 0]

    if subj.shape != seg.shape or pam.shape != subj.shape:
        return None

    subj_mask = seg > 0
    if not subj_mask.any():
        return None

    # Filter out scattered cord mask fragments - keep only largest connected component
    subj_mask = _largest_connected_component(subj_mask)
    if not subj_mask.any():
        return None

    pam50_dir = _resolve_pam50_dir()
    if pam50_dir is None:
        return None
    pam50_cord = _find_pam50_cord_mask(pam50_dir)
    if pam50_cord is None:
        return None

    # Warp PAM50 cord mask to subject space using SCT-native method
    # sct_warp_template properly handles template objects in subject grid
    warp_qc_dir = qc_root / "warp_template"
    warp_qc_dir.mkdir(parents=True, exist_ok=True)

    # Use sct_warp_template to warp template objects (cord mask, labels, etc.)
    # The -a 0 flag applies the warp without additional alignment
    ok, _ = _run_command(
        [
            "sct_warp_template",
            "-d",
            str(subject_image),
            "-w",
            str(warp_template2anat),
            "-a",
            "0",
            "-qc",
            str(warp_qc_dir),
        ]
    )
    if not ok:
        return None

    # sct_warp_template outputs warped template objects
    # Look for the warped cord mask (typically named PAM50_cord.nii.gz in output)
    # Check common output locations
    pam_cord_in_s2 = None
    for candidate_name in ("PAM50_cord.nii.gz", "PAM50_cordseg.nii.gz", "template_cord.nii.gz"):
        candidate = warp_qc_dir / candidate_name
        if candidate.exists():
            pam_cord_in_s2 = candidate
            break

    # If not found in qc dir, check if sct_warp_template outputs to same dir as destination
    # Some SCT versions output to the directory containing the warp file
    if pam_cord_in_s2 is None or not pam_cord_in_s2.exists():
        warp_dir = warp_template2anat.parent
        for candidate_name in ("PAM50_cord.nii.gz", "PAM50_cordseg.nii.gz", "template_cord.nii.gz"):
            candidate = warp_dir / candidate_name
            if candidate.exists():
                pam_cord_in_s2 = candidate
                break

    # Fallback: if sct_warp_template doesn't output cord mask directly,
    # we can still use sct_apply_transfo as backup (but log a warning)
    if pam_cord_in_s2 is None or not pam_cord_in_s2.exists():
        # Fallback to sct_apply_transfo
        pam_cord_in_s2 = qc_root / "pam50_cord_in_s2.nii.gz"
        ok, _ = _run_command(
            [
                "sct_apply_transfo",
                "-i",
                str(pam50_cord),
                "-d",
                str(subject_image),
                "-w",
                str(warp_template2anat),
                "-o",
                str(pam_cord_in_s2),
                "-x",
                "nn",
            ]
        )
        if not ok or not pam_cord_in_s2.exists():
            return None
    try:
        pam_cord_img = nib.as_closest_canonical(nib.load(pam_cord_in_s2))
    except Exception:
        return None
    pam_cord = pam_cord_img.get_fdata()
    if pam_cord.ndim > 3:
        pam_cord = pam_cord[..., 0]
    if pam_cord.shape != subj.shape:
        return None
    pam_mask = pam_cord > 0

    # Extract centerlines for SI mismatch diagnostics (in physical space along cord axis)
    # This is more accurate than assuming k index = z (works for oblique acquisitions)
    # Note: Diagnostics are non-blocking - if they fail, rendering continues
    diagnostics_dir = qc_root / "si_diagnostics"
    diagnostics_dir.mkdir(parents=True, exist_ok=True)

    # Skip orientation check for speed - assume images are already properly oriented from pipeline
    # Extract centerlines directly (sct_get_centerline works with any orientation)
    try:
        subj_centerline_csv = _extract_centerline_csv(subject_cordmask, diagnostics_dir / "subj_centerline")
        pam_centerline_csv = _extract_centerline_csv(pam_cord_in_s2, diagnostics_dir / "pam_centerline")

        if subj_centerline_csv and pam_centerline_csv:
            # Compute SI mismatch diagnostics
            si_diagnostics = _compute_si_mismatch_from_centerlines(subj_centerline_csv, pam_centerline_csv)

            # Save diagnostics to JSON (non-blocking)
            diagnostics_json = diagnostics_dir / "si_mismatch_diagnostics.json"
            try:
                _write_json(diagnostics_json, si_diagnostics)
            except Exception:  # noqa: BLE001
                pass  # Non-fatal: continue rendering even if diagnostics save fails
    except Exception:  # noqa: BLE001
        # Diagnostics failed - continue rendering without them
        pass

    # Z anchoring in mm based on subject_image affine.
    # Note: This assumes k index = z, which may break for oblique acquisitions.
    # The centerline-based diagnostics above provide a more accurate check in physical space.
    affine = subj_img.affine
    z_mm = np.array([float((affine @ np.array([0.0, 0.0, float(k), 1.0]))[2]) for k in range(subj.shape[2])])

    # Determine z-range: prefer vertebral labels (C1 top to last vertebral bottom), fallback to cord mask bbox.
    z_slices = np.where(subj_mask.any(axis=(0, 1)))[0]
    if z_slices.size == 0:
        return None
    z_min_k = int(z_slices.min())
    z_max_k = int(z_slices.max())

    if vertebral_labels_path is not None and vertebral_labels_path.exists():
        try:
            vert_img = nib.as_closest_canonical(nib.load(vertebral_labels_path))
            vert_data = vert_img.get_fdata()
            if vert_data.ndim > 3:
                vert_data = vert_data[..., 0]
            if vert_data.shape == subj.shape:
                # Find C1 (label==1) - use topmost z-slice where C1 exists
                # Round to nearest integer to handle float labels
                vert_int = np.round(vert_data).astype(int)
                c1_mask = vert_int == 1
                if c1_mask.any():
                    # Get z-indices where C1 exists (axis 2 is z)
                    c1_z_indices = np.where(c1_mask.any(axis=(0, 1)))[0]
                    if c1_z_indices.size > 0:
                        z_c1_top = int(c1_z_indices.min())
                    else:
                        z_c1_top = z_min_k
                else:
                    z_c1_top = z_min_k

                # Find highest label - use bottommost z-slice where any label exists
                non_zero = vert_int > 0
                if non_zero.any():
                    all_labeled_slices = np.where(non_zero.any(axis=(0, 1)))[0]
                    if all_labeled_slices.size > 0:
                        z_last_vertebral_bottom = int(all_labeled_slices.max())
                    else:
                        z_last_vertebral_bottom = z_max_k
                else:
                    z_last_vertebral_bottom = z_max_k

                # Apply padding (10 slices above C1, 10 below last vertebral)
                pad = 10
                z_min_k = max(0, z_c1_top - pad)
                z_max_k = min(subj.shape[2] - 1, z_last_vertebral_bottom + pad)
        except Exception:
            # Fallback to cord mask bbox if vertebral labels fail to load
            pass

    z_min_mm = float(z_mm[z_min_k])
    z_max_mm = float(z_mm[z_max_k])
    if z_max_mm < z_min_mm:
        z_min_mm, z_max_mm = z_max_mm, z_min_mm

    n_tiles = int(mosaic_cols * mosaic_rows)
    targets_mm = np.linspace(z_min_mm, z_max_mm, num=n_tiles)
    z_indices_all = [int(np.argmin(np.abs(z_mm - t))) for t in targets_mm]

    # Pre-filter z_indices to only include slices where both masks have content
    z_indices = []
    for k in z_indices_all:
        subj_has_content = subj_mask[:, :, k].any()
        pam_has_content = pam_mask[:, :, k].any()
        if subj_has_content and pam_has_content:
            z_indices.append(k)

    canvas_w, canvas_h = canvas_size
    left_w = int(canvas_w * 0.2)  # 20% for sagittal
    right_w = canvas_w - left_w   # 80% for axial tiles
    tile_w = right_w // mosaic_cols
    tile_h = canvas_h // mosaic_rows

    # Sagittal slice index based on median x of the cord.
    coords = np.argwhere(subj_mask)
    x_index = int(np.median(coords[:, 0]))
    x_index = max(0, min(x_index, subj.shape[0] - 1))

    # Crop sagittal to cord mask z-range (top to bottom), then fit-resize to left panel
    # Find z-range where cord mask exists
    proj_yz = subj_mask.any(axis=0)  # (Y, Z)
    proj_disp = np.flipud(proj_yz.T)  # (Z, Y) for display
    disp_coords = np.argwhere(proj_disp)
    if disp_coords.size == 0:
        return None
    z0_cord, _ = disp_coords.min(axis=0)
    z1_cord, _ = disp_coords.max(axis=0)
    # Add small padding
    pad = 5
    z0_cord = max(0, int(z0_cord) - pad)
    z1_cord = min(proj_disp.shape[0] - 1, int(z1_cord) + pad)

    # For Y dimension, use full extent with 30% additional padding on each side
    _, y0_cord = disp_coords.min(axis=0)
    _, y1_cord = disp_coords.max(axis=0)
    # Calculate Y-range and add 30% as padding on each side
    y_range = y1_cord - y0_cord
    y_pad_extra = int(y_range * 0.3)  # 30% of range on each side
    y0_cord = max(0, int(y0_cord) - pad - y_pad_extra)
    y1_cord = min(proj_disp.shape[1] - 1, int(y1_cord) + pad + y_pad_extra)

    def _render_underlay_canvas(underlay_3d: np.ndarray) -> Optional[Image.Image]:
        # Left sagittal: crop to cord mask z-range
        sag_slice = underlay_3d[x_index, :, :]
        sag_disp = np.flipud(sag_slice.T)  # (Z, Y)

        # Crop to cord mask extent
        sag_disp = sag_disp[z0_cord : z1_cord + 1, y0_cord : y1_cord + 1]

        sag_rgb = _scale_to_rgb(sag_disp)
        # Fit-resize sagittal to show full extent within left half.
        sag_fit = _fit_resize_and_paste_rgb(sag_rgb, left_w, canvas_h)
        sag_panel = Image.fromarray(sag_fit, mode="RGB")

        # Right mosaic: crop each axial tile to cord mask, rotate 90 degrees, then fit-resize
        mosaic = Image.new("RGB", (right_w, canvas_h), (0, 0, 0))  # type: ignore[arg-type]
        for idx, k in enumerate(z_indices):
            # Check if both masks have content (safety check, should already be filtered)
            subj_has_content = subj_mask[:, :, k].any()
            pam_has_content = pam_mask[:, :, k].any()
            if not (subj_has_content and pam_has_content):
                continue  # Skip this tile

            r = idx // mosaic_cols
            c = idx % mosaic_cols
            x0 = c * tile_w
            y0t = r * tile_h

            # Get axial slice and mask
            slice2d = underlay_3d[:, :, k]  # (X, Y)
            mask_slice = subj_mask[:, :, k]  # (X, Y)

            # Find cord mask bounding box
            coords = np.argwhere(mask_slice)
            if coords.size > 0:
                x_min, y_min = coords.min(axis=0)
                x_max, y_max = coords.max(axis=0)
                # Zoom out to show 1.5x area: calculate padding as 25% of bbox size (0.25 on each side = 1.5x total)
                bbox_w = x_max - x_min
                bbox_h = y_max - y_min
                pad = max(10, int(max(bbox_w, bbox_h) * 0.25))  # 25% of largest dimension, min 10px
                x_min = max(0, int(x_min) - pad)
                y_min = max(0, int(y_min) - pad)
                x_max = min(slice2d.shape[0] - 1, int(x_max) + pad)
                y_max = min(slice2d.shape[1] - 1, int(y_max) + pad)
                # Crop to cord bbox
                slice_cropped = slice2d[x_min : x_max + 1, y_min : y_max + 1]
            else:
                # Fallback to full slice if no mask
                slice_cropped = slice2d

            # Rotate 90 degrees clockwise (k=1 means rotate 90 degrees counterclockwise, so we use k=-1 for clockwise)
            slice_rotated = np.rot90(slice_cropped, k=-1)

            # Scale to RGB and fit-resize to tile
            rgb = _scale_to_rgb(slice_rotated)
            rgb_fit = _fit_resize_and_paste_rgb(rgb, tile_w, tile_h)
            tile_img = Image.fromarray(rgb_fit, mode="RGB")
            mosaic.paste(tile_img, (x0, y0t))

        # Compose full canvas
        canvas = Image.new("RGB", (canvas_w, canvas_h), (0, 0, 0))  # type: ignore[arg-type]
        canvas.paste(sag_panel, (0, 0))
        canvas.paste(mosaic, (left_w, 0))
        return canvas

    subj_base = _render_underlay_canvas(subj)
    pam_base = _render_underlay_canvas(pam)
    if subj_base is None or pam_base is None:
        return None

    # Precompute a constant overlay layer (contours + labels + title/legend/meta).
    overlay = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))  # type: ignore[arg-type]
    draw = ImageDraw.Draw(overlay)

    # Sagittal contours: compute from cord mask cropped sagittal masks, then fit-resize to left panel.
    subj_sag = np.flipud(subj_mask[x_index, :, :].T)  # (Z, Y)
    pam_sag = np.flipud(pam_mask[x_index, :, :].T)  # (Z, Y)
    # Crop to cord mask extent (same as underlay)
    subj_sag = subj_sag[z0_cord : z1_cord + 1, y0_cord : y1_cord + 1]
    pam_sag = pam_sag[z0_cord : z1_cord + 1, y0_cord : y1_cord + 1]
    subj_sag_r = _fit_resize_and_paste_mask(subj_sag, left_w, canvas_h)
    pam_sag_r = _fit_resize_and_paste_mask(pam_sag, left_w, canvas_h)
    subj_edge = _mask_contour_2d(subj_sag_r)
    pam_edge = _mask_contour_2d(pam_sag_r)
    # Draw thick borders with dark outline for better visibility
    # Subject cord: red with dark outline
    _draw_thick_contour(overlay, subj_edge, (255, 0, 0, 255), thickness=2, outline_color=(0, 0, 0, 255))
    # PAM50 cord: dark blue with dark outline for better contrast on whitish backgrounds
    _draw_thick_contour(overlay, pam_edge, (0, 100, 200, 255), thickness=2, outline_color=(0, 0, 0, 255))

    # Mosaic contours + per-tile z label: crop to cord, rotate, then fit-resize (same as underlay).
    for idx, k in enumerate(z_indices):
        # Check if both masks have content (safety check, should already be filtered)
        subj_has_content = subj_mask[:, :, k].any()
        pam_has_content = pam_mask[:, :, k].any()
        if not (subj_has_content and pam_has_content):
            continue  # Skip this tile

        r = idx // mosaic_cols
        c = idx % mosaic_cols
        x0 = left_w + c * tile_w
        y0t = r * tile_h

        # Get masks for this slice
        subj_m_slice = subj_mask[:, :, k]  # (X, Y)
        pam_m_slice = pam_mask[:, :, k]  # (X, Y)

        # Find cord mask bounding box (use subject mask)
        coords = np.argwhere(subj_m_slice)
        if coords.size > 0:
            x_min, y_min = coords.min(axis=0)
            x_max, y_max = coords.max(axis=0)
            # Zoom out to show 1.5x area: calculate padding as 25% of bbox size (same as underlay)
            bbox_w = x_max - x_min
            bbox_h = y_max - y_min
            pad = max(10, int(max(bbox_w, bbox_h) * 0.25))  # 25% of largest dimension, min 10px
            x_min = max(0, int(x_min) - pad)
            y_min = max(0, int(y_min) - pad)
            x_max = min(subj_m_slice.shape[0] - 1, int(x_max) + pad)
            y_max = min(subj_m_slice.shape[1] - 1, int(y_max) + pad)
            # Crop to cord bbox
            subj_m_cropped = subj_m_slice[x_min : x_max + 1, y_min : y_max + 1]
            pam_m_cropped = pam_m_slice[x_min : x_max + 1, y_min : y_max + 1]
        else:
            # Fallback to full mask if no cord
            subj_m_cropped = subj_m_slice
            pam_m_cropped = pam_m_slice

        # Rotate 90 degrees clockwise (same as underlay, k=-1 for clockwise)
        subj_m_rotated = np.rot90(subj_m_cropped, k=-1)
        pam_m_rotated = np.rot90(pam_m_cropped, k=-1)

        # Fit-resize to tile size
        subj_m = _fit_resize_and_paste_mask(subj_m_rotated, tile_w, tile_h)
        pam_m = _fit_resize_and_paste_mask(pam_m_rotated, tile_w, tile_h)

        # Compute contours and draw with thick borders and dark outline
        subj_edge_t = _mask_contour_2d(subj_m)
        pam_edge_t = _mask_contour_2d(pam_m)
        # Subject cord: red with dark outline
        _draw_thick_contour(overlay, subj_edge_t, (255, 0, 0, 255), x_offset=x0, y_offset=y0t, thickness=2, outline_color=(0, 0, 0, 255))
        # PAM50 cord: dark blue with dark outline for better contrast
        _draw_thick_contour(overlay, pam_edge_t, (0, 100, 200, 255), x_offset=x0, y_offset=y0t, thickness=2, outline_color=(0, 0, 0, 255))
        z_label = float(z_mm[k])
        draw.text((x0 + 5, y0t + 5), f"z={z_label:.0f}mm", fill=(230, 230, 230, 255))

    # Title + legend + meta
    draw.text((10, 10), "S2 PAM50 registration QC", fill=(255, 255, 255, 255))
    legend_y = 40
    draw.text((10, legend_y), "subject cord", fill=(255, 0, 0, 255))
    draw.text((10, legend_y + 18), "PAM50 cord (warped to S2)", fill=(0, 100, 200, 255))
    meta = f"sub={subject_label or 'unknown'} ses={session_label or 'none'}  z=[{z_min_mm:.0f},{z_max_mm:.0f}]mm"
    draw.text((10, canvas_h - 20), meta, fill=(180, 180, 180, 255))

    # Crossfade: generate intermediate blended underlays and composite the fixed overlay.
    steps = max(1, int(crossfade_steps))
    alphas_fwd = np.linspace(0.0, 1.0, num=steps + 1)
    alphas_bwd = np.linspace(1.0, 0.0, num=steps + 1)[1:]
    alphas = [float(a) for a in np.concatenate([alphas_fwd, alphas_bwd])]

    frames_dir = qc_root / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    frame_paths: list[Path] = []
    for i, a in enumerate(alphas):
        base = Image.blend(subj_base, pam_base, a).convert("RGBA")
        composed = Image.alpha_composite(base, overlay)
        p = frames_dir / f"frame_{i:03d}.png"
        composed.convert("RGB").save(p)
        frame_paths.append(p)

    if not frame_paths:
        return None

    # Use ImageMagick for deterministic GIF assembly.
    # frame_delay_ms applies to a full subject->pam50 transition; the loop is ping-pong, so total ~2*frame_delay_ms.
    total_ms = int(max(1, frame_delay_ms) * 2)
    delay_cs = max(1, int(round((total_ms / max(1, len(frame_paths))) / 10.0)))  # centiseconds
    gif_path = qc_root / "S2_pam50_reg_overlay.gif"
    ok, _ = _run_command(
        [
            "convert",
            "-delay",
            str(delay_cs),
            "-loop",
            "0",
            *[str(p) for p in frame_paths],
            str(gif_path),
        ]
    )
    return gif_path if ok else None


def _find_qc_overlay(qc_root: Path) -> Optional[Path]:
    matches = sorted(qc_root.rglob("overlay_img.png"))
    return matches[-1] if matches else None


def _find_qc_background(qc_root: Path) -> Optional[Path]:
    matches = sorted(qc_root.rglob("background_img.png"))
    return matches[-1] if matches else None


def _copy_reportlet(source: Optional[Path], dest: Path, out_root: Path) -> Optional[str]:
    if source is None:
        return None
    _copy_file(source, dest)
    return _relpath(dest, out_root)


def _render_mid_slice_overlay_png(
    qc_root: Path,
    image: Optional[Path],
    seg: Optional[Path],
    axis: int,
) -> Optional[Path]:
    if image is None or seg is None:
        return None
    qc_root.mkdir(parents=True, exist_ok=True)
    try:
        img = cast(Any, nib.load(image))
        seg_img = cast(Any, nib.load(seg))
    except Exception:
        return None
    img_data = img.get_fdata()
    seg_data = seg_img.get_fdata()
    if img_data.ndim > 3:
        img_data = img_data[..., 0]
    if seg_data.ndim > 3:
        seg_data = seg_data[..., 0]
    if img_data.shape != seg_data.shape:
        return None
    index = img_data.shape[axis] // 2
    img_slice = np.take(img_data, index, axis=axis)
    seg_slice = np.take(seg_data, index, axis=axis) > 0
    if img_slice.ndim != 2:
        return None

    vmin, vmax = np.percentile(img_slice, [1, 99])
    if vmax <= vmin:
        vmin, vmax = float(img_slice.min()), float(img_slice.max())
    if vmax <= vmin:
        vmax = vmin + 1.0

    normalized = np.clip((img_slice - vmin) / (vmax - vmin), 0, 1)
    base = (normalized * 255).astype(np.uint8)
    base_rgb = np.repeat(base[..., np.newaxis], 3, axis=2)
    overlay = base_rgb.copy()
    mask = seg_slice.astype(bool)
    overlay[mask] = (overlay[mask] * 0.4 + np.array([255, 0, 0]) * 0.6).astype(np.uint8)

    output = qc_root / "overlay.png"
    ppm_path = qc_root / "overlay.ppm"
    _write_ppm(ppm_path, overlay)
    ok, _ = _run_command(
        [
            "convert",
            str(ppm_path),
            "-filter",
            "Lanczos",
            "-resize",
            "1200x",
            str(output),
        ]
    )
    if ok:
        return output
    return None


def _render_sagittal_mask_panel_from_ref(
    qc_root: Path,
    image: Optional[Path],
    mask: np.ndarray,
    ref_mask: np.ndarray,
    color: tuple[int, int, int] = (255, 0, 0),
) -> Optional[Path]:
    """Render a sagittal overlay panel using ref_mask to choose the slice and mask for overlay."""
    if image is None:
        return None
    qc_root.mkdir(parents=True, exist_ok=True)
    try:
        img = nib.as_closest_canonical(nib.load(image))
    except Exception:
        return None
    img_data = img.get_fdata()
    if img_data.ndim > 3:
        img_data = img_data[..., 0]
    if img_data.shape != mask.shape or img_data.shape != ref_mask.shape:
        return None

    coords = np.argwhere(ref_mask)
    if coords.size == 0:
        return None
    x_index = int(np.median(coords[:, 0]))
    x_index = max(0, min(x_index, img_data.shape[0] - 1))
    img_slice = img_data[x_index, :, :]
    mask_proj = mask.any(axis=0)
    if img_slice.ndim != 2:
        return None

    # Display with superior at the top: z-axis becomes vertical after transpose.
    img_slice = np.flipud(img_slice.T)
    mask_proj = np.flipud(mask_proj.T)

    vmin, vmax = np.percentile(img_slice, [1, 99])
    if vmax <= vmin:
        vmin, vmax = float(img_slice.min()), float(img_slice.max())
    if vmax <= vmin:
        vmax = vmin + 1.0

    normalized = np.clip((img_slice - vmin) / (vmax - vmin), 0, 1)
    base = (normalized * 255).astype(np.uint8)
    base_rgb = np.repeat(base[..., np.newaxis], 3, axis=2)
    overlay = base_rgb.copy()
    c = np.array(color, dtype=np.uint8)
    overlay[mask_proj] = (overlay[mask_proj] * 0.4 + c * 0.6).astype(np.uint8)

    output = qc_root / "overlay.png"
    ppm_path = qc_root / "overlay.ppm"
    _write_ppm(ppm_path, overlay)
    ok, _ = _run_command(
        [
            "convert",
            str(ppm_path),
            "-filter",
            "Lanczos",
            "-resize",
            "1200x",
            str(output),
        ]
    )
    return output if ok else None


def _render_centerline_montage(
    qc_root: Path,
    image: Optional[Path],
    centerline_sagittal: Optional[Path],
    centerline_axial: Optional[Path],
    cordmask: Optional[Path],
    tile_size: int = 200,
    max_tiles: Optional[int] = None,
) -> Optional[Path]:
    if image is None or centerline_sagittal is None or centerline_axial is None:
        return None
    qc_root.mkdir(parents=True, exist_ok=True)
    try:
        img = nib.as_closest_canonical(nib.load(image))
        seg_sag_img = nib.as_closest_canonical(nib.load(centerline_sagittal))
        seg_ax_img = nib.as_closest_canonical(nib.load(centerline_axial))
        mask_img = nib.as_closest_canonical(nib.load(cordmask)) if cordmask else None
    except Exception:
        return None
    img_data = img.get_fdata()
    seg_sag = seg_sag_img.get_fdata()
    seg_ax = seg_ax_img.get_fdata()
    mask_data = mask_img.get_fdata() if mask_img else None
    if img_data.ndim > 3:
        img_data = img_data[..., 0]
    if seg_sag.ndim > 3:
        seg_sag = seg_sag[..., 0]
    if seg_ax.ndim > 3:
        seg_ax = seg_ax[..., 0]
    if img_data.shape != seg_sag.shape or img_data.shape != seg_ax.shape:
        return None
    if mask_data is not None:
        if mask_data.ndim > 3:
            mask_data = mask_data[..., 0]
        if mask_data.shape != img_data.shape:
            mask_data = None

    seg_sag = _largest_connected_component(seg_sag > 0)
    seg_ax = _largest_connected_component(seg_ax > 0)
    seg_mask = seg_ax
    coords = np.argwhere(seg_mask)
    if coords.size == 0:
        return None
    cord_mask = (mask_data > 0) if mask_data is not None else seg_mask

    z_dim = img_data.shape[2]
    y_dim = img_data.shape[1]
    sagittal_height = int(round(z_dim * 1200 / max(y_dim, 1)))
    sagittal_height = max(sagittal_height, tile_size)
    desired_tiles = min(len(np.unique(coords[:, 2])), 12)
    if desired_tiles > 0:
        tile_size = min(tile_size, max(120, sagittal_height // desired_tiles))
    max_tiles_dynamic = max(8, sagittal_height // tile_size)
    tile_cap = min(max_tiles_dynamic, max_tiles) if max_tiles is not None else max_tiles_dynamic

    slice_infos = []
    for z in np.unique(coords[:, 2]):
        slice_mask = seg_mask[:, :, z]
        if not slice_mask.any():
            continue
        indices = np.argwhere(slice_mask)
        center = indices.mean(axis=0)
        world = img.affine @ np.array([center[0], center[1], float(z), 1.0])
        slice_infos.append(
            {
                "z": int(z),
                "center": center,
                "world_z": float(world[2]),
            }
        )
    if not slice_infos:
        return None

    scale = sagittal_height / max(z_dim, 1)
    min_gap = max(6, tile_size // 10)
    slice_infos.sort(key=lambda item: item["z"], reverse=True)
    min_sep_z = max(1, int(np.ceil((tile_size + min_gap) / max(scale, 1e-6))))
    selected = []
    last_z = None
    for info in slice_infos:
        if last_z is None or (last_z - info["z"]) >= min_sep_z:
            selected.append(info)
            last_z = info["z"]
        if len(selected) >= tile_cap:
            break
    if not selected:
        return None

    tiles_dir = qc_root / "tiles"
    tiles_dir.mkdir(parents=True, exist_ok=True)
    tile_items: list[tuple[Path, int]] = []
    for info in selected:
        z = info["z"]
        slice_data = img_data[:, :, z]
        seg_slice = seg_mask[:, :, z]
        cord_slice = cord_mask[:, :, z] if cord_mask is not None else seg_slice
        if slice_data.ndim != 2:
            continue
        tile = _render_centerline_tile(
            out_dir=tiles_dir,
            slice_data=slice_data,
            centerline_slice=seg_slice,
            cord_slice=cord_slice,
            world_z=info["world_z"],
            z_index=z,
            tile_size=tile_size,
        )
        if tile is not None:
            tile_items.append((tile, z))
    if not tile_items:
        return None

    column = qc_root / "axial_column.png"
    ok, _ = _run_command(["convert", "-size", f"{tile_size}x{sagittal_height}", "xc:#000000", str(column)])
    if not ok:
        return None
    tile_items.sort(key=lambda item: item[1], reverse=True)
    if len(tile_items) > 1:
        total_height = len(tile_items) * tile_size + (len(tile_items) - 1) * min_gap
        if total_height > sagittal_height:
            tile_size = max(120, (sagittal_height - (len(tile_items) - 1) * min_gap) // len(tile_items))
            total_height = len(tile_items) * tile_size + (len(tile_items) - 1) * min_gap

    max_y = max(0, sagittal_height - tile_size)
    targets = []
    for tile_path, z_index in tile_items:
        row = (z_dim - 1 - z_index) * scale
        target = int(round(row - tile_size / 2))
        target = max(0, min(target, max_y))
        targets.append((target, tile_path, z_index))

    targets.sort(key=lambda item: item[0])
    positions = [t[0] for t in targets]
    for i in range(1, len(positions)):
        positions[i] = max(positions[i], positions[i - 1] + tile_size + min_gap)
    if positions:
        positions[-1] = min(positions[-1], max_y)
        for i in range(len(positions) - 2, -1, -1):
            positions[i] = min(positions[i], positions[i + 1] - tile_size - min_gap)
            positions[i] = max(0, positions[i])
        for i in range(1, len(positions)):
            positions[i] = max(positions[i], positions[i - 1] + tile_size + min_gap)

    for (target, tile_path, z_index), y_offset in zip(targets, positions):
        ok, _ = _run_command(
            [
                "convert",
                str(column),
                str(tile_path),
                "-geometry",
                f"+0+{y_offset}",
                "-composite",
                str(column),
            ]
        )
        if not ok:
            return None
        y_offset += tile_size + min_gap

    sagittal = _render_sagittal_centerline_panel(
        qc_root=qc_root / "sagittal",
        image=image,
        centerline=centerline_sagittal,
    )
    if sagittal is None:
        return None

    column_height = sagittal_height
    sagittal_resized = qc_root / "sagittal_resized.png"
    ok, _ = _run_command(
        [
            "convert",
            str(sagittal),
            "-filter",
            "Lanczos",
            "-resize",
            f"x{column_height}",
            str(sagittal_resized),
        ]
    )
    if not ok:
        return None

    montage = qc_root / "centerline_montage.png"
    ok, _ = _run_command(
        [
            "convert",
            str(sagittal_resized),
            str(column),
            "+append",
            str(montage),
        ]
    )
    return montage if ok else None


def _render_centerline_tile(
    out_dir: Path,
    slice_data: np.ndarray,
    centerline_slice: np.ndarray,
    cord_slice: np.ndarray,
    world_z: float,
    z_index: int,
    tile_size: int,
) -> Optional[Path]:
    if slice_data.ndim != 2:
        return None
    if centerline_slice.ndim != 2 or cord_slice.ndim != 2:
        return None

    centerline_coords = np.argwhere(centerline_slice > 0)
    if centerline_coords.size == 0:
        return None

    cord_coords = np.argwhere(cord_slice > 0)
    if cord_coords.size == 0:
        cord_coords = centerline_coords
    min_xy = cord_coords.min(axis=0)
    max_xy = cord_coords.max(axis=0)
    margin = 6
    min_xy = np.maximum(min_xy - margin, 0)
    max_xy = np.minimum(max_xy + margin, np.array(slice_data.shape) - 1)
    size_xy = max_xy - min_xy + 1
    min_size = 32
    target_size = int(max(size_xy.max(), min_size))
    half = target_size // 2
    center_xy = np.round((min_xy + max_xy) / 2).astype(int)
    x0 = max(center_xy[0] - half, 0)
    y0 = max(center_xy[1] - half, 0)
    x1 = min(x0 + target_size, slice_data.shape[0])
    y1 = min(y0 + target_size, slice_data.shape[1])
    x0 = max(x1 - target_size, 0)
    y0 = max(y1 - target_size, 0)

    slice_data = slice_data[x0:x1, y0:y1]
    centerline_slice = centerline_slice[x0:x1, y0:y1]
    # Axial view in canonical RAS: anterior up.
    slice_data = np.flipud(slice_data.T)
    centerline_slice = np.flipud(centerline_slice.T)
    centerline_coords_t = np.argwhere(centerline_slice > 0)
    if centerline_coords_t.size == 0:
        return None
    center = centerline_coords_t.mean(axis=0)
    vmin, vmax = np.percentile(slice_data, [1, 99])
    if vmax <= vmin:
        vmin, vmax = float(slice_data.min()), float(slice_data.max())
    if vmax <= vmin:
        vmax = vmin + 1.0
    normalized = np.clip((slice_data - vmin) / (vmax - vmin), 0, 1)
    base = (normalized * 255).astype(np.uint8)
    rgb = np.repeat(base[..., np.newaxis], 3, axis=2)

    row = int(round(center[0]))
    col = int(round(center[1]))
    radius = 2
    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            rr = row + dx
            cc = col + dy
            if rr < 0 or rr >= rgb.shape[0] or cc < 0 or cc >= rgb.shape[1]:
                continue
            if dx * dx + dy * dy > radius * radius:
                continue
            rgb[rr, cc] = np.array([255, 0, 0], dtype=np.uint8)

    ppm_path = out_dir / f"axial_{z_index:04d}.ppm"
    png_path = out_dir / f"axial_{z_index:04d}.png"
    _write_ppm(ppm_path, rgb)
    label = f"z={world_z:.1f}mm"
    ok, _ = _run_command(
        [
            "convert",
            str(ppm_path),
            "-filter",
            "Lanczos",
            "-resize",
            f"{tile_size}x{tile_size}",
            "-gravity",
            "north",
            "-pointsize",
            "18",
            "-fill",
            "#ff3333",
            "-annotate",
            "0",
            label,
            str(png_path),
        ]
    )
    return png_path if ok else None


def _render_cordmask_montage(
    qc_root: Path,
    image: Optional[Path],
    cordmask: Optional[Path],
    tile_size: int = 200,
    max_tiles: Optional[int] = None,
) -> Optional[Path]:
    if image is None or cordmask is None:
        return None
    qc_root.mkdir(parents=True, exist_ok=True)
    try:
        img = nib.as_closest_canonical(nib.load(image))
        mask_img = nib.as_closest_canonical(nib.load(cordmask))
    except Exception:
        return None
    img_data = img.get_fdata()
    mask_data = mask_img.get_fdata()
    if img_data.ndim > 3:
        img_data = img_data[..., 0]
    if mask_data.ndim > 3:
        mask_data = mask_data[..., 0]
    if img_data.shape != mask_data.shape:
        return None
    mask = _largest_connected_component(mask_data > 0)
    coords = np.argwhere(mask)
    if coords.size == 0:
        return None

    z_dim = img_data.shape[2]
    y_dim = img_data.shape[1]
    sagittal_height = int(round(z_dim * 1200 / max(y_dim, 1)))
    sagittal_height = max(sagittal_height, tile_size)
    scale = sagittal_height / max(z_dim, 1)
    min_gap = max(6, tile_size // 10)

    slice_infos = []
    for z in np.unique(coords[:, 2]):
        slice_mask = mask[:, :, z]
        if not slice_mask.any():
            continue
        indices = np.argwhere(slice_mask)
        center = indices.mean(axis=0)
        slice_infos.append({"z": int(z), "center": center})
    if not slice_infos:
        return None

    desired_tiles = min(len(slice_infos), 12)
    if desired_tiles > 0:
        tile_size = min(tile_size, max(120, sagittal_height // desired_tiles))
    max_tiles_dynamic = max(8, sagittal_height // tile_size)
    tile_cap = min(max_tiles_dynamic, max_tiles) if max_tiles is not None else max_tiles_dynamic

    slice_infos.sort(key=lambda item: item["z"], reverse=True)
    min_sep_z = max(1, int(np.ceil((tile_size + min_gap) / max(scale, 1e-6))))
    selected = []
    last_z = None
    for info in slice_infos:
        if last_z is None or (last_z - info["z"]) >= min_sep_z:
            selected.append(info)
            last_z = info["z"]
        if len(selected) >= tile_cap:
            break
    if not selected:
        return None

    tiles_dir = qc_root / "tiles"
    tiles_dir.mkdir(parents=True, exist_ok=True)
    tile_items: list[tuple[Path, int]] = []
    for info in selected:
        z = info["z"]
        slice_data = img_data[:, :, z]
        mask_slice = mask[:, :, z]
        if slice_data.ndim != 2:
            continue
        tile = _render_mask_tile(
            out_dir=tiles_dir,
            slice_data=slice_data,
            mask_slice=mask_slice,
            z_index=z,
            tile_size=tile_size,
        )
        if tile is not None:
            tile_items.append((tile, z))
    if not tile_items:
        return None

    column = qc_root / "axial_column.png"
    ok, _ = _run_command(["convert", "-size", f"{tile_size}x{sagittal_height}", "xc:#000000", str(column)])
    if not ok:
        return None

    tile_items.sort(key=lambda item: item[1], reverse=True)
    max_y = max(0, sagittal_height - tile_size)
    targets = []
    for tile_path, z_index in tile_items:
        row = (z_dim - 1 - z_index) * scale
        target = int(round(row - tile_size / 2))
        target = max(0, min(target, max_y))
        targets.append((target, tile_path, z_index))

    targets.sort(key=lambda item: item[0])
    positions = [t[0] for t in targets]
    for i in range(1, len(positions)):
        positions[i] = max(positions[i], positions[i - 1] + tile_size + min_gap)
    if positions:
        positions[-1] = min(positions[-1], max_y)
        for i in range(len(positions) - 2, -1, -1):
            positions[i] = min(positions[i], positions[i + 1] - tile_size - min_gap)
            positions[i] = max(0, positions[i])
        for i in range(1, len(positions)):
            positions[i] = max(positions[i], positions[i - 1] + tile_size + min_gap)

    for (target, tile_path, z_index), y_offset in zip(targets, positions):
        ok, _ = _run_command(
            [
                "convert",
                str(column),
                str(tile_path),
                "-geometry",
                f"+0+{y_offset}",
                "-composite",
                str(column),
            ]
        )
        if not ok:
            return None

    sagittal = _render_sagittal_mask_panel(
        qc_root=qc_root / "sagittal",
        image=image,
        mask=mask,
    )
    if sagittal is None:
        return None

    sagittal_resized = qc_root / "sagittal_resized.png"
    ok, _ = _run_command(
        [
            "convert",
            str(sagittal),
            "-filter",
            "Lanczos",
            "-resize",
            f"x{sagittal_height}",
            str(sagittal_resized),
        ]
    )
    if not ok:
        return None

    montage = qc_root / "cordmask_montage.png"
    ok, _ = _run_command(
        [
            "convert",
            str(sagittal_resized),
            str(column),
            "+append",
            str(montage),
        ]
    )
    return montage if ok else None


def _render_mask_tile(
    out_dir: Path,
    slice_data: np.ndarray,
    mask_slice: np.ndarray,
    z_index: int,
    tile_size: int,
) -> Optional[Path]:
    if slice_data.ndim != 2 or mask_slice.ndim != 2:
        return None
    mask_coords = np.argwhere(mask_slice > 0)
    if mask_coords.size == 0:
        return None
    min_xy = mask_coords.min(axis=0)
    max_xy = mask_coords.max(axis=0)
    margin = 6
    min_xy = np.maximum(min_xy - margin, 0)
    max_xy = np.minimum(max_xy + margin, np.array(slice_data.shape) - 1)
    size_xy = max_xy - min_xy + 1
    min_size = 32
    target_size = int(max(size_xy.max(), min_size))
    half = target_size // 2
    center_xy = np.round((min_xy + max_xy) / 2).astype(int)
    x0 = max(center_xy[0] - half, 0)
    y0 = max(center_xy[1] - half, 0)
    x1 = min(x0 + target_size, slice_data.shape[0])
    y1 = min(y0 + target_size, slice_data.shape[1])
    x0 = max(x1 - target_size, 0)
    y0 = max(y1 - target_size, 0)

    slice_data = slice_data[x0:x1, y0:y1]
    mask_slice = mask_slice[x0:x1, y0:y1]

    # Axial view in canonical RAS: anterior up.
    slice_data = np.flipud(slice_data.T)
    mask_slice = np.flipud(mask_slice.T)

    vmin, vmax = np.percentile(slice_data, [1, 99])
    if vmax <= vmin:
        vmin, vmax = float(slice_data.min()), float(slice_data.max())
    if vmax <= vmin:
        vmax = vmin + 1.0
    normalized = np.clip((slice_data - vmin) / (vmax - vmin), 0, 1)
    base = (normalized * 255).astype(np.uint8)
    rgb = np.repeat(base[..., np.newaxis], 3, axis=2)
    mask = mask_slice.astype(bool)
    rgb[mask] = (rgb[mask] * 0.4 + np.array([255, 0, 0]) * 0.6).astype(np.uint8)

    ppm_path = out_dir / f"axial_{z_index:04d}.ppm"
    png_path = out_dir / f"axial_{z_index:04d}.png"
    _write_ppm(ppm_path, rgb)
    ok, _ = _run_command(
        [
            "convert",
            str(ppm_path),
            "-filter",
            "Lanczos",
            "-resize",
            f"{tile_size}x{tile_size}",
            str(png_path),
        ]
    )
    return png_path if ok else None


def _render_rootlets_tile(
    out_dir: Path,
    slice_data: np.ndarray,
    rootlets_slice: np.ndarray,
    cord_slice: np.ndarray,
    z_index: int,
    tile_size: int,
    level_text: str,
    level_color: tuple[int, int, int],
    frame_id: str,
) -> Optional[Path]:
    if slice_data.ndim != 2 or rootlets_slice.ndim != 2 or cord_slice.ndim != 2:
        return None
    cord_coords = np.argwhere(cord_slice > 0)
    if cord_coords.size == 0:
        return None
    min_xy = cord_coords.min(axis=0)
    max_xy = cord_coords.max(axis=0)
    margin = 6
    min_xy = np.maximum(min_xy - margin, 0)
    max_xy = np.minimum(max_xy + margin, np.array(slice_data.shape) - 1)
    size_xy = max_xy - min_xy + 1
    min_size = 32
    target_size = int(max(size_xy.max(), min_size))
    half = target_size // 2
    center_xy = np.round((min_xy + max_xy) / 2).astype(int)
    x0 = max(center_xy[0] - half, 0)
    y0 = max(center_xy[1] - half, 0)
    x1 = min(x0 + target_size, slice_data.shape[0])
    y1 = min(y0 + target_size, slice_data.shape[1])
    x0 = max(x1 - target_size, 0)
    y0 = max(y1 - target_size, 0)

    slice_data = slice_data[x0:x1, y0:y1]
    rootlets_slice = (rootlets_slice[x0:x1, y0:y1] > 0)

    # Axial view in canonical RAS: anterior up.
    slice_data = np.flipud(slice_data.T)
    rootlets_slice = np.flipud(rootlets_slice.T)

    vmin, vmax = np.percentile(slice_data, [1, 99])
    if vmax <= vmin:
        vmin, vmax = float(slice_data.min()), float(slice_data.max())
    if vmax <= vmin:
        vmax = vmin + 1.0
    normalized = np.clip((slice_data - vmin) / (vmax - vmin), 0, 1)
    base = (normalized * 255).astype(np.uint8)
    rgb = np.repeat(base[..., np.newaxis], 3, axis=2)

    # Binary rootlets overlay.
    overlay_color = np.array([255, 0, 0], dtype=np.uint8)
    rgb[rootlets_slice] = (rgb[rootlets_slice] * 0.3 + overlay_color * 0.7).astype(np.uint8)

    ppm_path = out_dir / f"axial_{frame_id}_{z_index:04d}.ppm"
    png_path = out_dir / f"axial_{frame_id}_{z_index:04d}.png"
    _write_ppm(ppm_path, rgb)
    r, g, b = level_color
    fill = f"rgb({int(r)},{int(g)},{int(b)})"
    ok, _ = _run_command(
        [
            "convert",
            str(ppm_path),
            "-filter",
            "Lanczos",
            "-resize",
            f"{tile_size}x{tile_size}",
            "-gravity",
            "north",
            "-pointsize",
            "32",
            "-stroke",
            "#ffffff",
            "-strokewidth",
            "1",
            "-fill",
            fill,
            "-undercolor",
            "#000000aa",
            "-annotate",
            "0",
            level_text,
            str(png_path),
        ]
    )
    return png_path if ok else None


def _render_rootlets_montage(
    qc_root: Path,
    image: Optional[Path],
    rootlets: Optional[Path],
    vertebral_labels: Optional[Path],
    cordmask: Optional[Path],
    tile_size: int = 200,
) -> Optional[Path]:
    run_id = "post-fix2"
    if image is None or rootlets is None or vertebral_labels is None or cordmask is None:
        return None
    qc_root.mkdir(parents=True, exist_ok=True)
    try:
        img = nib.as_closest_canonical(nib.load(image))
        root_img = nib.as_closest_canonical(nib.load(rootlets))
        lab_img = nib.as_closest_canonical(nib.load(vertebral_labels))
        cord_img = nib.as_closest_canonical(nib.load(cordmask))
    except Exception:
        return None
    img_data = img.get_fdata()
    root_data = root_img.get_fdata()
    lab_data = lab_img.get_fdata()
    cord_data = cord_img.get_fdata()
    if img_data.ndim > 3:
        img_data = img_data[..., 0]
    if root_data.ndim > 3:
        root_data = root_data[..., 0]
    if lab_data.ndim > 3:
        lab_data = lab_data[..., 0]
    if cord_data.ndim > 3:
        cord_data = cord_data[..., 0]
    if img_data.shape != root_data.shape or img_data.shape != lab_data.shape or img_data.shape != cord_data.shape:
        return None

    cord_mask = _largest_connected_component(cord_data > 0)
    if not cord_mask.any():
        return None
    root_mask = root_data > 0

    # Use all vertebral labels without LCC filtering.
    # The labels may be in disconnected components (e.g., if FOV doesn't cover full spine),
    # and we want to show tiles for ALL levels present in the data.
    lab_mask = lab_data > 0
    if not lab_mask.any():
        return None
    # Debug overall extents
    root_coords = np.argwhere(root_mask)
    lab_coords = np.argwhere(lab_data > 0)
    cord_coords = np.argwhere(cord_mask)
    root_vals = np.unique(root_data.astype(int))
    def _level_name(label_value: int) -> str:
        if label_value <= 0:
            return str(label_value)
        if label_value <= 7:
            return f"C{label_value}"
        if label_value <= 19:
            return f"T{label_value - 7}"
        if label_value <= 24:
            return f"L{label_value - 19}"
        return str(label_value)

    palette = np.array(
        [
            [255, 0, 0],
            [255, 165, 0],
            [255, 255, 0],
            [0, 255, 0],
            [0, 255, 255],
            [0, 0, 255],
            [255, 0, 255],
        ],
        dtype=np.uint8,
    )

    present_levels = sorted({int(v) for v in np.unique(lab_data.astype(int)) if v > 0})
    if not present_levels:
        return None

    z_dim = img_data.shape[2]
    y_dim = img_data.shape[1]
    sagittal_height = int(round(z_dim * 1200 / max(y_dim, 1)))
    sagittal_height = max(sagittal_height, tile_size)
    scale = sagittal_height / max(z_dim, 1)

    desired_tiles = min(len(present_levels), 24)
    if desired_tiles > 0:
        tile_size = min(tile_size, max(90, sagittal_height // desired_tiles))
    min_gap = max(6, tile_size // 10)

    level_infos: list[dict] = []
    lab_int = lab_data.astype(int)
    for lab in present_levels:
        coords = np.argwhere(lab_int == lab)
        if coords.size == 0:
            continue
        z_idx = int(round(np.median(coords[:, 2])))
        z_idx = max(0, min(z_idx, z_dim - 1))
        level_infos.append({"lab": lab, "z": z_idx})
    if not level_infos:
        return None

    tiles_dir = qc_root / "tiles"
    tiles_dir.mkdir(parents=True, exist_ok=True)
    tile_frames: list[dict] = []
    max_frames = 0
    lab_int = lab_data.astype(int)
    for info in level_infos:
        lab = int(info["lab"])
        color = palette[(lab - 1) % len(palette)]
        level_mask = (lab_int == lab)
        level_root_mask = root_mask  # do not intersect spatially; just use z overlap with level
        z_level = [int(z) for z in np.where(level_mask.any(axis=(0, 1)))[0].tolist()]
        z_root = [int(z) for z in np.where(level_root_mask.any(axis=(0, 1)))[0].tolist()]
        z_candidates_root = sorted(set(z_level).intersection(z_root))
        # Show only levels where rootlets are detected.
        # Skip levels with no rootlet z-overlap to keep montage focused on actual rootlets.
        if not z_candidates_root:
            continue
        # Sample from z_candidates_root (slices with rootlets), not z_level.
        if len(z_candidates_root) > 10:
            idxs = np.linspace(0, len(z_candidates_root) - 1, num=10, dtype=int)
            z_samples = [z_candidates_root[i] for i in idxs]
        else:
            z_samples = z_candidates_root

        frame_paths: list[Path] = []
        for z in z_samples:
            slice_data = img_data[:, :, z]
            root_slice = root_mask[:, :, z]
            cord_slice = cord_mask[:, :, z]
            if slice_data.ndim != 2:
                continue
            frame = _render_rootlets_tile(
                out_dir=tiles_dir,
                slice_data=slice_data,
                rootlets_slice=root_slice,
                cord_slice=cord_slice,
                z_index=z,
                tile_size=tile_size,
                level_text=_level_name(lab),
                level_color=(int(color[0]), int(color[1]), int(color[2])),
                frame_id=f"lab{lab}",
            )
            if frame is not None:
                frame_paths.append(frame)
        if not frame_paths:
            continue
        max_frames = max(max_frames, len(frame_paths))
        tile_frames.append({"lab": lab, "z": int(info["z"]), "color": color, "frames": frame_paths})
    if not tile_frames:
        return None

    column = qc_root / "axial_column.png"
    ok, _ = _run_command(["convert", "-size", f"{tile_size}x{sagittal_height}", "xc:#000000", str(column)])
    if not ok:
        return None

    # Use median z of each level for positioning.
    tile_items = [(t["frames"][0], t["z"], t["lab"]) for t in tile_frames]
    tile_items.sort(key=lambda item: item[1], reverse=True)
    max_y = max(0, sagittal_height - tile_size)
    targets = []
    for tile_path, z_index, _lab in tile_items:
        row = (z_dim - 1 - z_index) * scale
        target = int(round(row - tile_size / 2))
        target = max(0, min(target, max_y))
        targets.append((target, tile_path, z_index))

    targets.sort(key=lambda item: item[0])
    positions = [t[0] for t in targets]
    for i in range(1, len(positions)):
        positions[i] = max(positions[i], positions[i - 1] + tile_size + min_gap)
    if positions:
        positions[-1] = min(positions[-1], max_y)
        for i in range(len(positions) - 2, -1, -1):
            positions[i] = min(positions[i], positions[i + 1] - tile_size - min_gap)
            positions[i] = max(0, positions[i])
        for i in range(1, len(positions)):
            positions[i] = max(positions[i], positions[i - 1] + tile_size + min_gap)

    # Build animated montage frames (GIF) by cycling through per-level frames.
    sagittal = _render_sagittal_mask_panel_from_ref(
        qc_root=qc_root / "sagittal",
        image=image,
        mask=root_mask,
        ref_mask=cord_mask,
    )
    if sagittal is None:
        return None
    sagittal_resized = qc_root / "sagittal_resized.png"
    ok, _ = _run_command(
        [
            "convert",
            str(sagittal),
            "-filter",
            "Lanczos",
            "-resize",
            f"x{sagittal_height}",
            str(sagittal_resized),
        ]
    )
    if not ok:
        return None

    frames_dir = qc_root / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    montage_frames: list[Path] = []
    try:
        sag_img = Image.open(sagittal_resized).convert("RGB")
    except Exception:
        return None
    column_width = tile_size
    frame_lookup = {t["frames"][0]: t for t in tile_frames}
    for frame_idx in range(max_frames):
        column_img = Image.new("RGB", (column_width, sagittal_height), (0, 0, 0))  # type: ignore[arg-type]
        for (target, tile_path, _), y_offset in zip(targets, positions):
            # Select frame for this tile
            tile_entry = frame_lookup.get(tile_path)
            if tile_entry is None:
                continue
            frames = tile_entry["frames"]
            if not frames:
                continue
            frame_path = frames[frame_idx % len(frames)]
            try:
                tile_img = Image.open(frame_path).convert("RGB")
            except Exception:
                continue
            column_img.paste(tile_img, (0, y_offset))
        montage_img = Image.new(
            "RGB", (sag_img.width + column_img.width, max(sag_img.height, column_img.height)), (0, 0, 0)  # type: ignore[arg-type]
        )
        montage_img.paste(sag_img, (0, 0))
        montage_img.paste(column_img, (sag_img.width, 0))
        frame_path = frames_dir / f"frame_{frame_idx:03d}.png"
        montage_img.save(frame_path)
        montage_frames.append(frame_path)

    if not montage_frames:
        return None

    montage_gif = qc_root / "rootlets_montage.gif"
    ok, _ = _run_command(
        [
            "convert",
            "-delay",
            "20",
            "-loop",
            "0",
            *[str(p) for p in montage_frames],
            str(montage_gif),
        ]
    )
    if not ok:
        return None

    # Also write first frame PNG for static preview/compatibility.
    montage_png = qc_root / "rootlets_montage.png"
    _run_command(["convert", str(montage_frames[0]), str(montage_png)])
    return montage_gif


def _render_sagittal_mask_panel(
    qc_root: Path,
    image: Optional[Path],
    mask: np.ndarray,
) -> Optional[Path]:
    qc_root.mkdir(parents=True, exist_ok=True)
    try:
        img = nib.as_closest_canonical(nib.load(image)) if image else None
    except Exception:
        return None
    if img is None:
        return None
    img_data = img.get_fdata()
    if img_data.ndim > 3:
        img_data = img_data[..., 0]
    if img_data.shape != mask.shape:
        return None
    coords = np.argwhere(mask)
    if coords.size == 0:
        return None
    x_index = int(np.median(coords[:, 0]))
    x_index = max(0, min(x_index, img_data.shape[0] - 1))
    img_slice = img_data[x_index, :, :]
    mask_proj = mask.any(axis=0)
    if img_slice.ndim != 2:
        return None

    img_slice = np.flipud(img_slice.T)
    mask_proj = np.flipud(mask_proj.T)

    vmin, vmax = np.percentile(img_slice, [1, 99])
    if vmax <= vmin:
        vmin, vmax = float(img_slice.min()), float(img_slice.max())
    if vmax <= vmin:
        vmax = vmin + 1.0

    normalized = np.clip((img_slice - vmin) / (vmax - vmin), 0, 1)
    base = (normalized * 255).astype(np.uint8)
    base_rgb = np.repeat(base[..., np.newaxis], 3, axis=2)
    overlay = base_rgb.copy()
    overlay[mask_proj] = (overlay[mask_proj] * 0.4 + np.array([255, 0, 0]) * 0.6).astype(np.uint8)

    output = qc_root / "overlay.png"
    ppm_path = qc_root / "overlay.ppm"
    _write_ppm(ppm_path, overlay)
    ok, _ = _run_command(
        [
            "convert",
            str(ppm_path),
            "-filter",
            "Lanczos",
            "-resize",
            "1200x",
            str(output),
        ]
    )
    return output if ok else None


def _render_vertebral_labels_montage(
    qc_root: Path,
    image: Optional[Path],
    labels_path: Optional[Path],
) -> Optional[Path]:
    if image is None or labels_path is None:
        return None
    qc_root.mkdir(parents=True, exist_ok=True)
    try:
        img = nib.as_closest_canonical(nib.load(image))
        lab_img = nib.as_closest_canonical(nib.load(labels_path))
    except Exception:
        return None
    img_data = img.get_fdata()
    lab_data = lab_img.get_fdata()
    if img_data.ndim > 3:
        img_data = img_data[..., 0]
    if lab_data.ndim > 3:
        lab_data = lab_data[..., 0]
    if img_data.shape != lab_data.shape:
        return None

    # Clean scattered label fragments (often inferior/superior to the main spinal cord segment).
    # We keep only the largest connected component of the non-zero label mask.
    lab_mask = _largest_connected_component(lab_data > 0)
    if not lab_mask.any():
        return None
    lab_data = lab_data * lab_mask
    coords = np.argwhere(lab_mask)
    if coords.size == 0:
        return None
    x_index = int(np.median(coords[:, 0]))
    x_index = max(0, min(x_index, img_data.shape[0] - 1))
    img_slice = img_data[x_index, :, :]
    lab_proj = lab_data.max(axis=0)
    if img_slice.ndim != 2:
        return None

    img_slice = np.flipud(img_slice.T)
    lab_proj = np.flipud(lab_proj.T)

    vmin, vmax = np.percentile(img_slice, [1, 99])
    if vmax <= vmin:
        vmin, vmax = float(img_slice.min()), float(img_slice.max())
    if vmax <= vmin:
        vmax = vmin + 1.0

    normalized = np.clip((img_slice - vmin) / (vmax - vmin), 0, 1)
    base = (normalized * 255).astype(np.uint8)
    base_rgb = np.repeat(base[..., np.newaxis], 3, axis=2)
    overlay = base_rgb.copy()
    palette = np.array(
        [
            [255, 0, 0],
            [255, 165, 0],
            [255, 255, 0],
            [0, 255, 0],
            [0, 255, 255],
            [0, 0, 255],
            [255, 0, 255],
        ],
        dtype=np.uint8,
    )
    label_plane = lab_proj.astype(int)
    mask = label_plane > 0
    if mask.any():
        colors = palette[(label_plane - 1) % len(palette)]
        overlay[mask] = (overlay[mask] * 0.3 + colors[mask] * 0.7).astype(np.uint8)

    output = qc_root / "overlay.png"
    ppm_path = qc_root / "overlay.ppm"
    _write_ppm(ppm_path, overlay)

    def _level_name(label_value: int) -> str:
        """Convert SCT-style integer vertebral levels to human-readable names (C/T/L...)."""
        if label_value <= 0:
            return str(label_value)
        # Common SCT convention: C1..C7 => 1..7; T1..T12 => 8..19; L1..L5 => 20..24
        if label_value <= 7:
            return f"C{label_value}"
        if label_value <= 19:
            return f"T{label_value - 7}"
        if label_value <= 24:
            return f"L{label_value - 19}"
        return str(label_value)

    # Add per-level colored text, anchored to the right side at the vertical center of each level.
    target_width = 1200
    src_h, src_w = int(overlay.shape[0]), int(overlay.shape[1])
    if src_w <= 0:
        return None
    scale = target_width / src_w
    out_h = max(1, int(round(src_h * scale)))
    # Keep labels readable even when the dashboard scales images down (max-width: 1200px).
    margin_width = 240
    pointsize = 36
    min_spacing = 42

    present_labels: list[int] = []
    if mask.any():
        present_labels = sorted({int(v) for v in np.unique(label_plane[mask]) if v > 0})

    # Compute (y) text positions in output pixel coordinates.
    label_text: list[tuple[int, int, str, str]] = []
    # Each tuple: (y_out, label_value, text, rgb_fill)
    for lab in present_labels:
        coords2d = np.argwhere(label_plane == lab)
        if coords2d.size == 0:
            continue
        y_center = float(np.median(coords2d[:, 0]))
        y_out = int(round(y_center * scale))
        y_out = max(0, min(y_out, out_h - 1))
        rgb = palette[(lab - 1) % len(palette)]
        rgb_fill = f"rgb({int(rgb[0])},{int(rgb[1])},{int(rgb[2])})"
        label_text.append((y_out, lab, _level_name(lab), rgb_fill))

    # Sort from superior to inferior and enforce minimum spacing to reduce overlaps.
    label_text.sort(key=lambda t: t[0])
    adjusted: list[tuple[int, int, str, str]] = []
    last_y = -10_000
    for y_out, lab, text, rgb_fill in label_text:
        y_adj = y_out
        if y_adj - last_y < min_spacing:
            y_adj = last_y + min_spacing
        y_adj = max(0, min(y_adj, out_h - 1))
        adjusted.append((y_adj, lab, text, rgb_fill))
        last_y = y_adj
    # If we pushed labels beyond the bottom, shift everything up to fit.
    if adjusted:
        y_limit = max(0, out_h - 1 - pointsize)
        overflow = adjusted[-1][0] - y_limit
        if overflow > 0:
            adjusted = [(max(0, y - overflow), lab, text, fill) for (y, lab, text, fill) in adjusted]

    ok, _ = _run_command(
        (
            [
                "convert",
                str(ppm_path),
                "-filter",
                "Lanczos",
                "-resize",
                f"{target_width}x",
                "-background",
                "#000000",
                "-gravity",
                "East",
                "-splice",
                f"{margin_width}x0",
                "-gravity",
                "NorthWest",
                "-pointsize",
                str(pointsize),
                # Slight outline increases legibility on varied backgrounds if margins are changed later.
                "-stroke",
                "#000000",
                "-strokewidth",
                "1",
            ]
            + [
                item
                for (y, lab, text, fill) in adjusted
                for item in (
                    "-fill",
                    fill,
                    "-annotate",
                    f"+{target_width + 10}+{max(0, y - pointsize // 2)}",
                    text,
                )
            ]
            + [str(output)]
        )
    )
    return output if ok else None


def _render_disc_labels_montage(
    qc_root: Path,
    image: Optional[Path],
    disc_labels_path: Optional[Path],
) -> Optional[Path]:
    """
    Render disc labels visualization showing intervertebral disc positions.
    
    Disc labels are shown as horizontal lines at each disc position with
    text annotations on the right margin (e.g., C2/C3, C3/C4, T1/T2, etc.).
    
    Args:
        qc_root: Directory for QC outputs
        image: Path to anatomical reference image
        disc_labels_path: Path to disc labels NIfTI (from sct_label_vertebrae)
        
    Returns:
        Path to generated PNG, or None on failure
    """
    if image is None or disc_labels_path is None:
        return None
    qc_root.mkdir(parents=True, exist_ok=True)
    try:
        img = nib.as_closest_canonical(nib.load(image))
        disc_img = nib.as_closest_canonical(nib.load(disc_labels_path))
    except Exception:
        return None
    img_data = img.get_fdata()
    disc_data = disc_img.get_fdata()
    if img_data.ndim > 3:
        img_data = img_data[..., 0]
    if disc_data.ndim > 3:
        disc_data = disc_data[..., 0]
    if img_data.shape != disc_data.shape:
        return None

    # Disc labels are typically point-like (single voxel per disc)
    # Find all non-zero disc labels
    disc_mask = disc_data > 0
    if not disc_mask.any():
        return None
    coords = np.argwhere(disc_mask)
    if coords.size == 0:
        return None
    
    # Find center x-slice for sagittal view
    x_index = int(np.median(coords[:, 0]))
    x_index = max(0, min(x_index, img_data.shape[0] - 1))
    img_slice = img_data[x_index, :, :]
    if img_slice.ndim != 2:
        return None

    # Flip for display (superior at top)
    img_slice = np.flipud(img_slice.T)
    
    # Get disc label positions - project to y-z plane (sagittal view)
    # Each disc label value corresponds to the disc below that vertebra
    # e.g., label 3 = C2-C3 disc, label 4 = C3-C4 disc, etc.
    disc_positions: list[tuple[int, int, float]] = []  # (y_pixel, z_pixel, label_value)
    for lab in sorted(np.unique(disc_data[disc_mask])):
        if lab <= 0:
            continue
        lab_coords = np.argwhere(disc_data == lab)
        if lab_coords.size == 0:
            continue
        # Use median y, z position for this disc
        y_pos = float(np.median(lab_coords[:, 1]))
        z_pos = float(np.median(lab_coords[:, 2]))
        disc_positions.append((int(y_pos), int(z_pos), int(lab)))

    if not disc_positions:
        return None

    # Normalize image
    vmin, vmax = np.percentile(img_slice, [1, 99])
    if vmax <= vmin:
        vmin, vmax = float(img_slice.min()), float(img_slice.max())
    if vmax <= vmin:
        vmax = vmin + 1.0

    normalized = np.clip((img_slice - vmin) / (vmax - vmin), 0, 1)
    base = (normalized * 255).astype(np.uint8)
    base_rgb = np.repeat(base[..., np.newaxis], 3, axis=2)
    overlay = base_rgb.copy()

    # Draw horizontal lines at disc positions
    h, w = img_slice.shape
    for y_pos, z_pos, lab in disc_positions:
        # Convert to display coordinates (after flip)
        z_display = h - 1 - z_pos
        z_display = max(0, min(z_display, h - 1))
        # Draw horizontal line across the image
        line_color = np.array([255, 255, 0], dtype=np.uint8)  # Yellow
        for y in range(w):
            # Blend the line with existing pixels
            overlay[z_display, y] = (overlay[z_display, y] * 0.3 + line_color * 0.7).astype(np.uint8)

    output = qc_root / "disc_labels.png"
    ppm_path = qc_root / "disc_labels.ppm"
    _write_ppm(ppm_path, overlay)

    def _disc_name(label_value: int) -> str:
        """Convert SCT-style disc label to human-readable name (C2/C3, T1/T2, etc.)."""
        if label_value <= 0:
            return str(label_value)
        # SCT convention: disc label N is below vertebra N-1 (between N-1 and N)
        # e.g., disc 3 = C2-C3, disc 4 = C3-C4, ..., disc 8 = C7-T1, disc 9 = T1-T2
        def _vert_name(v: int) -> str:
            if v <= 0:
                return str(v)
            if v <= 7:
                return f"C{v}"
            if v <= 19:
                return f"T{v - 7}"
            if v <= 24:
                return f"L{v - 19}"
            if v <= 29:
                return f"S{v - 24}"
            return str(v)
        
        upper = label_value - 1
        lower = label_value
        return f"{_vert_name(upper)}/{_vert_name(lower)}"

    # Resize and add text annotations
    target_width = 1200
    src_h, src_w = int(overlay.shape[0]), int(overlay.shape[1])
    if src_w <= 0:
        return None
    scale = target_width / src_w
    out_h = max(1, int(round(src_h * scale)))
    margin_width = 240
    pointsize = 32
    min_spacing = 38

    # Compute text positions
    label_text: list[tuple[int, int, str]] = []
    for y_pos, z_pos, lab in disc_positions:
        z_display = h - 1 - z_pos
        y_out = int(round(z_display * scale))
        y_out = max(0, min(y_out, out_h - 1))
        label_text.append((y_out, lab, _disc_name(lab)))

    # Sort and enforce minimum spacing
    label_text.sort(key=lambda t: t[0])
    adjusted: list[tuple[int, int, str]] = []
    last_y = -10_000
    for y_out, lab, text in label_text:
        y_adj = y_out
        if y_adj - last_y < min_spacing:
            y_adj = last_y + min_spacing
        y_adj = max(0, min(y_adj, out_h - 1))
        adjusted.append((y_adj, lab, text))
        last_y = y_adj
    
    # Handle overflow
    if adjusted:
        y_limit = max(0, out_h - 1 - pointsize)
        overflow = adjusted[-1][0] - y_limit
        if overflow > 0:
            adjusted = [(max(0, y - overflow), lab, text) for (y, lab, text) in adjusted]

    ok, _ = _run_command(
        [
            "convert",
            str(ppm_path),
            "-filter",
            "Lanczos",
            "-resize",
            f"{target_width}x",
            "-background",
            "#000000",
            "-gravity",
            "East",
            "-splice",
            f"{margin_width}x0",
            "-gravity",
            "NorthWest",
            "-pointsize",
            str(pointsize),
            "-stroke",
            "#000000",
            "-strokewidth",
            "1",
        ]
        + [
            item
            for (y, lab, text) in adjusted
            for item in (
                "-fill",
                "#FFFF00",  # Yellow text matching lines
                "-annotate",
                f"+{target_width + 10}+{max(0, y - pointsize // 2)}",
                text,
            )
        ]
        + [str(output)]
    )
    return output if ok else None


def _render_totalspineseg_montage(
    qc_root: Path,
    image: Optional[Path],
    tss_output_path: Optional[Path],
    cord_path: Optional[Path],
    canal_path: Optional[Path],
) -> Optional[Path]:
    """
    Render TotalSpineSeg-style comprehensive visualization.
    
    Shows a sagittal view with:
    - Vertebrae as colored regions (rainbow per level)
    - Intervertebral discs as colored bands
    - Spinal cord as blue overlay
    - Spinal canal as cyan overlay
    - Disc labels on LEFT margin
    - Vertebral labels on RIGHT margin
    
    Args:
        qc_root: Directory for QC outputs
        image: Path to anatomical reference image
        tss_output_path: Path to TotalSpineSeg output NIfTI (with all labels)
        cord_path: Path to cord segmentation (optional, extracted from TSS)
        canal_path: Path to canal segmentation (optional, extracted from TSS)
        
    Returns:
        Path to generated PNG, or None on failure
    """
    if image is None or tss_output_path is None:
        return None
    qc_root.mkdir(parents=True, exist_ok=True)
    
    try:
        img = nib.as_closest_canonical(nib.load(image))
        tss_img = nib.as_closest_canonical(nib.load(tss_output_path))
    except Exception:
        return None
    
    img_data = img.get_fdata()
    tss_data = tss_img.get_fdata()
    if img_data.ndim > 3:
        img_data = img_data[..., 0]
    if tss_data.ndim > 3:
        tss_data = tss_data[..., 0]
    if img_data.shape != tss_data.shape:
        return None
    
    # Load cord and canal if provided separately (for cleaner overlays)
    cord_data = None
    canal_data = None
    if cord_path and cord_path.exists():
        try:
            cord_img = nib.as_closest_canonical(nib.load(cord_path))
            cord_data = cord_img.get_fdata()
            if cord_data.ndim > 3:
                cord_data = cord_data[..., 0]
        except Exception:
            cord_data = None
    if canal_path and canal_path.exists():
        try:
            canal_img = nib.as_closest_canonical(nib.load(canal_path))
            canal_data = canal_img.get_fdata()
            if canal_data.ndim > 3:
                canal_data = canal_data[..., 0]
        except Exception:
            canal_data = None
    
    # Find center x-slice for sagittal view using the TSS segmentation
    tss_mask = tss_data > 0
    if not tss_mask.any():
        return None
    coords = np.argwhere(tss_mask)
    if coords.size == 0:
        return None
    x_index = int(np.median(coords[:, 0]))
    x_index = max(0, min(x_index, img_data.shape[0] - 1))
    
    # Extract sagittal slices
    img_slice = img_data[x_index, :, :]
    tss_slice = tss_data[x_index, :, :]
    if img_slice.ndim != 2:
        return None
    
    # Flip for display (superior at top)
    img_slice = np.flipud(img_slice.T)
    tss_slice = np.flipud(tss_slice.T)
    h, w = img_slice.shape
    
    # Normalize image
    vmin, vmax = np.percentile(img_slice, [1, 99])
    if vmax <= vmin:
        vmin, vmax = float(img_slice.min()), float(img_slice.max())
    if vmax <= vmin:
        vmax = vmin + 1.0
    normalized = np.clip((img_slice - vmin) / (vmax - vmin), 0, 1)
    base = (normalized * 255).astype(np.uint8)
    base_rgb = np.repeat(base[..., np.newaxis], 3, axis=2)
    overlay = base_rgb.copy()
    
    # Define color palette for vertebrae (TotalSpineSeg-like rainbow)
    # Each vertebral level gets a unique color
    vertebrae_colors = {
        # Cervical: blues/cyans
        11: (135, 206, 250),  # C1 - light sky blue
        12: (100, 149, 237),  # C2 - cornflower blue
        13: (255, 215, 0),    # C3 - gold
        14: (255, 165, 0),    # C4 - orange
        15: (50, 205, 50),    # C5 - lime green
        16: (144, 238, 144),  # C6 - light green
        17: (178, 102, 255),  # C7 - purple
        # Thoracic: warm colors
        21: (255, 99, 71),    # T1 - tomato
        22: (255, 215, 0),    # T2 - gold
        23: (255, 182, 193),  # T3 - light pink
        24: (152, 251, 152),  # T4 - pale green
        25: (135, 206, 235),  # T5 - sky blue
        26: (238, 130, 238),  # T6 - violet
        27: (255, 160, 122),  # T7 - light salmon
        28: (173, 216, 230),  # T8 - light blue
        29: (255, 228, 181),  # T9 - moccasin
        30: (221, 160, 221),  # T10 - plum
        31: (176, 224, 230),  # T11 - powder blue
        32: (250, 250, 210),  # T12 - light goldenrod
        # Lumbar: greens/browns
        41: (144, 238, 144),  # L1 - light green
        42: (189, 183, 107),  # L2 - dark khaki
        43: (216, 191, 216),  # L3 - thistle
        44: (245, 222, 179),  # L4 - wheat
        45: (188, 143, 143),  # L5 - rosy brown
        # Sacrum
        50: (139, 69, 19),    # S - saddle brown
    }
    
    # Disc colors (slightly darker/different hue than adjacent vertebrae)
    disc_colors = {
        63: (255, 200, 100),   # C2-C3
        64: (255, 180, 80),    # C3-C4
        65: (255, 160, 60),    # C4-C5
        66: (255, 140, 40),    # C5-C6
        67: (255, 120, 20),    # C6-C7
        71: (200, 100, 100),   # C7-T1
        72: (180, 100, 120),   # T1-T2
        73: (160, 100, 140),   # T2-T3
        74: (140, 100, 160),   # T3-T4
        75: (120, 100, 180),   # T4-T5
        76: (100, 100, 200),   # T5-T6
        77: (100, 120, 180),   # T6-T7
        78: (100, 140, 160),   # T7-T8
        79: (100, 160, 140),   # T8-T9
        80: (100, 180, 120),   # T9-T10
        81: (100, 200, 100),   # T10-T11
        82: (120, 180, 100),   # T11-T12
        91: (140, 160, 100),   # T12-L1
        92: (160, 140, 100),   # L1-L2
        93: (180, 120, 100),   # L2-L3
        94: (200, 100, 100),   # L3-L4
        95: (220, 80, 100),    # L4-L5
        100: (240, 60, 100),   # L5-S
    }
    
    # Overlay vertebrae
    for label, color in vertebrae_colors.items():
        mask = tss_slice == label
        if mask.any():
            overlay[mask] = (overlay[mask] * 0.3 + np.array(color) * 0.7).astype(np.uint8)
    
    # Overlay discs
    for label, color in disc_colors.items():
        mask = tss_slice == label
        if mask.any():
            overlay[mask] = (overlay[mask] * 0.2 + np.array(color) * 0.8).astype(np.uint8)
    
    # Overlay spinal canal (cyan, semi-transparent)
    if canal_data is not None:
        canal_slice = canal_data[x_index, :, :]
        canal_slice = np.flipud(canal_slice.T)
        canal_mask = canal_slice > 0
        if canal_mask.any():
            canal_color = np.array([0, 200, 200])  # Cyan
            overlay[canal_mask] = (overlay[canal_mask] * 0.5 + canal_color * 0.5).astype(np.uint8)
    else:
        # Extract from TSS data
        canal_mask = tss_slice == TSS_LABELS["spinal_canal"]
        if canal_mask.any():
            canal_color = np.array([0, 200, 200])  # Cyan
            overlay[canal_mask] = (overlay[canal_mask] * 0.5 + canal_color * 0.5).astype(np.uint8)
    
    # Overlay spinal cord (blue, on top)
    if cord_data is not None:
        cord_slice = cord_data[x_index, :, :]
        cord_slice = np.flipud(cord_slice.T)
        cord_mask = cord_slice > 0
        if cord_mask.any():
            cord_color = np.array([65, 105, 225])  # Royal blue
            overlay[cord_mask] = (overlay[cord_mask] * 0.4 + cord_color * 0.6).astype(np.uint8)
    else:
        # Extract from TSS data
        cord_mask = tss_slice == TSS_LABELS["spinal_cord"]
        if cord_mask.any():
            cord_color = np.array([65, 105, 225])  # Royal blue
            overlay[cord_mask] = (overlay[cord_mask] * 0.4 + cord_color * 0.6).astype(np.uint8)
    
    # Save overlay as PPM
    output = qc_root / "tss_montage.png"
    ppm_path = qc_root / "tss_overlay.ppm"
    _write_ppm(ppm_path, overlay)
    
    # Collect present vertebrae and discs for labels
    present_vertebrae: list[tuple[int, int, str]] = []  # (z_display, label, name)
    present_discs: list[tuple[int, int, str]] = []  # (z_display, label, name)
    
    for label, name in TSS_VERTEBRA_NAMES.items():
        mask = tss_slice == label
        if mask.any():
            coords2d = np.argwhere(mask)
            z_center = float(np.median(coords2d[:, 0]))
            present_vertebrae.append((int(z_center), label, name))
    
    for label, name in TSS_DISC_NAMES.items():
        mask = tss_slice == label
        if mask.any():
            coords2d = np.argwhere(mask)
            z_center = float(np.median(coords2d[:, 0]))
            present_discs.append((int(z_center), label, name))
    
    # Sort by z position (superior to inferior)
    present_vertebrae.sort(key=lambda t: t[0])
    present_discs.sort(key=lambda t: t[0])
    
    # Resize and add labels
    target_width = 1200
    src_h, src_w = int(overlay.shape[0]), int(overlay.shape[1])
    if src_w <= 0:
        return None
    scale = target_width / src_w
    out_h = max(1, int(round(src_h * scale)))
    
    # Margins for labels on both sides
    left_margin = 200   # For disc labels
    right_margin = 200  # For vertebral labels
    pointsize = 28
    min_spacing = 32
    
    # Compute label positions for vertebrae (RIGHT side)
    vert_labels: list[tuple[int, str, str]] = []
    for z_pos, label, name in present_vertebrae:
        y_out = int(round(z_pos * scale))
        y_out = max(0, min(y_out, out_h - 1))
        color = vertebrae_colors.get(label, (255, 255, 255))
        rgb_fill = f"rgb({color[0]},{color[1]},{color[2]})"
        vert_labels.append((y_out, name, rgb_fill))
    
    # Adjust spacing for vertebrae
    vert_adjusted: list[tuple[int, str, str]] = []
    last_y = -10_000
    for y_out, name, rgb_fill in vert_labels:
        y_adj = y_out
        if y_adj - last_y < min_spacing:
            y_adj = last_y + min_spacing
        y_adj = max(0, min(y_adj, out_h - 1))
        vert_adjusted.append((y_adj, name, rgb_fill))
        last_y = y_adj
    
    # Compute label positions for discs (LEFT side)
    disc_labels_list: list[tuple[int, str, str]] = []
    for z_pos, label, name in present_discs:
        y_out = int(round(z_pos * scale))
        y_out = max(0, min(y_out, out_h - 1))
        color = disc_colors.get(label, (255, 200, 100))
        rgb_fill = f"rgb({color[0]},{color[1]},{color[2]})"
        disc_labels_list.append((y_out, name, rgb_fill))
    
    # Adjust spacing for discs
    disc_adjusted: list[tuple[int, str, str]] = []
    last_y = -10_000
    for y_out, name, rgb_fill in disc_labels_list:
        y_adj = y_out
        if y_adj - last_y < min_spacing:
            y_adj = last_y + min_spacing
        y_adj = max(0, min(y_adj, out_h - 1))
        disc_adjusted.append((y_adj, name, rgb_fill))
        last_y = y_adj
    
    # Build ImageMagick command
    # Resize, add margins on both sides, then annotate
    cmd = [
        "convert",
        str(ppm_path),
        "-filter", "Lanczos",
        "-resize", f"{target_width}x",
        "-background", "#000000",
        # Add left margin for disc labels
        "-gravity", "West",
        "-splice", f"{left_margin}x0",
        # Add right margin for vertebral labels
        "-gravity", "East",
        "-splice", f"{right_margin}x0",
        "-gravity", "NorthWest",
        "-pointsize", str(pointsize),
        "-stroke", "#000000",
        "-strokewidth", "1",
    ]
    
    # Add disc labels on left side
    for y, name, rgb_fill in disc_adjusted:
        cmd.extend([
            "-fill", rgb_fill,
            "-annotate", f"+10+{max(0, y - pointsize // 2)}",
            name,
        ])
    
    # Add vertebral labels on right side
    total_width = left_margin + target_width + right_margin
    for y, name, rgb_fill in vert_adjusted:
        cmd.extend([
            "-fill", rgb_fill,
            "-annotate", f"+{left_margin + target_width + 10}+{max(0, y - pointsize // 2)}",
            name,
        ])
    
    cmd.append(str(output))
    
    ok, _ = _run_command(cmd)
    return output if ok else None


def _render_sagittal_centerline_panel(
    qc_root: Path,
    image: Optional[Path],
    centerline: Optional[Path],
) -> Optional[Path]:
    if image is None or centerline is None:
        return None
    qc_root.mkdir(parents=True, exist_ok=True)
    try:
        img = nib.load(image)
        seg_img = nib.load(centerline)
    except Exception:
        return None

    img_canon = nib.as_closest_canonical(img)
    seg_canon = nib.as_closest_canonical(seg_img)
    img_data = img_canon.get_fdata()
    seg_data = seg_canon.get_fdata()
    if img_data.ndim > 3:
        img_data = img_data[..., 0]
    if seg_data.ndim > 3:
        seg_data = seg_data[..., 0]
    if img_data.shape != seg_data.shape:
        return None

    seg_mask = _largest_connected_component(seg_data > 0)
    coords = np.argwhere(seg_mask)
    if coords.size == 0:
        return None
    x_index = int(np.median(coords[:, 0]))
    x_index = max(0, min(x_index, img_data.shape[0] - 1))

    img_slice = img_data[x_index, :, :]
    seg_proj = seg_mask.any(axis=0)
    if img_slice.ndim != 2:
        return None

    # Display with superior at the top: z-axis becomes vertical after transpose.
    img_slice = np.flipud(img_slice.T)
    seg_slice = np.flipud(seg_proj.T)

    vmin, vmax = np.percentile(img_slice, [1, 99])
    if vmax <= vmin:
        vmin, vmax = float(img_slice.min()), float(img_slice.max())
    if vmax <= vmin:
        vmax = vmin + 1.0

    normalized = np.clip((img_slice - vmin) / (vmax - vmin), 0, 1)
    base = (normalized * 255).astype(np.uint8)
    base_rgb = np.repeat(base[..., np.newaxis], 3, axis=2)
    overlay = base_rgb.copy()
    mask = seg_slice.astype(bool)
    overlay[mask] = (overlay[mask] * 0.4 + np.array([255, 0, 0]) * 0.6).astype(np.uint8)

    output = qc_root / "overlay.png"
    ppm_path = qc_root / "overlay.ppm"
    _write_ppm(ppm_path, overlay)
    ok, _ = _run_command(
        [
            "convert",
            str(ppm_path),
            "-filter",
            "Lanczos",
            "-resize",
            "1200x",
            str(output),
        ]
    )
    return output if ok else None


def _write_not_available_panel(dest: Path, out_root: Path, message: str) -> Optional[str]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    ok, _ = _run_command(
        [
            "convert",
            "-size",
            "1200x900",
            "xc:#111111",
            "-gravity",
            "center",
            "-pointsize",
            "36",
            "-fill",
            "#e6e6e6",
            "-annotate",
            "0",
            message,
            str(dest),
        ]
    )
    if not ok:
        return None
    return _relpath(dest, out_root)


def _make_gif(source: Optional[Path], dest: Path, out_root: Path) -> Optional[str]:
    if source is None:
        return None
    ok, _ = _run_command(["convert", str(source), str(dest)])
    if not ok:
        return None
    return _relpath(dest, out_root)


def _write_ppm(path: Path, rgb: np.ndarray) -> None:
    if rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError("RGB array must have shape (H, W, 3).")
    height, width, _ = rgb.shape
    header = f"P6\n{width} {height}\n255\n".encode("ascii")
    path.write_bytes(header + rgb.astype(np.uint8).tobytes())


def _compose_overlay(background: Path, overlay: Path, dest: Path) -> bool:
    ok, _ = _run_command(
        [
            "convert",
            str(background),
            str(overlay),
            "-compose",
            "over",
            "-composite",
            str(dest),
        ]
    )
    return ok


def _dilate_mask(source: Path, dest: Path, radius: int = 0) -> Optional[Path]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    ok, _ = _run_command(
        [
            "sct_maths",
            "-i",
            str(source),
            "-dilate",
            str(radius),
            "-o",
            str(dest),
        ]
    )
    return dest if ok else None


def _largest_connected_component(mask: np.ndarray) -> np.ndarray:
    if mask.ndim != 3:
        return mask
    visited = np.zeros(mask.shape, dtype=bool)
    best_component = None
    best_size = 0
    coords = np.argwhere(mask)
    for start in coords:
        x, y, z = start
        if visited[x, y, z]:
            continue
        stack = [(x, y, z)]
        component = []
        visited[x, y, z] = True
        while stack:
            cx, cy, cz = stack.pop()
            component.append((cx, cy, cz))
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        if dx == 0 and dy == 0 and dz == 0:
                            continue
                        nx, ny, nz = cx + dx, cy + dy, cz + dz
                        if (
                            0 <= nx < mask.shape[0]
                            and 0 <= ny < mask.shape[1]
                            and 0 <= nz < mask.shape[2]
                            and mask[nx, ny, nz]
                            and not visited[nx, ny, nz]
                        ):
                            visited[nx, ny, nz] = True
                            stack.append((nx, ny, nz))
        if len(component) > best_size:
            best_size = len(component)
            best_component = component
    if best_component is None:
        return mask
    cleaned = np.zeros(mask.shape, dtype=bool)
    for cx, cy, cz in best_component:
        cleaned[cx, cy, cz] = True
    return cleaned


def _validate_json(path: Path, schema_path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft7Validator(schema)  # type: ignore[arg-type]
    errors = sorted(validator.iter_errors(data), key=lambda e: e.path)
    if errors:
        msgs = "; ".join(e.message for e in errors)
        raise ValueError(f"Schema validation failed for {path}: {msgs}")


def _write_evidence(
    evidence_dir: Path,
    qc_path: Path,
    runs_path: Path,
    runs: list[dict],
    status: str,
    command_line: str,
    out_root: Path,
) -> None:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    checks_txt = evidence_dir / "checks.txt"
    summary_md = evidence_dir / "summary.md"
    qc_copy = evidence_dir / qc_path.name
    runs_copy = evidence_dir / runs_path.name
    qc_copy.write_bytes(qc_path.read_bytes())
    runs_copy.write_bytes(runs_path.read_bytes())
    reportlets_dir = evidence_dir / "reportlets"
    reportlets_dir.mkdir(parents=True, exist_ok=True)
    reportlet_paths = []
    for run in runs:
        reportlets = run.get("reportlets") or {}
        for rel in reportlets.values():
            if not rel:
                continue
            path = out_root / rel if not Path(rel).is_absolute() else Path(rel)
            if not path.exists():
                continue
            destination = reportlets_dir / path.name
            _copy_file(path, destination)
            reportlet_paths.append(destination)
    checks_txt.write_text(f"{command_line}\nstatus={status}\n", encoding="utf-8")
    summary_md.write_text(
        "\n".join(
            [
                "# S2_anat_cordref evidence",
                "",
                f"Status: {status}",
                "",
                "Artifacts:",
                f"- {qc_copy}",
                f"- {runs_copy}",
                *[f"- {path}" for path in reportlet_paths],
                "",
            ]
        ),
        encoding="utf-8",
    )


def _compute_label_metrics(label_path: Path) -> dict:
    img = cast(Any, nib.load(label_path))
    data = img.get_fdata()
    if data.ndim > 3:
        data = data[..., 0]
    labels = np.unique(data.astype(int))
    labels = labels[labels > 0]
    label_count = int(labels.size)
    return {
        "label_count": label_count,
        "label_min": int(labels.min()) if label_count else None,
        "label_max": int(labels.max()) if label_count else None,
    }


def _validate_vertebral_label_outputs(
    vertebral_labels_path: Optional[Path],
    disc_labels_path: Optional[Path],
    cordmask_path: Optional[Path],
    min_disc_labels: int = 2,
) -> tuple[bool, list[str]]:
    """
    Validate vertebral labeling outputs for consistency and basic sanity.
    
    Args:
        vertebral_labels_path: Path to vertebral level labels NIfTI
        disc_labels_path: Path to disc labels NIfTI
        cordmask_path: Path to cordmask segmentation (for overlap check)
        min_disc_labels: Minimum number of disc labels required
    
    Returns:
        (is_valid, list_of_reasons) where reasons are empty if valid, or describe failures
    """
    reasons = []
    
    if disc_labels_path is None or not disc_labels_path.exists():
        reasons.append("Disc labels file missing")
        return False, reasons
    
    if vertebral_labels_path is None or not vertebral_labels_path.exists():
        reasons.append("Vertebral labels file missing")
        return False, reasons
    
    try:
        disc_img = cast(Any, nib.load(disc_labels_path))
        disc_data = disc_img.get_fdata()
        if disc_data.ndim > 3:
            disc_data = disc_data[..., 0]
        
        # Check disc labels are non-empty
        disc_mask = disc_data > 0
        if not disc_mask.any():
            reasons.append("Disc labels mask is empty")
            return False, reasons
        
        # Check disc label count
        disc_labels = np.unique(disc_data.astype(int))
        disc_labels = disc_labels[disc_labels > 0]
        disc_count = int(disc_labels.size)
        if disc_count < min_disc_labels:
            reasons.append(f"Too few disc labels: {disc_count} < {min_disc_labels}")
            return False, reasons
        
        # Check monotonic SI ordering: disc labels should progress along z
        # Extract z-coordinates for each disc label value
        disc_z_by_label = {}
        for label_val in disc_labels:
            coords = np.argwhere(disc_data == label_val)
            if coords.size > 0:
                z_coords = coords[:, 2]  # z is third dimension (RPI orientation)
                disc_z_by_label[int(label_val)] = float(np.median(z_coords))
        
        if len(disc_z_by_label) >= 2:
            # Check that labels are ordered by z (allowing some tolerance for noise)
            sorted_by_z = sorted(disc_z_by_label.items(), key=lambda x: x[1])
            sorted_labels = [x[0] for x in sorted_by_z]
            # Labels should be monotonically increasing (or at least not wildly out of order)
            # Allow some flexibility: if we have labels [3,4,5] but z order is [4,3,5], that's suspicious
            # Simple check: if label values are mostly increasing with z, that's good
            label_diffs = [sorted_labels[i+1] - sorted_labels[i] for i in range(len(sorted_labels)-1)]
            if any(d < 0 for d in label_diffs):
                # Some labels are out of order (e.g., label 5 appears before label 4 in z)
                # This is suspicious but not necessarily fatal - just warn
                reasons.append(f"Disc labels show non-monotonic z-ordering (may indicate labeling error)")
        
        # Check vertebral labels overlap cordmask (basic sanity)
        if cordmask_path is not None and cordmask_path.exists():
            try:
                vert_img = cast(Any, nib.load(vertebral_labels_path))
                vert_data = vert_img.get_fdata()
                if vert_data.ndim > 3:
                    vert_data = vert_data[..., 0]
                
                cordmask_img = cast(Any, nib.load(cordmask_path))
                cordmask_data = cordmask_img.get_fdata()
                if cordmask_data.ndim > 3:
                    cordmask_data = cordmask_data[..., 0]
                
                # Check shapes match (or at least compatible)
                if vert_data.shape != cordmask_data.shape:
                    reasons.append(f"Shape mismatch: vertebral labels {vert_data.shape} vs cordmask {cordmask_data.shape}")
                    return False, reasons
                
                # Check overlap: vertebral labels should overlap cordmask
                vert_mask = vert_data > 0
                cordmask_mask = cordmask_data > 0
                overlap = (vert_mask & cordmask_mask).sum()
                cordmask_voxels = cordmask_mask.sum()
                
                if cordmask_voxels > 0:
                    overlap_ratio = float(overlap) / float(cordmask_voxels)
                    if overlap_ratio < 0.1:  # Less than 10% overlap is suspicious
                        reasons.append(f"Low overlap between vertebral labels and cordmask: {overlap_ratio:.1%}")
                else:
                    reasons.append("Cordmask is empty (cannot validate overlap)")
            except Exception as e:
                # Non-fatal: if we can't check overlap, just note it
                reasons.append(f"Could not check vertebral-cordmask overlap: {e}")
        
    except Exception as e:
        reasons.append(f"Validation error: {e}")
        return False, reasons
    
    return True, reasons


def _check_labeling_consistency(
    sct_labels_path: Optional[Path],
    template_levels_path: Optional[Path],
    cordmask_path: Optional[Path],
    enabled: bool = True,
    max_mismatch_percent: float = 30.0,
    min_slices_for_decision: int = 10,
) -> tuple[str, list[str], Optional[dict]]:
    """
    Check consistency between SCT vertebral labels and template-derived levels.
    
    Detects:
    - Global offset (consistent +1/-1 shift across all slices)
    - Single jump (offset changes at one z-slice, indicating a missed/spurious disc)
    
    Args:
        sct_labels_path: Path to SCT vertebral labels (from sct_label_vertebrae)
        template_levels_path: Path to template-derived vertebral levels
        cordmask_path: Path to cordmask (for masking)
        enabled: Whether consistency checking is enabled
        max_mismatch_percent: Maximum allowed mismatch percentage before WARN
        min_slices_for_decision: Minimum number of slices needed for reliable decision
    
    Returns:
        Tuple of (qc_status, qc_reasons, consistency_metrics)
        qc_status: "PASS" | "WARN"
        qc_reasons: List of reason strings
        consistency_metrics: Optional dict with offset_mode, jump_z, jump_level_estimate, mismatch_rate
    """
    if not enabled:
        return "PASS", [], None
    
    if sct_labels_path is None or not sct_labels_path.exists():
        return "PASS", [], None  # No SCT labels to compare
    
    if template_levels_path is None or not template_levels_path.exists():
        return "PASS", [], None  # No template levels to compare
    
    if cordmask_path is None or not cordmask_path.exists():
        return "PASS", [], None  # No cordmask for masking
    
    try:
        sct_img = nib.as_closest_canonical(nib.load(sct_labels_path))
        template_img = nib.as_closest_canonical(nib.load(template_levels_path))
        cordmask_img = nib.as_closest_canonical(nib.load(cordmask_path))
        
        sct_data = sct_img.get_fdata()
        template_data = template_img.get_fdata()
        cordmask_data = cordmask_img.get_fdata()
        
        if sct_data.ndim > 3:
            sct_data = sct_data[..., 0]
        if template_data.ndim > 3:
            template_data = template_data[..., 0]
        if cordmask_data.ndim > 3:
            cordmask_data = cordmask_data[..., 0]
        
        if sct_data.shape != template_data.shape or sct_data.shape != cordmask_data.shape:
            return "PASS", [], None  # Shape mismatch, skip check
        
        # Mask to cord region only
        cordmask = cordmask_data > 0.5
        if not cordmask.any():
            return "PASS", [], None
        
        # Compute per-slice dominant level for both SCT and template
        z_slices = np.where(cordmask.any(axis=(0, 1)))[0]
        if len(z_slices) < min_slices_for_decision:
            return "PASS", [], None
        
        sct_dominant_by_z = []
        template_dominant_by_z = []
        
        for z in z_slices:
            sct_slice = sct_data[:, :, z]
            template_slice = template_data[:, :, z]
            mask_slice = cordmask[:, :, z]
            
            if not mask_slice.any():
                continue
            
            # Get dominant label value in this slice (within cordmask)
            sct_masked = sct_slice[mask_slice]
            template_masked = template_slice[mask_slice]
            
            if sct_masked.size == 0 or template_masked.size == 0:
                continue
            
            # Use mode (most frequent value) as dominant level
            sct_values = sct_masked[sct_masked > 0]
            template_values = template_masked[template_masked > 0]
            
            if sct_values.size > 0 and template_values.size > 0:
                sct_mode = int(np.bincount(sct_values.astype(int)).argmax())
                template_mode = int(np.bincount(template_values.astype(int)).argmax())
                
                if sct_mode > 0 and template_mode > 0:
                    sct_dominant_by_z.append((z, sct_mode))
                    template_dominant_by_z.append((z, template_mode))
        
        if len(sct_dominant_by_z) < min_slices_for_decision or len(template_dominant_by_z) < min_slices_for_decision:
            return "PASS", [], None
        
        # Compute offset per slice
        # Match slices by z-coordinate
        sct_dict = dict(sct_dominant_by_z)
        template_dict = dict(template_dominant_by_z)
        common_z = sorted(set(sct_dict.keys()) & set(template_dict.keys()))
        
        if len(common_z) < min_slices_for_decision:
            return "PASS", [], None
        
        offsets = []
        for z in common_z:
            offset = sct_dict[z] - template_dict[z]
            offsets.append((z, offset))
        
        if not offsets:
            return "PASS", [], None
        
        # Detect global offset: if most offsets are the same value
        offset_values = [o[1] for o in offsets]
        offset_mode = int(np.bincount([int(o + 10) for o in offset_values]).argmax() - 10)  # Shift to avoid negative indices
        
        # Count how many slices have the modal offset
        mode_count = sum(1 for o in offset_values if o == offset_mode)
        mode_percent = (mode_count / len(offset_values)) * 100.0
        
        # Detect single jump: if offset changes significantly at one z-slice
        jump_z = None
        jump_level_estimate = None
        if len(offsets) >= 3:
            # Check for a single slice where offset changes
            for i in range(1, len(offsets) - 1):
                prev_offset = offsets[i-1][1]
                curr_offset = offsets[i][1]
                next_offset = offsets[i+1][1]
                
                # If current offset differs from both neighbors by at least 1
                if abs(curr_offset - prev_offset) >= 1 and abs(curr_offset - next_offset) >= 1:
                    # Check if neighbors agree (indicating a jump at current slice)
                    if abs(prev_offset - next_offset) <= 1:
                        jump_z = offsets[i][0]
                        jump_level_estimate = curr_offset
                        break
        
        # Compute mismatch rate (percentage of slices where offset != mode)
        mismatch_count = sum(1 for o in offset_values if o != offset_mode)
        mismatch_rate = (mismatch_count / len(offset_values)) * 100.0
        
        consistency_metrics = {
            "offset_mode": int(offset_mode),
            "mode_percent": float(mode_percent),
            "jump_z": int(jump_z) if jump_z is not None else None,
            "jump_level_estimate": int(jump_level_estimate) if jump_level_estimate is not None else None,
            "mismatch_rate": float(mismatch_rate),
        }
        
        qc_reasons = []
        qc_status = "PASS"
        
        # WARN if global offset detected (systematic shift)
        if abs(offset_mode) >= 1 and mode_percent >= (100.0 - max_mismatch_percent):
            qc_status = "WARN"
            qc_reasons.append(f"Global offset detected: SCT labels shifted by {offset_mode:+d} levels relative to template (affects {mode_percent:.1f}% of slices)")
        
        # WARN if single jump detected (missed/spurious disc)
        # Gate single-jump WARN: only trigger if mismatch rate is elevated OR jump persists across multiple slices
        # This reduces false positives from isolated single-slice discrepancies
        if jump_z is not None:
            # Check if jump persists: count slices with offset != mode around the jump
            jump_persists = False
            if len(offsets) >= 5:
                jump_idx = next((i for i in range(len(offsets)) if offsets[i][0] == jump_z), None)
                if jump_idx is not None:
                    # Check ±2 slices around jump
                    window_start = max(0, jump_idx - 2)
                    window_end = min(len(offsets), jump_idx + 3)
                    window_offsets = [offsets[i][1] for i in range(window_start, window_end)]
                    # If most offsets in window differ from mode, jump persists
                    window_mismatch = sum(1 for o in window_offsets if o != offset_mode)
                    jump_persists = window_mismatch >= len(window_offsets) * 0.6  # 60% threshold
            
            # Only WARN if mismatch rate is elevated OR jump persists
            if mismatch_rate > max_mismatch_percent * 0.5 or jump_persists:
                qc_status = "WARN"
                qc_reasons.append(f"Single jump detected at z={jump_z}: offset changes by {jump_level_estimate:+d} levels (likely missed/spurious disc)")
        
        # WARN if high mismatch rate (inconsistent labeling)
        if mismatch_rate > max_mismatch_percent:
            qc_status = "WARN"
            qc_reasons.append(f"High mismatch rate: {mismatch_rate:.1f}% of slices disagree with template levels")
        
        return qc_status, qc_reasons, consistency_metrics
    
    except Exception:  # noqa: BLE001
        # If consistency check fails, don't gate the run (non-gating WARN)
        return "PASS", [], None


def _estimate_initcenter_from_disc_labels(disc_labels_path: Path) -> Optional[int]:
    """
    Estimate initcenter value from disc labels by finding the disc label closest to mid-z.
    
    This matches SCT's semantics: -initcenter means "disc value at the center of z-FOV".
    
    Args:
        disc_labels_path: Path to disc labels NIfTI file
    
    Returns:
        Disc label value (int) closest to mid-z, or None if cannot be determined
    """
    try:
        disc_img = cast(Any, nib.load(disc_labels_path))
        disc_data = disc_img.get_fdata()
        if disc_data.ndim > 3:
            disc_data = disc_data[..., 0]
        
        # Get z dimension
        nz = disc_data.shape[2]
        z_center = round(nz / 2)
        
        # Find disc labels and their z-coordinates
        disc_labels = np.unique(disc_data.astype(int))
        disc_labels = disc_labels[disc_labels > 0]
        
        if disc_labels.size == 0:
            return None
        
        # For each disc label, find its median z-coordinate
        disc_z_by_label = {}
        for label_val in disc_labels:
            coords = np.argwhere(disc_data == label_val)
            if coords.size > 0:
                z_coords = coords[:, 2]  # z is third dimension (RPI orientation)
                disc_z_by_label[int(label_val)] = float(np.median(z_coords))
        
        if not disc_z_by_label:
            return None
        
        # Find the disc label whose z-coordinate is closest to z_center
        closest_label = min(
            disc_z_by_label.items(),
            key=lambda x: abs(x[1] - z_center)
        )[0]
        
        return int(closest_label)
    except Exception:
        return None


def _find_first(folder: Path, pattern: str) -> Optional[Path]:
    matches = sorted(folder.glob(pattern))
    return matches[0] if matches else None


def _find_rootlets_output(folder: Path, base: Path) -> Optional[Path]:
    candidates = sorted(folder.glob("*.nii.gz"))
    for candidate in candidates:
        if "rootlets" in candidate.name:
            return candidate
    expected = Path(str(base) + ".nii.gz")
    if expected.exists():
        return expected
    return candidates[0] if candidates else None


def _derivatives_xfm_dir(out_root: Path, subject: str, session: Optional[str]) -> Path:
    if session:
        return out_root / "derivatives" / "spinalfmriprep" / f"sub-{subject}" / f"ses-{session}" / "xfm"
    return out_root / "derivatives" / "spinalfmriprep" / f"sub-{subject}" / "xfm"


def _format_xfm_name(subject: str, session: Optional[str], suffix: str) -> str:
    if session:
        return f"sub-{subject}_ses-{session}_{suffix}.nii.gz"
    return f"sub-{subject}_{suffix}.nii.gz"
