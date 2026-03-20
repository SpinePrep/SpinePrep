"""Batch processing entry points: run_S2_anat_cordref_batch, reportlets_only_batch."""
from __future__ import annotations

import json
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

from .io import (
    StepResult,
    _write_runs_jsonl,
    _read_runs_jsonl,
    _write_json,
    _append_metrics,
    _format_command_line,
    _format_run_id,
)
from .policy import _load_policy
from .session import (
    _collect_anat_candidates,
    _collect_subject_sessions,
    _process_single_session_batch_worker,
    _summarise_runs,
)
from .reportlets import _render_reportlets_for_runs


def run_S2_anat_cordref_reportlets_only_batch(
    dataset_keys: list[str],
    out_base: Path,
) -> dict[str, StepResult]:
    """
    Regenerate only QC reportlets for multiple datasets, skipping all processing.

    This is the batch version of run_S2_anat_cordref_reportlets_only.
    """
    from .orchestrate import run_S2_anat_cordref_reportlets_only

    results: dict[str, StepResult] = {}

    aggregate_runs_path = out_base / "logs" / "S2_anat_cordref_runs.jsonl"
    if not aggregate_runs_path.exists():
        for ds_key in dataset_keys:
            result = run_S2_anat_cordref_reportlets_only(
                dataset_key=ds_key, datasets_local=None, bids_root=None, out=out_base,
            )
            results[ds_key] = result
        from spinalfmriprep.qc_dashboard import generate_dashboard_safe
        generate_dashboard_safe(out_base)
        return results

    try:
        all_runs = _read_runs_jsonl(aggregate_runs_path)
    except Exception as err:
        for ds_key in dataset_keys:
            results[ds_key] = StepResult(
                status="FAIL", failure_message=f"Failed to read aggregate runs.jsonl: {err}",
            )
        return results

    policy_path = Path("policy") / "S2_anat_cordref.yaml"
    try:
        policy = _load_policy(policy_path)
    except ValueError as err:
        for ds_key in dataset_keys:
            results[ds_key] = StepResult(status="FAIL", failure_message=str(err))
        return results

    for ds_key in dataset_keys:
        dataset_runs = [r for r in all_runs if r.get("dataset_key") == ds_key]
        if not dataset_runs:
            results[ds_key] = StepResult(
                status="FAIL",
                failure_message=f"No runs found for dataset_key={ds_key} in {aggregate_runs_path}",
            )
            continue
        dataset_runs = _render_reportlets_for_runs(runs=dataset_runs, out_root=out_base, dataset_key=ds_key)

        inventory_path = out_base / "work" / "S1_input_verify" / ds_key / "bids_inventory.json"
        if inventory_path.exists():
            try:
                inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
            except Exception:
                inventory = {"dataset_key": ds_key, "bids_root": "unknown"}
        else:
            inventory = {"dataset_key": ds_key, "bids_root": "unknown"}

        qc_path = out_base / "logs" / "S2_anat_cordref" / ds_key / "qc.json"
        qc_path.parent.mkdir(parents=True, exist_ok=True)
        qc = _summarise_runs(inventory, policy_path, dataset_runs)
        _write_json(qc_path, qc)

        results[ds_key] = StepResult(
            status=qc.get("status", "PASS"),
            failure_message=qc.get("failure_message"),
            qc_path=qc_path,
        )

    updated_runs = []
    processed_keys = set(dataset_keys)
    for run in all_runs:
        if run.get("dataset_key") not in processed_keys:
            updated_runs.append(run)
    for ds_key in dataset_keys:
        dataset_runs = [r for r in all_runs if r.get("dataset_key") == ds_key]
        dataset_runs = _render_reportlets_for_runs(runs=dataset_runs, out_root=out_base, dataset_key=ds_key)
        updated_runs.extend(dataset_runs)

    _write_runs_jsonl(aggregate_runs_path, updated_runs)

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
    """
    inventory_base = s1_base if s1_base else out_base

    all_sessions = []
    dataset_inventories = {}

    for dk in dataset_keys:
        inventory_path = inventory_base / "work" / "S1_input_verify" / dk / "bids_inventory.json"
        if not inventory_path.exists():
            continue
        inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
        dataset_inventories[dk] = inventory
        bids_root_path = Path(inventory["bids_root"])
        candidates = _collect_anat_candidates(inventory)
        sessions_set = _collect_subject_sessions(inventory)
        for subject, session in sessions_set:
            key = (subject, session)
            all_sessions.append({
                "dataset_key": dk,
                "subject": subject,
                "session": session,
                "bids_root": str(bids_root_path),
                "out_root": str(out_base),
                "candidates": candidates.get(key, []),
            })

    if not all_sessions:
        return {
            key: StepResult(status="FAIL", failure_message="No sessions found in any dataset")
            for key in dataset_keys
        }

    for sess in all_sessions:
        candidates_str = []
        for cand in sess["candidates"]:
            cand_copy = cand.copy()
            if "path" in cand_copy and isinstance(cand_copy["path"], Path):
                cand_copy["path"] = str(cand_copy["path"])
            candidates_str.append(cand_copy)
        sess["candidates"] = candidates_str

    all_runs: dict[str, list[dict]] = {}
    all_runs_flat: list[dict] = []
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        future_to_session = {
            executor.submit(_process_single_session_batch_worker, sess): sess
            for sess in all_sessions
        }
        for future in as_completed(future_to_session):
            sess = future_to_session[future]
            try:
                dk, subject, session, run = future.result()
                run["dataset_key"] = dk
                run["command_line"] = _format_command_line(
                    dataset_key=dk, datasets_local=datasets_local, bids_root=None, out=out_base,
                )
                if dk not in all_runs:
                    all_runs[dk] = []
                all_runs[dk].append(run)
                all_runs_flat.append(run)
            except Exception as e:  # noqa: BLE001
                import traceback
                dk = sess["dataset_key"]
                error_msg = f"Session processing error: {e}"
                error_trace = traceback.format_exc()
                run = {
                    "dataset_key": dk,
                    "subject": sess["subject"],
                    "session": sess["session"],
                    "status": "FAIL",
                    "failure_message": error_msg,
                    "error_traceback": error_trace,
                    "run_id": _format_run_id(sess["subject"], sess["session"]),
                }
                if dk not in all_runs:
                    all_runs[dk] = []
                all_runs[dk].append(run)
                all_runs_flat.append(run)

    policy_path = Path("policy") / "S2_anat_cordref.yaml"
    for dk in list(all_runs.keys()):
        dk_runs = all_runs[dk]
        dk_runs = _render_reportlets_for_runs(runs=dk_runs, out_root=out_base, dataset_key=dk)
        all_runs[dk] = dk_runs

    all_runs_flat = []
    for dk in dataset_keys:
        if dk in all_runs:
            all_runs_flat.extend(all_runs[dk])

    runs_path = out_base / "logs" / "S2_anat_cordref_runs.jsonl"
    runs_path.parent.mkdir(parents=True, exist_ok=True)
    _write_runs_jsonl(runs_path, all_runs_flat)

    results = {}
    for dk in dataset_keys:
        if dk not in all_runs:
            results[dk] = StepResult(status="FAIL", failure_message="No sessions processed for this dataset")
            continue
        dk_runs = all_runs[dk]
        if dk not in dataset_inventories:
            results[dk] = StepResult(status="FAIL", failure_message="Inventory not found for this dataset")
            continue
        inventory = dataset_inventories[dk]
        qc_dir = out_base / "logs" / "S2_anat_cordref" / dk
        qc_dir.mkdir(parents=True, exist_ok=True)
        qc_path = qc_dir / "qc.json"
        qc = _summarise_runs(inventory, policy_path, dk_runs)
        qc["dataset_key"] = dk
        _write_json(qc_path, qc)

        metrics_path = out_base / "logs" / "metrics" / "summary.jsonl"
        _append_metrics(metrics_path, dk, dk_runs)

        status = qc.get("status", "FAIL")
        failure_message = qc.get("failure_message")
        results[dk] = StepResult(
            status=status, failure_message=failure_message,
            runs_path=runs_path, qc_path=qc_path,
        )

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

    from spinalfmriprep.qc_dashboard import generate_dashboard_safe
    generate_dashboard_safe(out_base)

    return results
