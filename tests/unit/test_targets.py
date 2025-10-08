"""Unit tests for targets path utilities."""

from workflow.lib.targets import (
    bold_fname,
    confounds_json_path,
    confounds_tsv_path,
    crop_json_path,
    deriv_path,
    motion_bold_path,
    mppca_bold_path,
)


def test_bold_fname():
    """Test BOLD filename generation."""
    # Basic case
    fname = bold_fname("sub-01", "ses-01", "rest", "01")
    assert fname == "sub-01_ses-01_task-rest_run-01_bold.nii.gz"

    # No session
    fname = bold_fname("sub-01", None, "rest", "01")
    assert fname == "sub-01_task-rest_run-01_bold.nii.gz"

    # No task/run
    fname = bold_fname("sub-01", "ses-01")
    assert fname == "sub-01_ses-01_bold.nii.gz"

    # Minimal
    fname = bold_fname("sub-01")
    assert fname == "sub-01_bold.nii.gz"


def test_deriv_path():
    """Test derivative path generation."""
    # With filename
    path = deriv_path("/tmp/deriv", "sub-01", "ses-01", "func", "test.nii.gz")
    assert path == "/tmp/deriv/sub-01/ses-01/func/test.nii.gz"

    # No session
    path = deriv_path("/tmp/deriv", "sub-01", None, "func", "test.nii.gz")
    assert path == "/tmp/deriv/sub-01/func/test.nii.gz"

    # No filename
    path = deriv_path("/tmp/deriv", "sub-01", "ses-01", "func")
    assert path == "/tmp/deriv/sub-01/ses-01/func"


def test_motion_bold_path():
    """Test motion-corrected BOLD path generation."""
    path = motion_bold_path("/tmp/deriv", "sub-01", "ses-01", "rest", "01")
    expected = "/tmp/deriv/sub-01/ses-01/func/sub-01_ses-01_task-rest_run-01_desc-motioncorr_bold.nii.gz"
    assert path == expected

    # No session
    path = motion_bold_path("/tmp/deriv", "sub-01", None, "rest", "01")
    expected = (
        "/tmp/deriv/sub-01/func/sub-01_task-rest_run-01_desc-motioncorr_bold.nii.gz"
    )
    assert path == expected


def test_confounds_paths():
    """Test confounds TSV and JSON path generation."""
    # TSV
    tsv_path = confounds_tsv_path("/tmp/deriv", "sub-01", "ses-01", "rest", "01")
    expected_tsv = "/tmp/deriv/sub-01/ses-01/func/sub-01_ses-01_task-rest_run-01_desc-confounds_timeseries.tsv"
    assert tsv_path == expected_tsv

    # JSON
    json_path = confounds_json_path("/tmp/deriv", "sub-01", "ses-01", "rest", "01")
    expected_json = "/tmp/deriv/sub-01/ses-01/func/sub-01_ses-01_task-rest_run-01_desc-confounds_timeseries.json"
    assert json_path == expected_json


def test_mppca_bold_path():
    """Test MP-PCA BOLD path generation."""
    path = mppca_bold_path("/tmp/deriv", "sub-01", "ses-01", "rest", "01")
    expected = "/tmp/deriv/sub-01/ses-01/func/sub-01_ses-01_task-rest_run-01_desc-mppca_bold.nii.gz"
    assert path == expected


def test_crop_json_path():
    """Test crop JSON path generation."""
    path = crop_json_path("/tmp/deriv", "sub-01", "ses-01", "rest", "01")
    expected = (
        "/tmp/deriv/sub-01/ses-01/func/sub-01_ses-01_task-rest_run-01_desc-crop.json"
    )
    assert path == expected


def test_targets_paths_roundtrip():
    """Test that path generation works end-to-end."""
    sub, ses, task, run = "sub-01", None, "rest", "01"

    # Generate base filename
    fname = bold_fname(sub, ses, task, run)
    assert fname.startswith("sub-01_") and fname.endswith("_bold.nii.gz")

    # Generate motion path
    mb = motion_bold_path("/tmp/deriv", sub, ses, task, run)
    assert mb.endswith("_desc-motioncorr_bold.nii.gz")
    assert "/tmp/deriv/sub-01/func/" in mb

    # Generate derivative path
    dp = deriv_path("/tmp/deriv", sub, ses, "func", fname)
    assert "/tmp/deriv/sub-01/func/" in dp
