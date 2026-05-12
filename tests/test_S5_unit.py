"""Unit tests for S5 distortion correction mode selection and helpers."""
from __future__ import annotations

import nibabel as nib
import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Mode selection
# ---------------------------------------------------------------------------


def _func_run(path="sub-01/func/sub-01_task-rest_bold.nii.gz", subject="01"):
    return {
        "modality": "func",
        "subject": subject,
        "session": None,
        "path": path,
        "acquisition": {"PhaseEncodingDirection": "j", "TotalReadoutTime": 0.04},
    }


def _fmap_epi(dir_label, pe, subject="01"):
    return {
        "modality": "fmap",
        "subject": subject,
        "session": None,
        "path": f"sub-{subject}/fmap/sub-{subject}_dir-{dir_label}_epi.nii.gz",
        "acquisition": {
            "PhaseEncodingDirection": pe,
            "TotalReadoutTime": 0.04,
        },
    }


def _fmap_gre_phase(subject="01"):
    return {
        "modality": "fmap",
        "subject": subject,
        "session": None,
        "path": f"sub-{subject}/fmap/sub-{subject}_phasediff.nii.gz",
        "acquisition": {},
    }


def _fmap_gre_mag(subject="01"):
    return {
        "modality": "fmap",
        "subject": subject,
        "session": None,
        "path": f"sub-{subject}/fmap/sub-{subject}_magnitude1.nii.gz",
        "acquisition": {},
    }


def test_mode_select_picks_topup_for_opposite_pe_pair():
    from spinalfmriprep.steps.s5.mode import select_mode
    bold = _func_run()
    fmaps = [_fmap_epi("AP", "j-"), _fmap_epi("PA", "j")]
    mode, eligible = select_mode(bold, fmaps)
    assert mode == "topup"
    assert len(eligible) == 2
    pe_set = {f["acquisition"]["PhaseEncodingDirection"] for f in eligible}
    assert pe_set == {"j", "j-"}


def test_mode_select_rejects_two_same_pe_fmaps():
    """Spec §S5.1: two AP fmaps with zero PA is NOT topup-eligible."""
    from spinalfmriprep.steps.s5.mode import select_mode
    bold = _func_run()
    fmaps = [_fmap_epi("AP_run1", "j-"), _fmap_epi("AP_run2", "j-")]
    mode, _ = select_mode(bold, fmaps)
    assert mode == "syn", "two same-PE fmaps must fall through to SyN"


def test_mode_select_picks_fugue_for_gre_pair():
    from spinalfmriprep.steps.s5.mode import select_mode
    bold = _func_run()
    fmaps = [_fmap_gre_phase(), _fmap_gre_mag()]
    mode, _ = select_mode(bold, fmaps)
    assert mode == "fugue"


def test_mode_select_falls_back_to_syn_when_no_fmaps():
    from spinalfmriprep.steps.s5.mode import select_mode
    bold = _func_run()
    mode, eligible = select_mode(bold, [])
    assert mode == "syn"
    assert eligible == []


def test_opposite_pe_detection():
    from spinalfmriprep.steps.s5.mode import _opposite_pe
    assert _opposite_pe("j", "j-")
    assert _opposite_pe("i-", "i")
    assert _opposite_pe("k", "k-")
    assert not _opposite_pe("j", "j")
    assert not _opposite_pe("i", "j-")  # different axes
    assert not _opposite_pe(None, "j")


# ---------------------------------------------------------------------------
# TRT extraction
# ---------------------------------------------------------------------------


def test_trt_prefers_bids_sidecar_value():
    from spinalfmriprep.steps.s5.process import _trt_for
    run = {"acquisition": {"TotalReadoutTime": 0.0406401,
                           "EffectiveEchoSpacing": 0.00032,
                           "ReconMatrixPE": 128}}
    assert _trt_for(run) == 0.0406401


def test_trt_fallback_follows_BIDS_convention_no_GRAPPA_division():
    """The fallback path must compute TRT as (matrix_PE - 1) * EES, NOT
    (N_PE / f_acc - 1) * EES. See round-2 audit findings."""
    from spinalfmriprep.steps.s5.process import _trt_for
    run = {"acquisition": {
        "EffectiveEchoSpacing": 0.000320001,
        "ReconMatrixPE": 128,
        "ParallelReductionFactorInPlane": 2,  # must NOT be applied
    }}
    expected = 127 * 0.000320001  # matches cospine_motor sidecar 0.0406401
    assert abs(_trt_for(run) - expected) < 1e-9
    assert _trt_for(run) > 0.04  # sanity: not the GRAPPA-divided 0.02


def test_trt_returns_none_when_no_data():
    from spinalfmriprep.steps.s5.process import _trt_for
    assert _trt_for({}) is None
    assert _trt_for({"acquisition": {}}) is None


# ---------------------------------------------------------------------------
# acqparams.txt writing
# ---------------------------------------------------------------------------


def test_write_acqparams_bids_pe_to_fsl_mapping(tmp_path):
    from spinalfmriprep.steps.s5.process import _write_acqparams
    out = tmp_path / "acqparams.txt"
    _write_acqparams(out, ["j-", "j"], 0.0406)
    content = out.read_text().strip()
    lines = content.splitlines()
    assert len(lines) == 2
    # AP (j-) -> 0 -1 0
    assert lines[0].startswith("0 -1 0 ")
    # PA (j) -> 0 1 0
    assert lines[1].startswith("0 1 0 ")
    assert lines[0].endswith("0.040600")
    assert lines[1].endswith("0.040600")


def test_write_acqparams_rejects_unsupported_pe(tmp_path):
    from spinalfmriprep.steps.s5.process import _write_acqparams
    with pytest.raises(ValueError, match="Unsupported"):
        _write_acqparams(tmp_path / "bad.txt", ["unknown"], 0.04)


# ---------------------------------------------------------------------------
# Status classification
# ---------------------------------------------------------------------------


def test_syn_mode_always_warn():
    from spinalfmriprep.steps.s5.process import _classify_run_status
    metrics = {"mi_delta_pct": 5.0}
    status, reasons = _classify_run_status(metrics, "syn", {})
    assert status == "WARN"
    assert any("SyN" in r for r in reasons)


def test_topup_mode_pass_when_mi_improves():
    from spinalfmriprep.steps.s5.process import _classify_run_status
    metrics = {"mi_delta_pct": 5.0}
    status, _ = _classify_run_status(metrics, "topup", {})
    assert status == "PASS"


def test_fail_on_large_mi_drop():
    from spinalfmriprep.steps.s5.process import _classify_run_status
    metrics = {"mi_delta_pct": -20.0}
    status, _ = _classify_run_status(metrics, "topup",
                                     {"fail_mi_max_drop_pct": 10.0})
    assert status == "FAIL"
