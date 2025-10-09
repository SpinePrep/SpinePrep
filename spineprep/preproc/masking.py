"""Spinal cord and CSF mask generation with QC overlays.

This module creates:
- Spinal cord mask from T2w using SCT deepseg
- Optional CSF ring mask (dilation-based)
- QC PNG overlay
- Provenance JSON with SCT version and commands
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import nibabel as nib
import numpy as np
from scipy.ndimage import binary_dilation, label

from spineprep._sct import run_sct_deepseg

logger = logging.getLogger(__name__)


def create_csf_ring_mask(
    cord_mask_img: Any,  # nibabel image
    inner_dilation: int = 1,
    outer_dilation: int = 2,
) -> Any:  # nibabel image
    """
    Create CSF ring mask by dilating cord mask.

    Args:
        cord_mask_img: Cord mask NIfTI image
        inner_dilation: Inner dilation radius (voxels)
        outer_dilation: Outer dilation radius (voxels)

    Returns:
        CSF ring mask as NIfTI image
    """
    cord_data = cord_mask_img.get_fdata().astype(bool)

    # Create outer and inner dilations
    outer = binary_dilation(cord_data, iterations=outer_dilation)
    inner = binary_dilation(cord_data, iterations=inner_dilation)

    # CSF ring = outer - inner
    csf_ring = np.logical_and(outer, np.logical_not(inner)).astype(np.uint8)

    # Clean small components (keep only largest connected component)
    labeled, num_features = label(csf_ring)
    if num_features > 1:
        # Keep largest component
        sizes = np.bincount(labeled.ravel())[1:]  # Skip background (0)
        largest_label = sizes.argmax() + 1
        csf_ring = (labeled == largest_label).astype(np.uint8)

    return nib.Nifti1Image(csf_ring, cord_mask_img.affine, cord_mask_img.header)


def create_qc_overlay(
    t2w_path: str,
    cord_mask_path: str,
    csf_mask_path: str | None,
    out_png: str,
) -> None:
    """
    Create QC overlay PNG showing T2w with cord and CSF masks.

    Args:
        t2w_path: Path to T2w image
        cord_mask_path: Path to cord mask
        csf_mask_path: Path to CSF mask (optional)
        out_png: Output PNG path
    """
    # Load images
    t2w_img = nib.load(t2w_path)
    t2w_data = t2w_img.get_fdata()

    cord_img = nib.load(cord_mask_path)
    cord_data = cord_img.get_fdata().astype(bool)

    csf_data = None
    if csf_mask_path and Path(csf_mask_path).exists():
        csf_img = nib.load(csf_mask_path)
        csf_data = csf_img.get_fdata().astype(bool)

    # Ensure output directory exists
    Path(out_png).parent.mkdir(parents=True, exist_ok=True)

    # Find middle slices in each dimension with signal
    def find_middle_slice(data, axis):
        """Find middle slice with non-zero data along axis."""
        projection = np.sum(data, axis=tuple(i for i in range(3) if i != axis))
        nonzero = np.where(projection > 0)[0]
        if len(nonzero) == 0:
            return data.shape[axis] // 2
        return nonzero[len(nonzero) // 2]

    # Get middle slices
    slice_sag = find_middle_slice(cord_data, 0)
    slice_cor = find_middle_slice(cord_data, 1)
    slice_ax = find_middle_slice(cord_data, 2)

    # Create figure with 3 subplots
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))

    # Sagittal
    ax = axes[0]
    ax.imshow(t2w_data[slice_sag, :, :].T, cmap="gray", origin="lower")
    if cord_data[slice_sag, :, :].any():
        ax.contour(
            cord_data[slice_sag, :, :].T,
            levels=[0.5],
            colors="red",
            linewidths=2,
            alpha=0.7,
        )
    if csf_data is not None and csf_data[slice_sag, :, :].any():
        ax.contour(
            csf_data[slice_sag, :, :].T,
            levels=[0.5],
            colors="blue",
            linewidths=2,
            alpha=0.7,
        )
    ax.set_title("Sagittal")
    ax.axis("off")

    # Coronal
    ax = axes[1]
    ax.imshow(t2w_data[:, slice_cor, :].T, cmap="gray", origin="lower")
    if cord_data[:, slice_cor, :].any():
        ax.contour(
            cord_data[:, slice_cor, :].T,
            levels=[0.5],
            colors="red",
            linewidths=2,
            alpha=0.7,
        )
    if csf_data is not None and csf_data[:, slice_cor, :].any():
        ax.contour(
            csf_data[:, slice_cor, :].T,
            levels=[0.5],
            colors="blue",
            linewidths=2,
            alpha=0.7,
        )
    ax.set_title("Coronal")
    ax.axis("off")

    # Axial
    ax = axes[2]
    ax.imshow(t2w_data[:, :, slice_ax].T, cmap="gray", origin="lower")
    if cord_data[:, :, slice_ax].any():
        ax.contour(
            cord_data[:, :, slice_ax].T,
            levels=[0.5],
            colors="red",
            linewidths=2,
            alpha=0.7,
        )
    if csf_data is not None and csf_data[:, :, slice_ax].any():
        ax.contour(
            csf_data[:, :, slice_ax].T,
            levels=[0.5],
            colors="blue",
            linewidths=2,
            alpha=0.7,
        )
    ax.set_title("Axial")
    ax.axis("off")

    # Add legend
    from matplotlib.patches import Patch

    legend_elements = [Patch(facecolor="red", alpha=0.7, label="Cord")]
    if csf_data is not None:
        legend_elements.append(Patch(facecolor="blue", alpha=0.7, label="CSF"))
    fig.legend(handles=legend_elements, loc="upper right")

    plt.tight_layout()
    plt.savefig(out_png, dpi=150, bbox_inches="tight")
    plt.close()


def save_provenance_json(
    out_path: str,
    cmd: str,
    sct_version: str,
    inputs: dict[str, str],
) -> None:
    """
    Save provenance JSON with SCT version and command.

    Args:
        out_path: Output JSON path
        cmd: Full command executed
        sct_version: SCT version string
        inputs: Dictionary of input file paths
    """
    provenance = {
        "cmd": cmd,
        "sct_version": sct_version,
        "time_utc": datetime.now(timezone.utc).isoformat(),
        "inputs": inputs,
    }

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)

    with open(out_path, "w") as f:
        json.dump(provenance, f, indent=2)


def run_masks(
    t2w_path: str,
    subject: str,
    out_root: str,
    session: str | None = None,
    make_csf: bool = True,
    qc: bool = True,
    logger_inst: logging.Logger | None = None,
) -> dict[str, str]:
    """
    Generate cord and optional CSF masks with QC overlay.

    Args:
        t2w_path: Path to input T2w image
        subject: Subject ID (e.g., "sub-01")
        out_root: Output root directory (e.g., derivatives/spineprep)
        session: Optional session ID (e.g., "ses-01")
        make_csf: Whether to create CSF ring mask
        qc: Whether to create QC overlay PNG
        logger_inst: Optional logger instance

    Returns:
        Dictionary with output paths:
        - cord_mask: cord mask NIfTI path
        - csf_mask: CSF mask NIfTI path (if make_csf=True)
        - cord_json: provenance JSON path
        - qc_png: QC overlay PNG path (if qc=True)

    Raises:
        RuntimeError: If SCT deepseg fails or mask is empty
    """
    log = logger_inst or logger

    # Build output paths
    base = Path(out_root) / subject
    if session:
        base = base / session

    anat_dir = base / "anat"
    qc_dir = base / "qc"

    anat_dir.mkdir(parents=True, exist_ok=True)
    qc_dir.mkdir(parents=True, exist_ok=True)

    # Build filenames
    entities = subject
    if session:
        entities += f"_{session}"

    cord_mask_path = anat_dir / f"{entities}_desc-cord_mask.nii.gz"
    csf_mask_path = anat_dir / f"{entities}_desc-csf_mask.nii.gz" if make_csf else None
    cord_json_path = anat_dir / f"{entities}_desc-cord_mask.json"
    qc_png_path = qc_dir / f"{entities}_anat_mask_overlay.png" if qc else None

    # Track outputs for cleanup on failure
    created_files = []

    try:
        # 1. Run SCT deepseg for cord mask
        log.info(f"Running SCT deepseg on {t2w_path}")
        result = run_sct_deepseg(
            t2w_path=t2w_path,
            out_mask=str(cord_mask_path),
            contrast="t2",
        )

        created_files.append(cord_mask_path)

        if not result["success"]:
            raise RuntimeError(
                f"SCT deepseg failed (exit {result['return_code']}): {result['stderr']}"
            )

        log.info(f"Cord mask created: {cord_mask_path}")

        # Check that mask is not empty
        cord_img = nib.load(cord_mask_path)
        cord_data = cord_img.get_fdata()
        if cord_data.sum() == 0:
            raise RuntimeError(
                f"SCT deepseg produced empty mask for {t2w_path}. "
                "Check input image quality and contrast."
            )

        # 2. Create CSF ring mask if requested
        if make_csf and csf_mask_path is not None:
            log.info("Creating CSF ring mask")
            csf_img = create_csf_ring_mask(cord_img, inner_dilation=1, outer_dilation=2)
            nib.save(csf_img, str(csf_mask_path))
            created_files.append(csf_mask_path)
            log.info(f"CSF mask created: {csf_mask_path}")

        # 3. Save provenance JSON
        save_provenance_json(
            out_path=str(cord_json_path),
            cmd=result["cmd"],
            sct_version=result["sct_version"],
            inputs={"t2w": t2w_path},
        )
        created_files.append(cord_json_path)
        log.info(f"Provenance saved: {cord_json_path}")

        # 4. Create QC overlay
        if qc:
            log.info("Creating QC overlay")
            create_qc_overlay(
                t2w_path=t2w_path,
                cord_mask_path=str(cord_mask_path),
                csf_mask_path=str(csf_mask_path) if make_csf else None,
                out_png=str(qc_png_path),
            )
            created_files.append(qc_png_path)
            log.info(f"QC overlay saved: {qc_png_path}")

        # Build return dictionary
        outputs = {
            "cord_mask": str(cord_mask_path),
            "cord_json": str(cord_json_path),
        }
        if make_csf:
            outputs["csf_mask"] = str(csf_mask_path)
        if qc:
            outputs["qc_png"] = str(qc_png_path)

        return outputs

    except Exception as e:
        # Clean up partial outputs on failure
        log.error(f"Masking failed: {e}")
        for filepath in created_files:
            if filepath.exists():
                log.warning(f"Removing partial output: {filepath}")
                filepath.unlink()
        raise
