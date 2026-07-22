"""Input validation, fmap/physio checks, and QC summary generation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import nibabel as nib
import numpy as np
from jsonschema import Draft7Validator


def _derive_adhoc_entry(run_records: Dict[str, dict]):
    """Derive a minimal dataset spec from the data itself, for unregistered
    (BIDS-App / ad-hoc) datasets that have no policy entry. Lets the fieldmap
    matching and physio checks run — most importantly it enables fieldmap
    matching so S5 can select TopUp on an ad-hoc dataset that ships a reverse-PE
    pair, instead of silently falling back to SyN. Expectations are set to what
    the data actually contains, so no false "expected X missing" warnings fire.
    """
    from types import SimpleNamespace

    mods = {r.get("modality") for r in run_records.values()}
    spec = SimpleNamespace(
        has_fmap=("fmap" in mods),
        has_physio=("physio" in mods),
        domains=[], modalities=sorted(m for m in mods if m), paradigms=[], tasks=[],
    )
    return SimpleNamespace(spec=spec, selection=None, derived=True)


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
            "acquisition": base_run.get("acquisition", {}),
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

    # Unregistered datasets have no policy entry; derive a minimal spec from the
    # data so the fieldmap/physio checks still run (esp. fieldmap matching → TopUp).
    effective_entry = policy_entry if policy_entry is not None else _derive_adhoc_entry(run_records)
    _apply_fieldmap_matching(root, run_records, effective_entry, issues, checks)
    _apply_physio_checks(root, run_records, effective_entry, issues, checks)
    _apply_acquisition_metadata_checks(run_records, checks, issues)
    _apply_session_requirements(run_records, checks, issues)
    _apply_selection_check(inventory, checks, issues)

    for run in run_records.values():
        issues_for_run = run.get("issues", [])
        run["status"] = _status_from_issues(issues_for_run)
        if not issues_for_run:
            run.pop("issues", None)

    runs = sorted(run_records.values(), key=lambda r: (r["subject"] or "", r["session"] or "", r["path"]))

    status = _overall_status(checks, runs, issues)
    failure_message = _failure_message(status, checks, issues, runs)

    # Aggregate quantitative metrics — give the step a step-local
    # truth gauge that's comparable across datasets without re-reading
    # the full check list (SpinePrep dev principle §3).
    n_checks_passed = sum(1 for c in checks if c.get("passed"))
    n_checks_failed = sum(1 for c in checks
                          if not c.get("passed") and c.get("severity") == "FAIL")
    n_checks_warned = sum(1 for c in checks
                          if not c.get("passed") and c.get("severity") == "WARN")
    n_runs_total = len(runs)
    n_runs_ok = sum(1 for r in runs if r.get("status") == "PASS")
    n_func_cord = sum(1 for r in runs
                      if r.get("modality") == "func"
                      and r.get("classification") == "cord_likely")
    n_anat = sum(1 for r in runs if r.get("modality") == "anat")
    n_fmap = sum(1 for r in runs if r.get("modality") == "fmap")

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
        "metrics": {
            "n_checks_total": len(checks),
            "n_checks_passed": n_checks_passed,
            "n_checks_warned": n_checks_warned,
            "n_checks_failed": n_checks_failed,
            "n_runs_total": n_runs_total,
            "n_runs_ok": n_runs_ok,
            "n_runs_with_issues": n_runs_total - n_runs_ok,
            # Subjects on disk vs actually processed. Without these, a policy
            # subset silently shrinks the cohort and every count below reads as
            # complete.
            "n_subjects_on_disk": (inventory.get("selection") or {}).get("n_subjects_on_disk", 0),
            "n_subjects_excluded": len((inventory.get("selection") or {}).get("subjects_excluded") or []),
            "n_func_cord_runs": n_func_cord,
            "n_anat_runs": n_anat,
            "n_fmap_runs": n_fmap,
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


def _apply_selection_check(inventory: dict, checks: list, issues: list) -> None:
    """Report subjects the policy subset dropped.

    The subset filter removes a subject's files before they enter the inventory,
    so an excluded subject leaves no trace and S1 reported "0 issues" while a
    complete subject sat unprocessed on disk. Whether an exclusion is deliberate
    is the operator's call -- but it must be visible, not silent. WARN rather than
    FAIL: a curated subset is legitimate, an undocumented one is not.
    """
    sel = (inventory or {}).get("selection") or {}
    excluded = sel.get("subjects_excluded") or []
    n_disk = sel.get("n_subjects_on_disk")
    if not excluded:
        checks.append({
            "name": "policy_selection_covers_disk",
            "passed": True,
            "severity": "WARN",
            "message": f"All {n_disk} subject(s) on disk are selected.",
        })
        return
    listed = ", ".join(f"sub-{s}" for s in excluded)
    msg = (
        f"policy selection excludes {len(excluded)} of {n_disk} subject(s) "
        f"present on disk: {listed}. If deliberate, record the reason in "
        f"policy/datasets.yaml; if not, the subject is being silently dropped."
    )
    checks.append({
        "name": "policy_selection_covers_disk",
        "passed": False,
        "severity": "WARN",
        "message": msg,
    })
    issues.append({"severity": "WARN", "message": msg})


def _apply_acquisition_metadata_checks(
    run_records: Dict[str, dict], checks: list[dict], issues: list[dict]
) -> None:
    """Pre-flight the sidecar fields downstream steps require, so a dataset that
    is missing them fails HERE (with a clear message) instead of silently
    breaking at S5/topup or later. See .claude/specs/s1-algorithm-audit.md F3.

    - Every cord fMRI run needs RepetitionTime (used everywhere downstream).
    - Every fieldmap needs PhaseEncodingDirection + TotalReadoutTime (FSL topup
      acqparams); without them S5 topup cannot run.
    All WARN (not FAIL): the analyst may still proceed with a fallback path
    (e.g. S5 SyN), so this surfaces the gap without blocking.
    """
    n_bold_missing_tr = 0
    for run in run_records.values():
        acq = run.get("acquisition") or {}
        if run["modality"] == "func" and run["classification"] == "cord_likely":
            if "RepetitionTime" not in acq:
                n_bold_missing_tr += 1
                run.setdefault("issues", []).append(
                    {"severity": "WARN", "message": "BOLD sidecar missing RepetitionTime."})
        elif run["modality"] == "fmap":
            missing = [k for k in ("PhaseEncodingDirection", "TotalReadoutTime") if k not in acq]
            if missing:
                run.setdefault("issues", []).append(
                    {"severity": "WARN",
                     "message": f"Fieldmap sidecar missing {', '.join(missing)} (needed for topup)."})
    checks.append({
        "name": "bold_repetition_time_present",
        "passed": n_bold_missing_tr == 0,
        "severity": "WARN",
        "message": "All cord fMRI runs declare RepetitionTime."
        if n_bold_missing_tr == 0 else f"{n_bold_missing_tr} cord fMRI run(s) missing RepetitionTime.",
    })
    if n_bold_missing_tr:
        issues.append({"severity": "WARN",
                       "message": f"{n_bold_missing_tr} cord fMRI run(s) missing RepetitionTime."})


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
        elif policy_entry is not None and policy_entry.spec.has_fmap:
            run.setdefault("issues", []).append(
                {"severity": "WARN", "message": "Expected fieldmap match not found."}
            )

    # Ad-hoc datasets (BIDS-App on an unregistered bids_dir) have no policy
    # spec to compare against — skip the "expected fieldmap" expectation.
    expected = policy_entry.spec.has_fmap if policy_entry is not None else False
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

    issues.extend(_check_data_complete(path, img))
    return issues


def _check_data_complete(path: Path, img) -> list[dict]:
    """Detect a truncated or partially-downloaded image.

    Everything above reads only the HEADER, which a truncated file preserves
    intact -- the header sits at the front. So a half-downloaded scan passed S1
    as clean and only surfaced much later as a gzip ``EOFError`` inside S3, or
    (uncompressed) as silently zero-filled volumes. That is the one failure an
    input-verification step exists to catch. Found 2026-07-19: the known
    truncated sub-22 in ds005883 passed S1 with no issues at all.

    Both checks are O(1) -- no decompression, no data load. Reading a 292 MB
    gzip to its end would be correct but far too slow to run over a cohort.
      * uncompressed .nii -- the file must be at least header + voxel bytes;
      * gzipped .nii.gz -- the last 4 bytes of a gzip stream are ISIZE, the
        uncompressed length (mod 2**32). A truncated file's trailing bytes are
        arbitrary compressed data, so ISIZE will not match the size the NIfTI
        header implies.
    """
    try:
        if not path.exists():
            return [{"severity": "FAIL", "message": "File does not exist."}]
        actual = path.stat().st_size
        if actual == 0:
            return [{"severity": "FAIL", "message": "File is empty (0 bytes)."}]

        hdr = img.header
        n_vox = int(np.prod(img.shape)) if img.shape else 0
        itemsize = int(np.dtype(hdr.get_data_dtype()).itemsize)
        data_bytes = n_vox * itemsize
        if data_bytes <= 0:
            return []
        # get_data_offset() reports 0 for a loaded .nii.gz, so fall back to the
        # header's own declared size + the 4-byte extension flag (352 for
        # NIfTI-1, 544 for NIfTI-2) rather than assuming a constant.
        try:
            vox_offset = int(hdr.get_data_offset())
        except Exception:
            vox_offset = 0
        if vox_offset <= 0:
            try:
                base = int(np.asarray(hdr["sizeof_hdr"]).reshape(-1)[0]) + 4
            except Exception:
                base = 352
            # A NIfTI header EXTENSION sits between the header and the voxel
            # data; get_data_offset() misses it here, so add its on-disk size
            # (each extension is padded to a 16-byte boundary, 8-byte esize+ecode
            # included). Omitting it made `expected` understate the true size,
            # so a complete file with a 6 kB AFNI extension read as "truncated"
            # and wrongly failed 46 complete motor runs (2026-07-22).
            ext_bytes = 0
            try:
                for e in hdr.extensions:
                    esize = 8 + len(e.get_content())
                    ext_bytes += ((esize + 15) // 16) * 16
            except Exception:
                ext_bytes = 0
            vox_offset = base + ext_bytes
        expected = vox_offset + data_bytes

        name = path.name.lower()
        if name.endswith(".nii"):
            if actual < expected:
                pct = 100.0 * actual / expected
                return [{
                    "severity": "FAIL",
                    "message": (f"Truncated NIfTI: file is {actual} bytes, header implies "
                                f"{expected} ({pct:.0f}%). Likely an incomplete download."),
                }]
        elif name.endswith(".gz"):
            with open(path, "rb") as fh:
                if fh.read(2) != b"\x1f\x8b":
                    return [{"severity": "FAIL",
                             "message": "File named .gz but lacks a gzip magic number."}]
                fh.seek(-4, 2)
                isize = int.from_bytes(fh.read(4), "little")
            # ISIZE is the uncompressed length mod 2**32; `expected` now counts
            # header + extension + voxels, so a COMPLETE file matches it exactly
            # and any deviation is genuine truncation or corruption (a truncated
            # gzip's last 4 bytes are mid-stream compressed data, so ISIZE
            # becomes garbage). Compare in the same modular ring so files larger
            # than 4 GB uncompressed do not raise a spurious mismatch.
            if isize != (expected % (1 << 32)):
                pct = 100.0 * isize / expected if expected else 0.0
                return [{
                    "severity": "FAIL",
                    "message": (f"Truncated or corrupt NIfTI: gzip trailer reports "
                                f"{isize} uncompressed bytes, header implies {expected} "
                                f"({pct:.0f}%). Likely an incomplete download."),
                }]
    except Exception as err:  # noqa: BLE001
        # Never let the completeness probe itself fail the run silently.
        return [{"severity": "WARN",
                 "message": f"Could not verify file completeness: {err}"}]
    return []


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


def _failure_message(status: str, checks: list[dict], issues: list[dict],
                     runs: Optional[list[dict]] = None) -> Optional[str]:
    if status == "PASS":
        return None
    failing_checks = [c for c in checks if not c.get("passed", True)]
    if failing_checks:
        return failing_checks[0]["message"]
    for issue in issues:
        if issue.get("severity") in {"FAIL", "WARN"}:
            return issue.get("message")
    # The status can also come from a per-run issue (e.g. a truncated file),
    # which lives on the run record, not in the dataset checks/issues. Surface
    # it so a FAIL is never reported with a null reason -- an unexplained FAIL
    # is a QC-honesty failure in its own right.
    order = {"FAIL": 2, "WARN": 1, "PASS": 0}
    flagged = sorted(
        (r for r in (runs or []) if r.get("status") in {"FAIL", "WARN"}),
        key=lambda r: order.get(r.get("status"), 0), reverse=True)
    if flagged:
        first = flagged[0]
        rissues = first.get("issues") or [{}]
        msg = rissues[0].get("message", "input validation issue")
        more = f" (and {len(flagged) - 1} more run(s))" if len(flagged) > 1 else ""
        return f"{first.get('path', 'run')}: {msg}{more}"
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
