"""The GLM specification must apply the verified dataset facts, not restate them.

Every rule here was proven against the data on 2026-07-21. The tests exist so a
future change cannot quietly undo a correction that took a day to establish.
"""
import json

import numpy as np
import pytest

from analysis.glm_spec import (
    PLACEHOLDER_HEADER_TR_S,
    RepetitionTimeError,
    SPEC,
    conditions_for,
    corrected_events,
    is_excluded,
    repetition_time_s,
)


# --- TR: the silent-failure risk ------------------------------------------


def _write_bold(tmp_path, name, tr_header, tr_sidecar):
    import nibabel as nib
    aff = np.eye(4)
    img = nib.Nifti1Image(np.zeros((4, 4, 3, 6), np.float32), aff)
    img.header.set_zooms((1., 1., 1., tr_header))
    p = tmp_path / name
    nib.save(img, p)
    if tr_sidecar is not None:
        p.with_suffix("").with_suffix(".json").write_text(
            json.dumps({"RepetitionTime": tr_sidecar}))
    return p


def test_tr_comes_from_the_sidecar_not_the_header(tmp_path):
    """All 450 cohort files carry a placeholder 1.0 s header TR while the
    sidecar is correct. Reading the header would silently model timing at 1 s."""
    p = _write_bold(tmp_path, "sub-01_bold.nii.gz",
                    tr_header=PLACEHOLDER_HEADER_TR_S, tr_sidecar=2.68)
    assert repetition_time_s(p) == 2.68


def test_missing_sidecar_raises_rather_than_falling_back(tmp_path):
    """A wrong TR corrupts a GLM with no visible symptom, so refuse."""
    p = _write_bold(tmp_path, "sub-02_bold.nii.gz",
                    tr_header=PLACEHOLDER_HEADER_TR_S, tr_sidecar=None)
    with pytest.raises(RepetitionTimeError):
        repetition_time_s(p)


def test_sidecar_without_tr_raises(tmp_path):
    p = _write_bold(tmp_path, "sub-03_bold.nii.gz", 1.0, None)
    p.with_suffix("").with_suffix(".json").write_text(json.dumps({"TaskName": "x"}))
    with pytest.raises(RepetitionTimeError):
        repetition_time_s(p)


def test_header_fallback_is_possible_but_must_be_explicit(tmp_path):
    p = _write_bold(tmp_path, "sub-04_bold.nii.gz", 2.0, None)
    assert repetition_time_s(p, allow_header=True) == pytest.approx(2.0)


# --- timing ---------------------------------------------------------------


def test_start_time_is_subtracted_from_onsets():
    """Events are on the full-acquisition clock incl. discarded dummies."""
    rows = [{"onset": "20.0", "duration": "15.0", "trial_type": "left"}]
    out = corrected_events("openneuro_ds004616_spinalcord_handgrasp_task",
                           rows, start_time_s=8.0, run_id="r")
    # 20 - 8 (StartTime) + 2.5 (measured offset) = 14.5
    assert out[0]["onset"] == pytest.approx(14.5)


def test_cospine_datasets_have_no_shift():
    """Both CoSpine datasets discard 0 volumes; a hardcoded shift is wrong."""
    for ds in ("openneuro_ds005883_cospine_pain", "openneuro_ds005884_cospine_motor"):
        assert SPEC[ds]["onset_shift_s"] == 0.0


def test_ds004616_offset_and_duration_are_applied():
    """Grip force showed the grasp starts +2.5 s late and lasts 16 s, not 15."""
    rows = [{"onset": "100.0", "duration": "15.0", "trial_type": "right"}]
    out = corrected_events("openneuro_ds004616_spinalcord_handgrasp_task",
                           rows, start_time_s=8.0, run_id="r")
    assert out[0]["onset"] == pytest.approx(94.5)
    assert out[0]["duration"] == pytest.approx(16.0)


def test_blocks_entirely_inside_the_discarded_period_are_dropped():
    rows = [{"onset": "0.0", "duration": "2.0", "trial_type": "motion"}]
    out = corrected_events("internal_balgrist_motor_11", rows, start_time_s=10.4)
    assert out == []


# --- baseline -------------------------------------------------------------


@pytest.mark.parametrize("ds", ["internal_balgrist_cospigvs_11",
                                "openneuro_ds004616_spinalcord_handgrasp_task"])
def test_tiling_datasets_use_rest_as_implicit_baseline(ds):
    """These tile 100% of the run; modelling rest gives VIF 23-25 vs ~1.4."""
    assert SPEC[ds]["implicit_baseline"] == "rest"
    assert "rest" not in conditions_for(ds, "r")


def test_baseline_condition_is_stripped_from_events():
    rows = [{"onset": "0", "duration": "30", "trial_type": "rest"},
            {"onset": "30", "duration": "30", "trial_type": "hand"}]
    out = corrected_events("internal_balgrist_cospigvs_11", rows, 0.0)
    assert [e["trial_type"] for e in out] == ["hand"]


def test_sparse_designs_keep_no_explicit_baseline():
    for ds in ("internal_balgrist_motor_11", "openneuro_ds004926_dorsalhorn_pain"):
        assert SPEC[ds]["implicit_baseline"] is None


# --- conditions and exclusions --------------------------------------------


def test_ds005884_condition_comes_from_the_filename():
    """Its events.tsv has no trial_type; the README wrongly claims one."""
    ds = "openneuro_ds005884_cospine_motor"
    assert SPEC[ds]["condition_from_filename"] is True
    assert conditions_for(ds, "sub-01_task-motorL") == ["motorL"]
    assert conditions_for(ds, "sub-01_task-motorR") == ["motorR"]


def test_ds005884_events_get_the_filename_condition():
    rows = [{"onset": "13", "duration": "8"}]      # no trial_type at all
    out = corrected_events("openneuro_ds005884_cospine_motor", rows, 0.0,
                           "sub-01_task-motorR")
    assert out[0]["trial_type"] == "motorR"


def test_truncated_run_is_excluded():
    assert is_excluded("openneuro_ds005883_cospine_pain", "sub-22_task-pain")
    assert not is_excluded("openneuro_ds005883_cospine_pain", "sub-21_task-pain")


def test_every_dataset_records_how_it_was_verified():
    """Provenance is part of the spec, not a comment."""
    for ds, s in SPEC.items():
        assert s.get("verified"), f"{ds} has no verification provenance"
