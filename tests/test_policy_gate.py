import copy
from pathlib import Path

import yaml

from spinalfmriprep.policy import load_dataset_policy, run_v1_policy_gate


BASE_POLICY = Path("policy/datasets.yaml")


def _load_manifest() -> dict:
    with BASE_POLICY.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _write_manifest(tmp_path: Path, manifest: dict) -> Path:
    path = tmp_path / "datasets.yaml"
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(manifest, f, sort_keys=False)
    return path


def _run_gate(tmp_path, manifest: dict):
    manifest_path = _write_manifest(tmp_path, manifest)
    policy = load_dataset_policy(manifest_path)
    result = run_v1_policy_gate(policy)
    checks = {check.name: check for check in result.checks}
    return result, checks


def test_gate_fails_when_required_key_missing(tmp_path):
    manifest = _load_manifest()
    manifest["datasets"] = [
        ds
        for ds in manifest["datasets"]
        if ds["key"] != "openneuro_ds004616_spinalcord_handgrasp_task"
    ]

    result, checks = _run_gate(tmp_path, manifest)

    assert not result.passed
    assert not checks["v1_required_keys"].passed
    assert "openneuro_ds004616_spinalcord_handgrasp_task" in checks["v1_required_keys"].message


def test_gate_fails_with_extra_v1_dataset(tmp_path):
    manifest = _load_manifest()
    extra = copy.deepcopy(manifest["datasets"][0])
    extra["key"] = "extra_v1_dataset"
    extra["intended_use"] = ["v1_validation"]
    manifest["datasets"].append(extra)

    result, checks = _run_gate(tmp_path, manifest)

    assert not result.passed
    assert not checks["v1_no_extra_keys"].passed
    assert "extra_v1_dataset" in checks["v1_no_extra_keys"].message


def test_gate_requires_explicit_fmap_and_physio_flags(tmp_path):
    manifest = _load_manifest()
    for ds in manifest["datasets"]:
        if ds["key"] == "openneuro_ds004386_spinalcord_rest_testretest":
            ds["spec"]["has_fmap"] = None
            ds["spec"]["has_physio"] = None

    result, checks = _run_gate(tmp_path, manifest)

    assert not result.passed
    assert not checks["coverage_fmap_physio_flags"].passed
    assert "openneuro_ds004386_spinalcord_rest_testretest" in checks["coverage_fmap_physio_flags"].message


def test_gate_requires_task_and_rest_coverage(tmp_path):
    manifest = _load_manifest()
    for ds in manifest["datasets"]:
        if "v1_validation" in ds.get("intended_use", []):
            ds["spec"]["paradigms"] = ["task"]

    result, checks = _run_gate(tmp_path, manifest)

    assert not result.passed
    assert not checks["coverage_rest"].passed
