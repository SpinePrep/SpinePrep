"""Regression tests for the S9 derivative BOLD sidecar.

Two bugs this pins:
1. The sidecar declared RepetitionTime read from the PROCESSED header's
   pixdim[4]. SCT does not preserve it (a 1.66 s run reads back as 1.0), so a
   "GLM-ready" derivative shipped a fabricated TR. Only the authoritative TR
   (raw BIDS sidecar) may be written; if unknown the key is omitted.
2. S3 drops initial volumes but nothing recorded the shift, so a GLM using the
   raw events.tsv was silently misaligned. The sidecar now records
   NumberOfVolumesDiscardedByUser and StartTime.

See .claude/specs/s3-algorithm-audit.md (F2).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from spineprep.steps.s9.process import _write_bold_sidecar


def _sidecar(tmp_path, **kw):
    bold = tmp_path / "sub-01_task-gvs_desc-preproc_bold.nii.gz"
    bold.write_bytes(b"")
    _write_bold_sidecar(bold, kw.pop("tr", 1.66), kw.pop("task", "gvs"), **kw)
    return json.loads((tmp_path / "sub-01_task-gvs_desc-preproc_bold.json").read_text())


def test_authoritative_tr_is_written(tmp_path):
    meta = _sidecar(tmp_path, tr=1.66)
    assert meta["RepetitionTime"] == 1.66


def test_unknown_tr_is_omitted_not_fabricated(tmp_path):
    """Better to omit than to declare a wrong TR: a GLM should fail loudly."""
    meta = _sidecar(tmp_path, tr=None)
    assert "RepetitionTime" not in meta


def test_dummy_drop_is_recorded_as_starttime(tmp_path):
    meta = _sidecar(tmp_path, tr=1.66, n_dummy_dropped=4)
    assert meta["NumberOfVolumesDiscardedByUser"] == 4
    assert meta["StartTime"] == round(4 * 1.66, 6)   # 6.64 s


def test_no_drop_emits_no_shift_keys(tmp_path):
    meta = _sidecar(tmp_path, tr=1.66, n_dummy_dropped=0)
    assert "NumberOfVolumesDiscardedByUser" not in meta
    assert "StartTime" not in meta


def test_starttime_omitted_when_tr_unknown(tmp_path):
    """StartTime is n_dropped x TR; without a TR it cannot be computed."""
    meta = _sidecar(tmp_path, tr=None, n_dummy_dropped=4)
    assert meta["NumberOfVolumesDiscardedByUser"] == 4
    assert "StartTime" not in meta
