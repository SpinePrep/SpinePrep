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
    """Build per-(subject, session) anat candidate list.

    Modalities detected:
      - T2star: MEGRE multi-echo magnitude (`_acq-MEGRE_..._echo-NN_part-mag_T2star.nii.gz`).
        All matching files for the (subject, session) are bundled into a SINGLE
        candidate with `echo_paths` list — they will be combined later via
        RMS-across-echoes + mean-across-runs to synthesize one 3D T2* image.
        Phase files (`_part-phase`) are skipped.
      - T2w / T1w: standard single-file candidates.
    """
    candidates: dict[tuple[str, Optional[str]], list[dict]] = {}
    megre_groups: dict[tuple[str, Optional[str]], list[str]] = {}

    for entry in inventory.get("files", []):
        path = entry.get("path")
        if not path or not isinstance(path, str):
            continue
        path_lower = path.lower()
        if "/anat/" not in path_lower:
            continue
        if not (path_lower.endswith(".nii") or path_lower.endswith(".nii.gz")):
            continue
        subject = entry.get("subject")
        session = entry.get("session")
        if not subject:
            continue
        key = (subject, session)

        # MEGRE magnitude detection: BIDS uses acq-MEGRE + part-mag + T2star suffix.
        # Skip phase files.
        is_megre = ("acq-megre" in path_lower
                    and "_t2star.nii" in path_lower
                    and ("_part-mag" in path_lower or "_part-phase" not in path_lower))
        if is_megre and "_part-phase" not in path_lower:
            megre_groups.setdefault(key, []).append(path)
            continue

        if "t1w" not in path_lower and "t2w" not in path_lower:
            continue
        modality = "T2w" if "t2w" in path_lower else "T1w"
        candidates.setdefault(key, []).append({"path": path, "modality": modality})

    for key, paths in megre_groups.items():
        # Use the first magnitude file's path as the canonical "path" for
        # ordering / display; carry the full echo list separately.
        sorted_paths = sorted(paths)
        candidates.setdefault(key, []).append({
            "path": sorted_paths[0],
            "modality": "T2star",
            "echo_paths": sorted_paths,
        })
    return candidates


def _synthesize_t2star(
    echo_paths: list[Path],
    out_path: Path,
    work_dir: Path,
    echo_combine: str = "rms",
    run_combine: str = "mean",
) -> tuple[bool, str]:
    """Combine MEGRE magnitude echoes into a single 3D T2* image.

    Recipe (CoSpi spi03_anat_preproc.sh): per run, concat all echoes along
    time and take RMS -> per-run T2*. Concat per-run images along time and
    take mean -> final 3D anat.

    Falls back to a single concat+combine if run grouping fails.
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    import re
    by_run: dict[str, list[Path]] = {}
    for p in echo_paths:
        m = re.search(r"_run-(\d+)_", p.name)
        run_id = m.group(1) if m else "01"
        by_run.setdefault(run_id, []).append(p)

    per_run_imgs: list[Path] = []
    for run_id, paths in sorted(by_run.items()):
        paths = sorted(paths)
        concat_path = work_dir / f"megre_run-{run_id}_4d.nii.gz"
        ok, msg = _run_command(["sct_image", "-i", *[str(p) for p in paths],
                                "-concat", "t", "-o", str(concat_path)])
        if not ok or not concat_path.exists():
            return False, f"sct_image concat failed (run {run_id}): {msg[:160]}"
        combined_path = work_dir / f"megre_run-{run_id}_{echo_combine}.nii.gz"
        ok, msg = _run_command(["sct_maths", "-i", str(concat_path),
                                f"-{echo_combine}", "t", "-o", str(combined_path)])
        if not ok or not combined_path.exists():
            return False, f"sct_maths {echo_combine} failed (run {run_id}): {msg[:160]}"
        per_run_imgs.append(combined_path)

    if len(per_run_imgs) == 1:
        # Single run — copy through.
        _copy_file(per_run_imgs[0], out_path)
        return True, ""

    if run_combine == "first_run":
        _copy_file(per_run_imgs[0], out_path)
        return True, ""

    # Rigidly align each subsequent run to the first BEFORE averaging.
    # A naive voxelwise mean of separately-acquired runs blurs the cord if
    # there is any between-run motion; a within-run rigid alignment removes it.
    # Strictly additive: if a run fails to register we keep its original image,
    # so this is never worse than the previous unaligned mean.
    aligned_imgs: list[Path] = [per_run_imgs[0]]
    for i, mov in enumerate(per_run_imgs[1:], start=1):
        reg_out = work_dir / f"megre_run{i}_to_run0.nii.gz"
        ok, _ = _run_command([
            "sct_register_multimodal",
            "-i", str(mov), "-d", str(per_run_imgs[0]),
            "-param", "step=1,type=im,algo=rigid,metric=MeanSquares,iter=10",
            "-x", "spline", "-o", str(reg_out),
        ])
        aligned_imgs.append(reg_out if (ok and reg_out.exists()) else mov)

    concat_runs = work_dir / "megre_runs_concat.nii.gz"
    ok, msg = _run_command(["sct_image", "-i", *[str(p) for p in aligned_imgs],
                            "-concat", "t", "-o", str(concat_runs)])
    if not ok or not concat_runs.exists():
        return False, f"sct_image run-concat failed: {msg[:160]}"
    op = "rms" if run_combine == "rms" else "mean"
    ok, msg = _run_command(["sct_maths", "-i", str(concat_runs),
                            f"-{op}", "t", "-o", str(out_path)])
    if not ok or not out_path.exists():
        return False, f"sct_maths {op} (runs) failed: {msg[:160]}"
    return True, ""


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
    dataset_key: Optional[str] = None,
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
        dataset_key=dataset_key,
    )


def _process_single_session_batch_worker(session_info: dict) -> tuple[str, str, Optional[str], dict]:
    """
    Worker function for batch processing - processes one (subject, session) from any dataset.

    This is a module-level function (not nested) so it can be pickled for multiprocessing.
    Derivatives are stored with dataset_key prefix: derivatives/spineprep/{dataset_key}/sub-XX/
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


