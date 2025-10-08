from __future__ import annotations

import csv
import gzip
from pathlib import Path

from spineprep.ingest import ingest


def _touch(p: Path, data=b"x"):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


def test_ingest_tiny_bids(tmp_path: Path):
    bids = tmp_path / "bids"
    # create minimal BIDS-like structure
    bold = bids / "sub-01" / "ses-1" / "func" / "sub-01_ses-1_task-rest_bold.nii.gz"
    jsonf = bids / "sub-01" / "ses-1" / "func" / "sub-01_ses-1_task-rest_bold.json"
    anat = bids / "sub-01" / "ses-1" / "anat" / "sub-01_ses-1_T1w.nii.gz"
    _touch(bold, gzip.compress(b"nii"))
    _touch(jsonf, b"{}")
    _touch(anat, gzip.compress(b"nii"))
    out = tmp_path / "out"
    stats = ingest(bids, out, hash_large=True)
    assert stats["total"] == 3
    assert stats["func"] == 2  # json+nii.gz both in func folder
    assert stats["anat"] == 1
    # Read manifest and verify columns
    rows = list(csv.DictReader((out / "manifest.csv").open()))
    assert {
        "path",
        "relpath",
        "size",
        "sha256",
        "subject",
        "session",
        "modality",
        "suffix",
        "ext",
    } <= set(rows[0].keys())
    assert rows[0]["subject"] == "sub-01"
    assert rows[0]["modality"] in {"func", "anat"}


def test_ingest_errors_on_missing_root(tmp_path: Path):
    try:
        ingest(tmp_path / "nope", tmp_path / "out")
        assert False, "Should have raised SystemExit"
    except SystemExit as e:
        assert "BIDS root not found" in str(e)
