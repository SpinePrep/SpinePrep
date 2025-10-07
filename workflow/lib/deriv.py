from __future__ import annotations

from pathlib import Path


def _parts_from_bold_path(bold_path: str) -> tuple[str, str | None, str, str]:
    """
    Parse BIDS pieces from a bold filename.
    Returns: (sub, ses|None, func_dir, base_bold_no_ext)
    e.g., /.../sub-01/ses-02/func/sub-01_task-motor_run-01_bold.nii.gz
          -> ("sub-01","ses-02","/.../sub-01/ses-02/func","sub-01_task-motor_run-01_bold")
    """
    p = Path(bold_path).resolve()
    func_dir = p.parent
    parts = p.parts
    sub = next((x for x in parts if x.startswith("sub-")), None)
    ses = next((x for x in parts if x.startswith("ses-")), None)
    base = p.name[:-7] if p.name.endswith(".nii.gz") else p.stem
    return sub or "", ses, str(func_dir), base


def _deriv_func_dir(deriv_root: str, sub: str, ses: str | None) -> Path:
    d = Path(deriv_root) / sub
    if ses:
        d = d / ses
    return d / "func"


def derive_paths(row: dict, deriv_root: str) -> dict[str, str]:
    """
    Given a manifest row with 'bold_path', compute absolute derivative paths
    under deriv_root following BIDS-derivatives layout.
    """
    bold = row["bold_path"]
    sub, ses, _func_dir, base = _parts_from_bold_path(bold)
    # filenames mirror current convention, just placed in derivatives
    base_no_bold = base[:-5] if base.endswith("_bold") else base
    out_dir = _deriv_func_dir(deriv_root, sub, ses)
    out_dir.mkdir(parents=True, exist_ok=True)

    mppca = out_dir / f"{base_no_bold}_desc-mppca_bold.nii.gz"
    motion = out_dir / f"{base_no_bold}_desc-motioncorr_bold.nii.gz"
    conf_tsv = out_dir / f"{base_no_bold}_desc-confounds_timeseries.tsv"
    conf_json = out_dir / f"{base_no_bold}_desc-confounds_timeseries.json"

    return {
        "deriv_mppca": str(mppca),
        "deriv_motion": str(motion),
        "deriv_confounds_tsv": str(conf_tsv),
        "deriv_confounds_json": str(conf_json),
    }
