"""S6_func_to_anat_registration: register the distortion-corrected BOLD to the anatomical cord reference.

The registration is driven by the cord segmentation (`sct_register_multimodal`),
not by image intensity.

Input: the S5 outputs `<run>_desc-undistorted_funcref.nii.gz` and
`<run>_desc-undistorted_bold.nii.gz`, the S5 EPI cord segmentation, the S2
`desc-cordref_<mod>` and `desc-cord_dseg_<mod>` (T2star preferred), and the runs
passed by `logs/S5_func_distortion_correction/<dataset>/qc.json`.

Output: under `derivatives/spineprep/sub-<id>/[ses-<id>/]func/`,
`<run>_from-bold_to-anat_xfm.nii.gz` (with a JSON sidecar),
`<run>_from-anat_to-bold_xfm.nii.gz`, `<run>_space-anat_desc-mean_bold.nii.gz` and
`<run>_desc-tsnr_funcref.nii.gz`. QC record:
`logs/S6_func_to_anat_registration/<dataset>/qc.json`.

QC picture: PNGs under `figures/`: `desc-S6_bold_on_anat` (BOLD against anatomy
with the cord contour, axial and sagittal) and `desc-S6_cord_dice_per_slice`.

Usage:
    spineprep run S6_func_to_anat_registration --dataset-key <key> --out <out_dir>
The step runs inside `spineprep <bids_dir> <out_dir> participant`.
"""

from .orchestrate import (
    StepResult,
    run_S6,
    check_S6_func_to_anat_registration,
    run_S6_func_to_anat_registration_reportlets_only,
    run_S6_func_to_anat_registration_reportlets_only_batch,
)
from .process import run_S6_func_to_anat_registration

__all__ = [
    "StepResult",
    "run_S6",
    "run_S6_func_to_anat_registration",
    "check_S6_func_to_anat_registration",
    "run_S6_func_to_anat_registration_reportlets_only",
    "run_S6_func_to_anat_registration_reportlets_only_batch",
]
