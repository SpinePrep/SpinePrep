from __future__ import annotations

import csv
import json
from pathlib import Path


def assign_motion_groups(
    rows: list[dict], mode: str, require_same: list[str]
) -> list[dict]:
    """
    Assign motion_group keys to rows based on grouping mode and requirements.

    Args:
        rows: List of sample rows
        mode: Grouping mode (none, subject, session, session+task)
        require_same: List of fields that must be identical within a group

    Returns:
        Updated rows with motion_group field

    Raises:
        ValueError: If grouping requirements are violated
    """
    if mode == "none":
        for row in rows:
            row["motion_group"] = f"per-run-{row['sub']}-{row['run']}"
        return rows

    # Group rows by the specified mode
    groups = {}
    for row in rows:
        if mode == "subject":
            group_key = row["sub"]
        elif mode == "session":
            group_key = f"{row['sub']}_ses-{row['ses']}" if row["ses"] else row["sub"]
        elif mode == "session+task":
            group_key = (
                f"{row['sub']}_ses-{row['ses']}_task-{row['task']}"
                if row["ses"]
                else f"{row['sub']}_task-{row['task']}"
            )
        else:
            raise ValueError(f"Unknown grouping mode: {mode}")

        if group_key not in groups:
            groups[group_key] = []
        groups[group_key].append(row)

    # Check requirements within each group
    for group_key, group_rows in groups.items():
        if len(group_rows) < 2:
            # Single run groups don't need checking
            for row in group_rows:
                row["motion_group"] = f"per-run-{row['sub']}-{row['run']}"
            continue

        # Check that all required fields are the same within the group
        for field in require_same:
            if field not in group_rows[0]:
                continue  # Skip missing fields
            values = [row.get(field) for row in group_rows]
            if len(set(values)) > 1:
                raise ValueError(
                    f"Grouping requirement violated: field '{field}' has different values "
                    f"within group '{group_key}': {set(values)}. "
                    f"Consider setting options.motion.concat.mode='none' or adjusting require_same."
                )

        # Assign group key to all rows in this group
        for row in group_rows:
            row["motion_group"] = group_key

    return rows


def build_samples(discover_json: str, bids_root: str, out_tsv: str) -> int:
    """
    Create a normalized per-run manifest for the workflow.
    Columns:
      sub, ses, run, task, bold_path, mppca_path, motion_path, motion_params_tsv, motion_params_json, confounds_tsv, confounds_json, motion_group
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

                # derive derived filenames next to bold (match actual wrapper output patterns)
                base = bold.name[:-7] if bold.name.endswith(".nii.gz") else bold.stem
                base_no_bold = base[:-5] if base.endswith("_bold") else base
                mppca = bold.parent / f"{base_no_bold}_mppca_bold.nii.gz"
                motion = bold.parent / f"{base_no_bold}_desc-motioncorr_bold.nii.gz"
                motion_params_tsv = (
                    bold.parent / f"{base_no_bold}_desc-motion_params.tsv"
                )
                motion_params_json = (
                    bold.parent / f"{base_no_bold}_desc-motion_params.json"
                )
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
                        "motion_params_tsv": str(motion_params_tsv.resolve()),
                        "motion_params_json": str(motion_params_json.resolve()),
                        "confounds_tsv": str(conf_tsv.resolve()),
                        "confounds_json": str(conf_json.resolve()),
                        "motion_group": "",  # Will be assigned later
                        "crop_from": 0,  # Will be updated by crop detection
                        "crop_to": 0,  # Will be updated by crop detection
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
                "motion_params_tsv",
                "motion_params_json",
                "confounds_tsv",
                "confounds_json",
                "motion_group",
                "crop_from",
                "crop_to",
            ],
            delimiter="\t",
        )
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return len(rows)


def first_row(samples_tsv: str) -> dict:
    """Return the first non-header row as a dict. Raises FileNotFoundError or ValueError."""
    p = Path(samples_tsv)
    if not p.exists():
        raise FileNotFoundError(samples_tsv)
    import csv

    with p.open("r", newline="") as f:
        r = csv.DictReader(f, delimiter="\t")
        for row in r:
            return row
    raise ValueError("samples.tsv has no rows")


def rows(samples_tsv: str) -> list[dict]:
    p = Path(samples_tsv)
    if not p.exists():
        raise FileNotFoundError(samples_tsv)
    out = []
    import csv

    with p.open("r", newline="") as f:
        r = csv.DictReader(f, delimiter="\t")
        for row in r:
            out.append(row)
    return out


def row_by_id(samples_tsv: str, idx: int) -> dict:
    rs = rows(samples_tsv)
    if idx < 0 or idx >= len(rs):
        raise IndexError(f"row index out of range: {idx}")
    return rs[idx]
