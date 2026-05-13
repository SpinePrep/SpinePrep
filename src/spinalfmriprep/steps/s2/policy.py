"""Policy loading and validation for S2_anat_cordref."""
from __future__ import annotations

from pathlib import Path

import yaml


def _load_policy(path: Path) -> dict:
    if not path.exists():
        raise ValueError(f"Policy not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("S2_anat_cordref policy must be a mapping.")
    version = raw.get("version")
    if not isinstance(version, int):
        raise ValueError("S2_anat_cordref policy missing integer 'version'.")
    selection = raw.get("selection", {})
    preference = selection.get("preference", ["T2w", "T1w"])
    if not isinstance(preference, list) or not all(isinstance(p, str) for p in preference):
        raise ValueError("S2_anat_cordref policy selection.preference must be a list of strings.")
    standardize = raw.get("standardize", {})
    orientation = standardize.get("orientation", "RPI")

    # Discovery parameters (for discovery segmentation before crop)
    discover = raw.get("discover", {})
    discover_method = discover.get("method", "sct_deepseg_sc")
    if not isinstance(discover_method, str):
        raise ValueError("S2_anat_cordref policy discover.method must be a string.")
    discover_task = discover.get("task")  # Optional, used when method="deepseg"
    if discover_task is not None and not isinstance(discover_task, str):
        raise ValueError("S2_anat_cordref policy discover.task must be a string or null.")
    discover_contrast_map = discover.get("contrast_map", {"T2w": "t2", "T1w": "t1"})
    if not isinstance(discover_contrast_map, dict):
        raise ValueError("S2_anat_cordref policy discover.contrast_map must be a mapping.")
    discover_min_z_slices = discover.get("min_z_slices", 20)
    if not isinstance(discover_min_z_slices, int) or discover_min_z_slices < 1:
        raise ValueError("S2_anat_cordref policy discover.min_z_slices must be a positive integer.")

    # Crop parameters (for mask-based cropping)
    crop = raw.get("crop", {})
    # Backward compatibility: keep size_vox and z_full but deprecated
    size_vox = crop.get("size_vox", [96, 96])
    if (
        not isinstance(size_vox, list)
        or len(size_vox) != 2
        or not all(isinstance(v, int) and v > 0 for v in size_vox)
    ):
        raise ValueError("S2_anat_cordref policy crop.size_vox must be [x, y] positive ints.")
    mask_diameter_mm = crop.get("mask_diameter_mm", 30)
    if not isinstance(mask_diameter_mm, (int, float)) or mask_diameter_mm <= 0:
        raise ValueError("S2_anat_cordref policy crop.mask_diameter_mm must be a positive number.")
    dilate_xyz = crop.get("dilate_xyz", [0, 0, 0])
    if (
        not isinstance(dilate_xyz, list)
        or len(dilate_xyz) != 3
        or not all(isinstance(v, int) for v in dilate_xyz)
    ):
        raise ValueError("S2_anat_cordref policy crop.dilate_xyz must be [x, y, z] integers.")
    crop_min_z_slices = crop.get("min_z_slices", 20)
    if not isinstance(crop_min_z_slices, int) or crop_min_z_slices < 1:
        raise ValueError("S2_anat_cordref policy crop.min_z_slices must be a positive integer.")

    segmentation = raw.get("segmentation", {})
    contrast_map = segmentation.get("contrast_map", {"T2w": "t2", "T1w": "t1"})
    if not isinstance(contrast_map, dict):
        raise ValueError("S2_anat_cordref policy segmentation.contrast_map must be a mapping.")
    # Cord segmentation method: contrast_agnostic (default) or totalspineseg
    cord_method = segmentation.get("cord_method", "contrast_agnostic")
    if cord_method not in ("contrast_agnostic", "totalspineseg"):
        raise ValueError("S2_anat_cordref policy segmentation.cord_method must be 'contrast_agnostic' or 'totalspineseg'.")
    labeling = raw.get("labeling", {})
    # Labeling method: totalspineseg (default) or sct_label_vertebrae
    labeling_method = labeling.get("method", "totalspineseg")
    if labeling_method not in ("totalspineseg", "sct_label_vertebrae"):
        raise ValueError("S2_anat_cordref policy labeling.method must be 'totalspineseg' or 'sct_label_vertebrae'.")
    clean_labels = labeling.get("clean_labels", 1)
    if not isinstance(clean_labels, int):
        raise ValueError("S2_anat_cordref policy labeling.clean_labels must be an int.")
    initcenter = labeling.get("initcenter")
    if initcenter is not None and not isinstance(initcenter, int):
        raise ValueError("S2_anat_cordref policy labeling.initcenter must be an int or null.")
    # TotalSpineSeg QC thresholds
    qc_thresholds = labeling.get("qc_thresholds", {})
    tss_min_levels = qc_thresholds.get("min_vertebral_levels", 5)
    tss_min_coverage = qc_thresholds.get("min_coverage_ratio", 0.8)
    tss_max_gap = qc_thresholds.get("max_inter_level_gap_mm", 15)
    tss_min_confidence = qc_thresholds.get("min_confidence", 0.7)
    rootlets = raw.get("rootlets", {})
    rootlets_enabled = bool(rootlets.get("enabled", False))
    eligible_modalities = rootlets.get("eligible_modalities", ["T2w"])
    if not isinstance(eligible_modalities, list) or not all(
        isinstance(mod, str) for mod in eligible_modalities
    ):
        raise ValueError("S2_anat_cordref policy rootlets.eligible_modalities must be a list of strings.")
    registration = raw.get("registration", {})
    prefer_rootlets = bool(registration.get("prefer_rootlets", True))
    megre = raw.get("megre_synthesis", {})
    echo_combine = megre.get("echo_combine", "rms")
    run_combine = megre.get("run_combine", "mean")
    if echo_combine not in ("rms", "mean", "first_echo"):
        raise ValueError("megre_synthesis.echo_combine must be rms|mean|first_echo")
    if run_combine not in ("rms", "mean", "first_run"):
        raise ValueError("megre_synthesis.run_combine must be rms|mean|first_run")
    return {
        "version": version,
        "preference": preference,
        "orientation": orientation,
        # Discovery parameters
        "discover_method": discover_method,
        "discover_task": discover_task,
        "discover_contrast_map": discover_contrast_map,
        "discover_min_z_slices": discover_min_z_slices,
        # Crop parameters
        "size_vox": size_vox,  # Deprecated, kept for backward compat
        "z_full": bool(crop.get("z_full", True)),  # Deprecated, kept for backward compat
        "mask_diameter_mm": mask_diameter_mm,
        "dilate_xyz": dilate_xyz,
        "crop_min_z_slices": crop_min_z_slices,
        # Segmentation parameters
        "contrast_map": contrast_map,
        "cord_method": cord_method,
        # Labeling parameters
        "labeling_method": labeling_method,
        "clean_labels": clean_labels,
        "initcenter": initcenter,
        # TotalSpineSeg QC thresholds
        "tss_min_levels": tss_min_levels,
        "tss_min_coverage": tss_min_coverage,
        "tss_max_gap": tss_max_gap,
        "tss_min_confidence": tss_min_confidence,
        # Rootlets parameters
        "rootlets_enabled": rootlets_enabled,
        "rootlets_modalities": eligible_modalities,
        # Registration parameters
        "prefer_rootlets": prefer_rootlets,
        # MEGRE synthesis
        "megre_echo_combine": echo_combine,
        "megre_run_combine": run_combine,
    }
