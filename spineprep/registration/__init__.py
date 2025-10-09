"""Registration utilities for SpinePrep (EPI→PAM50)."""

from .header import (
    check_affines_match,
    check_form_codes,
    check_header,
    validate_registration_output,
)
from .metrics import compute_psnr, compute_ssim, normalize_intensity
from .sct import (
    build_sct_register_cmd,
    check_doctor_status,
    create_output_paths,
    map_sct_error,
    run_sct_register,
)

__all__ = [
    "check_affines_match",
    "check_form_codes",
    "check_header",
    "validate_registration_output",
    "compute_psnr",
    "compute_ssim",
    "normalize_intensity",
    "build_sct_register_cmd",
    "check_doctor_status",
    "create_output_paths",
    "map_sct_error",
    "run_sct_register",
]
