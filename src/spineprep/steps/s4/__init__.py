"""S4_func_motion_correction: two-stage cord motion correction, in-plane bulk alignment then slice-wise realignment.

Input: from `runs/S3_func_init_and_crop/<run_id>/`, the cropped BOLD, the
functional reference and the cord segmentation, for the runs passed by
`logs/S3_func_init_and_crop/<dataset>/qc.json`.

Output: `derivatives/spineprep/sub-<id>/[ses-<id>/]func/<run>_desc-mocoref_bold.nii.gz`
and `<run>_moco_params.tsv`; the signed slice-wise translations
`moco_params_x.nii.gz` and `moco_params_y.nii.gz` stay in
`work/S4_func_motion_correction/<run_id>/` for S8. QC record:
`logs/S4_func_motion_correction/<dataset>/qc.json`.

QC picture: PNGs under `figures/`: `desc-S4_motion_traces` (in-plane translation,
FD and DVARS on one time axis), `desc-S4_slicewise_heatmap` (signed slice-wise
shift, slice by time), and `desc-S4_tsnr_comparison` (cord tSNR before and after,
with a per-slice profile). The step metric is cord tSNR before and after correction.

Usage:
    spineprep run S4_func_motion_correction --dataset-key <key> --out <out_dir>
    spineprep run S4_func_motion_correction --dataset-key <key> --out <out_dir> --reportlets-only
The step runs inside `spineprep <bids_dir> <out_dir> participant`.
"""

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
