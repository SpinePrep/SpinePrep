"""Reportlet orchestration: _render_reportlets_for_runs and _render_reportlets."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from .io import (
    _abs_path,
    _derivatives_figures_dir,
    _format_reportlet_name,
    _run_command,
)
from .reportlets_core import (
    _copy_reportlet,
    _write_not_available_panel,
    _find_qc_overlay,
    _find_qc_background,
    _compose_overlay,
)
from .reportlets_montage import (
    _render_crop_box_sagittal,
    _render_cordmask_montage,
)
from .reportlets_tss import (
    _render_totalspineseg_montage,
    _render_rootlets_montage,
)
from .reportlets_pam50 import (
    _render_pam50_reg_overlay_gif,
)


def _render_reportlets_for_runs(runs: list[dict], out_root: Path, dataset_key: str) -> list[dict]:
    updated = []
    for run in runs:
        if run.get("status") != "PASS":
            updated.append(run)
            continue
        reportlets, error = _render_reportlets(run, out_root, dataset_key)
        if error:
            run["status"] = "FAIL"
            run["failure_message"] = error
        run["reportlets"] = reportlets
        updated.append(run)
    return updated


def _render_reportlets(run: dict, out_root: Path, dataset_key: str) -> tuple[dict, Optional[str]]:
    subject = run.get("subject")
    session = run.get("session")
    # Use dataset_key from run record if present, otherwise use passed dataset_key
    run_dataset_key = run.get("dataset_key", dataset_key)
    figures_dir = _derivatives_figures_dir(out_root, subject, session, run_dataset_key)
    figures_dir.mkdir(parents=True, exist_ok=True)

    cordref_path = _abs_path(out_root, run.get("cordref_path"))
    cordmask_path = _abs_path(out_root, run.get("cordmask_path"))
    vertebral_labels_path = _abs_path(out_root, run.get("vertebral_labels_path"))
    disc_labels_path = _abs_path(out_root, run.get("disc_labels_path"))
    canal_path = _abs_path(out_root, run.get("canal_path"))
    tss_output_path = _abs_path(out_root, run.get("tss_output_path"))
    rootlets_path = _abs_path(out_root, run.get("rootlets_path"))
    reg_selected = run.get("registration", {}).get(run.get("registration", {}).get("selected", "disc"), {})
    template2anat = reg_selected.get("template2anat")
    if template2anat:
        template2anat = Path(template2anat)
    warp_template2anat = reg_selected.get("warp_template2anat")
    if warp_template2anat:
        warp_template2anat = Path(warp_template2anat)

    reportlets: dict[str, Optional[str]] = {}
    qc_root = out_root / "work" / "S2_anat_cordref" / run.get("run_id", "unknown") / "qc"
    work_dir = out_root / "work" / "S2_anat_cordref" / run.get("run_id", "unknown")

    # S2.1: Discovery + Crop sagittal figure
    cordref_std_path = work_dir / "cordref_std.nii.gz"
    cordref_crop_path = work_dir / "cordref_crop.nii.gz"
    discovery_seg_path = work_dir / "cordmask_discovery.nii.gz"
    crop_mask_path_local = work_dir / "crop_mask.nii.gz"
    crop_box_sagittal = _render_crop_box_sagittal(
        qc_root=qc_root / "crop_box_sagittal",
        cordref_std_path=cordref_std_path if cordref_std_path.exists() else None,
        cordref_crop_path=cordref_crop_path if cordref_crop_path.exists() else None,
        discovery_seg_path=discovery_seg_path if discovery_seg_path.exists() else None,
        crop_mask_path=crop_mask_path_local if crop_mask_path_local.exists() else None,
    )
    reportlets["crop_box_sagittal"] = _copy_reportlet(
        crop_box_sagittal,
        figures_dir / _format_reportlet_name(subject, session, "S2_crop_box_sagittal"),
        out_root,
    )

    cordmask_montage = _render_cordmask_montage(
        qc_root=qc_root / "cordmask_montage",
        image=cordref_path,
        cordmask=cordmask_path,
    )
    reportlets["cordmask_montage"] = _copy_reportlet(
        cordmask_montage,
        figures_dir / _format_reportlet_name(subject, session, "S2_cordmask_montage"),
        out_root,
    )

    # TotalSpineSeg comprehensive visualization (vertebrae + discs + cord + canal)
    tss_info = run.get("tss") or run.get("labels") or {}
    tss_status = tss_info.get("status", "PASS")
    if tss_status == "PASS" and tss_output_path is not None:
        tss_montage_png = _render_totalspineseg_montage(
            qc_root=qc_root / "totalspineseg_montage",
            image=cordref_path,
            tss_output_path=tss_output_path,
            cord_path=cordmask_path,  # Use the contrast-agnostic cord segmentation
            canal_path=canal_path,
        )
        reportlets["totalspineseg_montage"] = _copy_reportlet(
            tss_montage_png,
            figures_dir / _format_reportlet_name(subject, session, "S2_totalspineseg_montage"),
            out_root,
        )
    else:
        reportlets["totalspineseg_montage"] = _write_not_available_panel(
            figures_dir / _format_reportlet_name(subject, session, "S2_totalspineseg_montage"),
            out_root,
            "TotalSpineSeg not available",
        )

    reg_gif = None
    if template2anat and warp_template2anat:
        reg_gif = _render_pam50_reg_overlay_gif(
            qc_root=qc_root / "pam50_reg_overlay",
            subject_image=cordref_path,
            pam50_in_s2=template2anat,
            subject_cordmask=cordmask_path,
            warp_template2anat=warp_template2anat,
            subject_label=subject,
            session_label=session,
            vertebral_labels_path=vertebral_labels_path,
        )
    reportlets["pam50_reg_overlay"] = _copy_reportlet(
        reg_gif,
        figures_dir / _format_reportlet_name(subject, session, "S2_pam50_reg_overlay", ext="gif"),
        out_root,
    )

    rootlets_info = run.get("rootlets", {})
    if rootlets_info.get("status") == "PASS" and rootlets_path:
        rootlets_montage = _render_rootlets_montage(
            qc_root=qc_root / "rootlets_montage",
            image=cordref_path,
            rootlets=rootlets_path,
            vertebral_labels=vertebral_labels_path,
            cordmask=cordmask_path,
        )
        if rootlets_montage is not None:
            reportlets["rootlets_montage"] = _copy_reportlet(
                rootlets_montage,
                figures_dir / _format_reportlet_name(subject, session, "S2_rootlets_montage", ext="gif"),
                out_root,
            )
        else:
            reportlets["rootlets_montage"] = _write_not_available_panel(
                figures_dir / _format_reportlet_name(subject, session, "S2_rootlets_montage"),
                out_root,
                "Rootlets montage not available",
            )
    else:
        reportlets["rootlets_montage"] = _write_not_available_panel(
            figures_dir / _format_reportlet_name(subject, session, "S2_rootlets_montage"),
            out_root,
            "Rootlets not available",
        )

    required = [
        "cordmask_montage",
        "totalspineseg_montage",
        "pam50_reg_overlay",
    ]
    missing = [key for key in required if not reportlets.get(key)]
    if rootlets_info.get("status") == "PASS":
        if not reportlets.get("rootlets_montage"):
            missing.append("rootlets_montage")
    if missing:
        return reportlets, f"Reportlet generation failed: {', '.join(missing)}"
    return reportlets, None
