"""S4_func_motion_correction subpackage: cord-aware motion correction."""

from .orchestrate import (
    StepResult,
    run_S4,
    check_S4_func_motion_correction,
    run_S4_func_motion_correction_reportlets_only,
    run_S4_func_motion_correction_reportlets_only_batch,
)
from .process import run_S4_func_motion_correction

__all__ = [
    "StepResult",
    "run_S4",
    "run_S4_func_motion_correction",
    "check_S4_func_motion_correction",
    "run_S4_func_motion_correction_reportlets_only",
    "run_S4_func_motion_correction_reportlets_only_batch",
]
