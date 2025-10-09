"""Confounds module: motion metrics, aCompCor, and censoring."""

from spineprep.confounds.io import write_confounds_tsv_json
from spineprep.confounds.motion import compute_dvars, compute_fd_power
from spineprep.confounds.plot import plot_motion_png

__all__ = [
    "compute_fd_power",
    "compute_dvars",
    "write_confounds_tsv_json",
    "plot_motion_png",
]
