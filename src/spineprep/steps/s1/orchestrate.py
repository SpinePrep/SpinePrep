"""Public API entry points: run, check, batch, and dataset resolution helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from spineprep.policy import DatasetPolicyError, load_dataset_policy

from .inventory import _build_inventory
from .validate import _summarise_inventory, _validate_json, _validate_runs_jsonl


@dataclass
class StepResult:
    status: str
    failure_message: Optional[str]
    inventory_path: Optional[Path] = None
    runs_path: Optional[Path] = None
    qc_path: Optional[Path] = None
    fix_plan_path: Optional[Path] = None


def run_S1_input_verify(
    dataset_key: Optional[str],
    datasets_local: Optional[Path],
    bids_root: Optional[Path],
    out: Optional[Path],
) -> StepResult:
    command_line = _format_command_line(dataset_key, datasets_local, bids_root, out)
    try:
        resolved_bids_root = _resolve_bids_root(dataset_key, datasets_local, bids_root)
    except ValueError as err:
        return StepResult(status="FAIL", failure_message=str(err))

    if out is None:
        return StepResult(status="FAIL", failure_message="--out is required for S1_input_verify")

    policy_entry = _load_policy_entry(dataset_key)
    inventory = _build_inventory(resolved_bids_root, dataset_key or "ad_hoc", policy_entry)
    # Per-dataset work directory to support multi-dataset validation
    ds_key = dataset_key or "ad_hoc"
    work_dir = Path(out) / "work" / "S1_input_verify" / ds_key
    work_dir.mkdir(parents=True, exist_ok=True)
    inventory_path = work_dir / "bids_inventory.json"
    _write_json(inventory_path, inventory)

    # Per-dataset logs directory
    logs_dir = Path(out) / "logs" / "S1_input_verify" / ds_key
    logs_dir.mkdir(parents=True, exist_ok=True)
    runs_path = logs_dir / "runs.jsonl"
    qc_path = logs_dir / "qc.json"
    fix_plan_path = work_dir / "fix_plan.yaml"

    runs, qc_summary, fix_plan = _summarise_inventory(inventory, policy_entry)
    _write_runs_jsonl(runs_path, runs)

    # Diagnostic reportlet — one PNG per dataset (SpinePrep
    # dev principle §4). Path is recorded in qc.json under
    # ``reportlets`` so the dashboard discovers it like every other step.
    out_resolved = Path(out).resolve()
    # S1 emits an HTML report (pure tabular data — no imaging viz to
    # rasterize). Lives under derivatives/.../_S1/.../reports/ to keep
    # `figures/` reserved for actual PNG/SVG imaging reportlets.
    reports_dir = (out_resolved / "derivatives" / "spineprep" / "_S1"
                   / ds_key / "reports")
    reports_dir.mkdir(parents=True, exist_ok=True)
    reportlet_path = reports_dir / f"{ds_key}_desc-S1_dataset_summary.html"
    try:
        from .reportlets import render_s1_dataset_summary
        render_s1_dataset_summary(inventory, qc_summary, reportlet_path)
    except Exception:
        pass

    # S1 has no per-run reportlet array; the dashboard scans the
    # top-level ``reportlets`` plus a synthetic "summary" entry under
    # ``runs`` so the dataset-level PNG shows up in the gallery.
    rel_path = str(reportlet_path.relative_to(out_resolved)) \
        if reportlet_path.exists() else None
    if rel_path:
        qc_summary["reportlets"] = {"dataset_summary": rel_path}
        qc_summary["runs"] = [{
            "subject": "all",
            "session": None,
            "run_id": ds_key,
            "status": qc_summary.get("status", "UNKNOWN"),
            "reportlets": {"dataset_summary": rel_path},
        }]
    _write_json(qc_path, qc_summary)
    _write_fix_plan(fix_plan_path, fix_plan)

    status = qc_summary.get("status", "FAIL")
    failure_message = qc_summary.get("failure_message")

    evidence_dir = logs_dir / "S1_evidence" / (dataset_key or "ad_hoc")
    evidence_dir.mkdir(parents=True, exist_ok=True)
    _write_evidence(
        evidence_dir=evidence_dir,
        qc_path=qc_path,
        runs_path=runs_path,
        inventory_path=inventory_path,
        fix_plan_path=fix_plan_path,
        status=status,
        command_line=command_line,
    )

    # Generate dashboard (non-blocking)
    from spineprep.qc_dashboard import generate_dashboard_safe
    generate_dashboard_safe(Path(out))

    return StepResult(
        status=status,
        failure_message=failure_message,
        inventory_path=inventory_path,
        runs_path=runs_path,
        qc_path=qc_path,
        fix_plan_path=fix_plan_path,
    )


def check_S1_input_verify(
    dataset_key: Optional[str],
    datasets_local: Optional[Path],
    bids_root: Optional[Path],
    out: Optional[Path],
) -> StepResult:
    if out is None:
        return StepResult(status="FAIL", failure_message="--out is required for S1_input_verify")
    ds_key = dataset_key or "ad_hoc"
    inventory_path = Path(out) / "work" / "S1_input_verify" / ds_key / "bids_inventory.json"
    runs_path = Path(out) / "logs" / "S1_input_verify" / ds_key / "runs.jsonl"
    qc_path = Path(out) / "logs" / "S1_input_verify" / ds_key / "qc.json"
    fix_plan_path = Path(out) / "work" / "S1_input_verify" / ds_key / "fix_plan.yaml"

    required = (inventory_path, runs_path, qc_path, fix_plan_path)
    missing = [p for p in required if not p.exists() or p.stat().st_size == 0]
    if missing:
        return StepResult(
            status="FAIL",
            failure_message=f"Missing required artifact(s): {', '.join(str(p) for p in missing)}",
            inventory_path=inventory_path,
            runs_path=runs_path,
            qc_path=qc_path,
            fix_plan_path=fix_plan_path,
        )

    try:
        resolved_bids_root = _resolve_bids_root(dataset_key, datasets_local, bids_root)
    except ValueError as err:
        return StepResult(status="FAIL", failure_message=str(err))

    try:
        with inventory_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as err:  # noqa: BLE001
        return StepResult(status="FAIL", failure_message=f"Failed to read inventory: {err}")

    if dataset_key and data.get("dataset_key") != dataset_key:
        return StepResult(status="FAIL", failure_message="Inventory dataset_key mismatch.")

    if data.get("bids_root") != str(resolved_bids_root):
        return StepResult(status="FAIL", failure_message="Inventory bids_root mismatch.")

    try:
        _validate_json(qc_path, Path("schemas/qc_S1_input_verify.json"))
        _validate_runs_jsonl(runs_path, Path("schemas/runs_S1_input_verify.json"))
    except ValueError as err:
        return StepResult(status="FAIL", failure_message=str(err), inventory_path=inventory_path)

    try:
        fix_plan = yaml.safe_load(fix_plan_path.read_text(encoding="utf-8")) or {}
    except Exception as err:  # noqa: BLE001
        return StepResult(status="FAIL", failure_message=f"Failed to read fix plan: {err}")
    if not isinstance(fix_plan, dict) or "issues" not in fix_plan:
        return StepResult(status="FAIL", failure_message="Malformed fix plan.", fix_plan_path=fix_plan_path)

    return StepResult(
        status="PASS",
        failure_message=None,
        inventory_path=inventory_path,
        runs_path=runs_path,
        qc_path=qc_path,
        fix_plan_path=fix_plan_path,
    )


def run_S1_input_verify_batch(
    dataset_keys: List[str],
    datasets_local: Optional[Path],
    out_base: Path,
) -> Dict[str, StepResult]:
    """
    Run S1_input_verify on multiple datasets.

    All datasets write to the same out_base, with per-dataset subdirectories.
    Dashboard is generated once at the end.
    """
    results: Dict[str, StepResult] = {}

    for ds_key in dataset_keys:
        result = run_S1_input_verify(
            dataset_key=ds_key,
            datasets_local=datasets_local,
            bids_root=None,
            out=out_base,
        )
        results[ds_key] = result

    # Regenerate dashboard once after all datasets
    from spineprep.qc_dashboard import generate_dashboard_safe
    generate_dashboard_safe(out_base)

    return results


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _format_command_line(
    dataset_key: Optional[str],
    datasets_local: Optional[Path],
    bids_root: Optional[Path],
    out: Optional[Path],
) -> str:
    parts = ["poetry", "run", "spineprep", "run", "S1_input_verify"]
    if dataset_key:
        parts.extend(["--dataset-key", str(dataset_key)])
    if datasets_local:
        parts.extend(["--datasets-local", str(datasets_local)])
    if bids_root:
        parts.extend(["--bids-root", str(bids_root)])
    if out:
        parts.extend(["--out", str(out)])
    return " ".join(parts)


def _load_policy_entry(dataset_key: Optional[str]):
    if dataset_key is None:
        return None
    # Ad-hoc datasets (BIDS-App on an unregistered bids_dir) carry a synthetic
    # key and have no policy spec — run without one (no fmap/physio expectation
    # checks). Registered-style keys must still exist, so a typo still errors.
    if dataset_key.startswith(("bidsapp_", "ad_hoc", "adhoc")):
        return None
    try:
        policy = load_dataset_policy(Path("policy") / "datasets.yaml")
    except DatasetPolicyError as err:
        raise ValueError(str(err)) from err
    for entry in policy.datasets:
        if entry.key == dataset_key:
            return entry
    raise ValueError(f"Dataset key '{dataset_key}' not found in policy/datasets.yaml")


def _resolve_bids_root(
    dataset_key: Optional[str],
    datasets_local: Optional[Path],
    bids_root: Optional[Path],
) -> Path:
    if bids_root:
        return bids_root.resolve()

    if dataset_key is None:
        raise ValueError("Provide --dataset-key with mapping or --bids-root for S1_input_verify")

    try:
        policy = load_dataset_policy(Path("policy") / "datasets.yaml")
    except DatasetPolicyError as err:
        raise ValueError(str(err)) from err
    all_keys = {entry.key for entry in policy.datasets}
    if dataset_key not in all_keys:
        raise ValueError(f"Dataset key '{dataset_key}' not found in policy/datasets.yaml")

    if datasets_local is None:
        raise ValueError("Provide --datasets-local mapping or --bids-root to resolve dataset path.")
    if not datasets_local.exists():
        raise ValueError(f"datasets_local mapping not found: {datasets_local}")

    with datasets_local.open("r", encoding="utf-8") as f:
        mapping = yaml.safe_load(f) or {}
    if dataset_key not in mapping:
        raise ValueError(f"Dataset key '{dataset_key}' not found in {datasets_local}")

    root = Path(mapping[dataset_key]).expanduser()
    if not root.exists():
        raise ValueError(f"BIDS root for '{dataset_key}' not found at {root}")

    return root.resolve()


def _write_json(path: Path, payload: dict) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")


def _write_runs_jsonl(path: Path, runs: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for record in runs:
            f.write(json.dumps(record, sort_keys=True))
            f.write("\n")


def _write_fix_plan(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(payload, f, sort_keys=True)


def _write_evidence(
    evidence_dir: Path,
    qc_path: Path,
    runs_path: Path,
    inventory_path: Path,
    fix_plan_path: Path,
    status: str,
    command_line: str,
) -> None:
    checks_txt = evidence_dir / "checks.txt"
    summary_md = evidence_dir / "summary.md"

    exit_code = 0 if status in {"PASS", "WARN"} else 1
    checks_txt.write_text(f"{command_line}: {exit_code}\n", encoding="utf-8")
    summary_md.write_text(
        "\n".join(
            [
                "# S1_input_verify evidence",
                f"Status: {status}",
                "",
                "Artifacts:",
                f"- {qc_path}",
                f"- {runs_path}",
                f"- {inventory_path}",
                f"- {fix_plan_path}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    for source in (qc_path, runs_path, inventory_path, fix_plan_path):
        destination = evidence_dir / source.name
        destination.write_bytes(source.read_bytes())
