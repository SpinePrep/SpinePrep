"""Tests for confounds motion metrics (FD and DVARS)."""

from __future__ import annotations

import json
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

from spineprep.confounds.io import write_confounds_tsv_json
from spineprep.confounds.motion import compute_dvars, compute_fd_power
from spineprep.confounds.plot import plot_motion_png


def test_fd_power_exactness():
    """Test FD computation (Power) with known synthetic motion parameters."""
    # Create synthetic motion: 10 timepoints, 6 parameters
    # Known deltas to produce predictable FD
    motion = np.array(
        [
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],  # t=0
            [1.0, 0.0, 0.0, 0.0, 0.0, 0.0],  # t=1: delta_x=1mm → FD=1.0
            [1.0, 2.0, 0.0, 0.0, 0.0, 0.0],  # t=2: delta_y=2mm → FD=2.0
            [1.0, 2.0, 0.0, 0.01, 0.0, 0.0],  # t=3: delta_rot_x=0.01rad → FD=0.5
            [1.0, 2.0, 0.0, 0.01, 0.0, 0.0],  # t=4: no change → FD=0.0
            [2.0, 3.0, 1.0, 0.02, 0.01, 0.0],  # t=5: complex
            [2.0, 3.0, 1.0, 0.02, 0.01, 0.0],  # t=6: no change → FD=0.0
            [2.0, 3.0, 1.0, 0.02, 0.01, 0.0],  # t=7: no change → FD=0.0
            [3.0, 3.0, 1.0, 0.02, 0.01, 0.0],  # t=8: delta_x=1mm → FD=1.0
            [3.0, 3.0, 2.0, 0.02, 0.01, 0.0],  # t=9: delta_z=1mm → FD=1.0
        ],
        dtype=np.float32,
    )

    fd = compute_fd_power(motion, radius_mm=50.0)

    # Expected FD values (Power: sum of absolute differences)
    expected = np.array(
        [
            0.0,  # t=0 (always 0)
            1.0,  # t=1: |1-0| = 1.0
            2.0,  # t=2: |2-0| = 2.0
            0.5,  # t=3: 50mm * 0.01rad = 0.5mm
            0.0,  # t=4: no change
            4.0,  # t=5: |1|+|1|+|1| + 50*(|0.01|+|0.01|+|0|) = 3 + 1.0 = 4.0
            0.0,  # t=6
            0.0,  # t=7
            1.0,  # t=8
            1.0,  # t=9
        ],
        dtype=np.float32,
    )

    # Assert exactness within tolerance 1e-6
    np.testing.assert_allclose(fd, expected, atol=1e-6)
    assert fd.dtype == np.float32


def test_fd_power_determinism():
    """Test that FD computation is deterministic."""
    motion = np.random.RandomState(42).randn(20, 6).astype(np.float32) * 0.5

    fd1 = compute_fd_power(motion)
    fd2 = compute_fd_power(motion)

    np.testing.assert_array_equal(fd1, fd2)


def test_dvars_determinism():
    """Test DVARS with synthetic 4D volume for determinism."""
    # Create small synthetic 4D array with fixed seed
    np.random.seed(42)
    data = np.random.randn(4, 4, 4, 10).astype(np.float32)

    # Insert a known step change at t=5
    data[:, :, :, 5:] += 10.0

    dvars = compute_dvars(data)

    # DVARS[0] should be 0
    assert dvars[0] == 0.0
    assert dvars.dtype == np.float32

    # DVARS[5] should be large (step change)
    assert dvars[5] > dvars[4]
    assert dvars[5] > 1.0  # Significant change

    # Later timepoints should have smaller DVARS (noise only)
    assert dvars[6] < dvars[5]

    # Test determinism
    dvars2 = compute_dvars(data)
    np.testing.assert_array_equal(dvars, dvars2)


def test_dvars_with_mask():
    """Test DVARS with explicit mask."""
    np.random.seed(42)
    data = np.random.randn(8, 8, 4, 10).astype(np.float32)

    # Create a mask
    mask = np.zeros((8, 8, 4), dtype=bool)
    mask[2:6, 2:6, :] = True

    dvars = compute_dvars(data, mask=mask)

    assert len(dvars) == 10
    assert dvars[0] == 0.0
    assert dvars.dtype == np.float32


