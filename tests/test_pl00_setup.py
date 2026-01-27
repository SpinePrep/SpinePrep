import json
import shutil
from pathlib import Path

import pytest
import yaml

from spinalfmriprep.S0_setup import EnvCheck, check_S0_setup, run_S0_setup


REQUIRED_V1_KEYS = {
    "openneuro_ds005884_cospine_motor",
    "openneuro_ds005883_cospine_pain",
    "openneuro_ds004386_spinalcord_rest_testretest",
    "openneuro_ds004616_spinalcord_handgrasp_task",
}


def _make_project_root(tmp_path: Path) -> Path:
    project_root = tmp_path / "project"
    policy_dir = project_root / "policy"
    policy_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(Path("policy") / "datasets.yaml", policy_dir / "datasets.yaml")
    return project_root


def _load_qc(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def test_S0_setup_run_and_check_are_deterministic(tmp_path):
    import spinalfmriprep.S0_setup as S0

    fake_checks = [
        EnvCheck(
            name="container_runtime",
            passed=True,
            message="ok",
            info={"runtime": "docker", "version": "24.0"},
        ),
        EnvCheck(
            name="image_present:spinalfmriprep",
            passed=True,
            message="present",
            info={"image": "spinalfmriprep:latest", "repodigests": "sha256:abc"},
        ),
        EnvCheck(
            name="spinalfmriprep_cmd:spinalfmriprep --version",
            passed=True,
            message="ok",
            info={"image": "spinalfmriprep:latest", "command": "spinalfmriprep --version", "stdout": "1.0"},
        ),
        EnvCheck(
            name="pam50_availability",
            passed=True,
            message="PAM50 templates available.",
            info={"pam50_path": "/tmp/PAM50"},
        ),
    ]
    S0._container_checks = lambda: fake_checks[:-1]  # type: ignore[assignment]
    S0._check_pam50_path = lambda: (True, "PAM50 templates available.", "/tmp/PAM50")  # type: ignore[assignment]

    project_root = _make_project_root(tmp_path)

    first = run_S0_setup(project_root, "S0_SETUP")
    assert first.status == "PASS"
    qc1 = first.qc_path.read_text(encoding="utf-8")
    state1 = first.state_path.read_text(encoding="utf-8")

    # Second run should produce identical QC/state files.
    second = run_S0_setup(project_root, "S0_SETUP")
    assert second.status == "PASS"
    assert qc1 == second.qc_path.read_text(encoding="utf-8")
    assert state1 == second.state_path.read_text(encoding="utf-8")

    # Check mode should pass using existing artifacts.
    check_res = check_S0_setup(project_root, "S0_SETUP")
    assert check_res.status == "PASS"

    # Evidence bundle present and non-empty.
    evidence_dir = project_root / "logs" / "S0_evidence"
    for name in ["checks.txt", "summary.md", "S0_setup_qc.json", "setup_state.yaml"]:
        evidence_file = evidence_dir / name
        assert evidence_file.exists()
        assert evidence_file.stat().st_size > 0


def test_S0_setup_fails_when_v1_dataset_missing(tmp_path):
    project_root = _make_project_root(tmp_path)
    manifest_path = project_root / "policy" / "datasets.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["datasets"] = [
        ds for ds in manifest["datasets"] if ds["key"] != "openneuro_ds004616_spinalcord_handgrasp_task"
    ]
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

    result = run_S0_setup(project_root, "S0_SETUP")
    assert result.status == "FAIL"
    qc = _load_qc(result.qc_path)
    gate = next(check for check in qc["checks"] if check["name"] == "dataset_policy_gate")
    assert gate["passed"] is False
    required_check = next(item for item in gate["details"]["checks"] if item["name"] == "v1_required_keys")
    assert required_check["passed"] is False


def test_S0_setup_fails_when_sct_missing(monkeypatch, tmp_path):
    project_root = _make_project_root(tmp_path)
    import spinalfmriprep.S0_setup as S0

    monkeypatch.setattr(
        S0,
        "_container_checks",
        lambda: [
            EnvCheck(
                name="container_runtime",
                passed=True,
                message="ok",
                info={"runtime": "docker", "version": "24.0"},
            ),
            EnvCheck(
                name="image_present:spinalfmriprep",
                passed=False,
                message="Required image not found locally.",
                info={"image": "spinalfmriprep:latest", "repodigests": ""},
            ),
        ],
    )
    monkeypatch.setattr(S0, "_check_pam50_path", lambda: (True, "PAM50 templates available.", "/tmp/PAM50"))

    result = run_S0_setup(project_root, "S0_SETUP")
    assert result.status == "FAIL"
    qc = _load_qc(result.qc_path)
    image_check = next(check for check in qc["checks"] if check["name"] == "image_present:spinalfmriprep")
    assert image_check["passed"] is False


def test_S0_setup_fails_when_container_command_fails(monkeypatch, tmp_path):
    project_root = _make_project_root(tmp_path)
    import spinalfmriprep.S0_setup as S0

    monkeypatch.setattr(
        S0,
        "_container_checks",
        lambda: [
            EnvCheck(
                name="container_runtime",
                passed=True,
                message="ok",
                info={"runtime": "docker", "version": "24.0"},
            ),
            EnvCheck(
                name="image_present:sct",
                passed=True,
                message="present",
                info={"image": "vnmd/spinalcordtoolbox_7.2:20251215", "repodigests": "sha256:abc"},
            ),
            EnvCheck(
                name="sct_cmd:sct_version",
                passed=False,
                message="Command failed inside container: boom",
                info={"image": "vnmd/spinalcordtoolbox_7.2:20251215", "command": "sct_version", "stdout": ""},
            ),
        ],
    )
    monkeypatch.setattr(S0, "_check_pam50_path", lambda: (True, "PAM50 templates available.", "/tmp/PAM50"))

    result = run_S0_setup(project_root, "S0_SETUP")
    assert result.status == "FAIL"
    qc = _load_qc(result.qc_path)
    cmd_check = next(check for check in qc["checks"] if check["name"] == "sct_cmd:sct_version")
    assert cmd_check["passed"] is False


def test_S0_setup_fails_when_pam50_missing(monkeypatch, tmp_path):
    project_root = _make_project_root(tmp_path)
    import spinalfmriprep.S0_setup as S0

    monkeypatch.setattr(S0, "_container_checks", lambda: [])
    monkeypatch.setattr(S0, "_check_pam50_path", lambda: (False, "PAM50 missing", None))

    result = run_S0_setup(project_root, "S0_SETUP")
    assert result.status == "FAIL"
    qc = _load_qc(result.qc_path)
    pam50_check = next(check for check in qc["checks"] if check["name"] == "pam50_availability")
    assert pam50_check["passed"] is False
