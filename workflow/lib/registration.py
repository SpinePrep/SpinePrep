"""Registration utilities for SpinePrep."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional, Tuple


def derive_inputs(row: dict, bids_root: str) -> Tuple[str, Optional[str]]:
    """
    Derive input paths for registration from a manifest row.

    Args:
        row: Row from manifest_deriv.tsv
        bids_root: Root of BIDS directory

    Returns:
        Tuple of (epi_path, t2_path) where t2_path may be None
    """
    epi_path = row["bold_path"]

    # Try to find T2w anatomical image
    sub = row["sub"]
    ses = row.get("ses", "")

    bids_path = Path(bids_root)
    if ses:
        anat_dir = bids_path / sub / f"ses-{ses}" / "anat"
    else:
        anat_dir = bids_path / sub / "anat"

    t2_path = None
    if anat_dir.exists():
        # Look for T2w images
        t2_candidates = list(anat_dir.glob(f"{sub}*T2w.nii.gz"))
        if ses:
            t2_candidates.extend(list(anat_dir.glob(f"{sub}_ses-{ses}*T2w.nii.gz")))

        if t2_candidates:
            t2_path = str(t2_candidates[0].resolve())

    return epi_path, t2_path


def derive_outputs(row: dict, deriv_root: str) -> Dict[str, str]:
    """
    Derive output paths for registration from a manifest row.

    Args:
        row: Row from manifest_deriv.tsv
        deriv_root: Root of derivatives directory

    Returns:
        Dictionary with registration output paths
    """
    sub = row["sub"]
    ses = row.get("ses", "")
    run = row["run"]
    task = row["task"]

    # Construct base paths
    deriv_sub_dir = Path(deriv_root) / sub
    if ses:
        deriv_ses_dir = deriv_sub_dir / f"ses-{ses}" / "func"
    else:
        deriv_ses_dir = deriv_sub_dir / "func"

    xfm_dir = deriv_sub_dir / "xfm"

    # Create base filename
    base_parts = [sub]
    if ses:
        base_parts.append(f"ses-{ses}")
    base_parts.extend([f"task-{task}", f"run-{run}"])
    base_name = "_".join(base_parts)

    return {
        # EPI mean
        "epi_mean": str(deriv_ses_dir / f"{base_name}_desc-mean_bold.nii.gz"),
        # Warps
        "warp_epi2t2": str(xfm_dir / "from-epi_to-t2.h5"),
        "warp_t22pam50": str(xfm_dir / "from-t2_to-pam50.h5"),
        # Warped images
        "epi_in_t2": str(deriv_ses_dir / f"{base_name}_space-T2_desc-mean_bold.nii.gz"),
        "t2_in_pam50": str(deriv_ses_dir / f"{base_name}_space-PAM50_desc-T2w.nii.gz"),
        # Vertebral levels
        "levels_native": str(
            deriv_ses_dir / f"{base_name}_space-native_desc-levels.nii.gz"
        ),
        # Cord segmentation (intermediate)
        "cordmask_seg": str(
            deriv_ses_dir / f"{base_name}_space-native_desc-cordmask-seg.nii.gz"
        ),
        # Masks in native space
        "mask_native_cord": str(
            deriv_ses_dir / f"{base_name}_space-native_desc-cordmask.nii.gz"
        ),
        "mask_native_wm": str(
            deriv_ses_dir / f"{base_name}_space-native_desc-wmmask.nii.gz"
        ),
        "mask_native_csf": str(
            deriv_ses_dir / f"{base_name}_space-native_desc-csfmask.nii.gz"
        ),
        # Masks in PAM50 space
        "mask_pam50_cord": str(
            deriv_ses_dir / f"{base_name}_space-PAM50_desc-cordmask.nii.gz"
        ),
        "mask_pam50_wm": str(
            deriv_ses_dir / f"{base_name}_space-PAM50_desc-wmmask.nii.gz"
        ),
        "mask_pam50_csf": str(
            deriv_ses_dir / f"{base_name}_space-PAM50_desc-csfmask.nii.gz"
        ),
    }


def write_prov(path: str, meta: dict) -> None:
    """
    Write provenance metadata to a .prov.json file.

    Args:
        path: Path to the target file
        meta: Metadata dictionary
    """
    prov_path = Path(path).with_suffix(Path(path).suffix + ".prov.json")
    prov_path.parent.mkdir(parents=True, exist_ok=True)

    with open(prov_path, "w") as f:
        json.dump(meta, f, indent=2)
