"""Unit tests for S8 confounds + physio regressor pure helpers.

Scope: deterministic numeric/logic helpers only — no FSL PNM, no real
BOLD/physio data. Synthetic numpy arrays, DataFrames, and tmp_path
sidecars. Every expected value is derived from the helper's documented
contract, never hand-tuned to the implementation.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# SliceTiming reconciliation (_slicetiming_for_bold)
# ---------------------------------------------------------------------------


def test_slicetiming_bids_exact_passthrough():
    """When BIDS SliceTiming length matches n_slices, it is used verbatim."""
    from spinalfmriprep.steps.s8.orchestrate import _slicetiming_for_bold
    bids = [0.0, 0.5, 1.0, 1.5]
    timing, source = _slicetiming_for_bold(bids, tr_s=2.0, n_slices=4)
    assert source == "bids_exact"
    assert timing == bids


def test_slicetiming_mismatch_falls_back_to_uniform_interleaved():
    """Length mismatch (S3 z-crop) -> uniform interleaved approximation.

    For an even slice count the Siemens default is even-first: the
    acquisition order is [1, 3, 0, 2], and slice s gets time
    i * TR / n_slices where i is its position in that order.
    """
    from spinalfmriprep.steps.s8.orchestrate import _slicetiming_for_bold
    # BIDS array has length 2, BOLD has 4 slices -> mismatch
    timing, source = _slicetiming_for_bold([0.0, 0.5], tr_s=2.0, n_slices=4)
    assert source == "approx_uniform_interleaved"
    assert len(timing) == 4
    # order [1,3,0,2] with step TR/n = 0.5: slice1->0.0, slice3->0.5,
    # slice0->1.0, slice2->1.5
    assert timing == [1.0, 0.0, 1.5, 0.5]


def test_slicetiming_ascending_order():
    """Ascending order assigns monotonically increasing times by slice index."""
    from spinalfmriprep.steps.s8.orchestrate import _slicetiming_for_bold
    timing, source = _slicetiming_for_bold(
        None, tr_s=2.0, n_slices=4, slice_order="ascending")
    assert source == "approx_uniform_interleaved"
    # i * TR / n for i in 0..3 with TR/n = 0.5
    assert timing == [0.0, 0.5, 1.0, 1.5]


def test_slicetiming_odd_interleaved_order():
    """Odd slice count -> odd-first interleave [0,2,4,1,3]."""
    from spinalfmriprep.steps.s8.orchestrate import _slicetiming_for_bold
    timing, _ = _slicetiming_for_bold(None, tr_s=5.0, n_slices=5)
    # order [0,2,4,1,3], step TR/n = 1.0: slice0->0, slice2->1, slice4->2,
    # slice1->3, slice3->4
    assert timing == [0.0, 3.0, 1.0, 4.0, 2.0]


# ---------------------------------------------------------------------------
# TR + SliceTiming sidecar reader (_tr_and_slicetiming)
# ---------------------------------------------------------------------------


def test_tr_and_slicetiming_reads_sidecar(tmp_path):
    from spinalfmriprep.steps.s8.orchestrate import _tr_and_slicetiming
    p = tmp_path / "bold.json"
    p.write_text(json.dumps({"RepetitionTime": 2.0,
                             "SliceTiming": [0, 0.5, 1.0]}))
    tr, st = _tr_and_slicetiming(p)
    assert tr == 2.0
    assert st == [0.0, 0.5, 1.0]


def test_tr_and_slicetiming_missing_slicetiming_is_none(tmp_path):
    from spinalfmriprep.steps.s8.orchestrate import _tr_and_slicetiming
    p = tmp_path / "bold.json"
    p.write_text(json.dumps({"RepetitionTime": 1.5}))
    tr, st = _tr_and_slicetiming(p)
    assert tr == 1.5
    assert st is None


def test_tr_and_slicetiming_absent_or_none_path():
    from spinalfmriprep.steps.s8.orchestrate import _tr_and_slicetiming
    assert _tr_and_slicetiming(None) == (None, None)


# ---------------------------------------------------------------------------
# PNM slicetiming writer (_write_pnm_slicetiming)
# ---------------------------------------------------------------------------


def test_write_pnm_slicetiming_one_line_six_decimals(tmp_path):
    from spinalfmriprep.steps.s8.process import _write_pnm_slicetiming
    dest = tmp_path / "slicetiming.txt"
    _write_pnm_slicetiming([0.0, 0.5, 1.25], dest)
    text = dest.read_text()
    # single line, space-separated, 6 decimal places, trailing newline
    assert text == "0.000000 0.500000 1.250000\n"


# ---------------------------------------------------------------------------
# Cosine drift basis (_cosine_basis)
# ---------------------------------------------------------------------------


def test_cosine_basis_shape_and_count():
    """n_keep = floor(2 * N * TR * cutoff). N=200, TR=2, cutoff=0.01 -> 8."""
    from spinalfmriprep.steps.s8.process import _cosine_basis
    cols = _cosine_basis(n_volumes=200, tr_s=2.0, cutoff_hz=0.01)
    assert len(cols) == 8
    # columns are zero-indexed cosine_00 .. cosine_07
    assert set(cols) == {f"cosine_{k:02d}" for k in range(8)}
    for v in cols.values():
        assert v.shape == (200,)
        assert v.dtype == np.float32


def test_cosine_basis_empty_below_frequency_cutoff():
    """A cutoff too low to admit even one basis term yields no columns."""
    from spinalfmriprep.steps.s8.process import _cosine_basis
    # 2 * 10 * 2 * 0.001 = 0.04 -> floor = 0 -> no columns
    assert _cosine_basis(n_volumes=10, tr_s=2.0, cutoff_hz=0.001) == {}


def test_cosine_basis_degenerate_inputs_return_empty():
    from spinalfmriprep.steps.s8.process import _cosine_basis
    assert _cosine_basis(n_volumes=1, tr_s=2.0, cutoff_hz=0.1) == {}
    assert _cosine_basis(n_volumes=200, tr_s=2.0, cutoff_hz=0.0) == {}


# ---------------------------------------------------------------------------
# Tukey upper-fence outlier mask (_tukey_outlier_mask)
# ---------------------------------------------------------------------------


def test_tukey_outlier_mask_flags_only_upper_fence():
    """Tukey flags values above Q3 + k*IQR; symmetric noise stays unflagged."""
    from spinalfmriprep.steps.s8.process import _tukey_outlier_mask
    x = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 100.0])
    mask = _tukey_outlier_mask(x, k=1.5)
    # only the 100.0 exceeds Q3 + 1.5*IQR
    assert mask.tolist() == [False, False, False, False, False, True]


# ---------------------------------------------------------------------------
# One-hot spike regressors (_build_outlier_columns)
# ---------------------------------------------------------------------------


def _flat_metrics(n, dvars=5.0, refrms=3.0):
    """Frame metrics with constant DVARS/refRMS (no statistical outliers)."""
    return pd.DataFrame({"dvars": np.full(n, dvars),
                         "ref_rms": np.full(n, refrms)})


def test_outlier_columns_all_good_run_has_zero_spikes():
    """A run with sub-threshold FD and flat DVARS/refRMS -> 0 spike regressors."""
    from spinalfmriprep.steps.s8.process import _build_outlier_columns
    n = 20
    cols, n_out = _build_outlier_columns(
        _flat_metrics(n), fd=np.zeros(n), fd_thresh=0.5)
    assert n_out == 0
    spikes = [k for k in cols if k.startswith("motion_outlier_")]
    assert spikes == []
    # dvars/ref_rms passthrough columns are always present
    assert "dvars" in cols and "ref_rms" in cols


def test_outlier_columns_one_spike_per_outlier_frame_via_fd():
    """One FD-over-threshold frame -> exactly one one-hot column on that frame."""
    from spinalfmriprep.steps.s8.process import _build_outlier_columns
    n = 20
    fd = np.zeros(n)
    fd[7] = 1.0  # above 0.5 mm
    cols, n_out = _build_outlier_columns(
        _flat_metrics(n), fd=fd, fd_thresh=0.5)
    assert n_out == 1
    spikes = [k for k in cols if k.startswith("motion_outlier_")]
    assert len(spikes) == 1
    spike = cols["motion_outlier_00"]
    # one-hot: exactly one nonzero, located at the outlier frame
    assert spike.sum() == 1.0
    assert int(np.argmax(spike)) == 7


def test_outlier_columns_count_matches_number_of_outlier_frames():
    """Spike regressor count equals the number of distinct outlier frames.

    Two FD spikes plus one DVARS Tukey outlier on a separate frame ->
    three one-hot columns.
    """
    from spinalfmriprep.steps.s8.process import _build_outlier_columns
    n = 30
    fd = np.zeros(n)
    fd[5] = 1.0
    fd[10] = 0.8
    dvars = np.full(n, 5.0)
    dvars[20] = 1000.0  # lone DVARS spike
    fm = pd.DataFrame({"dvars": dvars, "ref_rms": np.full(n, 3.0)})
    cols, n_out = _build_outlier_columns(fm, fd=fd, fd_thresh=0.5)
    assert n_out == 3
    spikes = sorted(k for k in cols if k.startswith("motion_outlier_"))
    assert len(spikes) == 3
    # the union of one-hot positions must be exactly {5, 10, 20}
    positions = {int(np.argmax(cols[k])) for k in spikes}
    assert positions == {5, 10, 20}


# ---------------------------------------------------------------------------
# DCT detrending (_detrend_dct)
# ---------------------------------------------------------------------------


def test_detrend_dct_removes_constant_and_linear_trend():
    """Detrending removes the DC + low-frequency drift, leaving ~zero mean."""
    from spinalfmriprep.steps.s8.process import _detrend_dct
    T = 50
    # row 0 is a pure linear ramp; row 1 is a constant offset
    ts = np.vstack([np.linspace(0.0, 10.0, T), np.full(T, 5.0)])
    out = _detrend_dct(ts, tr_s=2.0, cutoff_hz=0.01)
    assert out.shape == (2, T)
    # both rows mean-removed to numerical zero
    assert np.allclose(out.mean(axis=1), 0.0, atol=1e-9)
    # the linear ramp is largely absorbed by the cosine basis -> small residual
    assert np.std(out[0]) < np.std(ts[0])


def test_detrend_dct_requires_2d():
    from spinalfmriprep.steps.s8.process import _detrend_dct
    with pytest.raises(ValueError, match="2D"):
        _detrend_dct(np.zeros(10), tr_s=2.0, cutoff_hz=0.01)


# ---------------------------------------------------------------------------
# Slice-column tagging + per-slice condition number
# ---------------------------------------------------------------------------


def test_slice_of_column_distinguishes_slicewise_from_global():
    from spinalfmriprep.steps.s8.process import _slice_of_column
    assert _slice_of_column("csf_slice03_pc02") == 3
    assert _slice_of_column("retroicor_evX_slice07") == 7
    # global regressors carry no slice token
    assert _slice_of_column("trans_x") is None
    assert _slice_of_column("cosine_00") is None


def test_condition_number_slicewise_flat_when_no_per_slice_family():
    """With only global columns, headline == global_only and no worst slice."""
    from spinalfmriprep.steps.s8.process import _condition_number_slicewise
    rng = np.random.default_rng(0)
    df = pd.DataFrame({"trans_x": rng.standard_normal(20),
                       "cosine_00": rng.standard_normal(20)})
    info = _condition_number_slicewise(df)
    assert info["worst_slice"] is None
    assert info["per_slice"] == {}
    assert np.isfinite(info["condition_number"])
    assert info["condition_number"] == info["global_only"]


def test_condition_number_slicewise_scores_each_slice_design():
    """Per-slice columns are scored slice-locally; headline = worst slice."""
    from spinalfmriprep.steps.s8.process import _condition_number_slicewise
    rng = np.random.default_rng(1)
    df = pd.DataFrame({
        "trans_x": rng.standard_normal(20),
        "csf_slice00_pc01": rng.standard_normal(20),
        "csf_slice01_pc01": rng.standard_normal(20),
    })
    info = _condition_number_slicewise(df)
    # one entry per slice that carried a per-slice column
    assert sorted(info["per_slice"].keys()) == [0, 1]
    assert info["worst_slice"] in (0, 1)
    # headline equals the worst (max) per-slice condition number
    assert info["condition_number"] == max(info["per_slice"].values())


def test_condition_number_slicewise_empty_df():
    from spinalfmriprep.steps.s8.process import _condition_number_slicewise
    info = _condition_number_slicewise(pd.DataFrame())
    assert info["worst_slice"] is None
    assert np.isnan(info["condition_number"])


# ---------------------------------------------------------------------------
# Status classification (_classify)
# ---------------------------------------------------------------------------


_QC_THR = {"pass_condition_number": 1000.0, "warn_condition_number": 10000.0,
           "pass_outlier_fraction_max": 0.20}


def test_classify_pass_good_design():
    from spinalfmriprep.steps.s8.process import _classify
    status, reasons = _classify(
        {"condition_number": 50.0, "outlier_fraction": 0.1}, _QC_THR)
    assert status == "PASS"
    assert reasons == []


def test_classify_warn_then_fail_on_condition_number():
    from spinalfmriprep.steps.s8.process import _classify
    warn, _ = _classify(
        {"condition_number": 5000.0, "outlier_fraction": 0.1}, _QC_THR)
    fail, _ = _classify(
        {"condition_number": 50000.0, "outlier_fraction": 0.1}, _QC_THR)
    assert warn == "WARN"
    assert fail == "FAIL"


def test_classify_high_outlier_fraction_is_warn_never_fail():
    """Outlier fraction is observability-only: elevated -> WARN, never FAIL."""
    from spinalfmriprep.steps.s8.process import _classify
    status, reasons = _classify(
        {"condition_number": 50.0, "outlier_fraction": 0.5}, _QC_THR)
    assert status == "WARN"
    assert any("outlier_fraction" in r for r in reasons)


def test_classify_uncomputed_condition_number_is_warn():
    from spinalfmriprep.steps.s8.process import _classify
    status, reasons = _classify(
        {"condition_number": float("nan"), "outlier_fraction": 0.1}, _QC_THR)
    assert status == "WARN"
    assert any("not computed" in r for r in reasons)


# ---------------------------------------------------------------------------
# Physio channel name normalization (_normalize_physio_channel)
# ---------------------------------------------------------------------------


def test_normalize_physio_channel_aliases():
    from spinalfmriprep.steps.s8.process import _normalize_physio_channel
    for alias in ("cardiac", "PULS", "ecg", "PPG"):
        assert _normalize_physio_channel(alias) == "cardiac"
    for alias in ("respiratory", "RESP", "breathing"):
        assert _normalize_physio_channel(alias) == "respiratory"
    assert _normalize_physio_channel("trigger") == "trigger"
    assert _normalize_physio_channel("unknown_chan") is None
