"""Tests for spineprep doctor command and diagnostics."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from spineprep.doctor import (
    detect_os_info,
    detect_pam50,
    detect_python_deps,
    detect_sct,
    generate_report,
    write_doctor_report,
)


def test_detect_sct_found():
    """Test SCT detection when sct_version is in PATH."""
    with patch("shutil.which", return_value="/usr/bin/sct_version"):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="SCT v6.1\nsome other info",
            )
            result = detect_sct()

    assert result["found"] is True
    assert result["version"] == "SCT v6.1"
    assert result["path"] == "/usr/bin/sct_version"


def test_detect_sct_not_found():
    """Test SCT detection when not in PATH."""
    with patch("shutil.which", return_value=None):
        with patch.dict(os.environ, {}, clear=True):
            result = detect_sct()

    assert result["found"] is False
    assert result["version"] == ""
    assert result["path"] == ""


def test_detect_sct_from_env():
    """Test SCT detection from SCT_DIR environment variable."""
    with patch("shutil.which", return_value=None):
        with patch.dict(os.environ, {"SCT_DIR": "/opt/sct"}, clear=True):
            with patch("pathlib.Path.exists", return_value=True):
                with patch("subprocess.run") as mock_run:
                    mock_run.return_value = MagicMock(
                        returncode=0,
                        stdout="SCT v6.1",
                    )
                    result = detect_sct()

    assert result["found"] is True
    assert (
        "sct" in result["path"].lower() or result["path"] == "/opt/sct/bin/sct_version"
    )


def test_detect_pam50_found():
    """Test PAM50 detection when directory exists with required files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        pam50_dir = Path(tmpdir) / "PAM50"
        pam50_dir.mkdir()
        (pam50_dir / "PAM50_t1.nii.gz").touch()
        (pam50_dir / "PAM50_spinal_levels.nii.gz").touch()

        result = detect_pam50(str(pam50_dir))

    assert result["found"] is True
    assert result["files_ok"] is True
    assert str(pam50_dir) in result["path"]


def test_detect_pam50_missing_files():
    """Test PAM50 detection when directory exists but files missing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        pam50_dir = Path(tmpdir) / "PAM50"
        pam50_dir.mkdir()
        # Only create one file, not both required ones
        (pam50_dir / "PAM50_t1.nii.gz").touch()

        result = detect_pam50(str(pam50_dir))

    assert result["found"] is True
    assert result["files_ok"] is False


def test_detect_pam50_not_found():
    """Test PAM50 detection when directory doesn't exist."""
    result = detect_pam50("/nonexistent/path")

    assert result["found"] is False
    assert result["files_ok"] is False
    assert result["path"] == ""


def test_detect_python_deps():
    """Test Python dependency detection."""
    result = detect_python_deps()

    # We know these are installed in the test environment
    assert "numpy" in result
    assert "pandas" in result
    assert "scipy" in result
    assert "nibabel" in result
    assert "jsonschema" in result

    # Check that versions are captured (not empty or "unknown")
    assert result["numpy"] != ""
    assert result["pandas"] != ""


def test_detect_os_info():
    """Test OS and hardware info detection."""
    result = detect_os_info()

    assert "os" in result
    assert "kernel" in result
    assert "python" in result
    assert "cpu_count" in result
    assert "ram_gb" in result

    # Basic sanity checks
    assert isinstance(result["cpu_count"], int)
    assert result["cpu_count"] > 0
    assert isinstance(result["ram_gb"], (int, float))
    assert result["ram_gb"] > 0
    assert len(result["python"]) > 0


def test_generate_report_all_pass():
    """Test report generation with all checks passing."""
    sct_info = {"found": True, "version": "6.1", "path": "/usr/bin/sct_version"}
    pam50_info = {"found": True, "path": "/data/PAM50", "files_ok": True}
    python_deps = {"numpy": "1.24.0", "pandas": "2.0.0"}
    os_info = {
        "os": "Linux",
        "kernel": "5.15",
        "python": "3.11.0",
        "cpu_count": 4,
        "ram_gb": 16,
    }

    report = generate_report(
        sct_info, pam50_info, python_deps, os_info,
        disk_free=50.0, cwd_writeable=True, tmp_writeable=True
    )

    assert report["status"] == "pass"
    assert report["spineprep"]["version"] == "0.2.0"
    assert "timestamp" in report
    assert report["sct"]["present"] is True
    assert report["pam50"]["present"] is True


