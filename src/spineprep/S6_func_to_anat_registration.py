"""S6_func_to_anat_registration: short import path for the step; what it does, its input, output and usage are in steps/s6/__init__.py."""
from spineprep.steps.s6 import (
    StepResult,
    run_S6,
    run_S6_func_to_anat_registration,
    check_S6_func_to_anat_registration,
    run_S6_func_to_anat_registration_reportlets_only,
    run_S6_func_to_anat_registration_reportlets_only_batch,
)

__all__ = [
    "StepResult",
    "run_S6",
    "run_S6_func_to_anat_registration",
    "check_S6_func_to_anat_registration",
    "run_S6_func_to_anat_registration_reportlets_only",
    "run_S6_func_to_anat_registration_reportlets_only_batch",
]
