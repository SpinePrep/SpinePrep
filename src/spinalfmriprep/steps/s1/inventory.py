"""BIDS inventory building, file discovery, and run classification."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List, Optional


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
        entry: dict[str, Any] = {
            "path": str(rel),
            "subject": subject,
            "session": session,
            "modality": modality,
            "classification": classification,
        }
        # Pull acquisition timing/distortion metadata from BIDS sidecars so
        # downstream steps don't have to re-parse BIDS. Applies to both
        # functional BOLD (for STC / motion / S5 SyN fallback eligibility) and
        # fmap volumes (S5 topup/fugue input). HEADER.md "Slice-timing
        # correction (deliberately skipped in v1)" + S5 spec rely on this.
        if (
            (modality == "func" and classification == "cord_likely")
            or modality == "fmap"
        ):
            meta = _read_bold_sidecar(bids_root, path)
            if meta:
                entry["acquisition"] = meta
        runs.append(entry)
    files.sort(key=lambda x: (x["subject"] or "", x["session"] or "", x["path"]))
    runs.sort(key=lambda x: (x["subject"] or "", x["session"] or "", x["path"]))
    return {"dataset_key": dataset_key, "bids_root": str(bids_root), "files": files, "runs": runs}


def _read_bold_sidecar(bids_root: Path, bold_path: Path) -> dict[str, Any]:
    """Return BIDS acquisition fields relevant to fMRI preprocessing.

    Walks BIDS inheritance: checks the same-directory sidecar first, then
    each parent directory up to bids_root for a sidecar whose stem matches
    the BOLD filename's task/run entities. Only extracts a small allowlist
    of fields so the inventory file stays small.
    """
    wanted = {
        "RepetitionTime",
        "SliceTiming",
        "SliceEncodingDirection",
        "PhaseEncodingDirection",
        "EffectiveEchoSpacing",
        "TotalReadoutTime",            # primary input for FSL topup acqparams
        "ParallelReductionFactorInPlane",
        "PartialFourier",
        "EchoTime",
        "MultibandAccelerationFactor",
        "AcquisitionMatrixPE",
        "ReconMatrixPE",
    }
    merged: dict[str, Any] = {}
    # Build the BIDS stem and its progressively-stripped variants. At deeper
    # ancestor levels, sub-/ses- entities are dropped (a dataset-root sidecar
    # named "task-rest_bold.json" applies to all sub-XX_task-rest_bold runs).
    stem = bold_path.name
    for suffix in (".nii.gz", ".nii"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    stem_no_ses = "_".join(p for p in stem.split("_") if not p.startswith("ses-"))
    stem_no_sub = "_".join(p for p in stem_no_ses.split("_") if not p.startswith("sub-"))

    # Walk from bold_path.parent up to bids_root. At each level try the most
    # specific stem first, then stripped variants. Apply in root-down order
    # so deeper levels override.
    levels: list[Path] = []
    cur = bold_path.parent
    while True:
        levels.append(cur)
        if cur == bids_root:
            break
        cur = cur.parent
        if not str(cur).startswith(str(bids_root)):
            break

    for level in reversed(levels):
        for candidate_stem in (stem_no_sub, stem_no_ses, stem):
            cand = level / f"{candidate_stem}.json"
            if not cand.exists():
                continue
            try:
                data = json.loads(cand.read_text(encoding="utf-8"))
            except Exception:
                continue
            for k in wanted:
                if k in data:
                    merged[k] = data[k]
    return merged


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
