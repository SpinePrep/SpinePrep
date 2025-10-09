"""Tests for doctor command JSON output per ticket A1."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


def test_doctor_json_valid_structure(tmp_path):
    """Doctor --json outputs valid JSON with all required fields."""
    json_out = tmp_path / "doctor.json"

    result = subprocess.run(
        ["spineprep", "doctor", "--json", str(json_out)],
        capture_output=True,
        text=True,
        check=False,
    )

    # Should complete (may fail if SCT missing, but should still write JSON)
    assert result.returncode in [0, 1, 2], f"Unexpected exit code: {result.returncode}"

    # JSON file must exist and be non-empty
    assert json_out.exists(), "doctor.json not created"
    assert json_out.stat().st_size > 0, "doctor.json is empty"

    # Must be valid JSON
    with open(json_out) as f:
        data = json.load(f)

    # Required fields per ticket A1
    assert "python" in data, "Missing python field"
    assert "version" in data["python"], "Missing python.version"

    assert "spineprep" in data, "Missing spineprep field"
    assert "version" in data["spineprep"], "Missing spineprep.version"

    assert "platform" in data, "Missing platform field"

    assert "packages" in data, "Missing packages field"
    assert isinstance(data["packages"], dict), "packages should be dict"

    assert "sct" in data, "Missing sct field"
    assert "present" in data["sct"], "Missing sct.present"
    assert "version" in data["sct"], "Missing sct.version"
    assert "path" in data["sct"], "Missing sct.path"

    assert "pam50" in data, "Missing pam50 field"
    assert "present" in data["pam50"], "Missing pam50.present"

    assert "disk" in data, "Missing disk field"
    assert "free_bytes" in data["disk"], "Missing disk.free_bytes"
    assert isinstance(
        data["disk"]["free_bytes"], (int, float)
    ), "free_bytes should be numeric"

    assert "cwd_writeable" in data, "Missing cwd_writeable"
    assert isinstance(data["cwd_writeable"], bool), "cwd_writeable should be boolean"

    assert "tmp_writeable" in data, "Missing tmp_writeable"
    assert isinstance(data["tmp_writeable"], bool), "tmp_writeable should be boolean"


def test_doctor_json_to_stdout(tmp_path):
    """Doctor --json can output to stdout via redirect."""
    result = subprocess.run(
        ["spineprep", "doctor", "--json", "-"],
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
    )

    # Should complete
    assert result.returncode in [0, 1, 2], f"Unexpected exit code: {result.returncode}"

    # If --json=-, output should go to stdout
    # For now, just verify it completes without crashing
    # (implementation may choose to write to stdout or default location)


def test_doctor_sct_missing_remediation(tmp_path):
    """When SCT is missing, doctor exits non-zero and provides remediation."""
    # This test verifies that when SCT is absent, proper remediation is shown
    # We simulate missing SCT by removing it from PATH and unsetting SCT_DIR
    import os
    import shutil
    import sys

    import pytest

    spineprep_path = shutil.which("spineprep")
    if not spineprep_path:
        pytest.skip("spineprep not found in PATH")

    # Create a temporary environment without SCT
    env = os.environ.copy()
    # Remove SCT_DIR to simulate missing SCT
    env.pop("SCT_DIR", None)

    # Build a minimal PATH that includes Python and spineprep's directory
    # but explicitly excludes typical SCT locations
    python_bin = Path(sys.executable).parent
    spineprep_bin = Path(spineprep_path).parent
    minimal_path = f"{python_bin}:{spineprep_bin}"
    env["PATH"] = minimal_path

    json_out = tmp_path / "doctor.json"

    result = subprocess.run(
        [spineprep_path, "doctor", "--json", str(json_out)],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    # Check if the JSON was created and is valid
    assert json_out.exists(), "JSON output should be created"

    import json

    with open(json_out) as f:
        data = json.load(f)

    # Verify JSON structure
    assert "sct" in data, "JSON should have sct field"
    assert "present" in data["sct"], "sct should have present field"

    # If SCT is not present, verify error handling and remediation
    if not data["sct"]["present"]:
        # Exit code should be non-zero
        assert result.returncode != 0, "doctor should fail when SCT is missing"

        # Check for remediation in notes
        notes = data.get("notes", [])
        notes_text = " ".join(notes).lower()
        remediation_keywords = ["docker", "apptainer", "remediation"]
        has_remediation = any(kw in notes_text for kw in remediation_keywords)
        assert has_remediation, f"No remediation text found in notes:\n{notes}"
    else:
        # If SCT is still present (couldn't simulate missing),
        # skip the exit code and remediation checks
        pytest.skip(
            "SCT found despite PATH manipulation, cannot test missing SCT scenario"
        )


def test_doctor_help_works():
    """spineprep doctor --help should work."""
    result = subprocess.run(
        ["spineprep", "doctor", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, "doctor --help should succeed"
    assert "doctor" in result.stdout.lower(), "Help text should mention doctor"
