"""S2 reportlet orchestration — dispatches to the unified matplotlib
renderer in `reportlets_unified.py`. Each per-run reportlet is one PNG:
crop_box_sagittal, cordmask_montage, totalspineseg_montage,
rootlets_montage, pam50_reg_overlay.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from .io import _abs_path, _derivatives_figures_dir, _format_reportlet_name
from .reportlets_unified import (
    render_cordmask_montage,
    render_crop_box_sagittal,
    render_pam50_reg_overlay,
    render_rootlets_montage,
    render_totalspineseg_montage,
    _warp_pam50_cord_to_anat,
)


def _render_reportlets_for_runs(runs: list[dict], out_root: Path,
                                  dataset_key: str) -> list[dict]:
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


def _render_reportlets(run: dict, out_root: Path,
                       dataset_key: str) -> tuple[dict, Optional[str]]:
    subject = run.get("subject") or "?"
    session = run.get("session")
    run_dataset_key = run.get("dataset_key", dataset_key)
    status = run.get("status", "UNKNOWN")
    metrics = run.get("metrics") or {}

    figures_dir = _derivatives_figures_dir(out_root, subject, session,
                                            run_dataset_key)
    figures_dir.mkdir(parents=True, exist_ok=True)

    cordref_path = _abs_path(out_root, run.get("cordref_path"))
    cordmask_path = _abs_path(out_root, run.get("cordmask_path"))
    canal_path = _abs_path(out_root, run.get("canal_path"))
    vertebral_labels_path = _abs_path(out_root, run.get("vertebral_labels_path"))
    disc_labels_path = _abs_path(out_root, run.get("disc_labels_path"))
    rootlets_path = _abs_path(out_root, run.get("rootlets_path"))
    tss_output_path = _abs_path(out_root, run.get("tss_output_path"))

    reg = run.get("registration") or {}
    selected_variant = reg.get("selected", "disc")
    sel_reg = reg.get(selected_variant) or {}
    warp_template2anat = sel_reg.get("warp_template2anat")
    warp_template2anat = Path(warp_template2anat) if warp_template2anat else None

    # Locate the S2 work dir for this run (carries cordref_std + discovery
    # seg + crop_mask used by the crop_box reportlet).
    run_id = run.get("run_id", "unknown")
    keyed = out_root / "work" / "S2_anat_cordref" / run_dataset_key / run_id
    unkeyed = out_root / "work" / "S2_anat_cordref" / run_id
    work_dir = keyed if (keyed / "cordref_std.nii.gz").exists() else unkeyed
    cordref_std_path = work_dir / "cordref_std.nii.gz"
    discovery_seg_path = work_dir / "cordmask_discovery.nii.gz"
    crop_mask_path_local = work_dir / "crop_mask.nii.gz"

    reportlets: dict[str, Optional[str]] = {}

    def _out(key: str) -> Path:
        return figures_dir / _format_reportlet_name(subject, session, key)

    def _rel(p: Path) -> str:
        try:
            return str(p.relative_to(out_root))
        except ValueError:
            return str(p)

    # S2.1 — Discovery + Crop
    p = _out("S2_crop_box_sagittal")
    render_crop_box_sagittal(
        output_path=p,
        cordref_std_path=cordref_std_path if cordref_std_path.exists() else None,
        discovery_seg_path=discovery_seg_path if discovery_seg_path.exists() else None,
        crop_mask_path=crop_mask_path_local if crop_mask_path_local.exists() else None,
        subject=subject, dataset_key=run_dataset_key, status=status,
    )
    reportlets["crop_box_sagittal"] = _rel(p) if p.exists() else None

    # S2.2a — Cord seg
    p = _out("S2_cordmask_montage")
    render_cordmask_montage(
        output_path=p,
        cordref_path=cordref_path or cordref_std_path,
        cordmask_path=cordmask_path,
        subject=subject, dataset_key=run_dataset_key, status=status,
        metrics=metrics,
    )
    reportlets["cordmask_montage"] = _rel(p) if p.exists() else None

    # S2.2b — TotalSpineSeg
    tss_info = run.get("tss") or run.get("labels") or {}
    if tss_info.get("status", "PASS") == "PASS":
        p = _out("S2_totalspineseg_montage")
        render_totalspineseg_montage(
            output_path=p,
            cordref_path=cordref_path or cordref_std_path,
            cordmask_path=cordmask_path,
            tss_output_path=tss_output_path,
            canal_path=canal_path,
            vertebral_labels_path=vertebral_labels_path,
            disc_labels_path=disc_labels_path,
            subject=subject, dataset_key=run_dataset_key, status=status,
            metrics=metrics,
        )
        reportlets["totalspineseg_montage"] = _rel(p) if p.exists() else None
    else:
        reportlets["totalspineseg_montage"] = None

    # S2.3 — Rootlets
    rootlets_info = run.get("rootlets") or {}
    if rootlets_info.get("status") == "PASS" and rootlets_path:
        p = _out("S2_rootlets_montage")
        render_rootlets_montage(
            output_path=p,
            cordref_path=cordref_path or cordref_std_path,
            cordmask_path=cordmask_path,
            rootlets_path=rootlets_path,
            subject=subject, dataset_key=run_dataset_key, status=status,
            metrics=metrics,
        )
        reportlets["rootlets_montage"] = _rel(p) if p.exists() else None
    else:
        reportlets["rootlets_montage"] = None

    # S2.4 — PAM50 reg overlay
    pam50_in_anat = None
    if warp_template2anat and warp_template2anat.exists() and cordref_path:
        pam50_in_anat = _warp_pam50_cord_to_anat(
            warp_template2anat, cordref_path, work_dir / "pam50_overlay",
        )
    p = _out("S2_pam50_reg_overlay")
    render_pam50_reg_overlay(
        output_path=p,
        cordref_path=cordref_path or cordref_std_path,
        cordmask_path=cordmask_path,
        pam50_cord_in_anat_path=pam50_in_anat,
        subject=subject, dataset_key=run_dataset_key, status=status,
        metrics=metrics,
    )
    reportlets["pam50_reg_overlay"] = _rel(p) if p.exists() else None

    required = ["cordmask_montage", "totalspineseg_montage",
                "pam50_reg_overlay"]
    if rootlets_info.get("status") == "PASS":
        required.append("rootlets_montage")
    missing = [k for k in required if not reportlets.get(k)]
    if missing:
        return reportlets, f"Reportlet generation failed: {', '.join(missing)}"
    return reportlets, None
