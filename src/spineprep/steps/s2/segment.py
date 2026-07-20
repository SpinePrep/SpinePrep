"""S2.2: cord segmentation, TotalSpineSeg, CSA metrics, TSS label constants."""
from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import nibabel as nib
import numpy as np

from .io import _run_command


# TotalSpineSeg label mapping (from https://github.com/neuropoly/totalspineseg)
TSS_LABELS = {
    "spinal_cord": 1,
    "spinal_canal": 2,
    # Vertebrae: C1-C7 (11-17), T1-T12 (21-32), L1-L5 (41-45), Sacrum (50)
    "vertebrae": {
        "C1": 11, "C2": 12, "C3": 13, "C4": 14, "C5": 15, "C6": 16, "C7": 17,
        "T1": 21, "T2": 22, "T3": 23, "T4": 24, "T5": 25, "T6": 26,
        "T7": 27, "T8": 28, "T9": 29, "T10": 30, "T11": 31, "T12": 32,
        "L1": 41, "L2": 42, "L3": 43, "L4": 44, "L5": 45,
        "S": 50,
    },
    # Discs: C2-C3 to C6-C7 (63-67), C7-T1 to T11-T12 (71-82), T12-L1 to L4-L5 (91-95), L5-S (100)
    "discs": {
        "C2/C3": 63, "C3/C4": 64, "C4/C5": 65, "C5/C6": 66, "C6/C7": 67,
        "C7/T1": 71, "T1/T2": 72, "T2/T3": 73, "T3/T4": 74, "T4/T5": 75,
        "T5/T6": 76, "T6/T7": 77, "T7/T8": 78, "T8/T9": 79, "T9/T10": 80,
        "T10/T11": 81, "T11/T12": 82,
        "T12/L1": 91, "L1/L2": 92, "L2/L3": 93, "L3/L4": 94, "L4/L5": 95,
        "L5/S": 100,
    },
}

# Reverse mappings for label -> name
TSS_VERTEBRA_NAMES = {v: k for k, v in TSS_LABELS["vertebrae"].items()}
TSS_DISC_NAMES = {v: k for k, v in TSS_LABELS["discs"].items()}


def _compute_segmentation_metrics(seg_path: Path) -> dict:
    img = cast(Any, nib.load(seg_path))
    data = img.get_fdata()
    if data.ndim > 3:
        data = data[..., 0]
    mask = data > 0
    voxels = int(mask.sum())
    zooms = img.header.get_zooms()[:3]
    voxel_volume = float(zooms[0] * zooms[1] * zooms[2])
    volume = float(voxels * voxel_volume)
    slice_counts = mask.sum(axis=(0, 1))
    slice_present = slice_counts > 0
    slice_area = slice_counts * (zooms[0] * zooms[1])
    length_mm = float(slice_present.sum() * zooms[2])
    if slice_present.any():
        stats = {
            "csa_mean_mm2": float(slice_area[slice_present].mean()),
            "csa_min_mm2": float(slice_area[slice_present].min()),
            "csa_max_mm2": float(slice_area[slice_present].max()),
        }
    else:
        stats = {"csa_mean_mm2": 0.0, "csa_min_mm2": 0.0, "csa_max_mm2": 0.0}
    return {
        "voxels": voxels,
        "voxel_volume_mm3": voxel_volume,
        "cord_volume_mm3": volume,
        "cord_length_mm": length_mm,
        **stats,
    }