def test_confounds_tsv_json_schema(tmp_path: Path):
    """Test that confounds TSV and JSON match schema v1."""
    # Create synthetic motion params
    motion = np.array(
        [
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            [0.1, 0.0, 0.0, 0.0, 0.0, 0.0],
            [0.1, 0.2, 0.0, 0.001, 0.0, 0.0],
        ],
        dtype=np.float32,
    )

    fd = compute_fd_power(motion, radius_mm=50.0)
    dvars = np.array([0.0, 1.2, 0.8], dtype=np.float32)

    # Write TSV and JSON
    tsv_path = tmp_path / "sub-01_task-rest_desc-confounds_timeseries.tsv"
    json_path = tmp_path / "sub-01_task-rest_desc-confounds_timeseries.json"

    write_confounds_tsv_json(
        tsv_path=tsv_path,
        json_path=json_path,
        motion_params=motion,
        fd=fd,
        dvars=dvars,
    )

    # Verify TSV exists and has correct structure
    assert tsv_path.exists()
    assert json_path.exists()

    # Read TSV
    import csv

    with tsv_path.open() as f:
        reader = csv.DictReader(f, delimiter="\t")
        rows = list(reader)
        cols = reader.fieldnames

    # Verify column order and names
    expected_cols = [
        "trans_x",
        "trans_y",
        "trans_z",
        "rot_x",
        "rot_y",
        "rot_z",
        "fd",
        "dvars",
    ]
    assert cols == expected_cols

    # Verify row count
    assert len(rows) == 3

    # Verify first row values
    assert float(rows[0]["trans_x"]) == 0.0
    assert float(rows[0]["fd"]) == 0.0
    assert float(rows[0]["dvars"]) == 0.0

    # Verify second row values
    assert float(rows[1]["trans_x"]) == pytest.approx(0.1, abs=1e-6)
    assert float(rows[1]["fd"]) == pytest.approx(0.1, abs=1e-6)

    # Read JSON and verify schema v1 compliance
    with json_path.open() as f:
        meta = json.load(f)

    # Verify required top-level keys
    assert "SpinePrepSchemaVersion" in meta
    assert meta["SpinePrepSchemaVersion"] == "1.0"

    # Verify column descriptions exist
    for col in expected_cols:
        assert col in meta, f"Column '{col}' missing from JSON sidecar"
        col_meta = meta[col]
        assert "LongName" in col_meta
        assert "Description" in col_meta
        assert "Units" in col_meta

    # Verify FD metadata
    fd_meta = meta["fd"]
    assert "Power" in fd_meta["Method"]
    assert "mm" in fd_meta["Units"]
    assert "SoftwareName" in meta
    assert "SoftwareVersion" in meta


def test_plot_motion_png(tmp_path: Path):
    """Test that motion plot PNG is created."""
    # Synthetic data
    motion = np.random.RandomState(42).randn(20, 6).astype(np.float32) * 0.5
    fd = compute_fd_power(motion)
    dvars = np.abs(np.random.RandomState(43).randn(20).astype(np.float32)) * 2.0
    dvars[0] = 0.0

    png_path = tmp_path / "sub-01_task-rest_motion.png"

    plot_motion_png(
        png_path=png_path,
        motion_params=motion,
        fd=fd,
        dvars=dvars,
    )

    # Verify PNG exists
    assert png_path.exists()
    assert png_path.stat().st_size > 1000  # Should be a real PNG


def test_full_pipeline_io(tmp_path: Path):
    """Test full pipeline: compute metrics, write TSV/JSON, plot."""
    # Create synthetic 4D NIfTI
    np.random.seed(100)
    data = np.random.randn(4, 4, 4, 15).astype(np.float32) + 100.0
    img = nib.Nifti1Image(data, affine=np.eye(4))
    nifti_path = tmp_path / "sub-01_task-rest_bold.nii.gz"
    nib.save(img, nifti_path)

    # Synthetic motion params
    motion = np.random.RandomState(200).randn(15, 6).astype(np.float32) * 0.3

    # Compute metrics
    fd = compute_fd_power(motion, radius_mm=50.0)
    dvars = compute_dvars(data)

    # Write outputs
    tsv_path = tmp_path / "sub-01_task-rest_desc-confounds_timeseries.tsv"
    json_path = tmp_path / "sub-01_task-rest_desc-confounds_timeseries.json"
    png_path = tmp_path / "sub-01_task-rest_motion.png"

    write_confounds_tsv_json(
        tsv_path=tsv_path,
        json_path=json_path,
        motion_params=motion,
        fd=fd,
        dvars=dvars,
    )

    plot_motion_png(
        png_path=png_path,
        motion_params=motion,
        fd=fd,
        dvars=dvars,
    )

    # Verify all outputs exist
    assert tsv_path.exists()
    assert json_path.exists()
    assert png_path.exists()
