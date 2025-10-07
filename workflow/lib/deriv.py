from __future__ import annotations

import os
import shutil
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
    motion_params_tsv = out_dir / f"{base_no_bold}_desc-motion_params.tsv"
    motion_params_json = out_dir / f"{base_no_bold}_desc-motion_params.json"
    conf_tsv = out_dir / f"{base_no_bold}_desc-confounds_timeseries.tsv"
    conf_json = out_dir / f"{base_no_bold}_desc-confounds_timeseries.json"

    # Mask paths for aCompCor
    cord_mask = out_dir / f"{base_no_bold}_space-EPI_desc-cordmask.nii.gz"
    wm_mask = out_dir / f"{base_no_bold}_space-EPI_desc-wmmask.nii.gz"
    csf_mask = out_dir / f"{base_no_bold}_space-EPI_desc-csfmask.nii.gz"

    return {
        "deriv_mppca": str(mppca),
        "deriv_motion": str(motion),
        "deriv_motion_params_tsv": str(motion_params_tsv),
        "deriv_motion_params_json": str(motion_params_json),
        "deriv_confounds_tsv": str(conf_tsv),
        "deriv_confounds_json": str(conf_json),
        "deriv_cord_mask": str(cord_mask),
        "deriv_wm_mask": str(wm_mask),
        "deriv_csf_mask": str(csf_mask),
    }


def stage_file(src: str, dst: str) -> None:
    """Stage file into derivatives: prefer hardlink, else copy. Create parent dirs."""
    s, d = Path(src), Path(dst)
    d.parent.mkdir(parents=True, exist_ok=True)
    if not s.exists():
        raise FileNotFoundError(src)
    # if exists and up-to-date, skip
    if d.exists() and d.stat().st_mtime >= s.stat().st_mtime:
        return
    try:
        if d.exists():
            d.unlink()
        os.link(s, d)  # hardlink
    except OSError:
        shutil.copy2(s, d)  # fallback copy, preserves mtime
