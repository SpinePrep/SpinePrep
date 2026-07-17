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
    from spineprep.steps.s5.mode import select_mode
    bold = _func_run()
    fmaps = [_fmap_epi("AP", "j-"), _fmap_epi("PA", "j")]
    mode, eligible = select_mode(bold, fmaps)
    assert mode == "topup"
    assert len(eligible) == 2
    pe_set = {f["acquisition"]["PhaseEncodingDirection"] for f in eligible}
    assert pe_set == {"j", "j-"}


def test_mode_select_rejects_two_same_pe_fmaps():
    """Spec §S5.1: two AP fmaps with zero PA is NOT topup-eligible."""
    from spineprep.steps.s5.mode import select_mode
    bold = _func_run()
    fmaps = [_fmap_epi("AP_run1", "j-"), _fmap_epi("AP_run2", "j-")]
    mode, _ = select_mode(bold, fmaps)
    assert mode == "none", "two same-PE fmaps are not topup-eligible -> default fallback (none)"


def test_mode_select_gre_pair_falls_through_to_fallback():
    # FUGUE was removed in v1 (no GRE-fieldmap data in the cohort); a GRE
    # phasediff/magnitude pair is not topup-eligible, so it takes the default
    # fallback, which is `none` since the 2026-07-17 held-out validation.
    from spineprep.steps.s5.mode import select_mode
    bold = _func_run()
    fmaps = [_fmap_gre_phase(), _fmap_gre_mag()]
    mode, eligible = select_mode(bold, fmaps)
    assert mode == "none"
    assert eligible == []


def test_mode_select_falls_back_to_default_when_no_fmaps():
    from spineprep.steps.s5.mode import select_mode
    bold = _func_run()
    mode, eligible = select_mode(bold, [])
    assert mode == "none"  # default fallback flipped syn->none 2026-07-17
    assert eligible == []


def test_opposite_pe_detection():
    from spineprep.steps.s5.mode import _opposite_pe
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
    from spineprep.steps.s5.process import _trt_for
    run = {"acquisition": {"TotalReadoutTime": 0.0406401,
                           "EffectiveEchoSpacing": 0.00032,
                           "ReconMatrixPE": 128}}
    assert _trt_for(run) == 0.0406401


def test_trt_fallback_follows_BIDS_convention_no_GRAPPA_division():
    """The fallback path must compute TRT as (matrix_PE - 1) * EES, NOT
    (N_PE / f_acc - 1) * EES. See round-2 audit findings."""
    from spineprep.steps.s5.process import _trt_for
    run = {"acquisition": {
        "EffectiveEchoSpacing": 0.000320001,
        "ReconMatrixPE": 128,
        "ParallelReductionFactorInPlane": 2,  # must NOT be applied
    }}
    expected = 127 * 0.000320001  # matches cospine_motor sidecar 0.0406401
    assert abs(_trt_for(run) - expected) < 1e-9
    assert _trt_for(run) > 0.04  # sanity: not the GRAPPA-divided 0.02


def test_trt_returns_none_when_no_data():
    from spineprep.steps.s5.process import _trt_for
    assert _trt_for({}) is None
    assert _trt_for({"acquisition": {}}) is None


# ---------------------------------------------------------------------------
# acqparams.txt writing
# ---------------------------------------------------------------------------


def test_write_acqparams_bids_pe_to_fsl_mapping(tmp_path):
    from spineprep.steps.s5.process import _write_acqparams
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
    from spineprep.steps.s5.process import _write_acqparams
    with pytest.raises(ValueError, match="Unsupported"):
        _write_acqparams(tmp_path / "bad.txt", ["unknown"], 0.04)


# ---------------------------------------------------------------------------
# Status classification
# ---------------------------------------------------------------------------


# Gating is geometry-based (CoSpine Dice + A-P displacement). Mode no longer
# decides status — the SyN-always-WARN rule was removed 2026-05-28. MI is only a
# backup signal: a catastrophic MI drop fails ONLY when geometry also didn't
# improve. These tests track that current contract.

_GATE_THR = {
    "pass_dice_min": 0.50, "warn_dice_min": 0.30,
    "pass_displacement_max_mm": 1.0, "warn_displacement_max_mm": 2.0,
    "fail_mi_max_drop_pct": 10.0,
}


def test_geometry_pass_regardless_of_mode():
    """Good geometry PASSes for every mode (SyN included)."""
    from spineprep.steps.s5.process import _classify_run_status
    metrics = {"dice_mean_after": 0.85, "dice_mean_before": 0.78,
               "displacement_mean_after_mm": 0.5, "displacement_mean_before_mm": 1.6}
    for mode in ("syn", "topup"):
        status, reasons = _classify_run_status(metrics, mode, _GATE_THR)
        assert status == "PASS", f"{mode}: {reasons}"


def test_warn_when_dice_below_pass_floor():
    from spineprep.steps.s5.process import _classify_run_status
    metrics = {"dice_mean_after": 0.45, "displacement_mean_after_mm": 0.5}
    status, reasons = _classify_run_status(metrics, "syn", _GATE_THR)
    assert status == "WARN"
    assert any("Dice" in r for r in reasons)


