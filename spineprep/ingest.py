from __future__ import annotations

import csv
import hashlib
import os
from pathlib import Path
from typing import Dict, Iterable, Tuple

INDEX_EXT = {".nii", ".nii.gz", ".json", ".tsv", ".bval", ".bvec"}
SKIP_DIRS = {"derivatives", "code", "sourcedata", "tmp", ".git", ".datalad", ".venv"}


def _iter_files(root: Path) -> Iterable[Path]:
    for dp, dn, fn in os.walk(root):
        # prune skip dirs
        dn[:] = [d for d in dn if d not in SKIP_DIRS]
        for f in fn:
            p = Path(dp) / f
            if any(str(p).endswith(ext) for ext in INDEX_EXT):
                yield p


def _sha256(path: Path, max_bytes=None) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        if max_bytes is None:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        else:
            remaining = max_bytes
            while remaining > 0:
                chunk = f.read(min(1 << 20, remaining))
                if not chunk:
                    break
                h.update(chunk)
                remaining -= len(chunk)
    return h.hexdigest()


def _parse_bids_rel(rel: str) -> Tuple[str, str, str, str]:
    # naive parse: sub-, ses-, modality folder, suffix from filename
    parts = rel.split("/")
    sub = next((p for p in parts if p.startswith("sub-")), "")
    ses = next((p for p in parts if p.startswith("ses-")), "")
    # Find modality from known folder names
    modality = next(
        (p for p in parts if p in {"anat", "func", "fmap", "dwi", "beh"}), "unknown"
    )
    base = parts[-1]
    # suffix between last '_' and extension(s)
    name = base
    if "." in name:
        name = name.split(".")[0]
    suffix = name.split("_")[-1] if "_" in name else ""
    return sub, ses, modality, suffix


def ingest(bids_root: Path, out_dir: Path, hash_large: bool = False) -> Dict[str, int]:
    if not bids_root.exists():
        raise SystemExit(f"[ingest] ERROR: BIDS root not found: {bids_root}")
    files = list(_iter_files(bids_root))
    if not files or not any("sub-" in str(p) for p in files):
        raise SystemExit("[ingest] ERROR: No BIDS subject files found")

    out_dir.mkdir(parents=True, exist_ok=True)
    man = out_dir / "manifest.csv"
    func_n = anat_n = other_n = 0
    with man.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "path",
                "relpath",
                "size",
                "sha256",
                "subject",
                "session",
                "modality",
                "suffix",
                "ext",
            ]
        )
        for p in sorted(files):
            rel = str(p.relative_to(bids_root))
            sub, ses, modality, suffix = _parse_bids_rel(rel)
            size = p.stat().st_size
            ext = ".nii.gz" if str(p).endswith(".nii.gz") else p.suffix
            do_hash = hash_large or size <= 50 * 1024 * 1024
            h = _sha256(p) if do_hash else ""
            if modality == "func":
                func_n += 1
            elif modality == "anat":
                anat_n += 1
            else:
                other_n += 1
            w.writerow([str(p), rel, size, h, sub, ses, modality, suffix, ext])
    return {
        "total": len(files),
        "func": func_n,
        "anat": anat_n,
        "other": other_n,
        "manifest": str(man),
    }
