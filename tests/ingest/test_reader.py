"""Tests for BIDS reader."""

from __future__ import annotations

import json
from pathlib import Path

import nibabel as nib
import numpy as np

from spineprep.ingest.reader import (
    extract_nifti_metadata,
    parse_bids_entities,
    read_json_sidecar,
    scan_bids_directory,
)


def test_parse_bids_entities():
    """Test BIDS entity parsing from filepath."""
    path = Path(
        "/data/bids/sub-01/ses-02/func/sub-01_ses-02_task-rest_run-03_bold.nii.gz"
    )
    entities = parse_bids_entities(path)

    assert entities["subject"] == "sub-01"
    assert entities["session"] == "ses-02"
    assert entities["task"] == "rest"
    assert entities["run"] == "03"
    assert entities["modality"] == "func"


def test_parse_bids_entities_minimal():
    """Test parsing with minimal entities (no session/task/run)."""
    path = Path("/data/bids/sub-99/anat/sub-99_T2w.nii.gz")
    entities = parse_bids_entities(path)

    assert entities["subject"] == "sub-99"
    assert entities["session"] == ""
    assert entities["task"] == ""
    assert entities["run"] == ""
    assert entities["modality"] == "anat"


def test_read_json_sidecar(tmp_path):
    """Test reading JSON sidecar."""
    nifti = tmp_path / "sub-01_bold.nii.gz"
    json_file = tmp_path / "sub-01_bold.json"

    sidecar_data = {
        "RepetitionTime": 2.0,
        "EchoTime": 0.03,
        "PhaseEncodingDirection": "j-",
    }

    json_file.write_text(json.dumps(sidecar_data))

    result = read_json_sidecar(nifti)

    assert result["RepetitionTime"] == 2.0
    assert result["EchoTime"] == 0.03
    assert result["PhaseEncodingDirection"] == "j-"


def test_read_json_sidecar_missing(tmp_path):
    """Test reading JSON when sidecar doesn't exist."""
    nifti = tmp_path / "sub-01_bold.nii.gz"

    result = read_json_sidecar(nifti)

    assert result == {}


def test_extract_nifti_metadata(tmp_path):
    """Test extracting metadata from NIfTI header."""
    # Create a small 4D NIfTI file
    data = np.random.rand(64, 64, 24, 100).astype(np.float32)
    affine = np.diag([2.0, 2.0, 3.0, 1.0])
    img = nib.Nifti1Image(data, affine)

    nifti_path = tmp_path / "test_bold.nii.gz"
    nib.save(img, str(nifti_path))

    meta = extract_nifti_metadata(nifti_path)

    assert meta["voxel_size_mm"] == "2.00x2.00x3.00"
    assert meta["fov_mm"] == "128.0x128.0x72.0"
    assert meta["dim"] == "64x64x24"
    assert meta["nslices"] == 24
    assert meta["volumes"] == 100


def test_extract_nifti_metadata_3d(tmp_path):
    """Test extracting metadata from 3D NIfTI (anatomical)."""
    data = np.random.rand(128, 128, 40).astype(np.float32)
    affine = np.diag([1.0, 1.0, 1.5, 1.0])
    img = nib.Nifti1Image(data, affine)

    nifti_path = tmp_path / "test_T2w.nii.gz"
    nib.save(img, str(nifti_path))

    meta = extract_nifti_metadata(nifti_path)

    assert meta["voxel_size_mm"] == "1.00x1.00x1.50"
    assert meta["dim"] == "128x128x40"
    assert meta["nslices"] == 40
    assert meta["volumes"] == 1


def test_scan_bids_directory(tmp_path):
    """Test scanning a tiny BIDS directory."""
    bids_dir = tmp_path / "bids"
    bids_dir.mkdir()

    # Create dataset_description.json
    (bids_dir / "dataset_description.json").write_text(
        json.dumps({"Name": "Test", "BIDSVersion": "1.8.0"})
    )

    # Create a functional series
    func_dir = bids_dir / "sub-01" / "ses-01" / "func"
    func_dir.mkdir(parents=True)

    nifti_path = func_dir / "sub-01_ses-01_task-rest_run-01_bold.nii.gz"
    json_path = func_dir / "sub-01_ses-01_task-rest_run-01_bold.json"

    # Create minimal NIfTI
    data = np.random.rand(64, 64, 20, 50).astype(np.float32)
    affine = np.diag([2.0, 2.0, 3.0, 1.0])
    img = nib.Nifti1Image(data, affine)
    nib.save(img, str(nifti_path))

    # Create JSON sidecar
    json_path.write_text(
        json.dumps(
            {
                "RepetitionTime": 2.0,
                "EchoTime": 0.03,
                "PhaseEncodingDirection": "j-",
            }
        )
    )

    # Scan directory
    rows = scan_bids_directory(bids_dir)

    assert len(rows) == 1
    row = rows[0]

    # Verify all required keys present
    assert row["subject"] == "sub-01"
    assert row["session"] == "ses-01"
    assert row["task"] == "rest"
    assert row["run"] == "01"
    assert row["modality"] == "func"
    assert row["pe_dir"] == "j-"
    assert row["tr"] == 2.0
    assert row["te"] == 0.03
    assert "2.00x2.00x3.00" in row["voxel_size_mm"]
    assert row["volumes"] == 50
    assert row["nslices"] == 20


def test_scan_bids_directory_no_dataset_description(tmp_path):
    """Test that scan fails without dataset_description.json."""
    bids_dir = tmp_path / "bids"
    bids_dir.mkdir()

    try:
        scan_bids_directory(bids_dir)
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "dataset_description.json" in str(e)


def test_scan_bids_directory_empty(tmp_path):
    """Test scanning BIDS directory with no imaging files."""
    bids_dir = tmp_path / "bids"
    bids_dir.mkdir()

    # Create dataset_description.json
    (bids_dir / "dataset_description.json").write_text(
        json.dumps({"Name": "Empty", "BIDSVersion": "1.8.0"})
    )

    # Create subject dir but no imaging files
    sub_dir = bids_dir / "sub-01"
    sub_dir.mkdir()

    rows = scan_bids_directory(bids_dir)

    # Should return empty list, not crash
    assert rows == []
