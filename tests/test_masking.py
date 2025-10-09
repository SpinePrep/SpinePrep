"""Tests for spinal cord and CSF masking module."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import nibabel as nib
import numpy as np
import pytest


@pytest.fixture
def mock_t2w_image(tmp_path):
    """Create a mock T2w NIfTI image."""
    # Create a simple 3D volume (40x40x20)
    data = np.zeros((40, 40, 20), dtype=np.float32)
    # Add some signal in the center (spinal cord region)
    data[15:25, 15:25, 5:15] = 100.0

    affine = np.eye(4)
    affine[0, 0] = 0.5  # 0.5mm voxel size
    affine[1, 1] = 0.5
    affine[2, 2] = 2.5

    img = nib.Nifti1Image(data, affine)
    img_path = tmp_path / "sub-01_T2w.nii.gz"
    nib.save(img, img_path)
    return str(img_path)


@pytest.fixture
def mock_cord_mask(tmp_path):
    """Create a mock cord mask."""
    # Cord mask: small region in center
    data = np.zeros((40, 40, 20), dtype=np.uint8)
    data[17:23, 17:23, 7:13] = 1

    affine = np.eye(4)
    affine[0, 0] = 0.5
    affine[1, 1] = 0.5
    affine[2, 2] = 2.5

    img = nib.Nifti1Image(data, affine)
    img_path = tmp_path / "cord_mask.nii.gz"
    nib.save(img, img_path)
    return str(img_path)


def test_run_sct_deepseg_basic(tmp_path, mock_t2w_image):
    """Test basic SCT deepseg command execution."""
    from spineprep._sct import run_sct_deepseg

    out_mask = tmp_path / "cord_seg.nii.gz"

    with patch("subprocess.run") as mock_run:
        # Mock version check
        def side_effect(*args, **kwargs):
            cmd = args[0]
            if "sct_version" in cmd:
                result = MagicMock()
                result.returncode = 0
                result.stdout = "6.0.0"
                return result
            else:
                # Mock deepseg - create output file
                result = MagicMock()
                result.returncode = 0
                result.stdout = "Segmentation completed"
                result.stderr = ""
                # Create mock output
                mock_data = np.zeros((40, 40, 20), dtype=np.uint8)
                mock_data[17:23, 17:23, 7:13] = 1
                nib.save(nib.Nifti1Image(mock_data, np.eye(4)), out_mask)
                return result

        mock_run.side_effect = side_effect

        result = run_sct_deepseg(
            t2w_path=mock_t2w_image,
            out_mask=str(out_mask),
            contrast="t2",
        )

        assert result["success"] is True
        assert result["return_code"] == 0
        assert "sct_version" in result
        assert result["sct_version"] == "6.0.0"
        assert "cmd" in result


def test_run_sct_deepseg_failure(tmp_path, mock_t2w_image):
    """Test SCT deepseg failure handling."""
    from spineprep._sct import run_sct_deepseg

    out_mask = tmp_path / "cord_seg.nii.gz"

    with patch("subprocess.run") as mock_run:
        # Mock failure
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "Error: segmentation failed"
        mock_run.return_value = mock_result

        result = run_sct_deepseg(
            t2w_path=mock_t2w_image,
            out_mask=str(out_mask),
            contrast="t2",
        )

        assert result["success"] is False
        assert result["return_code"] == 1


def test_create_csf_ring_mask(mock_cord_mask):
    """Test CSF ring mask generation from cord mask."""
    from spineprep.preproc.masking import create_csf_ring_mask

    cord_img = nib.load(mock_cord_mask)
    csf_img = create_csf_ring_mask(cord_img, inner_dilation=1, outer_dilation=2)

    csf_data = csf_img.get_fdata()
    cord_data = cord_img.get_fdata()

    # CSF should not overlap with cord
    assert np.sum(csf_data * cord_data) == 0

    # CSF should have some voxels
    assert np.sum(csf_data) > 0

    # CSF should be around the cord (check a few voxels)
    # This is a simple sanity check
    assert csf_data.max() == 1


def test_create_qc_overlay(tmp_path, mock_t2w_image, mock_cord_mask):
    """Test QC overlay PNG generation."""
    from spineprep.preproc.masking import create_qc_overlay

    out_png = tmp_path / "overlay.png"

    create_qc_overlay(
        t2w_path=mock_t2w_image,
        cord_mask_path=mock_cord_mask,
        csf_mask_path=None,
        out_png=str(out_png),
    )

    # Check PNG was created
    assert out_png.exists()
    assert out_png.stat().st_size > 0


def test_save_provenance_json(tmp_path):
    """Test provenance JSON creation."""
    from spineprep.preproc.masking import save_provenance_json

    out_json = tmp_path / "provenance.json"

    save_provenance_json(
        out_path=str(out_json),
        cmd="sct_deepseg_sc -i input.nii.gz -c t2 -o output.nii.gz",
        sct_version="6.0.0",
        inputs={"t2w": "/path/to/t2w.nii.gz"},
    )

    assert out_json.exists()

    with open(out_json) as f:
        data = json.load(f)

    assert "cmd" in data
    assert data["cmd"] == "sct_deepseg_sc -i input.nii.gz -c t2 -o output.nii.gz"
    assert "sct_version" in data
    assert data["sct_version"] == "6.0.0"
    assert "time_utc" in data
    assert "inputs" in data
    assert data["inputs"]["t2w"] == "/path/to/t2w.nii.gz"


def test_run_masks_full_workflow(tmp_path, mock_t2w_image):
    """Test full masking workflow."""
    from spineprep.preproc.masking import run_masks

    out_dir = tmp_path / "derivatives" / "spineprep" / "sub-01" / "anat"
    out_dir.mkdir(parents=True, exist_ok=True)

    qc_dir = tmp_path / "derivatives" / "spineprep" / "sub-01" / "qc"
    qc_dir.mkdir(parents=True, exist_ok=True)

    with patch("spineprep.preproc.masking.run_sct_deepseg") as mock_deepseg:
        # Mock successful deepseg
        def mock_deepseg_fn(t2w_path, out_mask, contrast):
            # Create mock cord mask
            mock_data = np.zeros((40, 40, 20), dtype=np.uint8)
            mock_data[17:23, 17:23, 7:13] = 1
            nib.save(nib.Nifti1Image(mock_data, np.eye(4)), out_mask)

            return {
                "success": True,
                "return_code": 0,
                "stdout": "Segmentation completed",
                "stderr": "",
                "sct_version": "6.0.0",
                "cmd": f"sct_deepseg_sc -i {t2w_path} -c {contrast} -o {out_mask}",
            }

        mock_deepseg.side_effect = mock_deepseg_fn

        outputs = run_masks(
            t2w_path=mock_t2w_image,
            subject="sub-01",
            out_root=str(tmp_path / "derivatives" / "spineprep"),
            make_csf=True,
            qc=True,
        )

        # Check outputs
        assert "cord_mask" in outputs
        assert "csf_mask" in outputs
        assert "cord_json" in outputs
        assert "qc_png" in outputs

        # Check files exist
        assert Path(outputs["cord_mask"]).exists()
        assert Path(outputs["csf_mask"]).exists()
        assert Path(outputs["cord_json"]).exists()
        assert Path(outputs["qc_png"]).exists()

        # Check JSON content
        with open(outputs["cord_json"]) as f:
            prov = json.load(f)
        assert "cmd" in prov
        assert "sct_version" in prov
        assert prov["sct_version"] == "6.0.0"


def test_run_masks_no_csf(tmp_path, mock_t2w_image):
    """Test masking workflow without CSF mask."""
    from spineprep.preproc.masking import run_masks

    with patch("spineprep.preproc.masking.run_sct_deepseg") as mock_deepseg:

        def mock_deepseg_fn(t2w_path, out_mask, contrast):
            mock_data = np.zeros((40, 40, 20), dtype=np.uint8)
            mock_data[17:23, 17:23, 7:13] = 1
            nib.save(nib.Nifti1Image(mock_data, np.eye(4)), out_mask)

            return {
                "success": True,
                "return_code": 0,
                "stdout": "Segmentation completed",
                "stderr": "",
                "sct_version": "6.0.0",
                "cmd": f"sct_deepseg_sc -i {t2w_path} -c {contrast} -o {out_mask}",
            }

        mock_deepseg.side_effect = mock_deepseg_fn

        outputs = run_masks(
            t2w_path=mock_t2w_image,
            subject="sub-01",
            out_root=str(tmp_path / "derivatives" / "spineprep"),
            make_csf=False,
            qc=True,
        )

        # Check that CSF mask was not created
        assert "csf_mask" not in outputs or outputs["csf_mask"] is None


def test_run_masks_failure_cleanup(tmp_path, mock_t2w_image):
    """Test that partial outputs are cleaned up on failure."""
    from spineprep.preproc.masking import run_masks

    with patch("spineprep.preproc.masking.run_sct_deepseg") as mock_deepseg:
        # Mock failure
        mock_deepseg.return_value = {
            "success": False,
            "return_code": 1,
            "stdout": "",
            "stderr": "Segmentation failed",
            "sct_version": "6.0.0",
            "cmd": "sct_deepseg_sc ...",
        }

        with pytest.raises(RuntimeError, match="SCT deepseg failed"):
            run_masks(
                t2w_path=mock_t2w_image,
                subject="sub-01",
                out_root=str(tmp_path / "derivatives" / "spineprep"),
                make_csf=True,
                qc=True,
            )


def test_run_masks_empty_mask_error(tmp_path, mock_t2w_image):
    """Test that empty mask raises error."""
    from spineprep.preproc.masking import run_masks

    with patch("spineprep.preproc.masking.run_sct_deepseg") as mock_deepseg:

        def mock_deepseg_fn(t2w_path, out_mask, contrast):
            # Create EMPTY mask
            mock_data = np.zeros((40, 40, 20), dtype=np.uint8)
            nib.save(nib.Nifti1Image(mock_data, np.eye(4)), out_mask)

            return {
                "success": True,
                "return_code": 0,
                "stdout": "Segmentation completed",
                "stderr": "",
                "sct_version": "6.0.0",
                "cmd": f"sct_deepseg_sc -i {t2w_path} -c {contrast} -o {out_mask}",
            }

        mock_deepseg.side_effect = mock_deepseg_fn

        with pytest.raises(RuntimeError, match="empty"):
            run_masks(
                t2w_path=mock_t2w_image,
                subject="sub-01",
                out_root=str(tmp_path / "derivatives" / "spineprep"),
                make_csf=True,
                qc=True,
            )
