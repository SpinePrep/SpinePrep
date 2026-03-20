"""Session processing, candidate collection, worker functions, and run aggregation."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from .io import (
    StepResult,
    _run_command,
    _copy_nifti,
    _copy_file,
    _fail_run,
    _format_command_line,
    _derivatives_anat_dir,
    _format_derivative_name,
    _format_run_id,
    _relpath,
    _get_sct_version,
    _derivatives_xfm_dir,
    _format_xfm_name,
)
from .policy import _load_policy
from .discover import _select_cordref, _standardize_orientation, _run_discovery_segmentation, _crop_based_on_mask
from .segment import _compute_segmentation_metrics, _run_totalspineseg
from .rootlets import _run_rootlets_segmentation
from .register import _run_register_to_template


def _collect_anat_candidates(inventory: dict) -> dict[tuple[str, Optional[str]], list[dict]]:
    candidates: dict[tuple[str, Optional[str]], list[dict]] = {}
    for entry in inventory.get("files", []):
        path = entry.get("path")
        if not path or not isinstance(path, str):
            continue
        path_lower = path.lower()
        if "/anat/" not in path_lower:
            continue
        if not (path_lower.endswith(".nii") or path_lower.endswith(".nii.gz")):
            continue
        if "t1w" not in path_lower and "t2w" not in path_lower:
            continue
        modality = "T2w" if "t2w" in path_lower else "T1w"
        subject = entry.get("subject")
        session = entry.get("session")
        if not subject:
            continue
        key = (subject, session)
        candidates.setdefault(key, []).append(
            {
                "path": path,
                "modality": modality,
            }
        )
    return candidates


def _collect_subject_sessions(inventory: dict) -> set[tuple[str, Optional[str]]]:
    sessions: set[tuple[str, Optional[str]]] = set()
    for entry in inventory.get("files", []):
        subject = entry.get("subject")
        if not subject:
            continue
        sessions.add((subject, entry.get("session")))
    return sessions


def _process_session_worker(
    subject: str,
    session: Optional[str],
    candidates: dict,
    bids_root: str,
    out_root: str,
    policy: dict,
) -> dict:
    """Worker function for parallel processing - unpacks candidates dict and converts strings to Paths."""
    key = (subject, session)
    candidate_list = candidates.get(key, [])
    candidate_list_paths = []
    for cand in candidate_list:
        cand_copy = cand.copy()
        if "path" in cand_copy and isinstance(cand_copy["path"], str):
            cand_copy["path"] = Path(cand_copy["path"])
        candidate_list_paths.append(cand_copy)

    return _process_session(
        subject=subject,
        session=session,
        candidates=candidate_list_paths,
        bids_root=Path(bids_root),
        out_root=Path(out_root),
        policy=policy,
    )


def _process_single_session_batch_worker(session_info: dict) -> tuple[str, str, Optional[str], dict]:
    """
    Worker function for batch processing - processes one (subject, session) from any dataset.

    This is a module-level function (not nested) so it can be pickled for multiprocessing.
    Derivatives are stored with dataset_key prefix: derivatives/spinalfmriprep/{dataset_key}/sub-XX/
    """
    candidates_paths = []
    for cand in session_info["candidates"]:
        cand_copy = cand.copy()
        if "path" in cand_copy and isinstance(cand_copy["path"], str):
            cand_copy["path"] = Path(cand_copy["path"])
        candidates_paths.append(cand_copy)

    policy_path = Path("policy") / "S2_anat_cordref.yaml"
    policy = _load_policy(policy_path)

    dataset_key = session_info["dataset_key"]

    run = _process_session(
        subject=session_info["subject"],
        session=session_info["session"],
        candidates=candidates_paths,
        bids_root=Path(session_info["bids_root"]),
        out_root=Path(session_info["out_root"]),
        policy=policy,
        dataset_key=dataset_key,
    )

    return (
        dataset_key,
        session_info["subject"],
        session_info["session"],
        run,
    )


def _process_session(
    subject: str,
    session: Optional[str],
    candidates: list[dict],
    bids_root: Path,
    out_root: Path,
    policy: dict,
    dataset_key: Optional[str] = None,
) -> dict:
    selection = _select_cordref(candidates, policy["preference"])
    run_id = _format_run_id(subject, session)
    if selection is None:
        return {
            "subject": subject,
            "session": session,
            "status": "FAIL",
            "failure_message": "No eligible T1w/T2w anatomy found for cordref selection.",
            "run_id": run_id,
        }

    source_rel = selection["path"]
    source_path = bids_root / source_rel
    if not source_path.exists():
        return {
            "subject": subject,
            "session": session,
            "status": "FAIL",
            "failure_message": f"Selected anatomy not found: {source_path}",
            "run_id": run_id,
        }

    work_dir = out_root / "work" / "S2_anat_cordref" / run_id
    work_dir.mkdir(parents=True, exist_ok=True)

    standard_path = work_dir / "cordref_std.nii.gz"
    ok, message = _standardize_orientation(source_path, standard_path, policy["orientation"])
    if not ok:
        return _fail_run(subject, session, run_id, f"Header standardization failed: {message}")

    discovery_seg_path = work_dir / "cordmask_discovery.nii.gz"
    discover_contrast = policy["discover_contrast_map"].get(selection["modality"], "t2")
    ok, message = _run_discovery_segmentation(
        standard_path=standard_path,
        discovery_seg_path=discovery_seg_path,
        contrast=discover_contrast,
        min_z_slices=policy["discover_min_z_slices"],
        method=policy["discover_method"],
        task=policy.get("discover_task"),
    )
    if not ok:
        return _fail_run(subject, session, run_id, f"Discovery segmentation failed: {message}")

    cropped_path = work_dir / "cordref_crop.nii.gz"
    crop_mask_path = work_dir / "crop_mask.nii.gz"
    ok, message = _crop_based_on_mask(
        standard_path=standard_path,
        discovery_seg_path=discovery_seg_path,
        cropped_path=cropped_path,
        crop_mask_path=crop_mask_path,
        mask_diameter_mm=policy["mask_diameter_mm"],
        dilate_xyz=policy["dilate_xyz"],
        min_z_slices=policy["crop_min_z_slices"],
    )
    if not ok:
        return _fail_run(subject, session, run_id, f"Cropping failed: {message}")

    derivatives_dir = _derivatives_anat_dir(out_root, subject, session, dataset_key)
    derivatives_dir.mkdir(parents=True, exist_ok=True)

    cordref_name = _format_derivative_name(subject, session, "desc-cordref", selection["modality"])
    cordref_path = derivatives_dir / cordref_name
    _copy_nifti(cropped_path, cordref_path)

    seg_path = derivatives_dir / _format_derivative_name(
        subject, session, "desc-cord_dseg", selection["modality"]
    )
    contrast = policy["contrast_map"].get(selection["modality"], "t2")
    cord_method = policy.get("cord_method", "contrast_agnostic")

    if cord_method == "contrast_agnostic":
        ok, message = _run_command(
            ["sct_deepseg", "spinalcord", "-i", str(cordref_path), "-o", str(seg_path)]
        )
    else:
        ok, message = _run_command(
            ["sct_deepseg_sc", "-i", str(cordref_path), "-c", str(contrast), "-o", str(seg_path)]
        )
    if not ok:
        return _fail_run(subject, session, run_id, f"Cord segmentation failed: {message}")

    try:
        metrics = _compute_segmentation_metrics(seg_path)
    except ValueError as err:
        return _fail_run(subject, session, run_id, f"Metric computation failed: {err}")

    tss_info = _run_totalspineseg(cordref_path=cordref_path, work_dir=work_dir)
    if tss_info["status"] == "FAIL":
        return _fail_run(subject, session, run_id, tss_info["failure_message"])

    vertebral_labels_path = None
    disc_labels_path = None
    canal_path = None
    tss_vertebrae_path = None
    tss_discs_path = None
    tss_output_path = None

    if tss_info["status"] == "PASS":
        vertebral_labels_path = derivatives_dir / _format_derivative_name(
            subject, session, "desc-vertebral_labels", selection["modality"]
        )
        _copy_file(Path(tss_info["vertebral_labels_path"]), vertebral_labels_path)

        disc_labels_path = derivatives_dir / _format_derivative_name(
            subject, session, "desc-disc_labels", selection["modality"]
        )
        _copy_file(Path(tss_info["disc_labels_path"]), disc_labels_path)

        canal_path = derivatives_dir / _format_derivative_name(
            subject, session, "desc-canal_dseg", selection["modality"]
        )
        _copy_file(Path(tss_info["canal_path"]), canal_path)

        tss_output_path = derivatives_dir / _format_derivative_name(
            subject, session, "desc-totalspineseg_dseg", selection["modality"]
        )
        _copy_file(Path(tss_info["tss_output_path"]), tss_output_path)

        tss_vertebrae_path = derivatives_dir / _format_derivative_name(
            subject, session, "desc-tss_vertebrae_dseg", selection["modality"]
        )
        _copy_file(Path(tss_info["vertebrae_path"]), tss_vertebrae_path)

        tss_discs_path = derivatives_dir / _format_derivative_name(
            subject, session, "desc-tss_discs_dseg", selection["modality"]
        )
        _copy_file(Path(tss_info["discs_path"]), tss_discs_path)

    label_info = {
        "status": tss_info["status"],
        "failure_message": tss_info.get("failure_message"),
        "vertebral_labels_path": str(vertebral_labels_path) if vertebral_labels_path else None,
        "disc_labels_path": str(disc_labels_path) if disc_labels_path else None,
        "metrics": tss_info.get("metrics", {}),
    }

    rootlets_info = _run_rootlets_segmentation(
        cordref_path=cordref_path,
        work_dir=work_dir,
        enabled=policy["rootlets_enabled"],
        eligible=selection["modality"] in policy["rootlets_modalities"],
    )
    rootlets_path = None
    if rootlets_info.get("status") == "PASS" and rootlets_info.get("rootlets_path"):
        rootlets_path = derivatives_dir / _format_derivative_name(
            subject, session, "desc-rootlets_dseg", selection["modality"]
        )
        _copy_file(Path(rootlets_info["rootlets_path"]), rootlets_path)

    reg_rootlet: Optional[dict] = None
    if rootlets_path is not None and policy["rootlets_enabled"]:
        reg_rootlet = _run_register_to_template(
            cordref_path=cordref_path,
            seg_path=seg_path,
            disc_labels_path=disc_labels_path,
            rootlets_path=rootlets_path,
            contrast=contrast,
            work_dir=work_dir / "reg_rootlet",
        )

    reg_disc: dict = _run_register_to_template(
        cordref_path=cordref_path,
        seg_path=seg_path,
        disc_labels_path=disc_labels_path,
        rootlets_path=None,
        contrast=contrast,
        work_dir=work_dir / "reg_disc",
    )

    selected_variant: str
    selected_reg: dict
    if reg_rootlet and reg_rootlet.get("status") == "PASS":
        selected_variant = "rootlet"
        selected_reg = reg_rootlet
    elif reg_disc and reg_disc.get("status") == "PASS":
        selected_variant = "disc"
        selected_reg = reg_disc
    else:
        if reg_rootlet and reg_rootlet.get("status") == "FAIL":
            msg = reg_rootlet.get("failure_message") or "rootlet registration failed."
            return _fail_run(subject, session, run_id, str(msg))
        return _fail_run(
            subject, session, run_id,
            str(reg_disc.get("failure_message") or "Registration failed."),
        )

    xfm_dir = _derivatives_xfm_dir(out_root, subject, session)
    xfm_dir.mkdir(parents=True, exist_ok=True)
    warp_to_template = xfm_dir / _format_xfm_name(subject, session, "from-cordref_to-PAM50_warp")
    warp_to_cordref = xfm_dir / _format_xfm_name(subject, session, "from-PAM50_to-cordref_warp")
    _copy_file(Path(selected_reg["warp_anat2template"]), warp_to_template)
    _copy_file(Path(selected_reg["warp_template2anat"]), warp_to_cordref)

    sct_version = _get_sct_version()

    return {
        "subject": subject,
        "session": session,
        "status": "PASS",
        "failure_message": None,
        "run_id": run_id,
        "source_path": source_rel,
        "cordref_modality": selection["modality"],
        "cordref_path": _relpath(cordref_path, out_root),
        "cordmask_path": _relpath(seg_path, out_root),
        "vertebral_labels_path": _relpath(vertebral_labels_path, out_root),
        "disc_labels_path": _relpath(disc_labels_path, out_root),
        "canal_path": _relpath(canal_path, out_root) if canal_path else None,
        "tss_output_path": _relpath(tss_output_path, out_root) if tss_output_path else None,
        "tss_vertebrae_path": _relpath(tss_vertebrae_path, out_root) if tss_vertebrae_path else None,
        "tss_discs_path": _relpath(tss_discs_path, out_root) if tss_discs_path else None,
        "rootlets_path": _relpath(rootlets_path, out_root) if rootlets_path else None,
        "metrics": metrics,
        "labels": label_info,
        "tss": tss_info,
        "rootlets": rootlets_info,
        "registration": {
            "selected": selected_variant,
            "disc": reg_disc,
            "rootlet": reg_rootlet,
        },
        "xfm": {
            "warp_to_template": _relpath(warp_to_template, out_root),
            "warp_to_cordref": _relpath(warp_to_cordref, out_root),
        },
        "provenance": {"sct_version": sct_version},
    }


def _summarise_runs(inventory: dict, policy_path: Path, runs: list[dict]) -> dict:
    total = len(runs)
    passed = sum(1 for run in runs if run.get("status") == "PASS")
    failed = sum(1 for run in runs if run.get("status") == "FAIL")
    status = "PASS" if failed == 0 and total > 0 else "FAIL"
    failure_message = None if status == "PASS" else "One or more runs failed in S2_anat_cordref."
    return {
        "dataset_key": inventory.get("dataset_key"),
        "bids_root": inventory.get("bids_root"),
        "status": status,
        "failure_message": failure_message,
        "policy_path": str(policy_path),
        "counts": {"runs": total, "passed": passed, "failed": failed},
        "runs": runs,
    }


def _qc_overlay(
    qc_root: Path,
    image: Optional[Path],
    seg: Optional[Path],
    process: str,
    dataset_key: str,
    subject: Optional[str],
    dest: Optional[Path] = None,
) -> Optional[Path]:
    if image is None or seg is None:
        return None
    qc_root.mkdir(parents=True, exist_ok=True)
    cmd = [
        "sct_qc",
        "-i", str(image),
        "-s", str(seg),
        "-p", process,
        "-qc", str(qc_root),
        "-qc-dataset", dataset_key,
        "-qc-subject", subject or "unknown",
    ]
    if dest is not None:
        cmd.extend(["-d", str(dest)])
    ok, _ = _run_command(cmd)
    if not ok:
        return None
    from .reportlets_core import _find_qc_overlay, _find_qc_background, _compose_overlay
    overlay = _find_qc_overlay(qc_root)
    if overlay is None:
        return None
    background = _find_qc_background(qc_root)
    if background is None:
        return overlay
    composed = overlay.parent / "composite_img.png"
    if _compose_overlay(background, overlay, composed):
        return composed
    return overlay
