"""S3_func_init_and_crop subpackage: functional initialization, outlier gating, and cropping."""

from spineprep.steps.s2.io import StepResult

from .orchestrate import (
    run_S3_func_init_and_crop,
    check_S3_func_init_and_crop,
    run_S3_func_init_and_crop_batch,
    run_S3_func_init_and_crop_reportlets_only,
    run_S3_func_init_and_crop_reportlets_only_batch,
)

__all__ = [
    "StepResult",
    "run_S3_func_init_and_crop",
    "check_S3_func_init_and_crop",
    "run_S3_func_init_and_crop_batch",
    "run_S3_func_init_and_crop_reportlets_only",
    "run_S3_func_init_and_crop_reportlets_only_batch",
]