def test_fail_when_dice_below_warn_floor():
    from spineprep.steps.s5.process import _classify_run_status
    metrics = {"dice_mean_after": 0.20, "displacement_mean_after_mm": 0.5}
    status, _ = _classify_run_status(metrics, "topup", _GATE_THR)
    assert status == "FAIL"


def test_fail_when_displacement_above_warn_ceiling():
    # TopUp keeps the hard FAIL — they are expected to meet the
    # TopUp-calibrated ceiling.
    from spineprep.steps.s5.process import _classify_run_status
    metrics = {"dice_mean_after": 0.80, "displacement_mean_after_mm": 2.5}
    status, _ = _classify_run_status(metrics, "topup", _GATE_THR)
    assert status == "FAIL"


def test_syn_above_ceiling_is_distortion_limited_warn_not_fail():
    # Image-based SyN (no fieldmap) cannot reach TopUp quality. When the cord
    # still registered (Dice OK) but displacement exceeds the ceiling, flag the
    # run distortion-limited (WARN, kept) rather than FAIL.
    from spineprep.steps.s5.process import _classify_run_status
    metrics = {"dice_mean_after": 0.80, "displacement_mean_after_mm": 2.5}
    status, reasons = _classify_run_status(metrics, "syn", _GATE_THR)
    assert status == "WARN"
    assert any("distortion-limited" in r for r in reasons)


def test_syn_above_ceiling_with_bad_dice_still_fails():
    # If even the cord did not register (Dice below the warn floor), it is a
    # genuine failure regardless of mode — the Dice gate fails first.
    from spineprep.steps.s5.process import _classify_run_status
    metrics = {"dice_mean_after": 0.20, "displacement_mean_after_mm": 2.5}
    status, _ = _classify_run_status(metrics, "syn", _GATE_THR)
    assert status == "FAIL"


def test_syn_distortion_limited_can_be_disabled():
    # Setting the policy flag false restores the hard FAIL for SyN too.
    from spineprep.steps.s5.process import _classify_run_status
    thr = dict(_GATE_THR, syn_displacement_distortion_limited=False)
    metrics = {"dice_mean_after": 0.80, "displacement_mean_after_mm": 2.5}
    status, _ = _classify_run_status(metrics, "syn", thr)
    assert status == "FAIL"


def test_catastrophic_mi_drop_fails_only_when_geometry_not_improved():
    from spineprep.steps.s5.process import _classify_run_status
    # No geometry metrics -> not improved -> MI drop fails outright
    status, _ = _classify_run_status({"mi_delta_pct": -20.0}, "topup", _GATE_THR)
    assert status == "FAIL"


def test_mi_drop_ignored_when_geometry_improved():
    """Geometry is ground truth (cospine_pain topup: MI -12.9% but Dice +0.07)."""
    from spineprep.steps.s5.process import _classify_run_status
    metrics = {"mi_delta_pct": -15.0, "dice_delta": 0.07,
               "displacement_delta_mm": -1.3, "dice_mean_after": 0.82,
               "displacement_mean_after_mm": 0.6}
    status, _ = _classify_run_status(metrics, "topup", _GATE_THR)
    assert status == "PASS"


# ---------------------------------------------------------------------------
# Reportlets (metric-driven; missing keys -> placeholder, never raise)
# ---------------------------------------------------------------------------


def _disp_metrics():
    return {"per_slice_z": [2, 3, 4, 5],
            "displacement_before_mm": [1.6, 1.8, 1.5, 1.7],
            "displacement_after_mm": [0.5, 0.6, 0.4, 0.5],
            "displacement_mean_before_mm": 1.65, "displacement_mean_after_mm": 0.5,
            "displacement_delta_mm": -1.15}


def _dice_metrics():
    return {"per_slice_z": [2, 3, 4, 5],
            "dice_per_slice_before": [0.72, 0.70, 0.74, 0.71],
            "dice_per_slice_after": [0.85, 0.86, 0.84, 0.85],
            "dice_mean_before": 0.72, "dice_mean_after": 0.85,
            "dice_3d_before": 0.70, "dice_3d_after": 0.84, "dice_delta": 0.13}


def test_s5_slice_displacement_renders(tmp_path):
    from spineprep.steps.s5.reportlets import render_s5_slice_displacement
    out = tmp_path / "disp.png"
    render_s5_slice_displacement(_disp_metrics(), out, "syn")
    assert out.exists() and out.stat().st_size > 1000


def test_s5_cord_dice_per_slice_renders(tmp_path):
    from spineprep.steps.s5.reportlets import render_s5_cord_dice_per_slice
    out = tmp_path / "dice.png"
    render_s5_cord_dice_per_slice(_dice_metrics(), out, "topup")
    assert out.exists() and out.stat().st_size > 1000


def test_s5_reportlets_handle_missing_keys(tmp_path):
    """Both metric-driven reportlets degrade to a placeholder, never raise."""
    from spineprep.steps.s5.reportlets import (
        render_s5_slice_displacement, render_s5_cord_dice_per_slice)
    d = tmp_path / "d.png"; c = tmp_path / "c.png"
    render_s5_slice_displacement({}, d, "syn")
    render_s5_cord_dice_per_slice({}, c, "syn")
    assert d.exists() and c.exists()
