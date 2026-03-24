"""Input validation, fmap/physio checks, and QC summary generation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import nibabel as nib
import numpy as np
from jsonschema import Draft7Validator


def _summarise_inventory(inventory: dict, policy_entry) -> tuple[list[dict], dict, dict]:
    runs = []
    issues: list[dict] = []
    checks: list[dict] = []
    root = Path(inventory["bids_root"])
    subjects = set()
    sessions = set()
    run_records: Dict[str, dict] = {}

    for base_run in inventory.get("runs", []):
        subj = base_run["subject"]
        ses = base_run["session"]
        if subj:
            subjects.add(subj)
        if ses:
            sessions.add(ses)
        run_record = {
            "path": base_run["path"],
            "subject": subj,
            "session": ses,
            "modality": base_run["modality"],
            "classification": base_run["classification"],
        }
        run_record["issues"] = []
        _validate_run_file(root, run_record)
        run_records[run_record["path"]] = run_record

    if not run_records:
        checks.append(
            {
                "name": "any_runs_present",
                "passed": False,
                "severity": "FAIL",
                "message": "No runs detected in BIDS root.",
            }
        )
        issues.append({"severity": "FAIL", "message": "No runs detected in BIDS root."})

    _apply_fieldmap_matching(root, run_records, policy_entry, issues, checks)
    _apply_physio_checks(root, run_records, policy_entry, issues, checks)
    _apply_session_requirements(run_records, checks, issues)

    for run in run_records.values():
        issues_for_run = run.get("issues", [])
        run["status"] = _status_from_issues(issues_for_run)
        if not issues_for_run:
            run.pop("issues", None)

    runs = sorted(run_records.values(), key=lambda r: (r["subject"] or "", r["session"] or "", r["path"]))

    status = _overall_status(checks, runs, issues)
    failure_message = _failure_message(status, checks, issues)

    qc_summary = {
        "dataset_key": inventory["dataset_key"],
        "bids_root": inventory["bids_root"],
        "status": status,
        "failure_message": failure_message,
        "subjects": sorted(subjects),
        "sessions": sorted(sessions),
        "counts": {
            "files": len(inventory.get("files", [])),
            "runs": len(runs),
            "subjects": len(subjects),
            "sessions": len(sessions),
            "classification": _classification_counts(runs),
        },
        "checks": checks,
        "issues": _dedupe_issues(issues),
        "heuristics": {
            "classification": [
                "func bold NIfTI -> cord_likely",
                "anat T1w/T2w NIfTI -> non_cord_likely",
                "fmap NIfTI -> non_cord_likely",
                "physio tsv/tsv.gz containing 'physio' -> non_cord_likely",
            ],
            "derivatives_excluded": True,
        },
    }
    return runs, qc_summary, _build_fix_plan(inventory, runs, issues)


def _validate_run_file(root: Path, run_record: dict) -> None:
    rel_path = Path(run_record["path"])
    abs_path = root / rel_path
    issues = run_record["issues"]

    if not abs_path.exists():
        issues.append({"severity": "FAIL", "message": "File missing on disk"})
        return

    if run_record["modality"] in {"func", "anat", "fmap"} and rel_path.suffix not in {".nii", ".gz", ".nii.gz"}:
        issues.append({"severity": "WARN", "message": "Unexpected file type for imaging run"})

    if run_record["modality"] in {"func", "anat", "fmap"} and abs_path.suffix.endswith((".nii", ".gz")):
        expect_4d = run_record["modality"] == "func" and run_record["classification"] == "cord_likely"
        issues.extend(_validate_nifti(abs_path, expect_4d=expect_4d))


def _apply_session_requirements(run_records: Dict[str, dict], checks: list[dict], issues: list[dict]) -> None:
    by_session: Dict[Tuple[Optional[str], Optional[str]], list[dict]] = {}
    for run in run_records.values():
        key = (run.get("subject"), run.get("session"))
        by_session.setdefault(key, []).append(run)

    for key, runs in by_session.items():
        subject, session = key
        func_present = any(r["classification"] == "cord_likely" and r["modality"] == "func" for r in runs)
        anat_present = any(r["modality"] == "anat" for r in runs)
        checks.append(
            {
                "name": f"{subject or 'unknown'}_{session or 'nosession'}_func_present",
                "passed": func_present,
                "severity": "FAIL",
                "message": "At least one cord fMRI run present.",
            }
        )
        checks.append(
            {
                "name": f"{subject or 'unknown'}_{session or 'nosession'}_anat_present",
                "passed": anat_present,
                "severity": "WARN",
                "message": "At least one anatomical reference present.",
            }
        )
        if not func_present:
            issues.append(
                {
                    "severity": "FAIL",
                    "message": "No cord-likely functional run found.",
                    "subject": subject,
                    "session": session,
                }
        )
        if not anat_present:
            issues.append(
                {
                    "severity": "WARN",
                    "message": "No anatomical reference (T1w/T2w) found.",
                    "subject": subject,
                    "session": session,
                }
            )


def _apply_fieldmap_matching(
    root: Path, run_records: Dict[str, dict], policy_entry, issues: list[dict], checks: list[dict]
) -> None:
    if policy_entry is None:
        return

    fmap_jsons = _gather_fmap_jsons(root)
    fmap_records = fmap_jsons["records"]
    fmap_files = [r for r in run_records.values() if r["modality"] == "fmap"]
    fmap_present = bool(fmap_records or fmap_files)
    issues.extend(fmap_jsons["issues"])
    match_records = list(fmap_records) + [
        {
            "path": fmap_file["path"],
            "subject": fmap_file.get("subject"),
            "session": fmap_file.get("session"),
            "intended_for": [],
        }
        for fmap_file in fmap_files
    ]

    for run in run_records.values():
        if run["modality"] != "func" or run["classification"] != "cord_likely":
            continue
        match = _match_fieldmap(run, match_records)
        if match:
            run.setdefault("details", {})
            run["details"]["fmap_match_method"] = match["method"]
            run["details"]["fmap_ref"] = match["path"]
        elif policy_entry.spec.has_fmap:
            run.setdefault("issues", []).append(
                {"severity": "WARN", "message": "Expected fieldmap match not found."}
            )

    expected = policy_entry.spec.has_fmap
    fmap_check = {
        "name": "fmap_expected",
        "passed": (not expected) or fmap_present,
        "severity": "WARN" if expected else "PASS",
        "message": "Fieldmap expectation satisfied." if fmap_present or not expected else "Expected fieldmap(s) missing.",
    }
    checks.append(fmap_check)
    if expected and not fmap_present:
        issues.append({"severity": "WARN", "message": fmap_check["message"]})


def _apply_physio_checks(
    root: Path, run_records: Dict[str, dict], policy_entry, issues: list[dict], checks: list[dict]
) -> None:
    physio_runs = [r for r in run_records.values() if r["modality"] == "physio"]
    physio_by_session = {(r.get("subject"), r.get("session")) for r in physio_runs}

    for phys_run in physio_runs:
        abs_path = root / phys_run["path"]
        phys_run.setdefault("issues", [])
        phys_run["issues"].extend(_validate_physio_metadata(abs_path))
        if not phys_run["issues"]:
            phys_run.pop("issues")

    if policy_entry is None:
        return

    expected = policy_entry.spec.has_physio
    for run in run_records.values():
        if run["modality"] != "func" or run["classification"] != "cord_likely":
            continue
        key = (run.get("subject"), run.get("session"))
        if expected and key not in physio_by_session:
            run.setdefault("issues", []).append(
                {"severity": "WARN", "message": "Expected physio recording missing for session."}
            )

    physio_check = {
        "name": "physio_expected",
        "passed": (not expected) or bool(physio_runs),
        "severity": "WARN" if expected else "PASS",
        "message": "Physio expectation satisfied."
        if physio_runs or not expected
        else "Expected physio recordings missing.",
    }
    checks.append(physio_check)

    if expected and not physio_runs:
        issues.append({"severity": "WARN", "message": "No physio files found despite expectation."})


def _match_fieldmap(run: dict, fmap_records: List[dict]) -> Optional[dict]:
    if not fmap_records:
        return None
    # Prefer IntendedFor matches.
    for record in fmap_records:
        if run["path"] in record["intended_for"] or Path(run["path"]).name in record["intended_for"]:
            return {"method": "intendedfor", "path": record["path"]}
    # Fallback: first fmap in same session/subject.
    candidates = [
        record
        for record in fmap_records
        if record["subject"] == run.get("subject") and record["session"] == run.get("session")
    ]
    if candidates:
        return {"method": "session_first", "path": candidates[0]["path"]}
    return None


def _gather_fmap_jsons(root: Path) -> dict:
    records: List[dict] = []
    issues: List[dict] = []
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            continue
        if "derivatives" in path.parts or "/fmap/" not in path.as_posix() or not path.name.endswith(".json"):
            continue
        rel = path.relative_to(root)
        subject, session = _parse_sub_ses_local(rel)
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
        except Exception as err:  # noqa: BLE001
            issues.append(
                {
                    "severity": "WARN",
                    "message": f"Failed to read fieldmap JSON {rel}: {err}",
                    "subject": subject,
                    "session": session,
                }
            )
            continue
        intended_raw = meta.get("IntendedFor", [])
        intended = _normalize_intended_for(intended_raw)
        records.append(
            {
                "path": str(rel),
                "subject": subject,
                "session": session,
                "intended_for": intended,
            }
        )
    return {"records": records, "issues": issues}


def _parse_sub_ses_local(rel_path: Path) -> tuple[Optional[str], Optional[str]]:
    """Local copy of _parse_sub_ses to avoid circular imports."""
    parts = rel_path.parts
    subject = None
    session = None
    if parts and parts[0].startswith("sub-"):
        subject = parts[0][4:]
    if len(parts) > 1 and parts[1].startswith("ses-"):
        session = parts[1][4:]
    return subject, session


def _normalize_intended_for(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(v) for v in value]
    return []


def _validate_physio_metadata(path: Path) -> list[dict]:
    issues: list[dict] = []
    if not path.exists():
        return [{"severity": "FAIL", "message": "Physio file missing."}]
    json_path = _physio_json_sidecar(path)
    if not json_path.exists():
        issues.append({"severity": "WARN", "message": f"Missing physio sidecar: {json_path.name}"})
        return issues
    try:
        meta = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception as err:  # noqa: BLE001
        issues.append({"severity": "WARN", "message": f"Failed to read physio sidecar: {err}"})
        return issues
    if not any(key in meta for key in ("SamplingFrequency", "SamplingFrequencyNominal", "SampleRate")):
        issues.append({"severity": "WARN", "message": "Physio sidecar missing sampling frequency."})
    return issues


def _physio_json_sidecar(path: Path) -> Path:
    if str(path).endswith(".tsv.gz"):
        return Path(str(path)[:-7] + ".json")
    if str(path).endswith(".tsv"):
        return Path(str(path)[:-4] + ".json")
    return path.with_suffix(".json")


def _validate_nifti(path: Path, expect_4d: bool) -> list[dict]:
    issues: list[dict] = []
    try:
        img = nib.load(str(path))
    except Exception as err:  # noqa: BLE001
        return [{"severity": "FAIL", "message": f"NIfTI load failed: {err}"}]

    shape = img.shape
    if expect_4d and (len(shape) < 4 or shape[3] <= 1):
        issues.append({"severity": "FAIL", "message": f"Functional run not 4D (shape={shape})."})

    affine = img.affine
    if not np.isfinite(affine).all():
        issues.append({"severity": "FAIL", "message": "Affine contains non-finite values."})

    header = img.header
    pixdim = header.get("pixdim", None)
    if pixdim is not None and not np.isfinite(pixdim).all():
        issues.append({"severity": "FAIL", "message": "Header pixdim contains non-finite values."})

    qform_code = int(np.array(header.get("qform_code", np.array([0]))).reshape(-1)[0])
    sform_code = int(np.array(header.get("sform_code", np.array([0]))).reshape(-1)[0])
    if qform_code == 0 and sform_code == 0:
        issues.append({"severity": "WARN", "message": "qform_code and sform_code are 0 (orientation unset)."})
    return issues


def _classification_counts(runs: list[dict]) -> dict:
    counts = {"cord_likely": 0, "non_cord_likely": 0, "unknown": 0}
    for run in runs:
        classification = run.get("classification", "unknown")
        if classification not in counts:
            counts["unknown"] += 1
        else:
            counts[classification] += 1
    return counts


def _status_from_issues(issues: list[dict]) -> str:
    severities = {issue.get("severity", "WARN") for issue in issues}
    if "FAIL" in severities:
        return "FAIL"
    if "WARN" in severities:
        return "WARN"
    return "PASS"


def _overall_status(checks: list[dict], runs: list[dict], issues: list[dict]) -> str:
    run_statuses = {run["status"] for run in runs if "status" in run}
    check_statuses = set()
    for check in checks:
        if not check.get("passed", False):
            severity = check.get("severity", "FAIL")
            check_statuses.add("FAIL" if severity == "FAIL" else "WARN")
    all_statuses = run_statuses | check_statuses
    issue_severities = {issue.get("severity") for issue in issues}
    if "FAIL" in issue_severities:
        all_statuses.add("FAIL")
    if "WARN" in issue_severities:
        all_statuses.add("WARN")
    if "FAIL" in all_statuses:
        return "FAIL"
    if "WARN" in all_statuses:
        return "WARN"
    return "PASS"


def _failure_message(status: str, checks: list[dict], issues: list[dict]) -> Optional[str]:
    if status == "PASS":
        return None
    failing_checks = [c for c in checks if not c.get("passed", True)]
    if failing_checks:
        return failing_checks[0]["message"]
    for issue in issues:
        if issue.get("severity") in {"FAIL", "WARN"}:
            return issue.get("message")
    return None


def _dedupe_issues(issues: list[dict]) -> list[dict]:
    seen = set()
    deduped = []
    for issue in issues:
        key = (
            issue.get("severity"),
            issue.get("message"),
            issue.get("subject"),
            issue.get("session"),
            issue.get("path"),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(issue)
    deduped.sort(key=lambda x: (x.get("severity", ""), x.get("subject") or "", x.get("session") or "", x.get("message") or ""))
    return deduped


def _build_fix_plan(inventory: dict, runs: list[dict], issues: list[dict]) -> dict:
    fix_entries = []
    for issue in issues:
        fix_entries.append(
            {
                "severity": issue.get("severity", "WARN"),
                "message": issue.get("message"),
                "subject": issue.get("subject"),
                "session": issue.get("session"),
                "path": issue.get("path"),
            }
        )
    for run in runs:
        for issue in run.get("issues", []):
            fix_entries.append(
                {
                    "severity": issue.get("severity", "WARN"),
                    "message": issue.get("message"),
                    "subject": run.get("subject"),
                    "session": run.get("session"),
                    "path": run.get("path"),
                }
            )
    fix_entries = _dedupe_issues(fix_entries)
    return {
        "dataset_key": inventory["dataset_key"],
        "bids_root": inventory["bids_root"],
        "issues": fix_entries,
    }


def _validate_json(path: Path, schema_path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft7Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: e.path)
    if errors:
        msgs = "; ".join(e.message for e in errors)
        raise ValueError(f"Schema validation failed for {path}: {msgs}")


def _validate_runs_jsonl(path: Path, schema_path: Path) -> None:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft7Validator(schema)
    with path.open("r", encoding="utf-8") as f:
        for idx, line in enumerate(f, start=1):
            if not line.strip():
                continue
            obj = json.loads(line)
            errors = sorted(validator.iter_errors(obj), key=lambda e: e.path)
            if errors:
                msgs = "; ".join(e.message for e in errors)
                raise ValueError(f"Schema validation failed for {path} line {idx}: {msgs}")
