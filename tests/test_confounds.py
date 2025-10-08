"""Tests for confounds (aCompCor and censoring)."""

from __future__ import annotations

import csv
from pathlib import Path

import nibabel as nib
import numpy as np

from spineprep.confounds import compute_censor, extract_acompcor, process


def test_acompcor_present_and_shape():
    """Test aCompCor extraction with synthetic data."""
    # Create small 4D volume
    data = np.random.randn(16, 16, 6, 60)

    # Add sinusoidal components to specific regions
    t = np.arange(60)
    comp1 = np.sin(2 * np.pi * t / 20)
    comp2 = np.cos(2 * np.pi * t / 15)

    # Create non-overlapping masks
    wm_mask = np.zeros((16, 16, 6), dtype=bool)
    csf_mask = np.zeros((16, 16, 6), dtype=bool)
    wm_mask[4:8, 4:8, 2:4] = True
    csf_mask[10:14, 10:14, 2:4] = True

    # Inject components
    for i in range(16):
        for j in range(16):
            for k in range(6):
                if wm_mask[i, j, k]:
                    data[i, j, k, :] += 10 * comp1 + np.random.randn(60) * 0.1
                if csf_mask[i, j, k]:
                    data[i, j, k, :] += 8 * comp2 + np.random.randn(60) * 0.1

    # Extract aCompCor
    acompcor = extract_acompcor(data, wm_mask, csf_mask, n_components=6)

    # Verify shape
    assert acompcor.shape == (60, 6)

    # First PC should explain more variance than later PCs
    # (simple check: std of first PC > std of last PC)
    assert np.std(acompcor[:, 0]) > np.std(acompcor[:, 5])


def test_censor_logic():
    """Test censor computation with known FD/DVARS."""
    fd = np.array([0.0, 0.2, 0.6, 0.3, 1.2, 0.1])  # Threshold 0.5
    dvars = np.array([0.0, 1.0, 1.2, 2.0, 0.5, 0.3])  # Threshold 1.5

    censor = compute_censor(fd, dvars, fd_threshold=0.5, dvars_threshold=1.5)

    # Expected: censor where fd > 0.5 OR dvars > 1.5
    # Indices: 2 (fd=0.6), 3 (dvars=2.0), 4 (fd=1.2)
    expected = np.array([0, 0, 1, 1, 1, 0])

    np.testing.assert_array_equal(censor, expected)
    assert censor.sum() == 3


def test_end_to_end_update_tsv(tmp_path: Path):
    """Test end-to-end TSV update with aCompCor and censor."""
    # Create synthetic 4D NIfTI
    data = np.random.randn(8, 8, 4, 10).astype(np.float32)
    img = nib.Nifti1Image(data, affine=np.eye(4))
    nifti_path = tmp_path / "sub-01_task-rest_bold.nii.gz"
    nib.save(img, nifti_path)

    # Create motion-only confounds TSV (from motion step)
    motion_tsv = tmp_path / "sub-01_task-rest_bold_desc-confounds_timeseries.tsv"
    with motion_tsv.open("w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["trans_x", "trans_y", "trans_z", "rot_x", "rot_y", "rot_z", "fd", "dvars"],
            delimiter="\t",
        )
        writer.writeheader()
        for i in range(10):
            writer.writerow(
                {
                    "trans_x": 0.1 * i,
                    "trans_y": 0.0,
                    "trans_z": 0.0,
                    "rot_x": 0.0,
                    "rot_y": 0.0,
                    "rot_z": 0.0,
                    "fd": 0.3 if i < 8 else 0.8,  # Last 2 above threshold
                    "dvars": 1.0,
                }
            )

    # Create manifest
    manifest = tmp_path / "manifest.csv"
    with manifest.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "path",
                "relpath",
                "size",
                "sha256",
                "subject",
                "session",
                "modality",
                "suffix",
                "ext",
            ]
        )
        writer.writerow(
            [str(nifti_path), "sub-01/func/sub-01_task-rest_bold.nii.gz", 1000, "", "sub-01", "", "func", "bold", ".nii.gz"]
        )

    # Create minimal config
    cfg = {"pipeline": {"motion": {"fd_threshold": 0.5, "dvars_threshold": 1.5}}}

    # Process confounds
    stats = process(manifest, tmp_path, cfg)

    assert stats["runs"] == 1
    assert stats["skipped"] == 0

    # Read updated TSV
    with motion_tsv.open() as f:
        reader = csv.DictReader(f, delimiter="\t")
        rows = list(reader)
        cols = reader.fieldnames

    # Verify columns
    assert "acompcor01" in cols
    assert "acompcor06" in cols
    assert "censor" in cols

    # Verify all rows have aCompCor values
    assert len(rows) == 10
    for row in rows:
        assert "acompcor01" in row
        assert row["acompcor01"] != ""

    # Verify censor count (last 2 frames should be censored)
    censored_count = sum(int(row["censor"]) for row in rows)
    assert censored_count == 2

