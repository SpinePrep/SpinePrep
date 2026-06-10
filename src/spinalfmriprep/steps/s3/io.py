"""JSON/JSONL helpers, path utilities, and S2 output finders for S3."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Subject / session extraction from work_dir path
# ---------------------------------------------------------------------------


def _extract_subject_session_from_work_dir(work_dir: Path) -> tuple[Optional[str], Optional[str], Optional[Path]]:
    """
    Extract subject, session, and out_root from work_dir path structure.

    Handles two path formats:
    1. {out_root}/runs/S3_func_init_and_crop/{run_id}/... where run_id = sub-{subject}_ses-{session}
    2. {out_root}/runs/S3_func_init_and_crop/sub-{subject}/ses-{session}/... (test case format)

    Args:
        work_dir: Work directory path

    Returns:
        Tuple of (subject, session, out_root) or (None, None, None) if cannot parse
    """
    try:
        current = work_dir.resolve()
        while current.parent != current:  # Not at root
            name = current.name

            # Check if directory name looks like a BIDS entity string (has sub- at least)
            if "sub-" in name:
                parts = name.split("_")

                # Extract subject
                subj_part = next((p for p in parts if p.startswith("sub-")), None)
                if not subj_part:
                    current = current.parent
                    continue

                subject = subj_part.replace("sub-", "")

                # Extract session
                sess_part = next((p for p in parts if p.startswith("ses-")), None)
                if sess_part:
                    session = sess_part.replace("ses-", "")
                    if session == "none":
                        session = None
                else:
                    # No ses- tag in directory name - session is None
                    session = None

                # Locate out_root
                # Structure: {out_root}/runs/S3_func_init_and_crop/{run_id}
                # Check if we are at {run_id} level
                if current.parent.name == "S3_func_init_and_crop" and current.parent.parent.name == "runs":
                     # out_root is parent of runs
                     out_root = current.parent.parent.parent
                     return subject, session, out_root

                # Structure: {out_root}/work/runs/S3... (test harness sometimes?)
                # Structure test case: .../sub-XX/ses-YY/...
                # If we found subject/session from folder name, and we are traversing up:

            # Handle standard split directory case: sub-XX/ses-YY
            if name.startswith("ses-"):
                 session_str = name.replace("ses-", "")
                 if session_str and session_str != "none":
                      session = session_str
                 else:
                      session = None

            current = current.parent

        return None, None, None
    except Exception:  # noqa: BLE001
        return None, None, None


# ---------------------------------------------------------------------------
# S2 output finders
# ---------------------------------------------------------------------------


def _s2_work_search_dirs(
    out_root: Path, run_id: str, dataset_key: Optional[str],
) -> list[Path]:
    """Candidate S2 work dirs holding `S2_anat_cordref/.../<run_id>/` outputs.

    S2 writes per-(dataset_key, run_id) — and multiple datasets can share the
    same run_id (e.g. sub-02 in balgrist AND cospine), so the flat run_id path
    is ambiguous and may miss. We search, in order:
      1. the linked S2 root, dataset-keyed     (current S2 layout)
      2. the linked S2 root, flat              (legacy / single-dataset)
      3. the PROMOTED S2 (work/done/<scope>/S2), dataset-keyed
      4. the promoted S2, flat
    (3)/(4) are the robust fallback when the chain's linked work tree diverges
    from the promoted S2 tree (independent re-promotions).
    """
    dirs: list[Path] = []
    base = out_root / "work" / "S2_anat_cordref"
    if dataset_key:
        dirs.append(base / dataset_key / run_id)
    dirs.append(base / run_id)
    # Promoted S2 fallback: derive scope from the wf folder name (wf_<scope>_NNN).
    name = out_root.name
    if name.startswith("wf_") and "_" in name[3:]:
        scope = name[3:].rsplit("_", 1)[0]
        promoted = out_root.parent / "done" / scope / "S2" / "work" / "S2_anat_cordref"
        if dataset_key:
            dirs.append(promoted / dataset_key / run_id)
        dirs.append(promoted / run_id)
    return dirs


def _find_s2_cordref_std(
    out_root: Path,
    subject: str,
    session: Optional[str],
    dataset_key: Optional[str] = None,
) -> Optional[Path]:
    """Locate S2.1 cordref_std.nii.gz, dataset-aware (see _s2_work_search_dirs).

    Args:
        out_root: Base output directory (the chain's S2 lookup root).
        subject: Subject ID (without 'sub-' prefix).
        session: Session ID (without 'ses-' prefix) or None.
        dataset_key: SpinalfMRIprep dataset key (disambiguates shared run_ids).

    Returns:
        Path to cordref_std.nii.gz or None if not found.
    """
    run_id = f"sub-{subject}_ses-{session}" if session else f"sub-{subject}_ses-none"
    for d in _s2_work_search_dirs(out_root, run_id, dataset_key):
        p = d / "cordref_std.nii.gz"
        try:
            if p.exists() and p.stat().st_size > 0:
                return p
        except OSError:
            continue
    return None


def _find_s2_cordmask_dseg(
    out_root: Path,
    subject: str,
    session: Optional[str],
) -> Optional[Path]:
    """
    Locate S2 anat cordmask definition (dseg).

    Looks in: derivatives/spinalfmriprep/sub-{subject}/[ses-{session}]/anat/
              *_desc-cordmask_dseg.nii.gz

    Args:
        out_root: Base output directory
        subject: Subject ID
        session: Session ID or None

    Returns:
        Path to cordmask_dseg.nii.gz or None
    """
    anat_dir = out_root / "derivatives" / "spinalfmriprep" / f"sub-{subject}"
    if session:
        anat_dir = anat_dir / f"ses-{session}" / "anat"
    else:
        anat_dir = anat_dir / "anat"

    if not anat_dir.exists():
        return None

    # Look for any file ending in _desc-cord_dseg*.nii.gz (matches S2 output naming)
    # S2 outputs: *_desc-cord_dseg_T1w.nii.gz or *_desc-cord_dseg_T2w.nii.gz
    candidates = list(anat_dir.glob("*_desc-cord_dseg*.nii.gz"))
    if not candidates:
        # Fallback: try legacy pattern
        candidates = list(anat_dir.glob("*_desc-cordmask_dseg.nii.gz"))
    if not candidates:
        return None

    # Prefer T2w if available, else take first
    for c in candidates:
        if "T2w" in c.name:
            return c

    return candidates[0]


# ---------------------------------------------------------------------------
# Functional candidate collection
# ---------------------------------------------------------------------------


def _collect_func_candidates(inventory: dict) -> dict[tuple[str, Optional[str]], list[dict]]:
    candidates: dict[tuple[str, Optional[str]], list[dict]] = {}
    for entry in inventory.get("files", []):
        path = entry.get("path")
        if not path or not isinstance(path, str):
            continue
        # Check if functional: contains /func/ and ends with _bold.nii[.gz]
        if "/func/" not in path:
            continue
        if not (path.endswith("_bold.nii") or path.endswith("_bold.nii.gz")):
            continue

        subject = entry.get("subject")
        session = entry.get("session")
        if not subject:
            continue

        key = (subject, session)
        candidates.setdefault(key, []).append(entry)
    return candidates


# ---------------------------------------------------------------------------
# JSONL / summary writers
# ---------------------------------------------------------------------------


def _write_s3_runs_jsonl(path: Path, runs: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for run in runs:
            # Helper to make Path serializable
            def _serialize(obj):
                if isinstance(obj, Path):
                    return str(obj)
                return str(obj)
            f.write(json.dumps(run, default=_serialize) + "\n")


def _summarise_s3_runs(inventory: dict, policy: dict, runs: list[dict], out_path: Optional[Path] = None) -> dict:
    pass_count = sum(1 for r in runs if r.get("status") == "PASS")
    fail_count = len(runs) - pass_count
    status = "PASS" if fail_count == 0 and pass_count > 0 else "WARN" if pass_count > 0 else "FAIL"

    summary_runs = []

    for run in runs:
        # Extract reportlets
        reportlets = {}

        # Helper to safely get result from tuple list [("S3.1", res), ...]
        def get_res(code):
            for c, r in run.get("results", []):
                if c == code: return r
            return {}

        s3_1 = get_res("S3.1")
        s3_2 = get_res("S3.2")
        s3_3 = get_res("S3.3")

        # Map to dashboard keys
        # "frame_metrics" (S3.2)
        if s3_2.get("figure_path"):
             reportlets["frame_metrics"] = s3_2["figure_path"]

        # "crop_box_sagittal" (S3.3 or S3.1)
        # S3.3 has "figures" list
        # Let's prefer S3.3 crop box if available (final), else S3.1 (init)

        s3_3_figs = s3_3.get("figures", [])
        crop_box_fig = next((f for f in s3_3_figs if "crop_box" in str(f)), None)

        # S3.1 figure (always func_localization)
        if s3_1.get("figure_path"):
            reportlets["func_localization"] = s3_1["figure_path"]

        if crop_box_fig:
            reportlets["crop_box_sagittal"] = crop_box_fig

        # "funcref_montage" (S3.3)
        funcref_fig = next((f for f in s3_3_figs if "funcref_montage" in str(f)), None)
        if funcref_fig:
            reportlets["funcref_montage"] = funcref_fig

        # Relativize paths to out_path
        if out_path:
            rel_reportlets = {}
            for k, p in reportlets.items():
                try:
                    p_obj = Path(p)
                    # output root is parent of logs? calling code passes 'out' which is dataset root
                    rel_p = p_obj.relative_to(out_path)
                    rel_reportlets[k] = str(rel_p)
                except (ValueError, TypeError):
                    rel_reportlets[k] = str(p)
            reportlets = rel_reportlets
        else:
             # Just stringify
             reportlets = {k: str(v) for k, v in reportlets.items()}

        summary_run = {
            "subject": run.get("subject"),
            "session": run.get("session"),
            "run_id": run.get("run_id"),
            "status": run.get("status"),
            "failure_message": run.get("failure_message"),
            "reportlets": reportlets,
            "metrics": run.get("metrics") or {},
        }
        summary_runs.append(summary_run)

    return {
        "status": status,
        "dataset_key": inventory.get("dataset_key"),
        "bids_root": inventory.get("bids_root"),
        "counts": {
            "total": len(runs),
            "pass": pass_count,
            "fail": fail_count
        },
        "failure_message": f"{fail_count} runs failed" if fail_count > 0 else None,
        "runs": summary_runs
    }
