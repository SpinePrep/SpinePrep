"""S2_anat_cordref: backwards-compatible re-export from steps.s2 subpackage."""
from spineprep.steps.s2 import (
    StepResult,
    run_S2_anat_cordref,
    check_S2_anat_cordref,
    run_S2_anat_cordref_batch,
    run_S2_anat_cordref_reportlets_only,
    run_S2_anat_cordref_reportlets_only_batch,
)

# Re-export private functions used by tests
from spineprep.steps.s2.validate import (
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
