"""S3.3 frame-count integrity guard (Phase-0 hardening).

The S3 double-dummy-drop bug shipped silently because nothing reconciled the
frame count through the crop. sct_crop_image is a SPATIAL crop, so the timepoint
count must be preserved; if it isn't, frames were silently dropped/added and the
run must FAIL loudly. These tests mock the sct calls so they run without SCT.
"""
import numpy as np
import nibabel as nib
import pytest

from spinalfmriprep.steps.s3 import crop as crop_mod
from spinalfmriprep.steps.s3.crop import _process_s3_3_crop_and_qc
from spinalfmriprep.subtask import set_execution_context


def _save(path, shape):
    nib.save(nib.Nifti1Image(np.random.rand(*shape).astype(np.float32), np.eye(4)), str(path))


def _make_inputs(tmp_path, n_frames):
    bold = tmp_path / "func_bold_coarse.nii.gz"; _save(bold, (8, 8, 4, n_frames))
    mask = tmp_path / "cordmask.nii.gz"; _save(mask, (8, 8, 4))
    ref = tmp_path / "ref.nii.gz"; _save(ref, (8, 8, 4))
    ref_fast = tmp_path / "ref_fast.nii.gz"; _save(ref_fast, (8, 8, 4))
    disc = tmp_path / "disc.nii.gz"; _save(disc, (8, 8, 4))
    return bold, mask, ref, ref_fast, disc


def _mock_run_command(crop_out_frames):
    """Fake sct: write the `-o` target. sct_crop_image emits crop_out_frames."""
    def _run(cmd, *a, **k):
        tool = cmd[0]
        out = cmd[cmd.index("-o") + 1] if "-o" in cmd else None
        if tool == "sct_create_mask" and out:
            _save(out, (8, 8, 4))
        elif tool == "sct_crop_image" and out:
            _save(out, (8, 8, 4, crop_out_frames))
        return True, ""
    return _run


def test_frame_guard_fails_on_dropped_frames(tmp_path, monkeypatch):
    set_execution_context(None)
    monkeypatch.setattr(crop_mod, "_run_command", _mock_run_command(crop_out_frames=8))
    bold, mask, ref, ref_fast, disc = _make_inputs(tmp_path, n_frames=10)
    res = _process_s3_3_crop_and_qc(bold, mask, ref, ref_fast, disc, tmp_path, {})
    assert res["qc_status"] == "FAIL"
    assert "integrity" in (res.get("failure_message") or "").lower()
    assert "10" in res["failure_message"] and "8" in res["failure_message"]


def test_frame_guard_passes_when_frames_preserved(tmp_path, monkeypatch):
    # Matching frame counts -> the guard does NOT fire (the run may still fail
    # later on figure rendering, but never with an integrity message).
    set_execution_context(None)
    monkeypatch.setattr(crop_mod, "_run_command", _mock_run_command(crop_out_frames=10))
    bold, mask, ref, ref_fast, disc = _make_inputs(tmp_path, n_frames=10)
    res = _process_s3_3_crop_and_qc(bold, mask, ref, ref_fast, disc, tmp_path, {})
    assert "integrity" not in (res.get("failure_message") or "").lower()
