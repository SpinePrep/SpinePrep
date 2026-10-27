"""S7_template_normalization: compose the BOLD-to-PAM50 transform and bring PAM50 masks into native functional space.

The 4D BOLD is not resampled into template space.

Input: the S6 warps (`from-bold_to-anat_xfm`, `from-anat_to-bold_xfm`), the S2
warps under `xfm/` and the S2 anatomy, and the runs passed by
`logs/S6_func_to_anat_registration/<dataset>/qc.json` and
`logs/S2_anat_cordref/<dataset>/qc.json`.

Output: under `derivatives/spineprep/<dataset>/sub-<id>/[ses-<id>/]func/`,
`<run>_from-bold_to-PAM50_xfm.nii.gz` (with a JSON sidecar),
`<run>_from-PAM50_to-bold_xfm.nii.gz`, `<run>_space-PAM50_desc-funcref.nii.gz`,
the native-space masks `desc-PAM50cord_mask`, `desc-PAM50csf_mask`,
`desc-PAM50wm_mask`, `desc-PAM50gm_mask`, the atlas `desc-PAM50spinallevels`, and
`desc-PAM50atlas_probseg`. QC record: `logs/S7_template_normalization/<dataset>/qc.json`.

QC picture: PNGs under `figures/`: `desc-S7_pam50_on_func` (functional reference
with the warped PAM50 cord contour) and `desc-S7_cord_dice_per_level`.

Usage:
    spineprep run S7_template_normalization --dataset-key <key> --out <out_dir>
The step runs inside `spineprep <bids_dir> <out_dir> participant`.
"""

from .orchestrate import (
    StepResult,
    run_S7,
    check_S7_template_normalization,
    run_S7_template_normalization_reportlets_only,
    run_S7_template_normalization_reportlets_only_batch,
)
from .process import run_S7_template_normalization

__all__ = [
    "StepResult",
    "run_S7",
    "run_S7_template_normalization",
    "check_S7_template_normalization",
    "run_S7_template_normalization_reportlets_only",
    "run_S7_template_normalization_reportlets_only_batch",
]
