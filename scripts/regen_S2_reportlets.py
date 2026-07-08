#!/usr/bin/env python3
"""Regenerate S2 reportlets WITHOUT re-running the S2 pipeline.

Renders the crop_box_sagittal for each (dataset, subject, session) tuple
from on-disk artifacts. Source priority per dataset:

  1. Per-dataset work dir at
     `work/S2_anat_cordref/<dataset_key>/<run_id>/` (new keyed layout).
  2. Shared work dir at `work/S2_anat_cordref/<run_id>/` (legacy; whichever
     S2 run wrote last wins, so the modality reflected may not be this
     dataset's).
  3. Derivative anat at `derivatives/spineprep/<dataset_key>/sub-XX/.../anat/`
     (modality-correct per dataset, but no discovery seg / crop box overlay).

This is a dev-loop tool. Each dataset is rendered separately so 3
datasets sharing sub-02 (e.g. internal_balgrist, ds005883_pain,
ds005884_motor) no longer get the same image.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from spineprep.steps.s2.io import (
    _copy_file,
    _derivatives_figures_dir,
    _format_reportlet_name,
)
from spineprep.steps.s2.reportlets_montage import _render_crop_box_sagittal

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _figures_dir_for(out_root: Path, subject: str, session: str | None,
                     dataset_key: str) -> Path:
    return _derivatives_figures_dir(out_root, subject, session, dataset_key)


def _datasets_for(out_root: Path) -> list[str]:
    logs = out_root / "logs" / "S2_anat_cordref"
    if not logs.exists():
        return []
    return sorted(d.name for d in logs.iterdir() if d.is_dir())


def _render_for_dataset(
    out_root: Path, dataset_key: str, subject: str, session: str | None,
    work_root: Path, run_id: str, bids_root: Path | None, source_rel: str | None,
) -> bool:
    figures_dir = _figures_dir_for(out_root, subject, session, dataset_key)
    figures_dir.mkdir(parents=True, exist_ok=True)
    dest = figures_dir / _format_reportlet_name(
        subject, session, "S2_crop_box_sagittal"
    )

    # 1. Per-dataset keyed work dir (preferred when S2 has been re-run with
    #    the dataset_key-keyed work dir patch). Gives full QC content.
    src = work_root / dataset_key / run_id
    cordref_std = src / "cordref_std.nii.gz"
    if cordref_std.exists():
        sag_qc = src / "qc" / "crop_box_sagittal"
        sag_qc.mkdir(parents=True, exist_ok=True)
        sag_png = _render_crop_box_sagittal(
            qc_root=sag_qc,
            cordref_std_path=cordref_std,
            cordref_crop_path=(src / "cordref_crop.nii.gz"
                               if (src / "cordref_crop.nii.gz").exists() else None),
            discovery_seg_path=(src / "cordmask_discovery.nii.gz"
                                if (src / "cordmask_discovery.nii.gz").exists() else None),
            crop_mask_path=(src / "crop_mask.nii.gz"
                            if (src / "crop_mask.nii.gz").exists() else None),
        )
        if sag_png and sag_png.exists():
            _copy_file(sag_png, dest)
            print(f"  {dataset_key}/{run_id} <- work/{dataset_key}/{run_id}/")
            return True

    # 2. BIDS source anat — the raw selected file from the dataset's BIDS
    #    tree. Guarantees per-dataset uniqueness (3 datasets sharing
    #    sub-02 still have 3 different acquisitions in BIDS). No overlay.
    if bids_root and source_rel:
        src_anat = bids_root / source_rel
        if src_anat.exists():
            sag_qc = work_root / dataset_key / run_id / "qc" / "crop_box_sagittal"
            sag_qc.mkdir(parents=True, exist_ok=True)
            sag_png = _render_crop_box_sagittal(
                qc_root=sag_qc,
                cordref_std_path=src_anat,
                cordref_crop_path=None,
                discovery_seg_path=None,
                crop_mask_path=None,
            )
            if sag_png and sag_png.exists():
                _copy_file(sag_png, dest)
                print(f"  {dataset_key}/{run_id} <- BIDS source ({src_anat.name})")
                return True

    # 3. Last-resort: per-dataset derivative cordref (may be cross-dataset
    #    duplicated due to legacy shared-work-dir bug).
    for anat_dir in (
        out_root / "derivatives" / "spineprep" / dataset_key
            / f"sub-{subject}" / (f"ses-{session}" if session else "") / "anat",
        out_root / "derivatives" / "spineprep"
            / f"sub-{subject}" / (f"ses-{session}" if session else "") / "anat",
    ):
        if not anat_dir.exists():
            continue
        cordref_hits = sorted(anat_dir.glob("*_desc-cordref_*.nii.gz"))
        dseg_hits = sorted(anat_dir.glob("*_desc-cord_dseg_*.nii.gz"))
        if not cordref_hits:
            continue
        sag_qc = work_root / dataset_key / run_id / "qc" / "crop_box_sagittal"
        sag_qc.mkdir(parents=True, exist_ok=True)
        sag_png = _render_crop_box_sagittal(
            qc_root=sag_qc,
            cordref_std_path=cordref_hits[0],
            cordref_crop_path=None,
            discovery_seg_path=dseg_hits[0] if dseg_hits else None,
            crop_mask_path=None,
        )
        if sag_png and sag_png.exists():
            _copy_file(sag_png, dest)
            print(f"  {dataset_key}/{run_id} <- derivatives ({cordref_hits[0].name})")
            return True

    print(f"  {dataset_key}/{run_id}: NO RENDERABLE SOURCE")
    return False


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--all", action="store_true",
                   help="Reserved for future use (cordmask_montage etc.)")
    args = p.parse_args()

    out_root = (PROJECT_ROOT / "work" / "done" / "reg" / "S2").resolve()
    work_root = out_root / "work" / "S2_anat_cordref"
    if not work_root.exists():
        print(f"No S2 work dir: {work_root}", file=sys.stderr)
        return 1
    dataset_keys = _datasets_for(out_root)
    if not dataset_keys:
        print("No S2 dataset dirs on chain", file=sys.stderr)
        return 1

    # Iterate dataset x run, NOT run x dataset, so each dataset always gets
    # its own modality-correct image even with the legacy shared work-dir.
    total = 0
    for ds in dataset_keys:
        qc_path = out_root / "logs" / "S2_anat_cordref" / ds / "qc.json"
        if not qc_path.exists():
            continue
        try:
            qc = json.loads(qc_path.read_text())
        except Exception:
            continue
        bids_root = Path(qc.get("bids_root")) if qc.get("bids_root") else None
        for r in qc.get("runs", []):
            if r.get("status") != "PASS":
                continue
            subj_raw = r.get("subject") or ""
            subject = subj_raw[4:] if str(subj_raw).startswith("sub-") else subj_raw
            ses_raw = r.get("session")
            session = None
            if ses_raw:
                session = (str(ses_raw)[4:] if str(ses_raw).startswith("ses-")
                           else ses_raw)
            run_id = r.get("run_id") or (
                f"sub-{subject}_ses-" + (session or "none")
            )
            source_rel = r.get("source_path")
            if _render_for_dataset(
                out_root, ds, subject, session, work_root, run_id,
                bids_root, source_rel,
            ):
                total += 1

    print(f"\n=== {total} sagittal reportlets refreshed ===")

    # Refresh the dashboard HTML for every workfolder so the ?v=<mtime>
    # cachebusters update. Without this, the browser keeps showing the
    # previous PNGs because the URLs in HTML still embed the OLD mtime.
    from spineprep.qc_dashboard import generate_dashboard_safe
    work_root = PROJECT_ROOT / "work"
    refreshed_dashboards = 0
    for wf in sorted(work_root.glob("wf_*"), key=lambda p: p.stat().st_mtime,
                     reverse=True):
        if not (wf / "dashboard" / "index.html").exists():
            continue
        try:
            generate_dashboard_safe(wf)
            refreshed_dashboards += 1
            # Only refresh the latest few; older ones rarely matter.
            if refreshed_dashboards >= 6:
                break
        except Exception:
            pass
    print(f"=== {refreshed_dashboards} dashboards' HTML refreshed ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
