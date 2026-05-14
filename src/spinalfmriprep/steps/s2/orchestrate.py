"""Public API entry points: run, check, reportlets-only, and batch (re-exported)."""
from __future__ import annotations

import json
from concurrent.futures import ProcessPoolExecutor, as_completed
from functools import partial
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
    _process_session,
    _process_session_worker,
    _summarise_runs,
)
from .reportlets import _render_reportlets_for_runs
from .validate import _validate_json, _write_evidence

# Re-export batch functions so __init__.py can import from orchestrate
from .batch import run_S2_anat_cordref_batch, run_S2_anat_cordref_reportlets_only_batch  # noqa: F401


def run_S2_anat_cordref(
    dataset_key: Optional[str],
    datasets_local: Optional[Path],
    bids_root: Optional[Path],
    out: Optional[Path],
) -> StepResult:
    command_line = _format_command_line(dataset_key, datasets_local, bids_root, out)
    if out is None:
        return StepResult(status="FAIL", failure_message="--out is required for S2_anat_cordref")

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

    # Per-dataset qc/runs paths (primary). Also keep the legacy aggregate
    # filenames in sync at the end of the run for back-compat with
    # `check_S2_anat_cordref` and historical consumers.
    per_dataset_runs_path = Path(out) / "logs" / "S2_anat_cordref" / ds_key / "runs.jsonl"
    per_dataset_qc_path = Path(out) / "logs" / "S2_anat_cordref" / ds_key / "qc.json"
    per_dataset_runs_path.parent.mkdir(parents=True, exist_ok=True)
    runs_path = per_dataset_runs_path
    qc_path = per_dataset_qc_path

    candidates = _collect_anat_candidates(inventory)
    sessions = _collect_subject_sessions(inventory)

    max_workers = 1
    runs = []
    sorted_sessions = sorted(sessions)

    if len(sorted_sessions) == 1 or max_workers == 1:
        for key in sorted_sessions:
            subject, session = key
            run = _process_session(
                subject=subject, session=session,
                candidates=candidates.get(key, []),
                bids_root=bids_root_path, out_root=Path(out), policy=policy,
                dataset_key=dataset_key,
            )
            run["command_line"] = command_line
            runs.append(run)
    else:
        candidates_str = {}
        for key, cand_list in candidates.items():
            candidates_str[key] = []
            for cand in cand_list:
                cand_copy = cand.copy()
                if "path" in cand_copy and isinstance(cand_copy["path"], Path):
                    cand_copy["path"] = str(cand_copy["path"])
                candidates_str[key].append(cand_copy)

        _process_session_partial = partial(
            _process_session_worker,
            candidates=candidates_str,
            bids_root=str(bids_root_path),
            out_root=str(Path(out)),
            policy=policy,
            dataset_key=dataset_key,
        )

        future_to_key = {}
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            for key in sorted_sessions:
                subject, session = key
                future = executor.submit(
                    _process_session_partial, subject=subject, session=session,
                )
                future_to_key[future] = key

            results_dict = {}
            for future in as_completed(future_to_key):
                key = future_to_key[future]
                try:
                    run = future.result()
                    run["command_line"] = command_line
                    results_dict[key] = run
                except Exception as e:  # noqa: BLE001
                    subject, session = key
                    run_id = _format_run_id(subject, session)
                    results_dict[key] = {
                        "subject": subject, "session": session,
                        "status": "FAIL",
                        "failure_message": f"Parallel processing error: {e}",
                        "run_id": run_id, "command_line": command_line,
                    }

        runs = [results_dict[key] for key in sorted_sessions]

    runs = _render_reportlets_for_runs(
        runs=runs, out_root=Path(out),
        dataset_key=dataset_key or inventory.get("dataset_key") or "ad_hoc",
    )

    _write_runs_jsonl(runs_path, runs)

    qc = _summarise_runs(inventory, policy_path, runs)
    _write_json(qc_path, qc)

    # Back-compat: keep the legacy aggregate file in sync with this dataset's
    # latest content so `check_S2_anat_cordref` and any historical consumers
    # still resolve. Per-dataset is the source of truth.
    legacy_runs = Path(out) / "logs" / "S2_anat_cordref_runs.jsonl"
    legacy_qc = Path(out) / "logs" / "S2_anat_cordref_qc.json"
    _write_runs_jsonl(legacy_runs, runs)
    _write_json(legacy_qc, qc)

    status = qc.get("status", "FAIL")
    failure_message = qc.get("failure_message")

    metrics_path = Path(out) / "logs" / "metrics" / "summary.jsonl"
    _append_metrics(metrics_path, inventory.get("dataset_key"), runs)

    evidence_dir = Path(out) / "logs" / "S2_evidence" / (dataset_key or inventory.get("dataset_key") or "ad_hoc")
    _write_evidence(
        evidence_dir=evidence_dir, qc_path=qc_path, runs_path=runs_path,
        runs=runs, status=status, command_line=command_line, out_root=Path(out),
    )

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

    # Prefer per-dataset qc.json + runs.jsonl over the legacy aggregate.
    # The aggregate is overwritten by whichever dataset ran last, so reading
    # it for a different dataset_key gives wrong results (and fails the
    # `qc.dataset_key != dataset_key` gate below).
    ds_key = dataset_key or "ad_hoc"
    per_dataset_runs = Path(out) / "logs" / "S2_anat_cordref" / ds_key / "runs.jsonl"
    per_dataset_qc = Path(out) / "logs" / "S2_anat_cordref" / ds_key / "qc.json"
    aggregate_runs = Path(out) / "logs" / "S2_anat_cordref_runs.jsonl"
    aggregate_qc = Path(out) / "logs" / "S2_anat_cordref_qc.json"
    if per_dataset_qc.exists() and per_dataset_runs.exists():
        runs_path = per_dataset_runs
        qc_path = per_dataset_qc
    else:
        runs_path = aggregate_runs
        qc_path = aggregate_qc

    required = (runs_path, qc_path)
    missing = [p for p in required if not p.exists() or p.stat().st_size == 0]
    if missing:
        return StepResult(
            status="FAIL",
            failure_message=f"Missing required artifact(s): {', '.join(str(p) for p in missing)}",
            runs_path=runs_path, qc_path=qc_path,
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
        required_reportlets = ["cordmask_montage", "totalspineseg_montage", "pam50_reg_overlay"]
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
            runs_path=runs_path, qc_path=qc_path,
        )
    if missing_reportlets:
        return StepResult(
            status="FAIL",
            failure_message=f"Missing required reportlets: {', '.join(missing_reportlets)}",
            runs_path=runs_path, qc_path=qc_path,
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

    ds_key = dataset_key or "ad_hoc"
    runs_path = Path(out) / "logs" / "S2_anat_cordref" / ds_key / "runs.jsonl"
    qc_path = Path(out) / "logs" / "S2_anat_cordref" / ds_key / "qc.json"

    if not runs_path.exists() or runs_path.stat().st_size == 0:
        return StepResult(
            status="FAIL",
            failure_message=f"Missing or empty runs.jsonl: {runs_path}. Run the full step first.",
            runs_path=runs_path, qc_path=qc_path,
        )

    inventory_path = Path(out) / "work" / "S1_input_verify" / ds_key / "bids_inventory.json"
    if not inventory_path.exists():
        return StepResult(
            status="FAIL",
            failure_message=f"Missing required inventory: {inventory_path}",
            runs_path=runs_path, qc_path=qc_path,
        )

    try:
        inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    except Exception as err:  # noqa: BLE001
        return StepResult(
            status="FAIL",
            failure_message=f"Failed to read inventory: {err}",
            runs_path=runs_path, qc_path=qc_path,
        )

    policy_path = Path("policy") / "S2_anat_cordref.yaml"
    try:
        policy = _load_policy(policy_path)
    except ValueError as err:
        return StepResult(status="FAIL", failure_message=str(err))

    try:
        runs = _read_runs_jsonl(runs_path)
    except Exception as err:  # noqa: BLE001
        return StepResult(
            status="FAIL",
            failure_message=f"Failed to read runs.jsonl: {err}",
            runs_path=runs_path, qc_path=qc_path,
        )

    if not runs:
        return StepResult(
            status="FAIL",
            failure_message=f"runs.jsonl is empty: {runs_path}",
            runs_path=runs_path, qc_path=qc_path,
        )

    resolved_dataset_key = dataset_key or inventory.get("dataset_key") or "ad_hoc"
    runs = _render_reportlets_for_runs(runs=runs, out_root=Path(out), dataset_key=resolved_dataset_key)

    _write_runs_jsonl(runs_path, runs)

    qc = _summarise_runs(inventory, policy_path, runs)
    _write_json(qc_path, qc)

    status = qc.get("status", "FAIL")
    failure_message = qc.get("failure_message")

    return StepResult(status=status, failure_message=failure_message, runs_path=runs_path, qc_path=qc_path)
