"""Unit tests for mask path generation."""

from workflow.lib.registration import mask_paths


def test_deriv_mask_paths_exposed():
    """Test that mask paths are correctly generated for derivatives."""
    row = {"sub": "sub-01", "ses": "ses-01", "task": "motor", "run": "01"}
    m = mask_paths(row)

    for k in ("cord", "wm", "csf"):
        assert f"{k}_mask_epi" in m
        assert m[f"{k}_mask_epi"] == "" or m[f"{k}_mask_epi"].endswith(".nii.gz")


def test_mask_paths_without_session():
    """Test mask path generation without session."""
    row = {"sub": "sub-01", "task": "motor", "run": "01"}
    m = mask_paths(row)

    for k in ("cord", "wm", "csf"):
        assert f"{k}_mask_epi" in m
        # Should not contain ses-01 in path
        assert "ses-01" not in m[f"{k}_mask_epi"]


def test_mask_paths_bids_naming():
    """Test that mask paths follow BIDS naming convention."""
    row = {"sub": "sub-01", "ses": "ses-01", "task": "motor", "run": "01"}
    m = mask_paths(row)

    expected_base = "sub-01_ses-ses-01_task-motor_run-01"

    for k in ("cord", "wm", "csf"):
        path = m[f"{k}_mask_epi"]
        if path:  # If not empty
            assert expected_base in path
            assert f"space-EPI_desc-{k}mask" in path
