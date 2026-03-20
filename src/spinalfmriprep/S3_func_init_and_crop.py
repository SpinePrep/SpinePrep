"""S3_func_init_and_crop: backwards-compatible re-export from steps.s3 subpackage."""
from spinalfmriprep.steps.s3 import (
    run_S3_func_init_and_crop,
    check_S3_func_init_and_crop,
    run_S3_func_init_and_crop_batch,
    run_S3_func_init_and_crop_reportlets_only,
    run_S3_func_init_and_crop_reportlets_only_batch,
)

# Re-export private symbols used by tests
from spinalfmriprep.steps.s3.localize import _process_s3_1_dummy_drop_and_localization  # noqa: F401
from spinalfmriprep.steps.s3.outlier import _process_s3_2_outlier_gating  # noqa: F401
from spinalfmriprep.steps.s3.crop import _process_s3_3_crop_and_qc  # noqa: F401
from spinalfmriprep.steps.s3.io import _extract_subject_session_from_work_dir  # noqa: F401
from spinalfmriprep.steps.s3.localize import _render_s3_1_simple_func_with_mask  # noqa: F401
from spinalfmriprep.steps.s3.reportlets import _render_t2_to_func_overlay  # noqa: F401
from spinalfmriprep.lib.run import run_command as _run_command  # noqa: F401
from PIL import Image  # noqa: F401 — needed for test mock patching

__all__ = [
    "run_S3_func_init_and_crop",
    "check_S3_func_init_and_crop",
    "run_S3_func_init_and_crop_batch",
    "run_S3_func_init_and_crop_reportlets_only",
    "run_S3_func_init_and_crop_reportlets_only_batch",
]
