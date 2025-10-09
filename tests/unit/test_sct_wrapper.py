"""Unit tests for SCT wrapper."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def test_build_sct_command_basic():
    """Test basic SCT command building."""
    from spineprep.registration.sct import build_sct_register_cmd

    cmd = build_sct_register_cmd(
        src_image="epi.nii.gz",
        dest_image="template.nii.gz",
        out_warp="warp.nii.gz",
    )

    assert "sct_register_multimodal" in cmd
    assert "-i" in cmd
    assert "epi.nii.gz" in cmd
    assert "-d" in cmd
    assert "template.nii.gz" in cmd
    assert "-owarp" in cmd
    assert "warp.nii.gz" in cmd


def test_build_sct_command_with_resampled():
    """Test SCT command with resampled output."""
    from spineprep.registration.sct import build_sct_register_cmd

    cmd = build_sct_register_cmd(
        src_image="epi.nii.gz",
        dest_image="template.nii.gz",
        out_warp="warp.nii.gz",
        out_resampled="epi_reg.nii.gz",
    )

    assert "-o" in cmd
    assert "epi_reg.nii.gz" in cmd


def test_build_sct_command_with_params():
    """Test SCT command with custom parameters."""
    from spineprep.registration.sct import build_sct_register_cmd

    cmd = build_sct_register_cmd(
        src_image="epi.nii.gz",
        dest_image="template.nii.gz",
        out_warp="warp.nii.gz",
        param="step=1,type=im,algo=rigid",
    )

    assert "-param" in cmd
    assert "step=1,type=im,algo=rigid" in cmd


@patch("subprocess.run")
def test_run_sct_register_success(mock_run):
    """Test successful SCT registration."""
    from spineprep.registration.sct import run_sct_register

    # Mock successful subprocess run
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "Registration completed successfully"
    mock_result.stderr = ""
    mock_run.return_value = mock_result

    result = run_sct_register(
        src_image="epi.nii.gz",
        dest_image="template.nii.gz",
        out_warp="warp.nii.gz",
    )

    assert result["success"] is True
    assert result["return_code"] == 0
    assert "Registration completed" in result["stdout"]
    # Should be called twice: once for version, once for registration
    assert mock_run.call_count == 2


@patch("subprocess.run")
def test_run_sct_register_failure(mock_run):
    """Test failed SCT registration."""
    from spineprep.registration.sct import run_sct_register

    # Mock failed subprocess run
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stdout = ""
    mock_result.stderr = "Error: Image not found"
    mock_run.return_value = mock_result

    result = run_sct_register(
        src_image="missing.nii.gz",
        dest_image="template.nii.gz",
        out_warp="warp.nii.gz",
    )

    assert result["success"] is False
    assert result["return_code"] == 1
    assert "Error" in result["stderr"]


@patch("subprocess.run")
def test_run_sct_register_captures_version(mock_run):
    """Test that SCT version is captured."""
    from spineprep.registration.sct import run_sct_register

    # Mock version check and registration
    def side_effect(*args, **kwargs):
        cmd = args[0]
        if "sct_version" in cmd:
            result = MagicMock()
            result.returncode = 0
            result.stdout = "5.8.0"
            return result
        else:
            result = MagicMock()
            result.returncode = 0
            result.stdout = "Registration completed"
            result.stderr = ""
            return result

    mock_run.side_effect = side_effect

    result = run_sct_register(
        src_image="epi.nii.gz",
        dest_image="template.nii.gz",
        out_warp="warp.nii.gz",
    )

    assert "sct_version" in result
    assert result["sct_version"] == "5.8.0"


def test_check_doctor_status_green(tmp_path):
    """Test doctor status check passes when green."""
    from spineprep.registration.sct import check_doctor_status

    doctor_json = tmp_path / "doctor.json"
    doctor_json.write_text(
        """{
        "checks": {
            "sct_installed": {"status": "green"},
            "pam50_available": {"status": "green"}
        }
    }"""
    )

    # Should not raise
    check_doctor_status(str(doctor_json))


def test_check_doctor_status_missing_file():
    """Test doctor status check raises if file missing."""
    from spineprep.registration.sct import check_doctor_status

    with pytest.raises((FileNotFoundError, RuntimeError), match="doctor"):
        check_doctor_status("/nonexistent/doctor.json")


def test_check_doctor_status_red(tmp_path):
    """Test doctor status check raises if checks are red."""
    from spineprep.registration.sct import check_doctor_status

    doctor_json = tmp_path / "doctor.json"
    doctor_json.write_text(
        """{
        "checks": {
            "sct_installed": {"status": "red", "message": "SCT not found"},
            "pam50_available": {"status": "green"}
        }
    }"""
    )

    with pytest.raises(RuntimeError, match="SCT.*red"):
        check_doctor_status(str(doctor_json))


def test_map_sct_error_actionable():
    """Test SCT error mapping provides actionable messages."""
    from spineprep.registration.sct import map_sct_error

    error_msg = map_sct_error(1, "sct_register_multimodal: command not found")
    assert "install" in error_msg.lower() or "path" in error_msg.lower()

    error_msg = map_sct_error(1, "cannot open image")
    assert "file" in error_msg.lower() or "path" in error_msg.lower()


def test_create_output_paths():
    """Test creation of output paths following BIDS derivatives structure."""
    from spineprep.registration.sct import create_output_paths

    paths = create_output_paths(
        subject="sub-01",
        session=None,
        task="rest",
        out_dir="/data/derivatives",
    )

    assert "warp" in paths
    assert "registered" in paths
    assert "metrics" in paths
    assert "mosaic_before" in paths
    assert "mosaic_after" in paths

    # Check paths follow BIDS structure
    assert "sub-01" in paths["warp"]
    assert "xfm" in paths["warp"]
    assert "func" in paths["registered"]
    assert "qc" in paths["metrics"]
