"""S4_func_motion_correction: backwards-compatible re-export from steps.s4 subpackage."""
from spineprep.steps.s4 import (
    StepResult,
    run_S4,
    run_S4_func_motion_correction,
    check_S4_func_motion_correction,
    run_S4_func_motion_correction_reportlets_only,
    run_S4_func_motion_correction_reportlets_only_batch,
)

__all__ = [
    "StepResult",
    "run_S4",
    "run_S4_func_motion_correction",
    "check_S4_func_motion_correction",
    "run_S4_func_motion_correction_reportlets_only",
    "run_S4_func_motion_correction_reportlets_only_batch",
]
