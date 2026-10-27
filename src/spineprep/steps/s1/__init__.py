"""S1_input_verify: inventory the BIDS dataset and check that it is complete and readable.

Input: the read-only BIDS dataset. Every file outside `derivatives/` is classified
by modality, and the sidecar fields of each functional and fieldmap run are read
following the BIDS inheritance principle.

Output: `work/S1_input_verify/<dataset>/bids_inventory.json` and `fix_plan.yaml`,
`logs/S1_input_verify/<dataset>/runs.jsonl`, and the step QC record
`logs/S1_input_verify/<dataset>/qc.json`. Every later step reads the inventory.

QC picture: an HTML page, not a PNG, at
`derivatives/spineprep/_S1/<dataset>/reports/<dataset>_desc-S1_dataset_summary.html`,
with three tables: a counts summary, a subject-by-modality grid of file counts,
and the check table with the status of each check.

Usage:
    spineprep run S1_input_verify --dataset-key <key> --bids-root <bids_dir> --out <out_dir>
    spineprep check S1_input_verify --dataset-key <key> --out <out_dir>
The step runs inside `spineprep <bids_dir> <out_dir> participant`.
"""

from .orchestrate import (
    StepResult,
    run_S1_input_verify,
    check_S1_input_verify,
    run_S1_input_verify_batch,
)

__all__ = [
    "StepResult",
    "run_S1_input_verify",
    "check_S1_input_verify",
    "run_S1_input_verify_batch",
]
