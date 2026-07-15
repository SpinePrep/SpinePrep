"""Session-level processing for S3: per-subject/session orchestration."""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Optional

import nibabel as nib
import numpy as np

from spineprep.steps.s2.io import StepResult
from spineprep.subtask import should_exit_after_subtask

from .io import (
    _find_s2_cordmask_dseg,
    _find_s2_cordref_std,
    _find_denoised_bold,
)
from .localize import _process_s3_1_dummy_drop_and_localization
from .outlier import _process_s3_2_outlier_gating
from .crop import _process_s3_3_crop_and_qc


# ---------------------------------------------------------------------------
# Session processor (per subject-session)
# ---------------------------------------------------------------------------


def _process_session_s3(
    subject: str,
    session: Optional[str],
    candidates: list[dict],
    bids_root: Path,
    out_root: Path,
    policy: dict[str, Any],
    s2_root: Optional[Path] = None,
    dataset_key: Optional[str] = None,
) -> list[dict]:
    session_runs = []

    # Locate S2 outputs - use s2_root if provided (chain model), else use out_root.
    # dataset_key disambiguates run_ids shared across datasets (e.g. sub-02 in
    # both balgrist and cospine) and enables the promoted-S2 fallback.
    s2_lookup_root = s2_root if s2_root else out_root
    cordref_std_path = _find_s2_cordref_std(s2_lookup_root, subject, session, dataset_key)
    cordmask_dseg_path = _find_s2_cordmask_dseg(s2_lookup_root, subject, session)

    if not cordref_std_path:
        # Cannot run S3 without S2 cord reference
        for cand in candidates:
            session_runs.append({
                "subject": subject,
                "session": session,
                "source_path": cand["path"],
                "status": "FAIL",
                "failure_message": "Missing S2 cordref_std",
            })
        return session_runs

    for cand in candidates:
        rel_path = cand["path"]
        bold_path = bids_root / rel_path

        # Determine run ID from source filename
        run_name = Path(rel_path).name.replace(".nii.gz", "").replace(".nii", "").replace("_bold", "")
        run_id = f"{run_name}"

        work_dir = out_root / "runs" / "S3_func_init_and_crop" / run_id
        work_dir.mkdir(parents=True, exist_ok=True)

        run_result = {
            "subject": subject,
            "session": session,
            "run_id": run_id,
            "source_path": rel_path,
            "status": "Running",
            "results": []
        }

        # MP-PCA denoising is its own step (S2B), run on the raw 4D BOLD before
        # any interpolation. If S2B produced a denoised series for this run,
        # consume it here; otherwise use the raw BOLD. (S2B is off by default.)
        func_input = _find_denoised_bold(out_root, run_id) or bold_path

        try:
            # S3.1
            s3_1_res = _process_s3_1_dummy_drop_and_localization(
                func_input,
                work_dir,
                policy,
                subject=subject,
                session=session,
                out_root=out_root,
                cordref_std_path=cordref_std_path,
                cordmask_dseg_path=cordmask_dseg_path,
                run_id=run_id,
            )
            run_result["results"].append(("S3.1", s3_1_res))

            if should_exit_after_subtask("S3.1"):
                run_result["status"] = "PASS"
                session_runs.append(run_result)
                continue

            # S3.1 drift gate: stop the run here when the cord discovery has
            # leaked into the brain. Keep the rendered figure so the user can
            # see *why* in the dashboard reportlet.
            if s3_1_res.get("localization_status") == "FAIL":
                run_result["status"] = "FAIL"
                run_result["failure_message"] = s3_1_res.get(
                    "failure_message", "S3.1 localization failed"
                )
                reportlets = {}
                if s3_1_res.get("figure_path"):
                    fp = Path(s3_1_res["figure_path"])
                    reportlets["func_localization"] = (
                        str(fp.relative_to(out_root)) if fp.is_absolute() else str(fp)
                    )
                run_result["reportlets"] = reportlets
                session_runs.append(run_result)
                continue

            # S3.2
            s3_2_res = _process_s3_2_outlier_gating(
                s3_1_res["func_bold_coarse_path"],
                s3_1_res["func_ref0_path"],
                s3_1_res["discovery_seg_crop_path"],  # Use CROPPED S3.1 mask
                work_dir,
                policy,
                n_dummy_dropped=s3_1_res.get("n_dummy_dropped"),
            )
            run_result["results"].append(("S3.2", s3_2_res))
            if should_exit_after_subtask("S3.2"):
                run_result["status"] = "PASS"
                session_runs.append(run_result)
                continue

            if s3_2_res.get("outlier_status") == "FAIL":
                 run_result["status"] = "FAIL"
                 run_result["failure_message"] = f"S3.2 Outlier gating failed: {s3_2_res.get('failure_message')}"
                 session_runs.append(run_result)
                 continue

            # S3.3
            s3_3_res = _process_s3_3_crop_and_qc(
                s3_1_res["func_bold_coarse_path"],
                s3_1_res["discovery_seg_crop_path"],  # Use CROPPED S3.1 mask
                s3_2_res["func_ref_path"],
                s3_1_res["func_ref_fast_path"],
                s3_1_res["discovery_seg_path"],
                work_dir,
                policy,
                cordref_std_path=cordref_std_path,
            )
            run_result["results"].append(("S3.3", s3_3_res))

            # Copy final figures to derivatives/figures
            reportlets = {}
            if "figure_path" in s3_1_res and s3_1_res["figure_path"]:
                 reportlets["func_localization"] = str(Path(s3_1_res["figure_path"]).relative_to(out_root)) if Path(s3_1_res["figure_path"]).is_absolute() else str(s3_1_res["figure_path"])

            if "figure_path" in s3_2_res and s3_2_res["figure_path"]:
                 reportlets["frame_metrics"] = str(Path(s3_2_res["figure_path"]).relative_to(out_root)) if Path(s3_2_res["figure_path"]).is_absolute() else str(s3_2_res["figure_path"])

            if s3_3_res.get("figures"):
                figs_out = out_root / "derivatives" / "spineprep" / f"sub-{subject}" / "figures"
                figs_out.mkdir(parents=True, exist_ok=True)

                # Helper to copy and record
                def _copy_and_record(src_path, key_suffix, reportlet_key):
                    if src_path and Path(src_path).exists():
                        name = Path(src_path).name
                        if not name.startswith(run_id):
                             name = f"{run_id}_{name}"
                        dest = figs_out / name
                        # Only copy if source and destination are different
                        src_resolved = Path(src_path).resolve()
                        dest_resolved = dest.resolve()
                        if src_resolved != dest_resolved:
                            shutil.copy2(src_path, dest)
                        reportlets[reportlet_key] = str(dest.relative_to(out_root))

                # Order: crop_box, funcref_montage, t2_to_func_overlay
                figures = s3_3_res["figures"]
                if len(figures) > 0:
                    _copy_and_record(figures[0], "crop_box_sagittal", "crop_box_sagittal")
                if len(figures) > 1:
                    _copy_and_record(figures[1], "funcref_montage", "funcref_montage")
                if len(figures) > 2:
                    _copy_and_record(figures[2], "t2_to_func_overlay", "t2_to_func_overlay")

            # Regenerate the four S3 reportlets via the unified renderer
            # so they match the chain-wide visual standard (S2 conventions).
            try:
                from .reportlets_unified import regenerate_s3_reportlets
                figs_out_dir = out_root / "derivatives" / "spineprep" / (
                    f"sub-{subject}/ses-{session}/figures"
                    if session else f"sub-{subject}/figures"
                )
                figs_out_dir.mkdir(parents=True, exist_ok=True)
                rendered = regenerate_s3_reportlets(
                    run_id=run_id,
                    subject=subject, session=session,
                    dataset_key=dataset_key,
                    status="PASS",
                    metrics={},  # populated below; renderer ignores when empty
                    figures_dir=figs_out_dir,
                    cordref_std_path=cordref_std_path,
                    func_ref_fast_path=Path(s3_1_res.get("func_ref_fast_path")) if s3_1_res.get("func_ref_fast_path") else None,
                    func_ref_path=Path(s3_2_res.get("func_ref_path")) if s3_2_res.get("func_ref_path") else None,
                    discovery_seg_path=Path(s3_1_res.get("discovery_seg_path")) if s3_1_res.get("discovery_seg_path") else None,
                    cord_mask_path=Path(s3_1_res.get("discovery_seg_crop_path")) if s3_1_res.get("discovery_seg_crop_path") else None,
                    crop_mask_path=Path(s3_3_res.get("crop_mask_path")) if s3_3_res.get("crop_mask_path") else None,
                    frame_metrics_tsv=Path(s3_2_res.get("frame_metrics_path")) if s3_2_res.get("frame_metrics_path") else None,
                    outlier_mask_json=Path(s3_2_res.get("outlier_mask_path")) if s3_2_res.get("outlier_mask_path") else None,
                )
                # Overwrite reportlet paths with the unified outputs
                for key, p in rendered.items():
                    reportlets[key] = str(p.relative_to(out_root))
            except Exception:
                # Don't fail the run on a viz hiccup
                import traceback; traceback.print_exc()

            run_result["reportlets"] = reportlets

            # Step-local truth metrics (CLAUDE.md dev principle §3).
            # Aggregate what the sub-steps already computed but never
            # surfaced into qc.json. Frame-metric outlier counts are
            # the headline truth gauge: a cord-fMRI run with > ~20%
            # outliers is unusable downstream.
            metrics: dict = {}
            try:
                om_path = s3_2_res.get("outlier_mask_path")
                if om_path and Path(om_path).exists():
                    import json as _json
                    om = _json.loads(Path(om_path).read_text(encoding="utf-8"))
                    metrics["n_frames_total"] = int(om.get("total_frames", 0))
                    # S3.1 is authoritative for the effective drop: S3.2 may
                    # return a CACHED outlier_mask.json written before the
                    # scanner-discard rule existed, whose dummy_dropped is the
                    # stale policy default. S8 (physio offset) and S9
                    # (StartTime) consume this, so prefer the applied count.
                    _eff = s3_1_res.get("n_dummy_dropped")
                    metrics["n_dummy_dropped"] = (
                        int(_eff) if _eff is not None else int(om.get("dummy_dropped", 0))
                    )
                    metrics["n_outliers"] = int(om.get("outlier_count", 0))
                    metrics["outlier_fraction"] = float(om.get("outlier_fraction", 0.0))
                    thresholds = om.get("thresholds") or {}
                    if "dvars" in thresholds:
                        metrics["dvars_threshold"] = float(thresholds["dvars"])
                    if "ref_rms" in thresholds:
                        # On-disk key "ref_rms" (downstream contract) ⇒
                        # surfaced in qc.json as "dvars_ref_threshold" to
                        # match the literature-standard "DVARS-ref" name.
                        metrics["dvars_ref_threshold"] = float(thresholds["ref_rms"])
            except Exception:
                pass
            # Localization gauges. drift_gate_info has `info.n_cord_slices`.
            try:
                gi = s3_1_res.get("drift_gate_info") or {}
                info = gi.get("info") if isinstance(gi, dict) else {}
                if isinstance(info, dict) and "n_cord_slices" in info:
                    metrics["n_cord_slices_localization"] = int(info["n_cord_slices"])
            except Exception:
                pass
            # Cord-tSNR estimate on the cropped funcref (cheap; uses
            # frame_metrics signal pooled across cord voxels via the
            # funcref + cord mask saved by S3.3).
            try:
                fr = s3_2_res.get("func_ref_path")
                cm = s3_3_res.get("crop_mask_path")
                if fr and cm and Path(fr).exists() and Path(cm).exists():
                    import nibabel as _nib
                    import numpy as _np
                    ref = _nib.load(fr).get_fdata()
                    mask = _nib.load(cm).get_fdata() > 0
                    if ref.shape[:3] == mask.shape and mask.any():
                        vals = ref[mask]
                        finite = vals[_np.isfinite(vals)]
                        if finite.size and finite.std() > 0:
                            metrics["funcref_in_cord_mean"] = float(finite.mean())
                            metrics["funcref_in_cord_std"] = float(finite.std())
            except Exception:
                pass
            run_result["metrics"] = metrics
            # Carry the S3.2 soft outlier WARN into the run status (never FAIL).
            if s3_2_res.get("outlier_status") == "WARN":
                run_result["status"] = "WARN"
                if not run_result.get("failure_message"):
                    run_result["failure_message"] = s3_2_res.get("failure_message")
            else:
                run_result["status"] = "PASS"

        except Exception as e:
            run_result["status"] = "FAIL"
            run_result["failure_message"] = str(e)
            import traceback
            run_result["traceback"] = traceback.format_exc()

        session_runs.append(run_result)

    return session_runs


