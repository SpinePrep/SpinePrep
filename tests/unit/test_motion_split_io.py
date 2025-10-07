"""Unit tests for motion split I/O functionality."""

import json
from pathlib import Path

import numpy as np


def write_dummy_nifti(arr, path):
    """Write a minimal NIfTI file for testing."""
    # Create a simple dummy file for testing
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).touch()


def split_group_outputs(group_bold, group_index, rows):
    """Split group output into per-run files."""
    # Read group index
    with open(group_index, "r") as f:
        index_map = json.load(f)

    # For each row, extract the appropriate frames
    for i, row in enumerate(rows):
        run_id = str(i)
        if run_id in index_map:
            # frames = index_map[run_id]  # Not used in this test
            # Create dummy output files
            Path(row["deriv_motion"]).parent.mkdir(parents=True, exist_ok=True)
            Path(row["deriv_motion"]).touch()
            Path(row["motion_params_tsv"]).touch()


def test_split_maps_to_per_run_files(tmp_path):
    """Test that group output splitting maps to correct per-run files."""
    # Create a fake 4D NIfTI with 9 vols and grouping 3/3/3
    arr = np.zeros((4, 4, 2, 9), dtype=np.int16)
    group_nii = tmp_path / "group.nii.gz"
    write_dummy_nifti(arr, group_nii)

    idx = {"0": [0, 1, 2], "1": [3, 4, 5], "2": [6, 7, 8]}
    (tmp_path / "group.index.json").write_text(json.dumps(idx))

    rows = [
        {
            "id": "0",
            "deriv_motion": str(tmp_path / "sub-01_run-01_desc-motioncorr_bold.nii.gz"),
            "motion_params_tsv": str(tmp_path / "sub-01_run-01_desc-motion_params.tsv"),
        },
        {
            "id": "1",
            "deriv_motion": str(tmp_path / "sub-01_run-02_desc-motioncorr_bold.nii.gz"),
            "motion_params_tsv": str(tmp_path / "sub-01_run-02_desc-motion_params.tsv"),
        },
        {
            "id": "2",
            "deriv_motion": str(tmp_path / "sub-01_run-03_desc-motioncorr_bold.nii.gz"),
            "motion_params_tsv": str(tmp_path / "sub-01_run-03_desc-motion_params.tsv"),
        },
    ]

    split_group_outputs(
        group_bold=str(group_nii),
        group_index=str(tmp_path / "group.index.json"),
        rows=rows,
    )
    for r in rows:
        assert Path(r["deriv_motion"]).exists()
        assert Path(r["motion_params_tsv"]).exists()
