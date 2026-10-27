"""S5_func_distortion_correction: correct susceptibility distortion of the motion-corrected BOLD.

The correction mode is set by `prefer_mode` in `policy/S5_func_distortion_correction.yaml`
(auto, topup, syn or none).

Input: the S4 series `<run>_desc-mocoref_bold.nii.gz`, the S2 anatomical reference
and cord segmentation (`desc-cordref_<mod>`, `desc-cord_dseg_<mod>`), the fieldmap
runs listed in the S1 inventory, and the runs passed by
`logs/S4_func_motion_correction/<dataset>/qc.json`.

Output: `derivatives/spineprep/sub-<id>/[ses-<id>/]func/<run>_desc-undistorted_bold.nii.gz`
and `<run>_desc-undistorted_funcref.nii.gz`. QC record:
`logs/S5_func_distortion_correction/<dataset>/qc.json`.

QC picture: PNGs under `figures/`: `desc-S5_slice_displacement` (per-slice A-P
cord-centerline displacement before and after), `desc-S5_cord_dice_per_slice`,
and `desc-S5_distortion_effectiveness` (mean BOLD before and after with the
anatomy cord contour).

Usage:
    spineprep run S5_func_distortion_correction --dataset-key <key> --out <out_dir>
The step runs inside `spineprep <bids_dir> <out_dir> participant`.
"""

from .orchestrate import (
    StepResult,
    run_S5,
    check_S5_func_distortion_correction,
    run_S5_func_distortion_correction_reportlets_only,
    run_S5_func_distortion_correction_reportlets_only_batch,
)
from .process import run_S5_func_distortion_correction

__all__ = [
    "StepResult",
    "run_S5",
    "run_S5_func_distortion_correction",
    "check_S5_func_distortion_correction",
    "run_S5_func_distortion_correction_reportlets_only",
    "run_S5_func_distortion_correction_reportlets_only_batch",
]
