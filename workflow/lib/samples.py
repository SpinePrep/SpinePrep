from __future__ import annotations

import csv
import json
from pathlib import Path


def build_samples(discover_json: str, bids_root: str, out_tsv: str) -> int:
    """
    Create a normalized per-run manifest for the workflow.
    Columns:
      sub, ses, run, task, bold_path, mppca_path, motion_path, confounds_tsv, confounds_json
    Returns number of rows written.
    """
    dj = json.loads(Path(discover_json).read_text())
    rows = []
    for subj in dj.get("subjects", []):
        sub = subj["id"]
        for sess in subj.get("sessions", []):
            ses = sess["id"]  # may be None
            for run in sess.get("runs", []):
                # Construct base BIDS bold path candidates
                func_dir = (
                    Path(bids_root) / sub / ("ses-" + ses if ses else "") / "func"
                )
                # normalize func_dir removing trailing "/" if ses is None
                func_dir = Path(str(func_dir).replace("//", "/"))
                # We don't know the task label here; discover() omitted it. Try both patterns:
                # Prefer task-agnostic (no task) then fallback to common "task-motor".
                base_no_task = f"{sub}"
                if ses:
                    base_no_task += f"_ses-{ses}"
                base_no_task += f"_run-{run}_bold"

                base_task_motor = f"{sub}"
                if ses:
                    base_task_motor += f"_ses-{ses}"
                base_task_motor += f"_task-motor_run-{run}_bold"

                cand1 = func_dir / f"{base_no_task}.nii.gz"
                cand2 = func_dir / f"{base_task_motor}.nii.gz"
                if cand1.exists():
                    bold = cand1
                    task = ""
                elif cand2.exists():
                    bold = cand2
                    task = "motor"
                else:
                    # best-effort wildcard search for *_run-XX_bold.nii.gz
                    hits = sorted(func_dir.glob(f"*run-{run}_bold.nii.gz"))
                    if not hits:
                        # skip if bold not present
                        continue
                    bold = hits[0]
                    # derive task from filename if present
                    # e.g., sub-01_task-rest_run-01_bold.nii.gz
                    name = bold.name
                    task = ""
                    for part in name.split("_"):
                        if part.startswith("task-"):
                            task = part.split("-", 1)[1]
                            break

                # derive derived filenames next to bold (current simple convention)
                base = bold.name[:-7] if bold.name.endswith(".nii.gz") else bold.stem
                base_no_bold = base[:-5] if base.endswith("_bold") else base
                mppca = bold.parent / f"{base_no_bold}_desc-mppca_bold.nii.gz"
                motion = bold.parent / f"{base_no_bold}_desc-motioncorr_bold.nii.gz"
                conf_tsv = bold.parent / f"{base_no_bold}_desc-confounds_timeseries.tsv"
                conf_json = (
                    bold.parent / f"{base_no_bold}_desc-confounds_timeseries.json"
                )

                rows.append(
                    {
                        "sub": sub,
                        "ses": ses or "",
                        "run": run,
                        "task": task,
                        "bold_path": str(bold.resolve()),
                        "mppca_path": str(mppca.resolve()),
                        "motion_path": str(motion.resolve()),
                        "confounds_tsv": str(conf_tsv.resolve()),
                        "confounds_json": str(conf_json.resolve()),
                    }
                )

    Path(out_tsv).parent.mkdir(parents=True, exist_ok=True)
    with open(out_tsv, "w", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "sub",
                "ses",
                "run",
                "task",
                "bold_path",
                "mppca_path",
                "motion_path",
                "confounds_tsv",
                "confounds_json",
            ],
            delimiter="\t",
        )
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return len(rows)
