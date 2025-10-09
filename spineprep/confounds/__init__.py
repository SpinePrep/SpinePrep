"""Confounds module: motion metrics, aCompCor, tCompCor, and censoring."""

from spineprep.confounds.censor import make_censor_columns
from spineprep.confounds.compcor import (
    extract_timeseries,
    fit_compcor,
    select_tcompcor_voxels,
)
from spineprep.confounds.io import (
    write_confounds_extended_tsv_json,
    write_confounds_tsv_json,
)
from spineprep.confounds.motion import compute_dvars, compute_fd_power
from spineprep.confounds.plot import plot_compcor_spectra_png, plot_motion_png

__all__ = [
    "compute_fd_power",
    "compute_dvars",
    "extract_timeseries",
    "fit_compcor",
    "select_tcompcor_voxels",
    "make_censor_columns",
    "write_confounds_tsv_json",
    "write_confounds_extended_tsv_json",
    "plot_motion_png",
    "plot_compcor_spectra_png",
]
