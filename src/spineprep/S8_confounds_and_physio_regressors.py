"""S8_confounds_and_physio_regressors: short import path for the step; what it does, its input, output and usage are in steps/s8/__init__.py."""
from spineprep.steps.s8 import (
    StepResult,
    run_S8,
    run_S8_confounds_and_physio_regressors,
    check_S8_confounds_and_physio_regressors,
    run_S8_confounds_and_physio_regressors_reportlets_only,
    run_S8_confounds_and_physio_regressors_reportlets_only_batch,
)

__all__ = [
    "StepResult",
    "run_S8",
    "run_S8_confounds_and_physio_regressors",
    "check_S8_confounds_and_physio_regressors",
    "run_S8_confounds_and_physio_regressors_reportlets_only",
    "run_S8_confounds_and_physio_regressors_reportlets_only_batch",
]
