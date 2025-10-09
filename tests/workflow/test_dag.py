"""Tests for DAG export."""

from __future__ import annotations

import json
import subprocess

import nibabel as nib
import numpy as np


def test_dag_export_svg(tmp_path):
    """Test DAG export to SVG format."""
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

    # Export DAG
    out_dir = tmp_path / "out"
    dag_path = out_dir / "dag.svg"

    result = subprocess.run(
        [
            "spineprep",
            "run",
            "--bids",
            str(bids_dir),
            "--out",
            str(out_dir),
            "--save-dag",
            str(dag_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert (
        result.returncode == 0
    ), f"DAG export failed: {result.stderr}\n{result.stdout}"
    assert dag_path.exists(), "DAG file not created"
    assert dag_path.stat().st_size > 0, "DAG file is empty"

    # Verify it's SVG
    content = dag_path.read_text()
    assert "<svg" in content or "<?xml" in content, "Not valid SVG"


def test_dag_export_dot(tmp_path):
    """Test DAG export to DOT format."""
    # Create minimal BIDS
    bids_dir = tmp_path / "bids"
    bids_dir.mkdir()

    (bids_dir / "dataset_description.json").write_text(
        json.dumps({"Name": "Test", "BIDSVersion": "1.8.0"})
    )

    sub_dir = bids_dir / "sub-01"
    sub_dir.mkdir()

    # Export DAG to .dot
    out_dir = tmp_path / "out"
    dag_path = out_dir / "dag.dot"

    # First generate manifest via dry-run
    subprocess.run(
        [
            "spineprep",
            "run",
            "--bids",
            str(bids_dir),
            "--out",
            str(out_dir),
            "--dry-run",
        ],
        capture_output=True,
        check=False,
    )

    # Now export DAG
    result = subprocess.run(
        [
            "spineprep",
            "run",
            "--bids",
            str(bids_dir),
            "--out",
            str(out_dir),
            "--save-dag",
            str(dag_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, f"DAG export failed: {result.stderr}"
    assert dag_path.exists(), "DAG DOT file not created"

    # Verify it's DOT format
    content = dag_path.read_text()
    assert "digraph" in content, "Not valid DOT format"
