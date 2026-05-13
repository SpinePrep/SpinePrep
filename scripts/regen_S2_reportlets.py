#!/usr/bin/env python3
"""Regenerate S2 reportlets WITHOUT re-running the S2 pipeline.

Iterate every per-subject work dir on the chain
(work/done/reg/S2/work/S2_anat_cordref/<run_id>/), call the renderers
directly against the on-disk artifacts, and write the figures to the
matching `derivatives/.../figures/` location.

Bypasses qc.json — that file can be stale or inconsistent across
chained workfolders. The work-dir layout is the source of truth.

This is a dev-loop tool for iterating on figure-rendering code; it
does NOT regenerate qc.json or update status fields.

Run only on `crop_box_sagittal` by default; pass `--all` to attempt
the cordmask_montage, totalspineseg_montage, pam50_reg_overlay, and
rootlets_montage too (those have heavier dependencies and may skip).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from spinalfmriprep.steps.s2.io import (
    _copy_file,
    _derivatives_figures_dir,
    _format_reportlet_name,
)
from spinalfmriprep.steps.s2.reportlets_montage import (
    _render_crop_box_sagittal,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _parse_run_id(run_id: str) -> tuple[str, str | None]:
    """Run dir name like `sub-02_ses-01` or `sub-02_ses-none` -> (subject, session_or_None)."""
    if "_ses-" not in run_id:
        return run_id.replace("sub-", ""), None
    sub_part, ses_part = run_id.split("_ses-", 1)
    sub = sub_part.replace("sub-", "")
    ses = None if ses_part == "none" else ses_part
    return sub, ses


def _figures_dir_for(out_root: Path, subject: str, session: str | None,
                     dataset_key: str) -> Path:
    """Mirror S2's _derivatives_figures_dir behavior, with dataset_key prefix."""
    return _derivatives_figures_dir(out_root, subject, session, dataset_key)


def _datasets_for(out_root: Path) -> list[str]:
    logs = out_root / "logs" / "S2_anat_cordref"
    if not logs.exists():
        return []
    return sorted(d.name for d in logs.iterdir() if d.is_dir())


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--all", action="store_true",
                   help="Also regenerate cordmask_montage and TotalSpineSeg")
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

    total = 0
    for run_dir in sorted(work_root.iterdir()):
        if not run_dir.is_dir():
            continue
        run_id = run_dir.name
        subject, session = _parse_run_id(run_id)
        # Determine dataset_key by checking which one has a matching log entry
        # for this run_id. Walk all dataset_key dirs and pick the one whose
        # qc.json mentions this subject/session, or fall back to any.
        # A single (subject, session) work dir is shared across multiple
        # datasets in our v1_validation (sub-02 appears in internal_balgrist,
        # ds005883_pain, ds005884_motor). Render once, copy to every
        # dataset's figures dir.
        my_dataset_keys: list[str] = []
        import json
        for ds in dataset_keys:
            qc_path = out_root / "logs" / "S2_anat_cordref" / ds / "qc.json"
            if not qc_path.exists():
                continue
            try:
                qc = json.loads(qc_path.read_text())
            except Exception:
                continue
            for r in qc.get("runs", []):
                if (r.get("subject") == subject
                        and (r.get("session") or None) == session):
                    my_dataset_keys.append(ds)
                    break
        if not my_dataset_keys:
            print(f"  {run_id}: no matching dataset; skipping")
            continue

        cordref_std = run_dir / "cordref_std.nii.gz"
        cordref_crop = run_dir / "cordref_crop.nii.gz"
        discovery_seg = run_dir / "cordmask_discovery.nii.gz"
        crop_mask = run_dir / "crop_mask.nii.gz"
        if not cordref_std.exists():
            print(f"  {run_id}: missing cordref_std; skipping")
            continue

        # crop_box_sagittal — render once into work-dir QC, then copy out
        # to every matching dataset's figures dir.
        sag_qc = run_dir / "qc" / "crop_box_sagittal"
        sag_qc.mkdir(parents=True, exist_ok=True)
        sag_png = _render_crop_box_sagittal(
            qc_root=sag_qc,
            cordref_std_path=cordref_std,
            cordref_crop_path=cordref_crop if cordref_crop.exists() else None,
            discovery_seg_path=discovery_seg if discovery_seg.exists() else None,
            crop_mask_path=crop_mask if crop_mask.exists() else None,
        )
        if not (sag_png and sag_png.exists()):
            print(f"  {run_id}: render returned None")
            continue
        for ds in my_dataset_keys:
            figures_dir = _figures_dir_for(out_root, subject, session, ds)
            figures_dir.mkdir(parents=True, exist_ok=True)
            dest = figures_dir / _format_reportlet_name(
                subject, session, "S2_crop_box_sagittal"
            )
            _copy_file(sag_png, dest)
            total += 1
            print(f"  {run_id} -> {ds}/{dest.name}")

    print(f"\n=== {total} sagittal reportlets refreshed ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
