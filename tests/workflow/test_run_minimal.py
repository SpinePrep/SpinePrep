"""Tests for minimal workflow execution."""

from __future__ import annotations

import json
import subprocess

import nibabel as nib
import numpy as np


def test_run_minimal_workflow(tmp_path):
    """Test minimal workflow execution creates touch file."""
    # Create minimal BIDS
    bids_dir = tmp_path / "bids"
    bids_dir.mkdir()

    (bids_dir / "dataset_description.json").write_text(
        json.dumps({"Name": "Test", "BIDSVersion": "1.8.0"})
    )

    func_dir = bids_dir / "sub-01" / "func"
    func_dir.mkdir(parents=True)

    nifti_path = func_dir / "sub-01_task-rest_bold.nii.gz"
    json_path = func_dir / "sub-01_task-rest_bold.json"

    # Create minimal NIfTI
    data = np.zeros((2, 2, 2, 2), dtype=np.float32)
    img = nib.Nifti1Image(data, np.eye(4))
    nib.save(img, str(nifti_path))

    json_path.write_text(json.dumps({"RepetitionTime": 2.0, "EchoTime": 0.03}))

    # Run workflow
    out_dir = tmp_path / "out"

    result = subprocess.run(
        ["spineprep", "run", "--bids", str(bids_dir), "--out", str(out_dir)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, f"Workflow failed: {result.stderr}\n{result.stdout}"

    # Verify outputs
    manifest_path = out_dir / "manifest.csv"
    assert manifest_path.exists(), "Manifest not created"

    touch_file = out_dir / ".manifest.touch"
    assert touch_file.exists(), "Touch file not created"


def test_run_requires_bids_and_out():
    """Test that run command requires --bids and --out."""
    result = subprocess.run(
        ["spineprep", "run"],
        capture_output=True,
        text=True,
        check=False,
    )

    # Should fail without --bids and --out
    assert result.returncode != 0
    assert "required" in result.stdout.lower() or "error" in result.stdout.lower()
