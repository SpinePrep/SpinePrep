"""S2_anat_cordref subpackage: cord reference selection, standardization, cropping, and segmentation."""

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