# ---------------------------------------------------------------------------
# Test harness
# ---------------------------------------------------------------------------


def _run_s3_test_harness(out: Optional[str]) -> StepResult:
    """Original test harness for verifying S3 subtasks logic without BIDS structure."""
    from spineprep.run_layout import setup_subtask_context

    if out is None:
        out = Path("work") / "test_s3_subtask"

    out_path = Path(out)
    work_dir = out_path / "runs" / "S3_func_init_and_crop" / "sub-test" / "ses-none" / "func" / "test_bold.nii"
    work_dir.mkdir(parents=True, exist_ok=True)

    test_bold_path = work_dir / "test_bold.nii.gz"
    test_affine = np.eye(4)
    if not test_bold_path.exists():
        test_data = np.random.rand(64, 64, 24, 100).astype(np.float32)
        test_img = nib.Nifti1Image(test_data, test_affine)
        nib.save(test_img, test_bold_path)

    s2_work_dir = out_path / "work" / "S2_anat_cordref" / "sub-test_ses-none"
    s2_work_dir.mkdir(parents=True, exist_ok=True)
    cordref_std_path = s2_work_dir / "cordref_std.nii.gz"
    if not cordref_std_path.exists():
        cordref_data = np.random.rand(64, 64, 24).astype(np.float32)
        cordref_img = nib.Nifti1Image(cordref_data, test_affine)
        nib.save(cordref_img, cordref_std_path)

    s2_anat_deriv = out_path / "derivatives" / "spineprep" / "sub-test" / "anat"
    s2_anat_deriv.mkdir(parents=True, exist_ok=True)
    cordmask_dseg_path = s2_anat_deriv / "sub-test_ses-none_desc-cordmask_dseg.nii.gz"
    if not cordmask_dseg_path.exists():
        mask_data = np.zeros((64, 64, 24), dtype=np.uint8)
        mask_data[28:36, 28:36, 8:16] = 1
        mask_img = nib.Nifti1Image(mask_data, test_affine)
        nib.save(mask_img, cordmask_dseg_path)

    policy = {
        "dummy": {"drop_count": 4},
        "func_localization": {"enabled": True, "method": "deepseg", "task": "sc_epi"},
        "crop": {"mask_diameter_mm": 40},
    }

    # S3.1
    s3_1 = _process_s3_1_dummy_drop_and_localization(test_bold_path, work_dir, policy)
    if should_exit_after_subtask("S3.1"): return StepResult("PASS", None)

    # S3.2
    s3_2 = _process_s3_2_outlier_gating(s3_1["func_bold_coarse_path"], s3_1["func_ref0_path"], s3_1["discovery_seg_crop_path"], work_dir, policy)
    if should_exit_after_subtask("S3.2"): return StepResult("PASS", None)

    if s3_2["outlier_status"] == "FAIL":
        return StepResult("FAIL", s3_2.get("failure_message"))

    # S3.3
    s3_3 = _process_s3_3_crop_and_qc(
        bold_data_path=s3_1["func_bold_coarse_path"],
        cordmask_func_path=s3_1["discovery_seg_crop_path"],
        functional_ref_path=s3_2["func_ref_path"],
        func_ref_fast_path=s3_1["func_ref_fast_path"],
        discovery_seg_path=s3_1["discovery_seg_path"],
        work_dir=work_dir,
        policy=policy
    )

    if out:
        from spineprep.qc_dashboard import generate_dashboard_safe
        generate_dashboard_safe(Path(out))

    return StepResult("PASS", None)