def _process_secondary_cordref(
    candidates: list[dict],
    primary_modality: Optional[str],
    subject: str,
    session: Optional[str],
    run_id: str,
    bids_root: Path,
    out_root: Path,
    policy: dict,
    dataset_key: Optional[str] = None,
) -> Optional[dict]:
    """Produce a SECONDARY cordref + cord_dseg in a contrast that matches
    T2*-EPI (for S5/S6 func->anat registration). Runs ONLY when a T2star
    (or whatever `secondary_cordref_preference` lists) candidate exists
    that differs from the primary modality. Skips labeling, TotalSpineSeg,
    rootlets, and PAM50 registration — those need full-FOV primary anats.

    Returns a small info dict {modality, cordref_path, cordmask_path} or
    None when the secondary role is not applicable / fails.
    """
    sec_pref = policy.get("secondary_cordref_preference", [])
    if not sec_pref:
        return None
    sec_sel = _select_cordref(candidates, sec_pref)
    if sec_sel is None or sec_sel.get("modality") == primary_modality:
        return None

    sec_mod = sec_sel["modality"]
    if dataset_key:
        sec_work_dir = (out_root / "work" / "S2_anat_cordref"
                        / dataset_key / run_id / f"_secondary_{sec_mod}")
    else:
        sec_work_dir = (out_root / "work" / "S2_anat_cordref"
                        / run_id / f"_secondary_{sec_mod}")
    sec_work_dir.mkdir(parents=True, exist_ok=True)

    sec_source = bids_root / sec_sel["path"]
    if sec_mod == "T2star" and sec_sel.get("echo_paths"):
        synthesized = sec_work_dir / "anat_T2star_synthesized.nii.gz"
        echo_paths_abs = [bids_root / p for p in sec_sel["echo_paths"]]
        ok, message = _synthesize_t2star(
            echo_paths=echo_paths_abs,
            out_path=synthesized,
            work_dir=sec_work_dir / "megre",
            echo_combine=policy.get("megre_echo_combine", "rms"),
            run_combine=policy.get("megre_run_combine", "mean"),
        )
        if not ok or not synthesized.exists():
            return {"status": "FAIL",
                    "failure_message": f"secondary MEGRE synth failed: {message}",
                    "modality": sec_mod}
        sec_source = synthesized
    elif not sec_source.exists():
        return None

    standard_path = sec_work_dir / "cordref_std.nii.gz"
    ok, message = _standardize_orientation(sec_source, standard_path,
                                           policy["orientation"])
    if not ok:
        return {"status": "FAIL",
                "failure_message": f"secondary standardize failed: {message}",
                "modality": sec_mod}

    discovery_seg_path = sec_work_dir / "cordmask_discovery.nii.gz"
    discover_contrast = policy["discover_contrast_map"].get(sec_mod, "t2")
    ok, message = _run_discovery_segmentation(
        standard_path=standard_path,
        discovery_seg_path=discovery_seg_path,
        contrast=discover_contrast,
        min_z_slices=policy["discover_min_z_slices"],
        method=policy["discover_method"],
        task=policy.get("discover_task"),
    )
    if not ok:
        return {"status": "FAIL",
                "failure_message": f"secondary discovery failed: {message}",
                "modality": sec_mod}

    cropped_path = sec_work_dir / "cordref_crop.nii.gz"
    crop_mask_path = sec_work_dir / "crop_mask.nii.gz"
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
        return {"status": "FAIL",
                "failure_message": f"secondary crop failed: {message}",
                "modality": sec_mod}

    derivatives_dir = _derivatives_anat_dir(out_root, subject, session,
                                            dataset_key)
    derivatives_dir.mkdir(parents=True, exist_ok=True)
    cordref_name = _format_derivative_name(subject, session, "desc-cordref", sec_mod)
    cordref_path = derivatives_dir / cordref_name
    _copy_nifti(cropped_path, cordref_path)

    seg_path = derivatives_dir / _format_derivative_name(
        subject, session, "desc-cord_dseg", sec_mod
    )
    cord_method = policy.get("cord_method", "contrast_agnostic")
    if cord_method == "contrast_agnostic":
        ok, message = _run_command(
            ["sct_deepseg", "spinalcord", "-i", str(cordref_path), "-o", str(seg_path)]
        )
    else:
        contrast = policy["contrast_map"].get(sec_mod, "t2")
        ok, message = _run_command(
            ["sct_deepseg_sc", "-i", str(cordref_path),
             "-c", str(contrast), "-o", str(seg_path)]
        )
    if not ok or not seg_path.exists():
        return {"status": "FAIL",
                "failure_message": f"secondary cord seg failed: {message}",
                "modality": sec_mod}

    return {
        "status": "PASS",
        "modality": sec_mod,
        "cordref_path": _relpath(cordref_path, out_root),
        "cordmask_path": _relpath(seg_path, out_root),
        "source_path": sec_sel["path"] if isinstance(sec_sel.get("path"), str)
                         else str(sec_sel["path"]),
    }


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
            "failure_message": "No eligible T1w/T2w/T2star anatomy found for cordref selection.",
            "run_id": run_id,
            "dataset_key": dataset_key,
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
            "dataset_key": dataset_key,
        }

    # When the same (subject, session) appears in multiple datasets (e.g.
    # sub-02 lives in internal_balgrist, ds005883_pain, ds005884_motor),
    # they must not share a work dir or the LAST S2 run overwrites the
    # others' cordref_std/cordmask_discovery files. Key the work dir by
    # dataset_key when available.
    if dataset_key:
        work_dir = out_root / "work" / "S2_anat_cordref" / dataset_key / run_id
    else:
        work_dir = out_root / "work" / "S2_anat_cordref" / run_id
    work_dir.mkdir(parents=True, exist_ok=True)

    # MEGRE synthesis (T2star modality with multiple echo paths): combine
    # echoes/runs into a single 3D T2* image and use that as the source.
    if selection.get("modality") == "T2star" and selection.get("echo_paths"):
        synthesized = work_dir / "anat_T2star_synthesized.nii.gz"
        echo_paths_abs = [bids_root / p for p in selection["echo_paths"]]
        ok, message = _synthesize_t2star(
            echo_paths=echo_paths_abs,
            out_path=synthesized,
            work_dir=work_dir / "megre",
            echo_combine=policy.get("megre_echo_combine", "rms"),
            run_combine=policy.get("megre_run_combine", "mean"),
        )
        if not ok or not synthesized.exists():
            return _fail_run(subject, session, run_id, f"MEGRE T2* synthesis failed: {message}", dataset_key=dataset_key)
        source_path = synthesized

    standard_path = work_dir / "cordref_std.nii.gz"
    ok, message = _standardize_orientation(source_path, standard_path, policy["orientation"])
    if not ok:
        return _fail_run(subject, session, run_id, f"Header standardization failed: {message}", dataset_key=dataset_key)

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
        return _fail_run(subject, session, run_id, f"Discovery segmentation failed: {message}", dataset_key=dataset_key)

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
        return _fail_run(subject, session, run_id, f"Cropping failed: {message}", dataset_key=dataset_key)

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
        return _fail_run(subject, session, run_id, f"Cord segmentation failed: {message}", dataset_key=dataset_key)

    try:
        metrics = _compute_segmentation_metrics(seg_path)
    except ValueError as err:
        return _fail_run(subject, session, run_id, f"Metric computation failed: {err}", dataset_key=dataset_key)

    tss_info = _run_totalspineseg(cordref_path=cordref_path, work_dir=work_dir)
    if tss_info["status"] == "FAIL":
        return _fail_run(subject, session, run_id, tss_info["failure_message"], dataset_key=dataset_key)

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

    # Always-prefer-rootlets: run the disc registration ONLY as a fallback when
    # the rootlet registration is absent or did not pass. Running both every
    # time and discarding disc doubled the (CPU-bound) registration cost — the
    # step's dominant wall-time — for no benefit. See s2-algorithm-audit.md F2.
    reg_disc: Optional[dict] = None
    if not (reg_rootlet and reg_rootlet.get("status") == "PASS"):
        reg_disc = _run_register_to_template(
            cordref_path=cordref_path,
            seg_path=seg_path,
            disc_labels_path=disc_labels_path,
            rootlets_path=None,
            contrast=contrast,
            work_dir=work_dir / "reg_disc",
        )

    # Selection is by DESIGN a completion-preference for rootlets, NOT a
    # quality comparison: rootlets mark the true spinal level (which vertebral
    # discs only approximate), so when the rootlet registration COMPLETES
    # (status PASS = exit 0 + warps written, see register.py) we always prefer
    # it; disc-based is the fallback only when rootlets are absent or the
    # rootlet registration failed. The downstream per-level Dice gate is what
    # actually judges the selected registration's quality. (Do not describe
    # this as "select best by overlap" — it is not; see
    # .claude/specs/s2-algorithm-audit.md F2.)
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
            return _fail_run(subject, session, run_id, str(msg), dataset_key=dataset_key)
        return _fail_run(
            subject, session, run_id,
            str(reg_disc.get("failure_message") or "Registration failed."),
            dataset_key=dataset_key,
        )

    xfm_dir = _derivatives_xfm_dir(out_root, subject, session, dataset_key)
    xfm_dir.mkdir(parents=True, exist_ok=True)
    warp_to_template = xfm_dir / _format_xfm_name(subject, session, "from-cordref_to-PAM50_warp")
    warp_to_cordref = xfm_dir / _format_xfm_name(subject, session, "from-PAM50_to-cordref_warp")
    _copy_file(Path(selected_reg["warp_anat2template"]), warp_to_template)
    _copy_file(Path(selected_reg["warp_template2anat"]), warp_to_cordref)

    # Step-local truth metric (CLAUDE.md dev principle §3): 3D Dice
    # between PAM50 cord warped to native anat space and the native
    # cord_dseg. Quantifies PAM50 registration quality; complements
    # the visual pam50_reg_overlay reportlet.
    from .register import compute_pam50_cord_dice, compute_pam50_cord_dice_per_level
    pam50_cord_dice = compute_pam50_cord_dice(
        native_cord_seg=seg_path,
        warp_template2anat=Path(selected_reg["warp_template2anat"]),
        work_dir=work_dir / "pam50_dice",
    )
    if pam50_cord_dice is not None:
        metrics["pam50_cord_dice"] = pam50_cord_dice
    # Per-vertebral-level cord Dice — the PRIMARY registration-quality gate
    # (coverage-independent; whole-cord Dice above is coverage-confounded and
    # blind to S-I misalignment). Same S7 per-level convention. See
    # .claude/specs/s2-algorithm-audit.md F1.
    pam50_dice_per_level = compute_pam50_cord_dice_per_level(
        native_cord_seg=seg_path,
        warp_template2anat=Path(selected_reg["warp_template2anat"]),
        work_dir=work_dir / "pam50_dice_per_level",
    )
    if pam50_dice_per_level:
        metrics["pam50_cord_dice_per_level"] = {str(k): v for k, v in pam50_dice_per_level.items()}

    # Vertebral / rootlets coverage gauges — count how many distinct
    # levels were detected. Easy to compute, hard to fake.
    try:
        labels_metrics = (label_info or {}).get("metrics", {}) if "label_info" in dir() else {}
    except Exception:
        labels_metrics = {}
    if isinstance(labels_metrics, dict):
        # _run_totalspineseg emits vertebrae_count / disc_count (segment.py).
        if "vertebrae_count" in labels_metrics:
            metrics["n_vertebral_levels"] = int(labels_metrics["vertebrae_count"])
        if "disc_count" in labels_metrics:
            metrics["n_disc_levels"] = int(labels_metrics["disc_count"])
    rootlets_meta = rootlets_info if isinstance(rootlets_info, dict) else {}
    if rootlets_meta.get("status") == "PASS" and rootlets_meta.get("rootlets_path"):
        try:
            import nibabel as nib
            import numpy as _np
            rdata = nib.load(rootlets_meta["rootlets_path"]).get_fdata()
            uniq = [v for v in _np.unique(rdata) if v > 0]
            metrics["n_rootlet_labels"] = int(len(uniq))
        except Exception:
            pass

    sct_version = _get_sct_version()

    # Secondary cordref (T2*/MEGRE) — runs only when available and distinct
    # from the primary modality. Produces only desc-cordref_<mod>.nii.gz +
    # desc-cord_dseg_<mod>.nii.gz; downstream S5/S6 prefer T2star when
    # globbing for cordref/cord_dseg.
    secondary_info = _process_secondary_cordref(
        candidates=candidates,
        primary_modality=selection["modality"],
        subject=subject, session=session, run_id=run_id,
        bids_root=bids_root, out_root=out_root, policy=policy,
        dataset_key=dataset_key,
    )

    # Step-local truth gate: PAM50 cord Dice (dev principle §3). Only gates when
    # the metric was actually computed (None when warps/PAM50 unavailable).
    run_status = "PASS"
    run_fail_msg = None
    _qt = policy.get("qc_thresholds", {})
    _reasons: list[str] = []
    _pl = metrics.get("pam50_cord_dice_per_level") or {}
    _pl_vals = [v for v in _pl.values() if isinstance(v, (int, float))]
    if _pl_vals:
        # PRIMARY gate: median per-level cord Dice (coverage-independent).
        import statistics as _stats
        _med = _stats.median(_pl_vals)
        _lo = min(_pl_vals)
        _pass_med = _qt.get("per_level_pass_min", 0.90)
        _fail_med = _qt.get("per_level_fail_below", 0.85)
        _broken = _qt.get("per_level_broken_below", 0.50)
        # Three-banded, matching S7. A hard cliff at the PASS level split runs
        # of the same subject on run-to-run noise; here a FAIL costs the whole
        # subject, since this is the anatomical reference. See the policy file.
        if _med < _fail_med:
            run_status = "FAIL"
            _reasons.append(f"per-level median cord Dice FAIL: {_med:.3f} (< {_fail_med:.2f})")
        elif _med < _pass_med:
            run_status = "WARN"
            _reasons.append(
                f"per-level median cord Dice WARN: {_med:.3f} "
                f"(in [{_fail_med:.2f}, {_pass_med:.2f}) — inspect the overlay)")
        # A broken single level is its own diagnostic and must still surface
        # inside the WARN band, so this is not an elif.
        if _lo < _broken:
            if run_status == "PASS":
                run_status = "WARN"
            _reasons.append(
                f"one level Dice={_lo:.3f} (< {_broken:.2f}) — exclude that level "
                f"(per-level median {_med:.3f})")
        _wc = metrics.get("pam50_cord_dice")
        if _wc is not None:
            _reasons.append(f"whole-cord Dice={_wc:.3f} (observability; coverage-confounded, not gated)")
    else:
        # Fallback: legacy whole-cord Dice gate when per-level is unavailable.
        _dice = metrics.get("pam50_cord_dice")
        if _dice is not None:
            if _dice < _qt.get("pam50_cord_dice_warn_min", 0.60):
                run_status = "FAIL"
                _reasons.append(f"pam50_cord_dice FAIL: {_dice:.3f}")
            elif _dice < _qt.get("pam50_cord_dice_pass_min", 0.80):
                run_status = "WARN"
                _reasons.append(f"pam50_cord_dice WARN: {_dice:.3f}")
    # F4: TotalSpineSeg labeling sanity — WARN (never downgrade a FAIL) when the
    # disc labeling shows a mislabel signature; visual QC on the TSS montage is
    # the validator. See .claude/specs/s2-algorithm-audit.md F4.
    _san = ((tss_info or {}).get("metrics", {}) or {}).get("labeling_sanity", {})
    if isinstance(_san, dict) and _san.get("ok") is False:
        if run_status == "PASS":
            run_status = "WARN"
        _reasons.append("labeling sanity: " + "; ".join(_san.get("reasons", [])))
    run_fail_msg = "; ".join(_reasons) if _reasons else None

    return {
        "subject": subject,
        "session": session,
        "status": run_status,
        "failure_message": run_fail_msg,
        "run_id": run_id,
        "dataset_key": dataset_key,
        "source_path": source_rel,
        "cordref_modality": selection["modality"],
        "cordref_secondary": secondary_info,
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
