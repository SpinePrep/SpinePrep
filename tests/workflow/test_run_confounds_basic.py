"""Tests for workflow with basic confounds computation."""

from __future__ import annotations

import csv
import json
import subprocess

import nibabel as nib
import numpy as np


def test_workflow_generates_confounds_tsv_json(tmp_path):
    """Test that workflow generates confounds TSV and JSON."""
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

    # Create 4D NIfTI with a jump to test spike detection
    data = np.ones((4, 4, 2, 6), dtype=np.float32) * 100.0
    # Add jump at volume 3
    data[:, :, :, 3] += 20.0

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

    # Verify confounds TSV exists
    tsv_path = out_dir / "confounds" / "sub-01_task-rest_bold_desc-basic_confounds.tsv"
    assert tsv_path.exists(), f"Confounds TSV not created at {tsv_path}"

    # Verify JSON sidecar exists
    json_sidecar = (
        out_dir / "confounds" / "sub-01_task-rest_bold_desc-basic_confounds.json"
    )
    assert json_sidecar.exists(), "Confounds JSON sidecar not created"

    # Verify TSV structure
    with open(tsv_path) as f:
        reader = csv.DictReader(f, delimiter="\t")
        rows = list(reader)

    # Should have 6 rows (6 volumes)
    assert len(rows) == 6, f"Expected 6 rows, got {len(rows)}"

    # Check columns
    expected_cols = [
        "trans_x",
        "trans_y",
        "trans_z",
        "rot_x",
        "rot_y",
        "rot_z",
        "fd_power",
        "dvars",
        "spike",
    ]
    assert list(rows[0].keys()) == expected_cols, "Column order mismatch"

    # First volume should have zeros for motion and FD
    assert float(rows[0]["fd_power"]) == 0.0
    assert float(rows[0]["dvars"]) == 0.0
    assert int(rows[0]["spike"]) == 0

    # Verify JSON sidecar content
    with open(json_sidecar) as f:
        metadata = json.load(f)

    assert "Estimator" in metadata
    assert "FDPowerRadiusMM" in metadata
    assert "SpikeFDThr" in metadata
    assert metadata["FDPowerRadiusMM"] == 50.0
