"""S8_confounds_and_physio_regressors: build the per-run confound table in native functional space.

Columns include the slice-wise translations, framewise displacement, DVARS,
motion-outlier flags, CSF regressors, RETROICOR physiological regressors and a
cosine drift basis.

Input: the S5 series `<run>_desc-undistorted_bold.nii.gz`, the S7
`desc-PAM50csf_mask`, the S6 `from-anat_to-bold_xfm`, the S4
`moco_params_x/_y.nii.gz`, the S3 `frame_metrics.tsv`, and BIDS
`*_physio.tsv.gz` recordings when present.

Output: under `derivatives/spineprep/<dataset>/sub-<id>/[ses-<id>/]func/`,
`<run>_desc-confounds_timeseries.tsv` and its JSON sidecar. QC record:
`logs/S8_confounds_and_physio_regressors/<dataset>/qc.json`.

QC picture: PNGs under `figures/`: `desc-S8_carpet_plot`, `desc-S8_confound_columns`,
`desc-S8_correlation_heatmap`, `desc-S8_fd_dvars_outliers` and `desc-S8_pnm_peaks`.
The step metric is the worst-slice design-matrix condition number.

Usage:
    spineprep run S8_confounds_and_physio_regressors --dataset-key <key> --out <out_dir>
The step runs inside `spineprep <bids_dir> <out_dir> participant`.
"""

from .orchestrate import (
    StepResult,
    run_S8,
    check_S8_confounds_and_physio_regressors,
    run_S8_confounds_and_physio_regressors_reportlets_only,
    run_S8_confounds_and_physio_regressors_reportlets_only_batch,
)
from .process import run_S8_confounds_and_physio_regressors

__all__ = [
    "StepResult",
    "run_S8",
    "run_S8_confounds_and_physio_regressors",
    "check_S8_confounds_and_physio_regressors",
    "run_S8_confounds_and_physio_regressors_reportlets_only",
    "run_S8_confounds_and_physio_regressors_reportlets_only_batch",
]
