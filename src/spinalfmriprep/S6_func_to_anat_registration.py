"""S6_func_to_anat_registration: re-export from steps.s6 subpackage."""
from spinalfmriprep.steps.s6 import (
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
