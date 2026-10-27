"""S2_anat_cordref: build the anatomical cord reference, segment it, and register it to PAM50.

Input: the subject's anatomical images listed in the S1 inventory
(`work/S1_input_verify/<dataset>/bids_inventory.json`).

Output: under `derivatives/spineprep/<dataset>/sub-<id>/[ses-<id>/]anat/`, the
cropped reference `desc-cordref_<mod>`, the cord segmentation `desc-cord_dseg_<mod>`
(`sct_deepseg spinalcord`), and the TotalSpineSeg outputs `desc-vertebral_labels`,
`desc-disc_labels`, `desc-canal_dseg` and `desc-totalspineseg_dseg`; under `xfm/`,
`from-cordref_to-PAM50_warp` and `from-PAM50_to-cordref_warp`. QC record:
`logs/S2_anat_cordref/<dataset>/qc.json` with `runs.jsonl`.

QC picture: PNGs under `figures/`: the cord-mask montage, the TotalSpineSeg
montage, the rootlets montage, the crop box on the sagittal, and the PAM50 cord
overlaid on the native anatomy. The step metric is the median per-level cord Dice
between the warped PAM50 cord and the native segmentation.

Usage:
    spineprep run S2_anat_cordref --dataset-key <key> --bids-root <bids_dir> --out <out_dir>
    spineprep run S2_anat_cordref --dataset-key <key> --out <out_dir> --reportlets-only
The step runs inside `spineprep <bids_dir> <out_dir> participant`.
"""

from .io import StepResult
from .orchestrate import (
    run_S2_anat_cordref,
    check_S2_anat_cordref,
    run_S2_anat_cordref_batch,
    run_S2_anat_cordref_reportlets_only,
    run_S2_anat_cordref_reportlets_only_batch,
)

# Also re-export private functions used by tests
from .validate import (
    _validate_vertebral_label_outputs,
    _estimate_initcenter_from_disc_labels,
    _check_labeling_consistency,
)

__all__ = [
    "StepResult",
    "run_S2_anat_cordref",
    "check_S2_anat_cordref",
    "run_S2_anat_cordref_batch",
    "run_S2_anat_cordref_reportlets_only",
    "run_S2_anat_cordref_reportlets_only_batch",
]
