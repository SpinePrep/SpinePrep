"""S2B_func_denoise: backwards-compatible re-export from steps.s2b subpackage."""
from spinalfmriprep.steps.s2b import (
    run_S2B_func_denoise,
    check_S2B_func_denoise,
)

__all__ = ["run_S2B_func_denoise", "check_S2B_func_denoise"]
