"""S10_qc_aggregation_and_release: aggregate the QC of every step and write the release reports.

Input: every step `qc.json` under `<out_dir>/logs/`, and the figures and
`desc-tsnr_per_level.tsv` tables under `derivatives/spineprep/`.

Output: under `derivatives/spineprep/` (or `release/` when `derivatives` is a
symlink), `release_report.html`, `group_report_<dataset>.html`, per-subject
`sub-<id>_qc_report.html`, `group_qc_dashboard.html`, `metrics_index.jsonl` and
`.tsv`, `run_inventory.tsv`, `cohort_coverage_matrix.tsv`, `cohort_tsnr_heatmap.tsv`,
`reproducibility_receipt.json`, `CITATION.cff`, `dataset_description.json`,
`participants.tsv`, and `logs/CITATION.{bib,md,tex,html}`. QC record:
`logs/S10_qc_aggregation_and_release/qc.json` (no per-dataset level).

QC picture: the HTML reports, plus `run_inventory.png`, `cohort_coverage_matrix.png`
and `cohort_tsnr_heatmap.png`. The step metric is the fraction of subjects with a
rendered report.

Usage:
    spineprep run S10_qc_aggregation_and_release --out <out_dir>
The step runs inside `spineprep <bids_dir> <out_dir> group`.
"""

from .orchestrate import (
    StepResult,
    run_S10,
    check_S10_qc_aggregation_and_release,
)

__all__ = [
    "StepResult",
    "run_S10",
    "check_S10_qc_aggregation_and_release",
]