def _run_totalspineseg(
    cordref_path: Path,
    work_dir: Path,
) -> dict:
    """
    Run TotalSpineSeg segmentation on the cordref image.

    TotalSpineSeg outputs a single NIfTI with multiple label values:
    - 1: spinal cord
    - 2: spinal canal
    - 11-50: vertebrae (C1-S)
    - 63-100: intervertebral discs

    Args:
        cordref_path: Path to cropped anatomical reference
        work_dir: Working directory for outputs

    Returns:
        Dict with status, paths to extracted components, and metrics
    """
    tss_dir = work_dir / "totalspineseg"
    tss_dir.mkdir(parents=True, exist_ok=True)

    # Run TotalSpineSeg
    # Syntax: sct_deepseg totalspineseg -i input.nii.gz -o output.nii.gz
    # SCT adds suffixes: _step2_output, _step1_cord, _step1_canal, etc.
    output_path = tss_dir / "tss.nii.gz"
    ok, message = _run_command(
        [
            "sct_deepseg",
            "totalspineseg",
            "-i",
            str(cordref_path),
            "-o",
            str(output_path),
        ]
    )
    # TotalSpineSeg outputs: tss_step2_output.nii.gz, tss_step1_cord.nii.gz, etc.
    tss_output = tss_dir / "tss_step2_output.nii.gz"
    tss_cord = tss_dir / "tss_step1_cord.nii.gz"
    tss_canal = tss_dir / "tss_step1_canal.nii.gz"

    # A failed segmentation must FAIL even when an output file is already on
    # disk. Previously `ok` was only consulted inside the `not exists()` branch,
    # so a crashed run (OOM, no GPU, killed) silently adopted the PREVIOUS
    # invocation's segmentation and reported PASS -- with nothing in qc.json
    # recording that the tool had failed. Vertebral and disc labels were then
    # regenerated from stale anatomy. Found in the 2026-07-19 audit.
    if not ok:
        return {
            "status": "FAIL",
            "failure_message": (
                f"TotalSpineSeg failed: {message}"
                + (" (a previous output exists on disk and was NOT reused)"
                   if tss_output.exists() else "")
            ),
        }

    if not tss_output.exists():
        # List what files were actually created for debugging
        created_files = list(tss_dir.rglob("*.nii.gz"))
        if not ok:
            return {
                "status": "FAIL",
                "failure_message": f"TotalSpineSeg failed: {message}",
            }
        return {
            "status": "FAIL",
            "failure_message": f"TotalSpineSeg output not found. Created files: {[str(f.relative_to(tss_dir)) for f in created_files[:10]]}",
        }

    # Load TSS output and extract components
    try:
        tss_img = cast(Any, nib.load(tss_output))
        tss_data = tss_img.get_fdata()
        if tss_data.ndim > 3:
            tss_data = tss_data[..., 0]
        affine = tss_img.affine
        header = tss_img.header
    except Exception as e:
        return {
            "status": "FAIL",
            "failure_message": f"Failed to load TotalSpineSeg output: {e}",
        }

    # Use TSS's own cord and canal outputs if available (more accurate)
    cord_path = tss_cord if tss_cord.exists() else tss_dir / "cord.nii.gz"
    canal_path = tss_canal if tss_canal.exists() else tss_dir / "canal.nii.gz"

    # If TSS didn't provide separate cord/canal files, extract from main output
    if not tss_cord.exists():
        cord_mask = (tss_data == TSS_LABELS["spinal_cord"]).astype(np.uint8)
        nib.save(nib.Nifti1Image(cord_mask, affine, header), cord_path)

    if not tss_canal.exists():
        canal_mask = (tss_data == TSS_LABELS["spinal_canal"]).astype(np.uint8)
        nib.save(nib.Nifti1Image(canal_mask, affine, header), canal_path)

    # Extract vertebrae (labels 11-50) - keep original labels for visualization
    vertebrae_labels = list(TSS_LABELS["vertebrae"].values())
    vertebrae_mask = np.isin(tss_data, vertebrae_labels).astype(np.uint8)
    vertebrae_data = np.where(vertebrae_mask, tss_data, 0).astype(np.uint8)
    vertebrae_path = tss_dir / "vertebrae.nii.gz"
    nib.save(nib.Nifti1Image(vertebrae_data, affine, header), vertebrae_path)

    # Extract discs (labels 63-100) - keep original labels
    disc_labels = list(TSS_LABELS["discs"].values())
    discs_mask = np.isin(tss_data, disc_labels).astype(np.uint8)
    discs_data = np.where(discs_mask, tss_data, 0).astype(np.uint8)
    discs_path = tss_dir / "discs.nii.gz"
    nib.save(nib.Nifti1Image(discs_data, affine, header), discs_path)

    # Create SCT-compatible vertebral labels (convert TSS labels to SCT convention)
    # SCT uses: C1=1, C2=2, ..., C7=7, T1=8, ..., T12=19, L1=20, ..., L5=24
    sct_vertebral_data = np.zeros_like(tss_data, dtype=np.uint8)
    for name, tss_label in TSS_LABELS["vertebrae"].items():
        if name == "S":
            continue  # Skip sacrum for SCT compat
        mask = tss_data == tss_label
        if name.startswith("C"):
            sct_label = int(name[1:])  # C1=1, C7=7
        elif name.startswith("T"):
            sct_label = int(name[1:]) + 7  # T1=8, T12=19
        elif name.startswith("L"):
            sct_label = int(name[1:]) + 19  # L1=20, L5=24
        else:
            continue
        sct_vertebral_data[mask] = sct_label
    sct_vertebral_path = tss_dir / "vertebral_labels_sct.nii.gz"
    nib.save(nib.Nifti1Image(sct_vertebral_data, affine, header), sct_vertebral_path)

    # Create SCT-compatible disc labels (point labels at disc centers)
    # SCT uses: disc below C2 = 3, disc below C3 = 4, etc.
    sct_disc_data = np.zeros_like(tss_data, dtype=np.uint8)
    placed_discs: list[tuple[int, int]] = []  # (sct_label, S-I index) for the sanity check
    for name, tss_label in TSS_LABELS["discs"].items():
        mask = tss_data == tss_label
        if not mask.any():
            continue
        coords = np.argwhere(mask)
        # Convert disc name to SCT label (disc C2/C3 = 3, C3/C4 = 4, etc.)
        upper, lower = name.split("/")
        if upper.startswith("C"):
            sct_label = int(upper[1:]) + 1  # C2/C3 = 3
        elif upper.startswith("T"):
            sct_label = int(upper[1:]) + 8  # T1/T2 = 9
        elif upper.startswith("L"):
            sct_label = int(upper[1:]) + 20  # L1/L2 = 21
        else:
            continue
        # SCT convention: the single-voxel disc label sits at the POSTERIOR TIP
        # of the disc at its S-I mid-level (this is what sct_label_vertebrae
        # emits and what sct_register_to_template -ldisc expects), NOT the mask
        # centroid. The images here are RPI-standardized, so axis 1 increases
        # toward Posterior and axis 2 toward Inferior: posterior tip = the
        # max-axis-1 voxel on the disc's mid S-I slice.
        cz = int(round(float(coords[:, 2].mean())))
        at_z = coords[coords[:, 2] == cz]
        if at_z.size == 0:  # no voxel exactly at mid-slice; use the nearest S-I slice
            cz = int(coords[int(np.argmin(np.abs(coords[:, 2] - cz))), 2])
            at_z = coords[coords[:, 2] == cz]
        tip = at_z[int(np.argmax(at_z[:, 1]))]
        sct_disc_data[tuple(tip)] = sct_label
        placed_discs.append((sct_label, int(tip[2])))
    sct_disc_path = tss_dir / "disc_labels_sct.nii.gz"
    nib.save(nib.Nifti1Image(sct_disc_data, affine, header), sct_disc_path)
    labeling_sanity = _check_labeling_sanity(placed_discs)

    # Compute metrics
    present_vertebrae = sorted([TSS_VERTEBRA_NAMES[int(v)] for v in np.unique(vertebrae_data) if v > 0])
    present_discs = sorted([TSS_DISC_NAMES[int(v)] for v in np.unique(discs_data) if v > 0])

    # Load cord/canal for volume metrics
    try:
        cord_vol_data = nib.load(cord_path).get_fdata()
        cord_volume_vox = int(np.sum(cord_vol_data > 0))
    except Exception:
        cord_volume_vox = 0
    try:
        canal_vol_data = nib.load(canal_path).get_fdata()
        canal_volume_vox = int(np.sum(canal_vol_data > 0))
    except Exception:
        canal_volume_vox = 0

    return {
        "status": "PASS",
        "failure_message": None,
        "tss_output_path": str(tss_output),
        "cord_path": str(cord_path),
        "canal_path": str(canal_path),
        "vertebrae_path": str(vertebrae_path),
        "discs_path": str(discs_path),
        "vertebral_labels_path": str(sct_vertebral_path),  # SCT-compatible
        "disc_labels_path": str(sct_disc_path),  # SCT-compatible
        "metrics": {
            "vertebrae_count": len(present_vertebrae),
            "disc_count": len(present_discs),
            "present_vertebrae": present_vertebrae,
            "present_discs": present_discs,
            "cord_volume_vox": cord_volume_vox,
            "canal_volume_vox": canal_volume_vox,
            "labeling_sanity": labeling_sanity,
        },
    }


