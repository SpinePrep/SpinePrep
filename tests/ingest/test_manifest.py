"""Tests for manifest writer and validation."""

from __future__ import annotations

import csv
import json

from spineprep.ingest.manifest import (
    MANIFEST_COLUMNS,
    validate_bids_essentials,
    write_manifest,
)


def test_manifest_columns_complete():
    """Verify MANIFEST_COLUMNS has all 16 required columns."""
    assert len(MANIFEST_COLUMNS) == 16
    assert "subject" in MANIFEST_COLUMNS
    assert "pe_dir" in MANIFEST_COLUMNS
    assert "tr" in MANIFEST_COLUMNS
    assert "filepath" in MANIFEST_COLUMNS


def test_write_manifest_creates_file(tmp_path):
    """Test that write_manifest creates file with correct structure."""
    rows = [
        {
            "subject": "sub-01",
            "session": "",
            "task": "rest",
            "acq": "",
            "run": "01",
            "modality": "func",
            "pe_dir": "j-",
            "tr": 2.0,
            "te": 0.03,
            "voxel_size_mm": "2.00x2.00x3.00",
            "fov_mm": "128.0x128.0x72.0",
            "dim": "64x64x24",
            "nslices": 24,
            "volumes": 150,
            "coverage_desc": "unknown",
            "filepath": "/data/test.nii.gz",
        }
    ]

    out_path = tmp_path / "out" / "manifest.csv"
    result_path = write_manifest(rows, out_path)

    assert result_path.exists()
    assert result_path == out_path

    # Verify content
    with open(result_path) as f:
        reader = csv.DictReader(f)
        header = reader.fieldnames

        assert header == MANIFEST_COLUMNS

        data_rows = list(reader)
        assert len(data_rows) == 1
        assert data_rows[0]["subject"] == "sub-01"
        assert data_rows[0]["tr"] == "2.0"
        assert data_rows[0]["pe_dir"] == "j-"


def test_validate_bids_essentials_nonexistent(tmp_path):
    """Test validation with nonexistent directory."""
    bids_dir = tmp_path / "nonexistent"

    valid, warnings = validate_bids_essentials(bids_dir)

    assert not valid
    assert len(warnings) > 0
    assert any("not exist" in w for w in warnings)


def test_validate_bids_essentials_missing_description(tmp_path):
    """Test validation without dataset_description.json."""
    bids_dir = tmp_path / "bids"
    bids_dir.mkdir()

    valid, warnings = validate_bids_essentials(bids_dir)

    assert not valid
    assert any("dataset_description" in w for w in warnings)


def test_validate_bids_essentials_no_subjects(tmp_path):
    """Test validation with dataset_description but no subjects."""
    bids_dir = tmp_path / "bids"
    bids_dir.mkdir()

    (bids_dir / "dataset_description.json").write_text(json.dumps({"Name": "Test"}))

    valid, warnings = validate_bids_essentials(bids_dir)

    assert not valid
    assert any("sub-*" in w or "subject" in w for w in warnings)


def test_validate_bids_essentials_valid(tmp_path):
    """Test validation with valid BIDS structure."""
    bids_dir = tmp_path / "bids"
    bids_dir.mkdir()

    (bids_dir / "dataset_description.json").write_text(
        json.dumps({"Name": "Test", "BIDSVersion": "1.8.0"})
    )

    (bids_dir / "sub-01").mkdir()

    valid, warnings = validate_bids_essentials(bids_dir)

    assert valid
    assert len(warnings) == 0
