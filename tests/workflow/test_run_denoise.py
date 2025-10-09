"""Tests for workflow with MP-PCA denoising."""

from __future__ import annotations

import json
import subprocess

import nibabel as nib
import numpy as np


def test_workflow_generates_mppca_output(tmp_path):
    """Test that workflow generates _desc-mppca_bold.nii.gz files."""
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

    # Create small 4D NIfTI
    data = np.random.randn(4, 4, 2, 3).astype(np.float32)
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

    # Verify denoised output exists
    denoised_path = (
        out_dir / "denoised" / "sub-01_task-rest_bold_desc-mppca_bold.nii.gz"
    )
    assert denoised_path.exists(), f"Denoised file not created at {denoised_path}"

    # Verify it's valid NIfTI
    denoised_img = nib.load(str(denoised_path))
    assert denoised_img.shape == data.shape, "Shape not preserved"
