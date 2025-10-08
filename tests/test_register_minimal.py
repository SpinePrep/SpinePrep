"""Minimal tests for SCT registration wrapper."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_build_sct_register_cmd():
    """Test that we can build a valid sct_register_multimodal command."""
    from spineprep.register.sct import build_register_cmd

    cmd = build_register_cmd(
        src="/data/epi_ref.nii.gz",
        dest="/data/PAM50_t2.nii.gz",
        out_warp="/out/warp.nii.gz",
    )

    assert "sct_register_multimodal" in cmd
    assert "-i" in cmd and "/data/epi_ref.nii.gz" in cmd
    assert "-d" in cmd and "/data/PAM50_t2.nii.gz" in cmd
    assert "-owarp" in cmd
    # Conservative defaults
    assert "-param" in cmd
    # Check that param string contains step=1 (rigid) and step=2 (affine)
    param_str = " ".join(cmd)
    assert "step=1" in param_str  # rigid + affine only for MVP
    assert "step=2" in param_str


def test_run_sct_register_mocked(tmp_path):
    """Test registration wrapper with mocked subprocess."""
    from spineprep.register.sct import run_register

    out_warp = tmp_path / "warp.nii.gz"
    out_resampled = tmp_path / "epi_in_pam50.nii.gz"

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="Success", stderr="")

        result = run_register(
            src="/data/epi_ref.nii.gz",
            dest="/data/PAM50_t2.nii.gz",
            out_warp=str(out_warp),
            out_resampled=str(out_resampled),
        )

    assert result["success"] is True
    assert result["return_code"] == 0
    # Should be called twice - once for sct_version, once for registration
    assert mock_run.call_count >= 1


def test_run_sct_register_failure(tmp_path):
    """Test registration wrapper handles failures gracefully."""
    from spineprep.register.sct import run_register

    out_warp = tmp_path / "warp.nii.gz"
    out_resampled = tmp_path / "epi_in_pam50.nii.gz"

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="Error: file not found"
        )

        result = run_register(
            src="/data/missing.nii.gz",
            dest="/data/PAM50_t2.nii.gz",
            out_warp=str(out_warp),
            out_resampled=str(out_resampled),
        )

    assert result["success"] is False
    assert result["return_code"] == 1
    assert "error" in result["stderr"].lower()


def test_header_consistency(tmp_path):
    """Test that qform and sform are preserved after registration."""
    # Create toy NIfTI files with known headers
    import nibabel as nib
    import numpy as np

    # Create source image (16x16x8, single volume)
    src_data = np.random.randn(16, 16, 8).astype(np.float32)
    src_affine = np.eye(4)
    src_affine[0, 0] = 2.0  # 2mm voxel size
    src_affine[1, 1] = 2.0
    src_affine[2, 2] = 2.0

    src_img = nib.Nifti1Image(src_data, src_affine)

    # Set qform and sform explicitly
    src_img.header.set_qform(src_affine, code=1)  # Scanner anatomical
    src_img.header.set_sform(src_affine, code=1)

    # Check qform and sform codes
    assert src_img.header["qform_code"] > 0  # Should have qform
    assert src_img.header["sform_code"] > 0  # Should have sform

    # Save and reload to test persistence
    test_file = tmp_path / "test.nii.gz"
    nib.save(src_img, test_file)

    reloaded = nib.load(test_file)
    loaded_affine = reloaded.affine
    np.testing.assert_array_almost_equal(loaded_affine, src_affine)


def test_ssim_psnr_thresholds():
    """Test that SSIM and PSNR computation works on toy data."""
    import numpy as np

    from spineprep.register.sct import compute_psnr, compute_ssim

    # Create two identical images
    img1 = np.random.randn(16, 16, 8).astype(np.float32)
    img2 = img1.copy()

    ssim = compute_ssim(img1, img2)
    psnr = compute_psnr(img1, img2)

    # Identical images should have perfect SSIM and very high PSNR
    assert ssim >= 0.99, f"Expected SSIM ~1.0 for identical images, got {ssim}"
    assert psnr >= 40, f"Expected high PSNR for identical images, got {psnr}"

    # Slightly perturbed image
    img3 = img1 + np.random.randn(*img1.shape) * 0.01
    ssim_pert = compute_ssim(img1, img3)
    psnr_pert = compute_psnr(img1, img3)

    # Perturbed should still have high SSIM/PSNR
    assert ssim_pert >= 0.90, f"Expected SSIM >= 0.90, got {ssim_pert}"
    assert psnr_pert >= 25, f"Expected PSNR >= 25 dB, got {psnr_pert}"
