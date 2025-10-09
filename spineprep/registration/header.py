"""NIfTI header validation and sanity checks for registration outputs."""

from __future__ import annotations

from typing import Any

import nibabel as nib
import numpy as np


def check_header(img: nib.Nifti1Image) -> dict[str, Any]:
    """
    Extract and validate basic header information from a NIfTI image.

    Args:
        img: NIfTI image object

    Returns:
        Dictionary with header information:
        - valid: bool indicating overall validity
        - shape: list of dimensions
        - zooms: list of voxel sizes
        - sform_code: int
        - qform_code: int
        - dtype: data type string
    """
    header = img.header
    shape = list(img.shape)
    zooms = list(img.header.get_zooms()[:3])  # Get first 3 dimensions (x, y, z)

    sform_code = int(header["sform_code"])
    qform_code = int(header["qform_code"])

    return {
        "valid": True,
        "shape": shape,
        "zooms": zooms,
        "sform_code": sform_code,
        "qform_code": qform_code,
        "dtype": str(img.get_data_dtype()),
    }


def check_affines_match(
    affine1: np.ndarray,
    affine2: np.ndarray,
    atol: float = 1e-6,
) -> bool:
    """
    Check if two affine matrices match within tolerance.

    Args:
        affine1: First affine matrix (4x4)
        affine2: Second affine matrix (4x4)
        atol: Absolute tolerance for comparison

    Returns:
        True if affines match within tolerance
    """
    return bool(np.allclose(affine1, affine2, atol=atol, rtol=0))


def check_form_codes(img: nib.Nifti1Image) -> dict[str, Any]:
    """
    Check NIfTI form codes (sform/qform) and their consistency.

    Args:
        img: NIfTI image object

    Returns:
        Dictionary with:
        - sform_code: int
        - qform_code: int
        - forms_match: bool (True if sform and qform are consistent)
        - has_unknown_codes: bool (True if either code is 0/unknown)
    """
    header = img.header
    sform_code = int(header["sform_code"])
    qform_code = int(header["qform_code"])

    # Get the actual affines
    sform = header.get_sform()
    qform = header.get_qform()

    # Check if forms match (both codes and affines should match)
    codes_match = sform_code == qform_code
    affines_match = check_affines_match(sform, qform, atol=1e-5)
    forms_match = codes_match and affines_match

    # Check for unknown codes
    has_unknown = sform_code == 0 or qform_code == 0

    return {
        "sform_code": sform_code,
        "qform_code": qform_code,
        "forms_match": forms_match,
        "has_unknown_codes": has_unknown,
    }


def validate_registration_output(
    img: nib.Nifti1Image,
    expected_zooms: tuple[float, float, float] | None = None,
    expected_shape: tuple[int, ...] | None = None,
) -> dict[str, Any]:
    """
    Validate a registration output image meets expected criteria.

    Args:
        img: Registered NIfTI image
        expected_zooms: Expected voxel sizes (x, y, z)
        expected_shape: Expected image dimensions

    Returns:
        Dictionary with validation results:
        - valid: bool (overall pass/fail)
        - header: dict from check_header
        - forms: dict from check_form_codes
        - zooms_match: bool (if expected_zooms provided)
        - shape_match: bool (if expected_shape provided)
    """
    header_info = check_header(img)
    form_info = check_form_codes(img)

    result: dict[str, Any] = {
        "valid": True,
        "header": header_info,
        "forms": form_info,
    }

    # Check zooms if expected
    if expected_zooms is not None:
        actual_zooms = header_info["zooms"]
        zooms_match = all(
            abs(a - e) < 1e-3 for a, e in zip(actual_zooms, expected_zooms)
        )
        result["zooms_match"] = zooms_match
        if not zooms_match:
            result["valid"] = False

    # Check shape if expected
    if expected_shape is not None:
        actual_shape = tuple(header_info["shape"])
        shape_match = actual_shape == expected_shape
        result["shape_match"] = shape_match
        if not shape_match:
            result["valid"] = False

    # Flag if forms don't match or have unknown codes
    if not form_info["forms_match"]:
        result["warning"] = "sform and qform do not match"

    if form_info["has_unknown_codes"]:
        result["warning"] = "Image has unknown form codes (0)"

    return result
