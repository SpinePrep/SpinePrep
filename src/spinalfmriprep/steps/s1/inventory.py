"""BIDS inventory building, file discovery, and run classification."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional


def _build_inventory(bids_root: Path, dataset_key: str, policy_entry) -> dict:
    files: List[dict] = []
    runs: List[dict] = []
    selection = policy_entry.selection if policy_entry is not None else None
    for path in sorted(bids_root.rglob("*")):
        if path.is_dir():
            continue
        if "derivatives" in path.parts:
            continue
        if not path.name:
            continue
        rel = path.relative_to(bids_root)
        subject, session = _parse_sub_ses(rel)
        if not _is_selected(subject, session, selection):
            continue
        files.append({"path": str(rel), "subject": subject, "session": session})
        modality, classification = _classify_path(rel)
        if modality is None:
            continue
        runs.append(
            {
                "path": str(rel),
                "subject": subject,
                "session": session,
                "modality": modality,
                "classification": classification,
            }
        )
    files.sort(key=lambda x: (x["subject"] or "", x["session"] or "", x["path"]))
    runs.sort(key=lambda x: (x["subject"] or "", x["session"] or "", x["path"]))
    return {"dataset_key": dataset_key, "bids_root": str(bids_root), "files": files, "runs": runs}


def _classify_path(rel_path: Path) -> tuple[Optional[str], Optional[str]]:
    path_str = rel_path.as_posix()
    name_lower = rel_path.name.lower()
    if "physio" in name_lower and (name_lower.endswith(".tsv") or name_lower.endswith(".tsv.gz")):
        return "physio", "non_cord_likely"
    if "/func/" in path_str:
        if "bold" in name_lower and (name_lower.endswith(".nii") or name_lower.endswith(".nii.gz")):
            return "func", "cord_likely"
        if name_lower.endswith(".nii") or name_lower.endswith(".nii.gz"):
            return "func", "unknown"
        return None, None
    if "/anat/" in path_str and ("t1w" in name_lower or "t2w" in name_lower) and (
        name_lower.endswith(".nii") or name_lower.endswith(".nii.gz")
    ):
        return "anat", "non_cord_likely"
    if "/fmap/" in path_str and (name_lower.endswith(".nii") or name_lower.endswith(".nii.gz")):
        return "fmap", "non_cord_likely"
    return None, None


def _parse_sub_ses(rel_path: Path) -> tuple[Optional[str], Optional[str]]:
    parts = rel_path.parts
    subject = None
    session = None
    if parts and parts[0].startswith("sub-"):
        subject = parts[0][4:]
    if len(parts) > 1 and parts[1].startswith("ses-"):
        session = parts[1][4:]
    return subject, session


def _is_selected(
    subject: Optional[str], session: Optional[str], selection
) -> bool:
    if selection is None or selection.mode != "subset":
        return True
    if subject is not None and selection.subjects:
        # Policy subject ids can be heterogeneous across datasets (e.g. "ZS001" vs "01"/"1").
        # Treat common normalized variants as equivalent for subset selection.
        allowed = {str(s) for s in selection.subjects}
        raw = str(subject)
        normalized = {
            raw,
            raw.lstrip("0") or "0",
            raw.zfill(2),
            f"ZS{raw.zfill(3)}",
        }
        if not (normalized & allowed):
            return False
    if session is not None and selection.sessions:
        if session not in selection.sessions:
            return False
    return True
