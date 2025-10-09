"""Tests for MP-PCA denoising wrapper."""

from __future__ import annotations

import nibabel as nib
import numpy as np

from spineprep.preproc.denoise import mppca_denoise


def test_mppca_preserves_shape_and_affine(tmp_path):
    """Test that denoising preserves image shape and affine."""
    # Create synthetic 4D data
    data = np.random.randn(8, 8, 4, 10).astype(np.float32)
    affine = np.diag([2.0, 2.0, 3.0, 1.0])
    img = nib.Nifti1Image(data, affine)

    in_path = tmp_path / "input_bold.nii.gz"
    out_path = tmp_path / "output_desc-mppca_bold.nii.gz"

    nib.save(img, str(in_path))

    # Denoise
    mppca_denoise(in_path, out_path, patch=3, stride=2)

    # Verify output exists
    assert out_path.exists(), "Output file not created"

    # Load and check
    result_img = nib.load(str(out_path))
    result_data = result_img.get_fdata()

    # Shape should be preserved
    assert (
        result_data.shape == data.shape
    ), f"Shape mismatch: {result_data.shape} vs {data.shape}"

    # Affine should be preserved
    np.testing.assert_array_almost_equal(
        result_img.affine, affine, decimal=5, err_msg="Affine not preserved"
    )


def test_mppca_creates_output_directory(tmp_path):
    """Test that denoising creates output directory if needed."""
    data = np.random.randn(6, 6, 3, 5).astype(np.float32)
    img = nib.Nifti1Image(data, np.eye(4))

    in_path = tmp_path / "input.nii.gz"
    out_path = tmp_path / "nested" / "dir" / "output.nii.gz"

    nib.save(img, str(in_path))

    # Output directory doesn't exist yet
    assert not out_path.parent.exists()

    # Denoise
    mppca_denoise(in_path, out_path, patch=2, stride=1)

    # Directory should be created
    assert out_path.parent.exists(), "Output directory not created"
    assert out_path.exists(), "Output file not created"


def test_mppca_small_volume(tmp_path):
    """Test denoising with small volume (edge case)."""
    # Very small volume
    data = np.random.randn(4, 4, 2, 3).astype(np.float32)
    img = nib.Nifti1Image(data, np.eye(4))

    in_path = tmp_path / "small.nii.gz"
    out_path = tmp_path / "small_denoised.nii.gz"

    nib.save(img, str(in_path))

    # Should handle gracefully (may copy-through if patch too large)
    mppca_denoise(in_path, out_path, patch=2, stride=1)

    assert out_path.exists(), "Output should exist even for small volumes"

    result_img = nib.load(str(out_path))
    assert result_img.shape == data.shape


def test_mppca_copy_through_no_dipy(tmp_path):
    """Test copy-through path when DIPY is not available.

    Note: This test assumes DIPY is not installed. If DIPY is present,
    the test still passes because the output will be created with either
    denoising or copy-through.
    """
    # Create test data
    data = np.random.randn(6, 6, 3, 4).astype(np.float32)
    affine = np.diag([2.0, 2.0, 2.0, 1.0])
    img = nib.Nifti1Image(data, affine)

    in_path = tmp_path / "input.nii.gz"
    out_path = tmp_path / "output.nii.gz"

    nib.save(img, str(in_path))

    # Run denoising (will use DIPY if available, otherwise copy-through)
    mppca_denoise(in_path, out_path)

    # Output should exist regardless of DIPY availability
    assert out_path.exists()
    result_img = nib.load(str(out_path))
    result_data = result_img.get_fdata()

    # Shape and affine should be preserved
    assert result_data.shape == data.shape
    np.testing.assert_array_almost_equal(result_img.affine, affine)
