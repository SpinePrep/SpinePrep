"""S3_func_init_and_crop: build the functional reference, flag outlier frames, and crop the BOLD to the cord.

Input: the BOLD runs from the S1 inventory (`work/S1_input_verify/<dataset>/bids_inventory.json`),
the S2B denoised series when present (else the raw BOLD), and the S2 standardized
anatomical reference `cordref_std.nii.gz` for the anatomy-on-function overlay.

Output: per run under `runs/S3_func_init_and_crop/<run_id>/`: `func_ref.nii.gz`,
`funccrop_bold.nii.gz`, `funccrop_mask.nii.gz`, `frame_metrics.tsv` and
`outlier_mask.json`. QC record: `logs/S3_func_init_and_crop/<dataset>/qc.json`
with `runs.jsonl`; S4 runs only the runs this record passes.

QC picture: PNGs under `derivatives/spineprep/sub-<id>/[ses-<id>/]figures/`:
`desc-S3_func_localization` (cord localization), `desc-S3_frame_metrics`
(per-frame metrics with flagged outliers), `desc-S3_crop_box_sagittal`,
`desc-S3_funcref_montage`, and `desc-S3_t2_to_func_overlay`.

Usage:
    spineprep run S3_func_init_and_crop --dataset-key <key> --out <out_dir>
    spineprep run S3_func_init_and_crop --dataset-key <key> --out <out_dir> --reportlets-only
The step runs inside `spineprep <bids_dir> <out_dir> participant`.
"""

from spineprep.steps.s2.io import StepResult

from .orchestrate import (
    run_S3_func_init_and_crop,
    check_S3_func_init_and_crop,
    run_S3_func_init_and_crop_batch,
    run_S3_func_init_and_crop_reportlets_only,
    run_S3_func_init_and_crop_reportlets_only_batch,
)

__all__ = [
    "StepResult",
    "run_S3_func_init_and_crop",
    "check_S3_func_init_and_crop",
    "run_S3_func_init_and_crop_batch",
    "run_S3_func_init_and_crop_reportlets_only",
    "run_S3_func_init_and_crop_reportlets_only_batch",
]
