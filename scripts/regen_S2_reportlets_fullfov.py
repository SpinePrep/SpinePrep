#!/usr/bin/env python3
"""
Regenerate S2_anat_cordref reportlets in-place (no SCT rerun).

Specifically targets the sagittal underlay for:
- cordmask montage
- centerline montage

For each run with status=PASS, we re-render those reportlets and overwrite the existing
`derivatives/spinalfmriprep/.../figures/*_desc-S2_{cordmask,centerline}_montage.png` files.
"""

from __future__ import annotations

import json
from pathlib import Path


def main() -> int:
    # v1_validation scope requested by user
    dataset_keys = [
        "openneuro_ds005884_cospine_motor",
        "openneuro_ds005883_cospine_pain",
        "openneuro_ds004386_spinalcord_rest_testretest",
        "openneuro_ds004616_spinalcord_handgrasp_task",
        "internal_balgrist_motor_11",
    ]

    # Local import so this script stays lightweight.
    from spinalfmriprep.S2_anat_cordref import _render_reportlets  # noqa: PLC0415

    only = {"cordmask_montage", "centerline_montage"}
    failures = 0
    total = 0
    work_root = Path("work")

    for key in dataset_keys:
        # Search for dataset in wf_full_* directories (canonical naming)
        out_root = None
        qc_path = None
        
        # First try new canonical naming: wf_full_*/<key>
        for wf_dir in sorted(work_root.glob("wf_full_*"), reverse=True):
            candidate = wf_dir / key
            candidate_qc = candidate / "logs" / "S2_anat_cordref_qc.json"
            if candidate_qc.exists():
                out_root = candidate
                qc_path = candidate_qc
                break
        
        # Fallback to old naming for backward compatibility
        if out_root is None:
            old_path = work_root / "s2_acceptance" / key
            old_qc = old_path / "logs" / "S2_anat_cordref_qc.json"
            if old_qc.exists():
                out_root = old_path
                qc_path = old_qc
        
        if out_root is None or qc_path is None or not qc_path.exists():
            print(f"[SKIP] missing QC JSON for {key}")
            continue

        qc = json.loads(qc_path.read_text(encoding="utf-8"))
        bids_root = Path(qc.get("bids_root", ""))
        if not bids_root.exists():
            # Still allow regeneration (falls back to cordref underlay), but warn.
            print(f"[WARN] bids_root does not exist on disk: {bids_root}")
            bids_root = None  # type: ignore[assignment]

        runs = qc.get("runs", [])
        if not isinstance(runs, list):
            print(f"[SKIP] invalid runs list in: {qc_path}")
            continue

        for run in runs:
            if not isinstance(run, dict):
                continue
            if run.get("status") != "PASS":
                continue
            total += 1
            reportlets, err = _render_reportlets(
                run=run,
                out_root=out_root,
                dataset_key=qc.get("dataset_key", key),
                bids_root=bids_root,
                only_reportlets=only,
            )
            if err:
                failures += 1
                rid = run.get("run_id", "unknown")
                print(f"[FAIL] {key} {rid}: {err}")
            else:
                # Best-effort message for traceability
                rid = run.get("run_id", "unknown")
                cm = reportlets.get("cordmask_montage")
                cl = reportlets.get("centerline_montage")
                print(f"[OK] {key} {rid}: cordmask={cm} centerline={cl}")

    print(f"Done. PASS-runs processed: {total}. Failures: {failures}.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())






