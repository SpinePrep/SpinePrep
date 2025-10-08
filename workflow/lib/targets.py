"""
Path utilities for SpinePrep targets.

Pure string-only functions for composing derivative paths from BIDS entities.
No global imports, no IO operations - unit testable.
"""


def bold_fname(sub: str, ses: str = None, task: str = None, run: str = None) -> str:
    """
    Generate BOLD filename from BIDS entities.

    Args:
        sub: Subject ID (e.g., "sub-01")
        ses: Session ID (optional, e.g., "ses-01")
        task: Task name (optional, e.g., "rest")
        run: Run number (optional, e.g., "01")

    Returns:
        BOLD filename (e.g., "sub-01_task-rest_run-01_bold.nii.gz")
    """
    parts = [sub]
    if ses:
        parts.append(ses)
    if task:
        parts.append(f"task-{task}")
    if run:
        parts.append(f"run-{run}")
    parts.append("bold.nii.gz")
    return "_".join(parts)


def deriv_path(
    deriv_root: str,
    sub: str,
    ses: str = None,
    modality: str = "func",
    fname: str = None,
) -> str:
    """
    Generate derivative path from BIDS entities.

    Args:
        deriv_root: Root derivatives directory
        sub: Subject ID (e.g., "sub-01")
        ses: Session ID (optional, e.g., "ses-01")
        modality: Modality (default: "func")
        fname: Filename (optional)

    Returns:
        Derivative path (e.g., "/path/derivatives/spineprep/sub-01/func/sub-01_task-rest_run-01_bold.nii.gz")
    """
    path_parts = [deriv_root, sub]
    if ses:
        path_parts.append(ses)
    path_parts.append(modality)

    base_path = "/".join(path_parts)
    if fname:
        return f"{base_path}/{fname}"
    return base_path


def motion_bold_path(
    deriv_root: str, sub: str, ses: str = None, task: str = None, run: str = None
) -> str:
    """
    Generate motion-corrected BOLD path.

    Args:
        deriv_root: Root derivatives directory
        sub: Subject ID (e.g., "sub-01")
        ses: Session ID (optional, e.g., "ses-01")
        task: Task name (optional, e.g., "rest")
        run: Run number (optional, e.g., "01")

    Returns:
        Motion-corrected BOLD path (e.g., "/path/derivatives/spineprep/sub-01/func/sub-01_task-rest_run-01_desc-motioncorr_bold.nii.gz")
    """
    # Generate base BOLD filename
    base_fname = bold_fname(sub, ses, task, run)

    # Replace "_bold.nii.gz" with "_desc-motioncorr_bold.nii.gz"
    motion_fname = base_fname.replace("_bold.nii.gz", "_desc-motioncorr_bold.nii.gz")

    return deriv_path(deriv_root, sub, ses, "func", motion_fname)


def confounds_tsv_path(
    deriv_root: str, sub: str, ses: str = None, task: str = None, run: str = None
) -> str:
    """
    Generate confounds TSV path.

    Args:
        deriv_root: Root derivatives directory
        sub: Subject ID (e.g., "sub-01")
        ses: Session ID (optional, e.g., "ses-01")
        task: Task name (optional, e.g., "rest")
        run: Run number (optional, e.g., "01")

    Returns:
        Confounds TSV path (e.g., "/path/derivatives/spineprep/sub-01/func/sub-01_task-rest_run-01_desc-confounds_timeseries.tsv")
    """
    base_fname = bold_fname(sub, ses, task, run)
    confounds_fname = base_fname.replace(
        "_bold.nii.gz", "_desc-confounds_timeseries.tsv"
    )
    return deriv_path(deriv_root, sub, ses, "func", confounds_fname)


def confounds_json_path(
    deriv_root: str, sub: str, ses: str = None, task: str = None, run: str = None
) -> str:
    """
    Generate confounds JSON path.

    Args:
        deriv_root: Root derivatives directory
        sub: Subject ID (e.g., "sub-01")
        ses: Session ID (optional, e.g., "ses-01")
        task: Task name (optional, e.g., "rest")
        run: Run number (optional, e.g., "01")

    Returns:
        Confounds JSON path (e.g., "/path/derivatives/spineprep/sub-01/func/sub-01_task-rest_run-01_desc-confounds_timeseries.json")
    """
    base_fname = bold_fname(sub, ses, task, run)
    confounds_fname = base_fname.replace(
        "_bold.nii.gz", "_desc-confounds_timeseries.json"
    )
    return deriv_path(deriv_root, sub, ses, "func", confounds_fname)


def mppca_bold_path(
    deriv_root: str, sub: str, ses: str = None, task: str = None, run: str = None
) -> str:
    """
    Generate MP-PCA denoised BOLD path.

    Args:
        deriv_root: Root derivatives directory
        sub: Subject ID (e.g., "sub-01")
        ses: Session ID (optional, e.g., "ses-01")
        task: Task name (optional, e.g., "rest")
        run: Run number (optional, e.g., "01")

    Returns:
        MP-PCA BOLD path (e.g., "/path/derivatives/spineprep/sub-01/func/sub-01_task-rest_run-01_desc-mppca_bold.nii.gz")
    """
    base_fname = bold_fname(sub, ses, task, run)
    mppca_fname = base_fname.replace("_bold.nii.gz", "_desc-mppca_bold.nii.gz")
    return deriv_path(deriv_root, sub, ses, "func", mppca_fname)


def crop_json_path(
    deriv_root: str, sub: str, ses: str = None, task: str = None, run: str = None
) -> str:
    """
    Generate crop JSON path.

    Args:
        deriv_root: Root derivatives directory
        sub: Subject ID (e.g., "sub-01")
        ses: Session ID (optional, e.g., "ses-01")
        task: Task name (optional, e.g., "rest")
        run: Run number (optional, e.g., "01")

    Returns:
        Crop JSON path (e.g., "/path/derivatives/spineprep/sub-01/func/sub-01_task-rest_run-01_desc-crop.json")
    """
    base_fname = bold_fname(sub, ses, task, run)
    crop_fname = base_fname.replace("_bold.nii.gz", "_desc-crop.json")
    return deriv_path(deriv_root, sub, ses, "func", crop_fname)
