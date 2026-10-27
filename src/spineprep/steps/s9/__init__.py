"""S9_primary_functional_derivatives: write the preprocessed BOLD in native space and its tSNR maps.

No high-pass filtering, confound regression or (by default) smoothing is applied.

Input: the S5 series `<run>_desc-undistorted_bold.nii.gz`, the S7
`from-bold_to-PAM50_xfm` and `desc-PAM50spinallevels`, the BIDS `<run>_bold.json`
sidecar, and the runs passed by `logs/S8_confounds_and_physio_regressors/<dataset>/qc.json`
(by S7's qc.json when S8 has not run).

Output: under `derivatives/spineprep/<dataset>/sub-<id>/[ses-<id>/]func/`,
`<run>_desc-preproc_bold.nii.gz`, `<run>_desc-preproc_funcref.nii.gz`,
`<run>_desc-tsnr_native.nii.gz`, `<run>_desc-tsnr_per_level.tsv`, and the 3D
`<run>_space-PAM50_desc-tsnr.nii.gz` and `<run>_space-PAM50_desc-preproc_funcref.nii.gz`;
`<run>_desc-smoothed_bold.nii.gz` only when smoothing is enabled. QC record:
`logs/S9_primary_functional_derivatives/<dataset>/qc.json`.

QC picture: PNGs under `figures/`: `desc-S9_tsnr_map_axial` and `desc-S9_tsnr_per_level`,
plus `desc-S9_smoothness_summary` when smoothing is enabled. The step metric is the median in-cord tSNR.

Usage:
    spineprep run S9_primary_functional_derivatives --dataset-key <key> --bids-root <bids_dir> --out <out_dir>
The step runs inside `spineprep <bids_dir> <out_dir> participant`.
"""

from .orchestrate import (
    StepResult,
    run_S9,
    check_S9_primary_functional_derivatives,
    run_S9_primary_functional_derivatives_reportlets_only,
    run_S9_primary_functional_derivatives_reportlets_only_batch,
)
from .process import run_S9_primary_functional_derivatives

__all__ = [
    "StepResult",
    "run_S9",
    "run_S9_primary_functional_derivatives",
    "check_S9_primary_functional_derivatives",
    "run_S9_primary_functional_derivatives_reportlets_only",
    "run_S9_primary_functional_derivatives_reportlets_only_batch",
]