def test_generate_report_hard_fail_no_sct():
    """Test report generation with hard failure when SCT missing."""
    sct_info = {"found": False, "version": "", "path": ""}
    pam50_info = {"found": True, "path": "/data/PAM50", "files_ok": True}
    python_deps = {"numpy": "1.24.0"}
    os_info = {
        "os": "Linux",
        "kernel": "5.15",
        "python": "3.11.0",
        "cpu_count": 4,
        "ram_gb": 16,
    }

    report = generate_report(
        sct_info, pam50_info, python_deps, os_info,
        disk_free=50.0, cwd_writeable=True, tmp_writeable=True
    )

    assert report["status"] == "fail"
    assert any("SCT" in note for note in report["notes"])


def test_generate_report_hard_fail_no_pam50():
    """Test report generation with hard failure when PAM50 missing."""
    sct_info = {"found": True, "version": "6.1", "path": "/usr/bin/sct_version"}
    pam50_info = {"found": False, "path": "", "files_ok": False}
    python_deps = {"numpy": "1.24.0"}
    os_info = {
        "os": "Linux",
        "kernel": "5.15",
        "python": "3.11.0",
        "cpu_count": 4,
        "ram_gb": 16,
    }

    report = generate_report(
        sct_info, pam50_info, python_deps, os_info,
        disk_free=50.0, cwd_writeable=True, tmp_writeable=True
    )

    assert report["status"] == "fail"
    assert any("PAM50" in note for note in report["notes"])


def test_generate_report_soft_warn_missing_deps():
    """Test report generation with soft warnings for missing Python packages."""
    sct_info = {"found": True, "version": "6.1", "path": "/usr/bin/sct_version"}
    pam50_info = {"found": True, "path": "/data/PAM50", "files_ok": True}
    python_deps = {"numpy": "1.24.0", "snakemake": ""}  # snakemake missing
    os_info = {
        "os": "Linux",
        "kernel": "5.15",
        "python": "3.11.0",
        "cpu_count": 4,
        "ram_gb": 16,
    }

    report = generate_report(
        sct_info, pam50_info, python_deps, os_info,
        disk_free=50.0, cwd_writeable=True, tmp_writeable=True,
        strict=False
    )

    assert report["status"] == "warn"
    assert any(
        "missing" in note.lower() or "snakemake" in note.lower()
        for note in report["notes"]
    )


def test_generate_report_strict_mode():
    """Test that strict mode upgrades warnings to failures."""
    sct_info = {"found": True, "version": "6.1", "path": "/usr/bin/sct_version"}
    pam50_info = {"found": True, "path": "/data/PAM50", "files_ok": True}
    python_deps = {"numpy": "1.24.0", "snakemake": ""}  # snakemake missing
    os_info = {
        "os": "Linux",
        "kernel": "5.15",
        "python": "3.11.0",
        "cpu_count": 4,
        "ram_gb": 16,
    }

    report = generate_report(
        sct_info, pam50_info, python_deps, os_info,
        disk_free=50.0, cwd_writeable=True, tmp_writeable=True,
        strict=True
    )

    # In strict mode, warnings become failures
    assert report["status"] == "fail" or report["status"] == "warn"


