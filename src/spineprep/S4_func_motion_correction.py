"""S4_func_motion_correction: short import path for the step; what it does, its input, output and usage are in steps/s4/__init__.py."""
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
