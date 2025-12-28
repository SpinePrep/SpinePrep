"""
Dataset manifest loading and v1 validation gate checks.

BUILD-S0-T1 implements policy validation for `policy/datasets.yaml` without
reading any BIDS inputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional

import yaml


class DatasetPolicyError(ValueError):
    """Raised when the dataset policy manifest is invalid."""


@dataclass(frozen=True)
class DatasetSpec:
    domains: List[str]
    modalities: List[str]
    paradigms: List[str]
    tasks: List[str]
    has_fmap: Optional[bool]
    has_physio: Optional[bool]


@dataclass(frozen=True)
class DatasetSelection:
    mode: str
    subjects: List[str]
    sessions: List[str]


@dataclass(frozen=True)
class DatasetEntry:
    key: str
    title: str
    source: str
    accession: str
    license: str
    intended_use: List[str]
    spec: DatasetSpec
    selection: DatasetSelection
    doi: Optional[str] = None
    homepage: Optional[str] = None
    counts: Optional[dict] = None
    notes: str = ""


@dataclass(frozen=True)
class DatasetPolicy:
    version: int
    datasets: List[DatasetEntry]


@dataclass
class CheckResult:
    name: str
    passed: bool
    message: str

    def as_dict(self) -> dict:
        return {"name": self.name, "passed": self.passed, "message": self.message}


@dataclass
class PolicyGateResult:
    passed: bool
    checks: List[CheckResult]

    def as_dict(self) -> dict:
        return {"passed": self.passed, "checks": [check.as_dict() for check in self.checks]}


REQUIRED_V1_KEYS = {
    "openneuro_ds005884_cospine_motor",
    "openneuro_ds005883_cospine_pain",
    "openneuro_ds004386_spinalcord_rest_testretest",
    "openneuro_ds004616_spinalcord_handgrasp_task",
    "internal_balgrist_motor_11",
}


def load_dataset_policy(policy_path: Path | str) -> DatasetPolicy:
    """
    Load and validate the dataset manifest.

    Raises:
        DatasetPolicyError: when the manifest fails structural validation.
    """
    path = Path(policy_path)
    if not path.exists():
        raise DatasetPolicyError(f"Dataset policy not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        try:
            raw = yaml.safe_load(f)
        except yaml.YAMLError as err:
            raise DatasetPolicyError(f"Failed to parse dataset policy YAML: {err}") from err

    if not isinstance(raw, dict):
        raise DatasetPolicyError("Dataset policy must be a mapping at the top level.")

    version = raw.get("version")
    if not isinstance(version, int):
        raise DatasetPolicyError("Dataset policy missing required integer field 'version'.")

    datasets_raw = raw.get("datasets")
    if not isinstance(datasets_raw, list) or not datasets_raw:
        raise DatasetPolicyError("Dataset policy must contain a non-empty 'datasets' list.")

    seen_keys: set[str] = set()
    entries: list[DatasetEntry] = []
    for idx, entry in enumerate(datasets_raw, start=1):
        entries.append(_parse_dataset_entry(entry, idx, seen_keys))

    return DatasetPolicy(version=version, datasets=entries)


def _parse_dataset_entry(entry: dict, idx: int, seen_keys: set[str]) -> DatasetEntry:
    if not isinstance(entry, dict):
        raise DatasetPolicyError(f"Dataset entry #{idx} must be a mapping.")

    required_fields = [
        "key",
        "title",
        "source",
        "accession",
        "license",
        "intended_use",
        "spec",
        "selection",
    ]
    missing = [field for field in required_fields if field not in entry]
    if missing:
        raise DatasetPolicyError(
            f"Dataset entry #{idx} missing required field(s): {', '.join(sorted(missing))}"
        )

    key = entry["key"]
    if not isinstance(key, str) or not key.strip():
        raise DatasetPolicyError(f"Dataset entry #{idx} has an empty or non-string 'key'.")
    if key in seen_keys:
        raise DatasetPolicyError(f"Duplicate dataset key detected: '{key}'.")
    seen_keys.add(key)

    intended_use = entry["intended_use"]
    if not isinstance(intended_use, list) or not all(isinstance(u, str) for u in intended_use):
        raise DatasetPolicyError(f"Dataset '{key}' has invalid 'intended_use'; expected list of strings.")
    if not intended_use:
        raise DatasetPolicyError(f"Dataset '{key}' must declare at least one intended_use.")

    spec_raw = entry["spec"]
    if not isinstance(spec_raw, dict):
        raise DatasetPolicyError(f"Dataset '{key}' has invalid 'spec'; expected a mapping.")

    selection_raw = entry["selection"]
    if not isinstance(selection_raw, dict):
        raise DatasetPolicyError(f"Dataset '{key}' has invalid 'selection'; expected a mapping.")

    spec = _parse_dataset_spec(spec_raw, key)
    selection = _parse_dataset_selection(selection_raw, key)

    notes = entry.get("notes", "")
    if notes is None:
        notes = ""
    if not isinstance(notes, str):
        raise DatasetPolicyError(f"Dataset '{key}' has non-string 'notes'.")

    doi = entry.get("doi")
    if doi is not None and not isinstance(doi, str):
        raise DatasetPolicyError(f"Dataset '{key}' has non-string 'doi'.")

    homepage = entry.get("homepage")
    if homepage is not None and not isinstance(homepage, str):
        raise DatasetPolicyError(f"Dataset '{key}' has non-string 'homepage'.")

    counts = entry.get("counts")
    if counts is not None and not isinstance(counts, dict):
        raise DatasetPolicyError(f"Dataset '{key}' has invalid 'counts'; expected a mapping or null.")

    for required_field in ("title", "source", "accession", "license"):
        value = entry[required_field]
        if not isinstance(value, str) or not value.strip():
            raise DatasetPolicyError(
                f"Dataset '{key}' has invalid '{required_field}'; expected a non-empty string."
            )

    return DatasetEntry(
        key=key,
        title=entry["title"],
        source=entry["source"],
        accession=entry["accession"],
        license=entry["license"],
        intended_use=intended_use,
        spec=spec,
        selection=selection,
        doi=doi,
        homepage=homepage,
        counts=counts,
        notes=notes,
    )


def _parse_dataset_spec(spec_raw: dict, key: str) -> DatasetSpec:
    required_spec_fields = ["domains", "modalities", "paradigms", "tasks", "has_fmap", "has_physio"]
    missing = [field for field in required_spec_fields if field not in spec_raw]
    if missing:
        raise DatasetPolicyError(
            f"Dataset '{key}' spec missing required field(s): {', '.join(sorted(missing))}"
        )

    for list_field in ["domains", "modalities", "paradigms", "tasks"]:
        value = spec_raw[list_field]
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise DatasetPolicyError(
                f"Dataset '{key}' spec field '{list_field}' must be a list of strings."
            )

    has_fmap = spec_raw["has_fmap"]
    has_physio = spec_raw["has_physio"]
    for field_name, field_value in (("has_fmap", has_fmap), ("has_physio", has_physio)):
        if field_value is not None and not isinstance(field_value, bool):
            raise DatasetPolicyError(
                f"Dataset '{key}' spec field '{field_name}' must be true, false, or null."
            )

    return DatasetSpec(
        domains=list(spec_raw["domains"]),
        modalities=list(spec_raw["modalities"]),
        paradigms=list(spec_raw["paradigms"]),
        tasks=list(spec_raw["tasks"]),
        has_fmap=has_fmap,
        has_physio=has_physio,
    )


def _parse_dataset_selection(selection_raw: dict, key: str) -> DatasetSelection:
    required_selection_fields = ["mode", "subjects", "sessions"]
    missing = [field for field in required_selection_fields if field not in selection_raw]
    if missing:
        raise DatasetPolicyError(
            f"Dataset '{key}' selection missing required field(s): {', '.join(sorted(missing))}"
        )

    mode = selection_raw["mode"]
    if mode not in {"all", "subset"}:
        raise DatasetPolicyError(
            f"Dataset '{key}' selection 'mode' must be either 'all' or 'subset'."
        )

    for list_field in ["subjects", "sessions"]:
        value = selection_raw[list_field]
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise DatasetPolicyError(
                f"Dataset '{key}' selection field '{list_field}' must be a list of strings."
            )

    return DatasetSelection(mode=mode, subjects=list(selection_raw["subjects"]), sessions=list(selection_raw["sessions"]))


def run_v1_policy_gate(policy: DatasetPolicy) -> PolicyGateResult:
    """
    Evaluate the v1 validation gate using the dataset policy.
    """
    checks: list[CheckResult] = []
    v1_entries = [entry for entry in policy.datasets if "v1_validation" in entry.intended_use]
    v1_keys = {entry.key for entry in v1_entries}

    missing = sorted(REQUIRED_V1_KEYS - v1_keys)
    extra = sorted(v1_keys - REQUIRED_V1_KEYS)

    checks.append(
        CheckResult(
            name="v1_required_keys",
            passed=not missing,
            message="All required v1_validation datasets present."
            if not missing
            else f"Missing required v1_validation dataset(s): {', '.join(missing)}.",
        )
    )
    checks.append(
        CheckResult(
            name="v1_no_extra_keys",
            passed=not extra,
            message="No unexpected v1_validation datasets present."
            if not extra
            else f"Unexpected v1_validation dataset(s): {', '.join(extra)}.",
        )
    )

    checks.append(_coverage_check("coverage_task", any("task" in e.spec.paradigms for e in v1_entries), "At least one v1_validation dataset must include paradigm 'task'."))
    checks.append(_coverage_check("coverage_rest", any("rest" in e.spec.paradigms for e in v1_entries), "At least one v1_validation dataset must include paradigm 'rest'."))
    checks.append(_coverage_check("coverage_brain_spine", any("brain_spine" in e.spec.domains for e in v1_entries), "At least one v1_validation dataset must include domain 'brain_spine'."))

    fmap_physio_failures = _find_null_flags(v1_entries)
    checks.append(
        CheckResult(
            name="coverage_fmap_physio_flags",
            passed=not fmap_physio_failures,
            message="All v1_validation datasets declare has_fmap and has_physio as booleans."
            if not fmap_physio_failures
            else "Datasets missing explicit has_fmap/has_physio: " + ", ".join(sorted(fmap_physio_failures)),
        )
    )

    passed = all(check.passed for check in checks)
    return PolicyGateResult(passed=passed, checks=checks)


def _coverage_check(name: str, condition: bool, failure_message: str) -> CheckResult:
    return CheckResult(
        name=name,
        passed=bool(condition),
        message="Coverage requirement satisfied." if condition else failure_message,
    )


def _find_null_flags(entries: Iterable[DatasetEntry]) -> list[str]:
    missing_flags: list[str] = []
    for entry in entries:
        if entry.spec.has_fmap is None or entry.spec.has_physio is None:
            missing_flags.append(entry.key)
    return missing_flags
