"""Unit tests for NIfTI header validation."""

from __future__ import annotations

import nibabel as nib
import numpy as np
import pytest


def test_check_header_valid():
    """Test header check passes for valid image."""
    from spineprep.registration.header import check_header

    # Create a simple valid NIfTI image
    data = np.random.rand(64, 64, 16).astype(np.float32)
    affine = np.eye(4)
    affine[0, 0] = 2.0  # 2mm voxels in x
    affine[1, 1] = 2.0  # 2mm voxels in y
    affine[2, 2] = 2.0  # 2mm voxels in z
    img = nib.Nifti1Image(data, affine)

    result = check_header(img)
    assert result["valid"] is True
    assert "shape" in result
    assert "zooms" in result
    assert "sform_code" in result
    assert "qform_code" in result


def test_check_header_shape():
    """Test header check captures image shape."""
    from spineprep.registration.header import check_header

    data = np.random.rand(32, 48, 24).astype(np.float32)
    img = nib.Nifti1Image(data, np.eye(4))

    result = check_header(img)
    assert result["shape"] == [32, 48, 24]


def test_check_header_zooms():
    """Test header check captures voxel sizes."""
    from spineprep.registration.header import check_header

    data = np.random.rand(64, 64, 16).astype(np.float32)
    affine = np.eye(4)
    affine[0, 0] = 1.5
    affine[1, 1] = 1.5
    affine[2, 2] = 3.0
    img = nib.Nifti1Image(data, affine)

    result = check_header(img)
    assert result["zooms"] == pytest.approx([1.5, 1.5, 3.0])


def test_check_affines_match():
    """Test affine matching check."""
    from spineprep.registration.header import check_affines_match

    affine1 = np.eye(4)
    affine1[0, 0] = 2.0
    affine2 = affine1.copy()

    assert check_affines_match(affine1, affine2) is True


def test_check_affines_mismatch():
    """Test affine mismatch detection."""
    from spineprep.registration.header import check_affines_match

    affine1 = np.eye(4)
    affine1[0, 0] = 2.0
    affine2 = np.eye(4)
    affine2[0, 0] = 1.5

    assert check_affines_match(affine1, affine2) is False


def test_check_affines_match_tolerance():
    """Test affine matching with tolerance."""
    from spineprep.registration.header import check_affines_match

    affine1 = np.eye(4)
    affine1[0, 0] = 2.0
    affine2 = affine1.copy()
    affine2[0, 0] = 2.0 + 1e-7  # Tiny difference

    assert check_affines_match(affine1, affine2, atol=1e-6) is True
    assert check_affines_match(affine1, affine2, atol=1e-8) is False


def test_check_form_codes():
    """Test form code validation."""
    from spineprep.registration.header import check_form_codes

    data = np.random.rand(64, 64, 16).astype(np.float32)
    img = nib.Nifti1Image(data, np.eye(4))

    # Set form codes to aligned (code 2)
    img.header.set_sform(img.affine, code=2)
    img.header.set_qform(img.affine, code=2)

    result = check_form_codes(img)
    assert result["sform_code"] == 2
    assert result["qform_code"] == 2
    assert result["forms_match"] is True


def test_check_form_codes_mismatch():
    """Test form code mismatch detection."""
    from spineprep.registration.header import check_form_codes

    data = np.random.rand(64, 64, 16).astype(np.float32)
    img = nib.Nifti1Image(data, np.eye(4))

    # Set different form codes
    img.header.set_sform(img.affine, code=2)
    img.header.set_qform(img.affine, code=1)

    result = check_form_codes(img)
    assert result["sform_code"] == 2
    assert result["qform_code"] == 1
    assert result["forms_match"] is False


def test_check_form_codes_unknown():
    """Test detection of unknown form codes."""
    from spineprep.registration.header import check_form_codes

    data = np.random.rand(64, 64, 16).astype(np.float32)
    img = nib.Nifti1Image(data, np.eye(4))

    # Set to unknown (code 0)
    img.header.set_sform(img.affine, code=0)
    img.header.set_qform(img.affine, code=0)

    result = check_form_codes(img)
    assert result["sform_code"] == 0
    assert result["qform_code"] == 0
    assert result["has_unknown_codes"] is True


def test_validate_registration_output():
    """Test complete registration output validation."""
    from spineprep.registration.header import validate_registration_output

    data = np.random.rand(64, 64, 16).astype(np.float32)
    affine = np.eye(4)
    affine[0, 0] = 0.5
    affine[1, 1] = 0.5
    affine[2, 2] = 0.5
    img = nib.Nifti1Image(data, affine)
    img.header.set_sform(affine, code=2)
    img.header.set_qform(affine, code=2)

    result = validate_registration_output(img, expected_zooms=(0.5, 0.5, 0.5))
    assert result["valid"] is True
    assert result["zooms_match"] is True


def test_validate_registration_output_wrong_zooms():
    """Test validation fails for incorrect voxel sizes."""
    from spineprep.registration.header import validate_registration_output

    data = np.random.rand(64, 64, 16).astype(np.float32)
    affine = np.eye(4)
    affine[0, 0] = 1.0
    affine[1, 1] = 1.0
    affine[2, 2] = 1.0
    img = nib.Nifti1Image(data, affine)

    result = validate_registration_output(img, expected_zooms=(0.5, 0.5, 0.5))
    assert result["zooms_match"] is False
