"""Confound regressors: aCompCor and censoring."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, List, Tuple

import nibabel as nib
import numpy as np
from scipy import ndimage
from sklearn.decomposition import PCA


def discover_masks(
    run_path: Path, out_dir: Path
) -> Tuple[np.ndarray | None, np.ndarray | None, List[str]]:
    """
    Discover WM and CSF masks for a functional run.

    Args:
        run_path: Path to the functional NIfTI
        out_dir: Output directory to search for masks

    Returns:
        Tuple of (wm_mask, csf_mask, notes)
    """
    stem = run_path.name.replace(".nii.gz", "").replace(".nii", "")
    notes = []

    # Search locations
    search_dirs = [run_path.parent, out_dir / "masks"]

    wm_mask = None
    csf_mask = None

    for search_dir in search_dirs:
        if wm_mask is None:
            wm_candidate = search_dir / f"{stem}_mask-WM.nii.gz"
            if wm_candidate.exists():
                wm_mask = nib.load(wm_candidate).get_fdata() > 0.5
                notes.append(f"WM mask: {wm_candidate}")

        if csf_mask is None:
            csf_candidate = search_dir / f"{stem}_mask-CSF.nii.gz"
            if csf_candidate.exists():
                csf_mask = nib.load(csf_candidate).get_fdata() > 0.5
                notes.append(f"CSF mask: {csf_candidate}")

    return wm_mask, csf_mask, notes


def build_fallback_masks(
    nifti_img: nib.Nifti1Image,
) -> Tuple[np.ndarray, np.ndarray, List[str]]:
    """
    Build heuristic WM and CSF masks from first volume.

    Args:
        nifti_img: 4D functional image

    Returns:
        Tuple of (wm_mask, csf_mask, notes)
    """
    data_4d = nifti_img.get_fdata()
    v0 = data_4d[:, :, :, 0]

    # Central crop: middle 30% of x and y
    nx, ny, nz = v0.shape
    x_start, x_end = int(nx * 0.35), int(nx * 0.65)
    y_start, y_end = int(ny * 0.35), int(ny * 0.65)

    crop = v0[x_start:x_end, y_start:y_end, :]

    # Compute robust z-scores
    median = np.median(crop)
    mad = np.median(np.abs(crop - median))
    z = (crop - median) / (mad + 1e-10)

    # WM proxy: top 20% (z >= 0.84)
    wm_crop = z >= 0.84

    # CSF proxy: bottom 20% (z <= -0.84) but > 0
    csf_crop = (z <= -0.84) & (crop > 0)

    # Morphological opening to remove small islands
    wm_crop = ndimage.binary_opening(wm_crop, iterations=1)
    csf_crop = ndimage.binary_opening(csf_crop, iterations=1)

    # Embed back into full volume
    wm_mask = np.zeros_like(v0, dtype=bool)
    csf_mask = np.zeros_like(v0, dtype=bool)
    wm_mask[x_start:x_end, y_start:y_end, :] = wm_crop
    csf_mask[x_start:x_end, y_start:y_end, :] = csf_crop

    notes = [
        f"Fallback masks: WM={wm_mask.sum()} voxels, CSF={csf_mask.sum()} voxels"
    ]

    # Validate minimum size
    if wm_mask.sum() < 50:
        notes.append("WARN: WM mask < 50 voxels, aCompCor may be unreliable")
    if csf_mask.sum() < 50:
        notes.append("WARN: CSF mask < 50 voxels, aCompCor may be unreliable")

    return wm_mask, csf_mask, notes


def extract_acompcor(
    img_4d: np.ndarray,
    wm_mask: np.ndarray,
    csf_mask: np.ndarray,
    n_components: int = 6,
) -> np.ndarray:
    """
    Extract aCompCor principal components.

    Args:
        img_4d: 4D array (x, y, z, t)
        wm_mask: 3D boolean WM mask
        csf_mask: 3D boolean CSF mask
        n_components: Number of PCs to extract (default 6)

    Returns:
        Array of shape (t, n_components) with aCompCor regressors
    """
    n_timepoints = img_4d.shape[3]

    # Combine masks
    combined_mask = wm_mask | csf_mask

    if combined_mask.sum() < n_components:
        # Not enough voxels, return zeros with warning
        return np.zeros((n_timepoints, n_components))

    # Extract masked timeseries (voxels × timepoints)
    masked_data = img_4d[combined_mask].T  # (timepoints, voxels)

    # Demean and standardize
    masked_data = masked_data - masked_data.mean(axis=0)
    std = masked_data.std(axis=0)
    std[std == 0] = 1.0  # Avoid division by zero
    masked_data = masked_data / std

    # PCA
    n_comp_actual = min(n_components, masked_data.shape[1], masked_data.shape[0])
    if n_comp_actual < n_components:
        # Not enough variance, pad with zeros
        pca = PCA(n_components=n_comp_actual)
        components = pca.fit_transform(masked_data)
        padded = np.zeros((n_timepoints, n_components))
        padded[:, :n_comp_actual] = components
        return padded
    else:
        pca = PCA(n_components=n_components)
        return pca.fit_transform(masked_data)


def compute_censor(
    fd: np.ndarray,
    dvars: np.ndarray,
    fd_threshold: float,
    dvars_threshold: float,
) -> np.ndarray:
    """
    Compute censoring mask from FD and DVARS.

    Args:
        fd: FD array
        dvars: DVARS array
        fd_threshold: FD threshold (mm)
        dvars_threshold: DVARS threshold

    Returns:
        Binary array where 1 = censor, 0 = keep
    """
    censor = np.zeros(len(fd), dtype=int)
    censor[(fd > fd_threshold) | (dvars > dvars_threshold)] = 1
    return censor


def process(manifest_csv: Path, out_dir: Path, cfg: Dict) -> Dict[str, int]:
    """
    Process confounds: add aCompCor and censor to existing motion TSVs.

    Args:
        manifest_csv: Path to manifest CSV
        out_dir: Output directory
        cfg: Configuration dictionary

    Returns:
        Stats dictionary
    """
    runs_processed = 0
    runs_skipped = 0
    total_censored = 0

    # Get thresholds from config
    fd_thresh = cfg.get("pipeline", {}).get("motion", {}).get("fd_threshold", 0.5)
    dvars_thresh = cfg.get("pipeline", {}).get("motion", {}).get("dvars_threshold", 1.5)

    with manifest_csv.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["modality"] != "func" or row["ext"] not in {".nii.gz", ".nii"}:
                continue

            run_path = Path(row["path"])
            if not run_path.exists():
                continue

            # Find the confounds TSV from motion step
            # Handle .nii.gz properly
            rel_path = str(run_path.name)
            if rel_path.endswith(".nii.gz"):
                rel_path = rel_path[:-7]  # Remove .nii.gz
            elif rel_path.endswith(".nii"):
                rel_path = rel_path[:-4]  # Remove .nii
            confounds_tsv = out_dir / f"{rel_path}_desc-confounds_timeseries.tsv"

            if not confounds_tsv.exists():
                runs_skipped += 1
                continue

            # Load existing confounds
            with confounds_tsv.open() as tsv_f:
                tsv_reader = csv.DictReader(tsv_f, delimiter="\t")
                existing_rows = list(tsv_reader)
                existing_cols = tsv_reader.fieldnames

            if not existing_rows:
                runs_skipped += 1
                continue

            # Load functional image
            img = nib.load(run_path)

            # Discover or build masks
            wm_mask, csf_mask, mask_notes = discover_masks(run_path, out_dir)
            if wm_mask is None or csf_mask is None:
                wm_mask, csf_mask, fallback_notes = build_fallback_masks(img)
                mask_notes.extend(fallback_notes)

            # Extract aCompCor
            data_4d = img.get_fdata()
            acompcor = extract_acompcor(data_4d, wm_mask, csf_mask, n_components=6)

            # Compute censor from existing FD/DVARS
            fd = np.array([float(r["fd"]) for r in existing_rows])
            dvars = np.array([float(r["dvars"]) for r in existing_rows])
            censor = compute_censor(fd, dvars, fd_thresh, dvars_thresh)

            # Update TSV with new columns
            new_cols = existing_cols + [
                f"acompcor{i+1:02d}" for i in range(6)
            ] + ["censor"]

            with confounds_tsv.open("w", newline="") as tsv_f:
                writer = csv.DictWriter(tsv_f, fieldnames=new_cols, delimiter="\t")
                writer.writeheader()
                for i, row_dict in enumerate(existing_rows):
                    # Add aCompCor columns
                    for j in range(6):
                        row_dict[f"acompcor{j+1:02d}"] = acompcor[i, j]
                    # Add censor
                    row_dict["censor"] = censor[i]
                    writer.writerow(row_dict)

            runs_processed += 1
            total_censored += int(censor.sum())

            # Print summary
            print(
                f"[confounds]   {rel_path}: 6 PCs, {censor.sum()}/{len(censor)} censored"
            )

    return {
        "runs": runs_processed,
        "skipped": runs_skipped,
        "censored": total_censored,
    }