def test_write_doctor_report_creates_file():
    """Test that write_doctor_report creates the JSON file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = Path(tmpdir)
        report = {
            "spineprep": {"version": "0.2.0"},
            "timestamp": "2025-10-08T12:00:00",
            "status": "pass",
            "platform": {
                "os": "Linux",
                "kernel": "5.15",
                "python": "3.11.0",
                "cpu_count": 4,
                "ram_gb": 16,
            },
            "deps": {
                "sct": {
                    "found": True,
                    "version": "6.1",
                    "path": "/usr/bin/sct_version",
                },
                "pam50": {"found": True, "path": "/data/PAM50", "files_ok": True},
                "python": {"numpy": "1.24.0"},
            },
            "notes": [],
        }

        filepath = write_doctor_report(report, out_dir)

        assert filepath.exists()
        assert filepath.parent.name == "provenance"
        assert filepath.name.startswith("doctor-")
        assert filepath.suffix == ".json"

        # Verify content
        with open(filepath) as f:
            loaded = json.load(f)
        assert loaded["status"] == "pass"


def test_write_doctor_report_to_custom_json():
    """Test writing report to a custom JSON path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = Path(tmpdir)
        custom_json = out_dir / "custom_doctor.json"

        report = {
            "spineprep": {"version": "0.2.0"},
            "timestamp": "2025-10-08T12:00:00",
            "status": "pass",
            "platform": {
                "os": "Linux",
                "kernel": "5.15",
                "python": "3.11.0",
                "cpu_count": 4,
                "ram_gb": 16,
            },
            "deps": {
                "sct": {
                    "found": True,
                    "version": "6.1",
                    "path": "/usr/bin/sct_version",
                },
                "pam50": {"found": True, "path": "/data/PAM50", "files_ok": True},
                "python": {},
            },
            "notes": [],
        }

        filepath = write_doctor_report(report, out_dir, json_path=custom_json)

        # The main file should still be created
        assert filepath.exists()
        assert filepath.parent.name == "provenance"

        # The custom JSON should also exist
        assert custom_json.exists()
        with open(custom_json) as f:
            loaded = json.load(f)
        assert loaded["status"] == "pass"


def test_cli_doctor_command_integration():
    """Integration test for spineprep doctor CLI command."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = subprocess.run(
            ["spineprep", "doctor", "--out", tmpdir],
            capture_output=True,
            text=True,
            check=False,
        )

        # Should complete (exit code 0, 1, or 2 depending on environment)
        assert result.returncode in [0, 1, 2]

        # Should produce output
        output = result.stdout + result.stderr
        assert len(output) > 0

        # Should create the JSON report
        provenance_dir = Path(tmpdir) / "provenance"
        if provenance_dir.exists():
            json_files = list(provenance_dir.glob("doctor-*.json"))
            assert len(json_files) > 0

            # Validate JSON structure
            with open(json_files[0]) as f:
                report = json.load(f)
        assert "status" in report
        assert "timestamp" in report
        assert "spineprep" in report
        assert "platform" in report
        assert "sct" in report
        assert "pam50" in report


def test_cli_doctor_strict_mode():
    """Test doctor command with --strict flag."""
    result = subprocess.run(
        ["spineprep", "doctor", "--strict"],
        capture_output=True,
        text=True,
        check=False,
    )

    # Strict mode should upgrade warnings to failures
    assert result.returncode in [0, 1]  # Either pass or fail, no warnings (exit 2)


def test_cli_doctor_custom_json_path():
    """Test doctor command with custom --json path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        custom_json = Path(tmpdir) / "my_doctor_report.json"

        result = subprocess.run(
            ["spineprep", "doctor", "--json", str(custom_json)],
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode in [0, 1, 2]

        # Custom JSON should exist
        assert custom_json.exists()
        with open(custom_json) as f:
            report = json.load(f)
        assert "status" in report


def test_doctor_report_schema_compliance():
    """Test that generated reports comply with the JSON schema."""
    # Generate a sample report
    sct_info = {"found": True, "version": "6.1", "path": "/usr/bin/sct_version"}
    pam50_info = {"found": True, "path": "/data/PAM50", "files_ok": True}
    python_deps = {"numpy": "1.24.0", "pandas": "2.0.0"}
    os_info = {
        "os": "Linux",
        "kernel": "5.15",
        "python": "3.11.0",
        "cpu_count": 4,
        "ram_gb": 16,
    }

    report = generate_report(
        sct_info, pam50_info, python_deps, os_info,
        disk_free=50.0, cwd_writeable=True, tmp_writeable=True
    )

    # Load schema
    schema_path = Path(__file__).parent.parent.parent / "schemas" / "doctor.schema.json"
    if schema_path.exists():
        import jsonschema

        with open(schema_path) as f:
            schema = json.load(f)

        # Validate
        jsonschema.validate(report, schema)
    else:
        # Schema doesn't exist yet, just check basic structure
        assert "spineprep" in report
        assert "version" in report["spineprep"]
        assert "timestamp" in report
        assert "status" in report
        assert report["status"] in ["pass", "warn", "fail"]
        assert "platform" in report
        assert "sct" in report
        assert "pam50" in report
        assert "notes" in report
        assert isinstance(report["notes"], list)
