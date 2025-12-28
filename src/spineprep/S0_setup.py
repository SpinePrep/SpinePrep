"""
pl00_SETUP run and check entry points.

Ensures policy/datasets.yaml passes the v1 gate and environment prerequisites
are satisfied, then writes QC and state outputs.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

from spineprep.policy import DatasetPolicyError, load_dataset_policy, run_v1_policy_gate


@dataclass
class StepResult:
    status: str
    failure_message: Optional[str]
    qc_path: Path
    state_path: Path


@dataclass
class EnvCheck:
    name: str
    passed: bool
    message: str
    info: Dict[str, str]

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "passed": self.passed,
            "message": self.message,
            "info": dict(self.info),
        }


def run_pl00_setup(project_root: Path, step: str) -> StepResult:
    _validate_step(step)
    project_root = project_root.resolve()
    policy_path = project_root / "policy" / "datasets.yaml"
    logs_dir = project_root / "logs"
    state_dir = project_root / "state"
    evidence_dir = logs_dir / "S0_evidence"
    logs_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)
    evidence_dir.mkdir(parents=True, exist_ok=True)

    try:
        policy = load_dataset_policy(policy_path)
        gate_result = run_v1_policy_gate(policy)
    except DatasetPolicyError as err:
        gate_result = None
        env_checks = _environment_checks()
        checks = [
            {
                "name": "dataset_policy_gate",
                "passed": False,
                "message": str(err),
                "details": {},
            }
        ]
        checks.extend(
            [
                {"name": c.name, "passed": c.passed, "message": c.message, "info": c.info}
                for c in _environment_checks()
            ]
        )
        status, failure_message = _overall_status(checks)
        qc = {"step": step, "status": status, "failure_message": failure_message, "checks": checks}
        qc_path = logs_dir / "pl00_setup_qc.json"
        _write_json(qc_path, qc)
        state_path = state_dir / "setup_state.yaml"
        _write_yaml(
            state_path,
            {
                "step": step,
                "dataset_policy_path": str(policy_path),
                "dataset_policy_fingerprint": None,
                "dataset_gate_passed": False,
                "environment": {check.name: {"passed": check.passed, **check.info} for check in env_checks},
            },
        )
        _write_evidence(
            evidence_dir,
            qc_path,
            state_path,
            status,
            f"poetry run spineprep run {step} --project-root {project_root}",
        )
        return StepResult(status=status, failure_message=failure_message, qc_path=qc_path, state_path=state_path)

    env_checks = _environment_checks()

    env_checks = _environment_checks()

    checks = []
    checks.append(
        {
            "name": "dataset_policy_gate",
            "passed": gate_result.passed,
            "message": "Dataset policy gate passed." if gate_result.passed else "Dataset policy gate failed.",
            "details": gate_result.as_dict(),
        }
    )
    checks.extend([{"name": c.name, "passed": c.passed, "message": c.message, "info": c.info} for c in env_checks])

    status, failure_message = _overall_status(checks)

    qc = {
        "step": step,
        "status": status,
        "failure_message": failure_message,
        "checks": checks,
    }

    qc_path = logs_dir / "pl00_setup_qc.json"
    _write_json(qc_path, qc)

    dataset_fingerprint = _fingerprint(policy_path)
    state = {
        "step": step,
        "dataset_policy_path": str(policy_path),
        "dataset_policy_fingerprint": dataset_fingerprint,
        "dataset_gate_passed": gate_result.passed,
        "environment": {
            check.name: {"passed": check.passed, **check.info} for check in env_checks
        },
    }
    state_path = state_dir / "setup_state.yaml"
    _write_yaml(state_path, state)

    _write_evidence(
        evidence_dir,
        qc_path,
        state_path,
        status,
        f"poetry run spineprep run {step} --project-root {project_root}",
    )

    return StepResult(status=status, failure_message=failure_message, qc_path=qc_path, state_path=state_path)


def check_pl00_setup(project_root: Path, step: str) -> StepResult:
    _validate_step(step)
    project_root = project_root.resolve()
    policy_path = project_root / "policy" / "datasets.yaml"
    logs_dir = project_root / "logs"
    state_dir = project_root / "state"
    qc_path = logs_dir / "pl00_setup_qc.json"
    state_path = state_dir / "setup_state.yaml"

    missing_artifacts = [
        path for path in (qc_path, state_path) if (not path.exists() or path.stat().st_size == 0)
    ]
    if missing_artifacts:
        message = f"Missing required artifact(s) or empty file(s): {', '.join(str(p) for p in missing_artifacts)}"
        return StepResult(status="FAIL", failure_message=message, qc_path=qc_path, state_path=state_path)

    # Re-run gates without rewriting artifacts.
    try:
        policy = load_dataset_policy(policy_path)
        gate_result = run_v1_policy_gate(policy)
    except DatasetPolicyError as err:
        return StepResult(status="FAIL", failure_message=str(err), qc_path=qc_path, state_path=state_path)

    env_checks = _environment_checks()
    checks = []
    checks.append(
        {
            "name": "dataset_policy_gate",
            "passed": gate_result.passed,
            "message": "Dataset policy gate passed." if gate_result.passed else "Dataset policy gate failed.",
            "details": gate_result.as_dict(),
        }
    )
    checks.extend([{"name": c.name, "passed": c.passed, "message": c.message, "info": c.info} for c in env_checks])
    status, failure_message = _overall_status(checks)

    return StepResult(status=status, failure_message=failure_message, qc_path=qc_path, state_path=state_path)


def _overall_status(checks: List[dict]) -> Tuple[str, Optional[str]]:
    failures = [check for check in checks if not check["passed"]]
    if failures:
        first = failures[0]
        return "FAIL", f"{first['name']} failed: {first['message']}"
    return "PASS", None


def _environment_checks() -> List[EnvCheck]:
    checks: List[EnvCheck] = []
    checks.extend(_container_checks())

    pam50_check = _check_pam50_path()
    checks.append(
        EnvCheck(
            name="pam50_availability",
            passed=pam50_check[0],
            message=pam50_check[1],
            info={"pam50_path": pam50_check[2] or ""},
        )
    )
    return checks


def _container_checks() -> List[EnvCheck]:
    checks: List[EnvCheck] = []
    runtime, runtime_version = _detect_runtime()
    if runtime is None:
        checks.append(
            EnvCheck(
                name="container_runtime",
                passed=False,
                message="No container runtime found (docker/apptainer).",
                info={},
            )
        )
        return checks

    checks.append(
        EnvCheck(
            name="container_runtime",
            passed=True,
            message="Container runtime available.",
            info={"runtime": runtime, "version": runtime_version or ""},
        )
    )

    if runtime != "docker":
        checks.append(
            EnvCheck(
                name="container_images",
                passed=False,
                message="Image checks require docker; apptainer path not implemented.",
                info={},
            )
        )
        return checks

    for image_def in _required_images():
        image = image_def["image"]
        key = image_def["key"]
        if image is None:
            checks.append(
                EnvCheck(
                    name=f"image_defined:{key}",
                    passed=False,
                    message="SpinePrep image not provided; set SPINEPREP_IMAGE.",
                    info={"image": ""},
                )
            )
            continue

        present, digests = _docker_image_inspect(image)
        checks.append(
            EnvCheck(
                name=f"image_present:{key}",
                passed=present,
                message="Image present locally." if present else "Required image not found locally.",
                info={"image": image, "repodigests": ";".join(digests)},
            )
        )
        if not present:
            continue

        for cmd in image_def["commands"]:
            ok, message, output = _docker_run(image, cmd)
            checks.append(
                EnvCheck(
                    name=f"{key}_cmd:{' '.join(cmd)}",
                    passed=ok,
                    message=message,
                    info={"image": image, "command": " ".join(cmd), "stdout": output or ""},
                )
            )

    return checks


def _check_command_version(cmd: str) -> Tuple[bool, str, Optional[str]]:
    if not _is_executable(cmd):
        return False, f"{cmd} not found on PATH", None
    try:
        output = subprocess.check_output([cmd, "--version"], text=True, stderr=subprocess.STDOUT).strip()
        first_line = output.splitlines()[0] if output else ""
        return True, "Command available", first_line
    except Exception as err:  # noqa: BLE001
        return False, f"{cmd} failed: {err}", None


def _check_pam50_path() -> Tuple[bool, str, Optional[str]]:
    candidates = []
    env_path = os.environ.get("PAM50_PATH")
    if env_path:
        candidates.append(Path(env_path))

    sct_dir = os.environ.get("SCT_DIR")
    if sct_dir:
        candidates.append(Path(sct_dir) / "data" / "PAM50")

    candidates.append(Path.home() / "sct_7.1" / "data" / "PAM50")

    for path in candidates:
        if path.exists():
            return True, "PAM50 templates available.", str(path)
    return False, "PAM50 templates not found; set PAM50_PATH or install SCT data.", None


def _fingerprint(path: Path) -> str:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    canonical = yaml.safe_dump(raw, sort_keys=True)
    digest = sha256(canonical.encode("utf-8")).hexdigest()
    return digest


def _detect_runtime() -> Tuple[Optional[str], Optional[str]]:
    for runtime in ("docker", "apptainer"):
        ok, _, version = _check_command_version(runtime)
        if ok:
            return runtime, version
    return None, None


def _required_images() -> List[dict]:
    spineprep_image = os.environ.get("SPINEPREP_IMAGE")
    images = [
        {
            "key": "spineprep",
            "image": spineprep_image,
            "commands": [["spineprep", "--version"], ["python", "--version"]],
        },
        {
            "key": "sct",
            "image": "vnmd/spinalcordtoolbox_7.2:20251215",
            "commands": [["sct_version"]],
        },
        {"key": "fsl", "image": "vnmd/fsl_6.0.7.18_20250928", "commands": [["fslversion"]]},
        {"key": "ants", "image": "vnmd/ants_2.6.0_20250424", "commands": [["antsRegistration", "--version"]]},
    ]
    return images


def _docker_image_inspect(image: str) -> Tuple[bool, List[str]]:
    try:
        output = subprocess.check_output(
            ["docker", "image", "inspect", "--format", "{{json .RepoDigests}}||{{.Id}}", image],
            text=True,
            stderr=subprocess.STDOUT,
        ).strip()
    except subprocess.CalledProcessError:
        return False, []
    try:
        if "||" in output:
            parts = output.split("||", 1)
            digests = json.loads(parts[0]) if parts[0] else []
            if not digests:
                digests = [parts[1]]
        else:
            digests = json.loads(output)
            if not isinstance(digests, list):
                digests = []
    except json.JSONDecodeError:
        digests = []
    return True, digests


def _docker_run(image: str, cmd: List[str]) -> Tuple[bool, str, Optional[str]]:
    try:
        output = subprocess.check_output(
            ["docker", "run", "--rm", image, *cmd],
            text=True,
            stderr=subprocess.STDOUT,
            timeout=30,
        )
        return True, "Command succeeded inside container.", output.strip()
    except subprocess.CalledProcessError as err:
        return False, f"Command failed inside container: {err}", err.output if hasattr(err, "output") else None
    except Exception as err:  # noqa: BLE001
        return False, f"Command failed inside container: {err}", None


def _write_json(path: Path, payload: dict) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")


def _write_yaml(path: Path, payload: dict) -> None:
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(payload, f, sort_keys=True)


def _write_evidence(
    evidence_dir: Path, qc_path: Path, state_path: Path, status: str, command_line: str
) -> None:
    checks_txt = evidence_dir / "checks.txt"
    summary_md = evidence_dir / "summary.md"
    qc_copy = evidence_dir / qc_path.name
    state_copy = evidence_dir / state_path.name

    exit_code = 0 if status == "PASS" else 1
    checks_txt.write_text(f"{command_line}: {exit_code}\n", encoding="utf-8")
    summary_md.write_text(
        f"# pl00_SETUP evidence\n\nStatus: {status}\n\nArtifacts:\n- {qc_path}\n- {state_path}\n",
        encoding="utf-8",
    )

    qc_copy.write_bytes(qc_path.read_bytes())
    state_copy.write_bytes(state_path.read_bytes())


def _is_executable(cmd: str) -> bool:
    from shutil import which

    return which(cmd) is not None


def _validate_step(step: str) -> None:
    if step != "pl00_SETUP":
        raise ValueError(f"Unsupported step: {step}")
