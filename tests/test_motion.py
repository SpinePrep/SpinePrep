"""Tests for motion metrics (FD and DVARS)."""

from __future__ import annotations

import csv
from pathlib import Path

import nibabel as nib
import numpy as np

from spineprep.motion import compute_dvars, compute_fd, process_run


def test_fd_exactness():
    """Test FD computation with known synthetic motion parameters."""
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
        ]
    )

    fd = compute_fd(motion, radius_mm=50.0)

    # Expected FD values
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
        ]
    )

    # Assert exactness within tolerance 1e-6
    np.testing.assert_allclose(fd, expected, atol=1e-6)


def test_dvars_smoke():
    """Test DVARS with synthetic 4D volume."""
    # Create small synthetic 4D array
    data = np.random.randn(4, 4, 4, 10)
    # Insert a known step change at t=5
    data[:, :, :, 5:] += 10.0

    dvars = compute_dvars(data)

    # DVARS[0] should be 0
    assert dvars[0] == 0.0

    # DVARS[5] should be large (step change)
    assert dvars[5] > dvars[4]
    assert dvars[5] > 1.0  # Significant change

    # Later timepoints should have smaller DVARS (noise only)
    assert dvars[6] < dvars[5]


def test_io_outputs(tmp_path: Path):
    """Test that confounds TSV and plots are created."""
    # Create synthetic 4D NIfTI
    data = np.random.randn(4, 4, 4, 10)
    img = nib.Nifti1Image(data, affine=np.eye(4))
    nifti_path = tmp_path / "sub-01_task-rest_bold.nii.gz"
    nib.save(img, nifti_path)

    # Synthetic motion params
    motion = np.random.randn(10, 6) * 0.1

    # Process
    out_dir = tmp_path / "out"
    outputs = process_run(nifti_path, out_dir, motion_params=motion)

    # Check TSV exists and has required columns
    tsv = outputs["confounds_tsv"]
    assert tsv.exists()

    with tsv.open() as f:
        reader = csv.DictReader(f, delimiter="\t")
        rows = list(reader)
        assert len(rows) == 10
        # Verify column order and presence
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
        first_row_keys = list(reader.fieldnames)
        assert first_row_keys == expected_cols

    # Check plots exist
    assert outputs["fd_png"].exists()
    assert outputs["dvars_png"].exists()