def _check_labeling_sanity(placed_discs: list[tuple[int, int]]) -> dict:
    """Sanity-check TotalSpineSeg disc labeling for the classic failure modes.

    TSS is a single network and is the linchpin for template registration: an
    off-by-one shifts every downstream level. There is no second labeling
    backend to cross-check against (sct_label_vertebrae is not wired), so this
    catches the tell-tale signatures of a mislabel from the labels alone:

    - **Internal gap**: the SCT disc values covering the imaged span should be
      contiguous (e.g. 3,4,5,6). A missing value in the middle (3,4,6) means a
      disc was skipped or mislabeled.
    - **Non-monotonic S-I ordering**: a higher disc number is more caudal, so in
      RPI its S-I index must increase monotonically. A reversal is a mislabel.
    - **Too few levels**: fewer than 3 discs is too little to anchor a reliable
      registration.

    Returns {ok, reasons, n_discs, internal_gaps}. `ok=False` drives a WARN in
    S2 (never a hard FAIL — visual QC on the TSS montage is the validator).
    """
    reasons: list[str] = []
    discs = sorted(placed_discs, key=lambda t: t[0])
    labels = [d[0] for d in discs]
    n = len(labels)
    internal_gaps = 0
    if n < 3:
        reasons.append(f"only {n} disc label(s) placed (< 3) — too few to anchor registration")
    else:
        expected = set(range(labels[0], labels[-1] + 1))
        missing = sorted(expected - set(labels))
        internal_gaps = len(missing)
        if missing:
            reasons.append(f"non-contiguous disc labels — missing {missing} between {labels[0]} and {labels[-1]}")
        # Disc S-I position must be strictly MONOTONIC with disc number. The
        # direction (increasing or decreasing z) depends on image orientation,
        # so we do NOT assume one — we only flag a REVERSAL (mixed signs) or a
        # tie, which is the actual mislabel signature. (Assuming "increasing"
        # false-flagged every subject whose S-I axis runs the other way.)
        zs = [d[1] for d in discs]
        diffs = [zs[i + 1] - zs[i] for i in range(len(zs) - 1)]
        has_up = any(dz > 0 for dz in diffs)
        has_down = any(dz < 0 for dz in diffs)
        if any(dz == 0 for dz in diffs) or (has_up and has_down):
            reasons.append("disc S-I ordering is non-monotonic with disc number — likely mislabel")
    return {
        "ok": len(reasons) == 0,
        "reasons": reasons,
        "n_discs": n,
        "internal_gaps": internal_gaps,
    }
