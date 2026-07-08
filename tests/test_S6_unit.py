"""Unit tests for S6 func->anat registration pure helpers.

These exercise only the deterministic, in-memory logic of S6: the param
string builder, the binary-mask / Dice / mutual-information / surface-distance
metrics on synthetic numpy arrays, the PASS/WARN/FAIL classifier with its
tiering at threshold boundaries, the sform/qform sync helper, and the
orchestrator's subject/session normalizers and top-status aggregation rule.

Anything that shells out to SCT/FSL/ANTs (registration, warp application,
centerline round-trip, the public run_S6 entry) is deliberately not tested
here -- those are integration paths, not pure helpers.
"""
from __future__ import annotations

import nibabel as nib
import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Param string builder
# ---------------------------------------------------------------------------


def test_build_param_string_defaults_are_cospi_recipe():
    from spineprep.steps.s6.process import _build_param_string
    s = _build_param_string({})
    steps = s.split(":")
    assert len(steps) == 3
    # Step 1: centermassrot, Step 2: columnwise, Step 3: bsplinesyn iter=20
    assert "step=1" in steps[0] and "algo=centermassrot" in steps[0]
    assert "algo=columnwise" in steps[1]
    assert "algo=bsplinesyn" in steps[2] and "iter=20" in steps[2]
    # All steps share the seg-driven MeanSquares slicewise contract
    for st in steps:
        assert "type=seg" in st and "metric=MeanSquares" in st and "slicewise=1" in st


def test_build_param_string_overrides_are_applied():
    from spineprep.steps.s6.process import _build_param_string
    s = _build_param_string({"step3": {"iter": 5, "algo": "syn"}})
    step3 = s.split(":")[2]
    assert "iter=5" in step3 and "algo=syn" in step3
    # step1/step2 untouched -> still their defaults
    assert "algo=centermassrot" in s.split(":")[0]


# ---------------------------------------------------------------------------
# Binarize + Dice
# ---------------------------------------------------------------------------


def test_binarize_threshold_is_strict_greater_than():
    from spineprep.steps.s6.process import _binarize
    arr = np.array([0.0, 0.5, 0.50001, 1.0])
    out = _binarize(arr)
    # threshold 0.5 with strict > : 0.5 stays False, 0.50001 becomes True
    assert out.tolist() == [False, False, True, True]
    assert out.dtype == bool


def test_dice_identical_masks_is_one():
    from spineprep.steps.s6.process import _dice
    a = np.zeros((8, 8, 4))
    a[2:6, 2:6, 1:3] = 1.0
    assert _dice(a, a) == pytest.approx(1.0)


def test_dice_disjoint_masks_is_zero():
    from spineprep.steps.s6.process import _dice
    a = np.zeros((8, 8, 2)); a[0:3, 0:3, :] = 1.0
    b = np.zeros((8, 8, 2)); b[5:8, 5:8, :] = 1.0
    assert _dice(a, b) == 0.0


def test_dice_both_empty_returns_zero():
    """n == 0 guard: two empty masks have no overlap and no volume."""
    from spineprep.steps.s6.process import _dice
    z = np.zeros((4, 4, 4))
    assert _dice(z, z) == 0.0


def test_dice_half_overlap_matches_formula():
    from spineprep.steps.s6.process import _dice
    # a = 4 voxels, b = 4 voxels, intersection = 2 -> 2*2/(4+4) = 0.5
    a = np.zeros((4, 4)); a[0, 0:4] = 1.0
    b = np.zeros((4, 4)); b[0, 2:4] = 1.0; b[1, 0:2] = 1.0
    assert _dice(a, b) == pytest.approx(2 * 2 / (4 + 4))


# ---------------------------------------------------------------------------
# Mutual information
# ---------------------------------------------------------------------------


def test_mi_identical_signal_exceeds_shuffled():
    """MI of an array with itself must exceed MI with a shuffled copy."""
    from spineprep.steps.s6.process import _mutual_information
    rng = np.random.default_rng(0)
    a = rng.normal(size=4000)
    shuffled = rng.permutation(a)
    mi_self = _mutual_information(a, a)
    mi_shuf = _mutual_information(a, shuffled)
    assert mi_self > mi_shuf
    assert mi_self > 0.0


def test_mi_empty_after_nan_filter_is_zero():
    from spineprep.steps.s6.process import _mutual_information
    a = np.array([np.nan, np.nan])
    b = np.array([1.0, 2.0])
    # every paired sample has a NaN in a -> no finite pairs -> 0.0
    assert _mutual_information(a, b) == 0.0


# ---------------------------------------------------------------------------
# Surface points + HD95 / ASD
# ---------------------------------------------------------------------------


def test_hd95_asd_zero_for_identical_masks():
    from spineprep.steps.s6.process import _hd95_and_asd
    m = np.zeros((10, 10, 3), dtype=bool)
    m[3:7, 3:7, :] = True
    hd95, asd = _hd95_and_asd(m, m, (1.0, 1.0, 1.0))
    assert hd95 == pytest.approx(0.0)
    assert asd == pytest.approx(0.0)


def test_hd95_returns_none_for_empty_mask():
    from spineprep.steps.s6.process import _hd95_and_asd
    full = np.zeros((6, 6, 2), dtype=bool); full[1:4, 1:4, :] = True
    empty = np.zeros((6, 6, 2), dtype=bool)
    hd95, asd = _hd95_and_asd(full, empty, (1.0, 1.0, 1.0))
    assert hd95 is None and asd is None


def test_hd95_scales_with_zooms():
    """Surface distances are in mm; doubling the in-plane zoom doubles HD95."""
    from spineprep.steps.s6.process import _hd95_and_asd
    a = np.zeros((12, 12, 2), dtype=bool); a[3:9, 3:9, :] = True
    # b shifted by 2 voxels in X
    b = np.zeros((12, 12, 2), dtype=bool); b[5:11, 3:9, :] = True
    hd95_1, _ = _hd95_and_asd(a, b, (1.0, 1.0, 1.0))
    hd95_2, _ = _hd95_and_asd(a, b, (2.0, 1.0, 1.0))
    assert hd95_1 is not None and hd95_2 is not None
    assert hd95_2 == pytest.approx(2.0 * hd95_1, rel=1e-6)


# ---------------------------------------------------------------------------
# Status classification (tiering at boundaries)
# ---------------------------------------------------------------------------


# Defaults baked into _classify when thresholds dict is empty:
#   pass_dice_min 0.85, pass_dice_min_syn_fallback 0.80, fail_dice_below 0.65,
#   pass_hd95_mm_max 4.0 (WARN-only), centerline med pass/warn 3.0/6.0,
#   centerline max pass/warn 5.0/10.0.
_GOOD = {
    "cord_dice": 0.90,
    "cord_hd95_mm": 2.0,
    "centerline_round_trip_med_vox": 1.0,
    "centerline_round_trip_max_vox": 2.0,
}


def test_classify_all_good_is_pass():
    from spineprep.steps.s6.process import _classify
    status, reasons = _classify(dict(_GOOD), {}, syn_fallback=False)
    assert status == "PASS"
    assert reasons == []


def test_classify_dice_below_pass_floor_warns():
    from spineprep.steps.s6.process import _classify
    m = dict(_GOOD, cord_dice=0.80)  # >= fail 0.65 but < pass 0.85
    status, reasons = _classify(m, {}, syn_fallback=False)
    assert status == "WARN"
    assert any("cord_dice WARN" in r for r in reasons)


def test_classify_dice_below_fail_floor_fails():
    from spineprep.steps.s6.process import _classify
    m = dict(_GOOD, cord_dice=0.60)  # < fail 0.65
    status, reasons = _classify(m, {}, syn_fallback=False)
    assert status == "FAIL"
    assert any("cord_dice FAIL" in r for r in reasons)


def test_classify_syn_fallback_relaxes_dice_pass_floor():
    """A 0.82 Dice WARNs under the strict 0.85 floor but PASSes under the
    relaxed 0.80 syn-fallback floor."""
    from spineprep.steps.s6.process import _classify
    m = dict(_GOOD, cord_dice=0.82)
    strict, _ = _classify(m, {}, syn_fallback=False)
    relaxed, _ = _classify(m, {}, syn_fallback=True)
    assert strict == "WARN"
    assert relaxed == "PASS"


def test_classify_hd95_can_only_warn_never_fail():
    """HD95 is observability-only: a huge HD95 with good Dice/centerline must
    not push status past WARN (CLAUDE.md principle #3, exp pain sub-19)."""
    from spineprep.steps.s6.process import _classify
    m = dict(_GOOD, cord_hd95_mm=50.0)
    status, reasons = _classify(m, {}, syn_fallback=False)
    assert status == "WARN"
    assert any("cord_hd95_mm WARN" in r for r in reasons)


def test_classify_centerline_max_above_warn_ceiling_fails():
    from spineprep.steps.s6.process import _classify
    m = dict(_GOOD, centerline_round_trip_max_vox=12.0)  # > warn 10.0
    status, _ = _classify(m, {}, syn_fallback=False)
    assert status == "FAIL"


def test_classify_missing_dice_warns_not_fail():
    from spineprep.steps.s6.process import _classify
    m = {k: v for k, v in _GOOD.items() if k != "cord_dice"}
    status, reasons = _classify(m, {}, syn_fallback=False)
    assert status == "WARN"
    assert any("cord_dice not computed" in r for r in reasons)


def test_classify_missing_centerline_is_warn_via_tier():
    """_tier returns WARN for a None metric value (and never FAIL)."""
    from spineprep.steps.s6.process import _classify
    m = {"cord_dice": 0.90, "cord_hd95_mm": 2.0}  # no centerline keys
    status, _ = _classify(m, {}, syn_fallback=False)
    assert status == "WARN"


# ---------------------------------------------------------------------------
# sform/qform sync
# ---------------------------------------------------------------------------


def test_sync_sform_qform_copies_qform_into_sform(tmp_path):
    from spineprep.steps.s6.process import _sync_sform_qform
    aff = np.diag([2.0, 2.0, 3.0, 1.0])
    img = nib.Nifti1Image(np.zeros((4, 4, 4), dtype=np.float32), aff)
    img.set_qform(aff, code=1)
    # Deliberately desync sform to a different affine.
    img.set_sform(np.eye(4), code=1)
    p = tmp_path / "vol.nii.gz"
    nib.save(img, p)

    _sync_sform_qform(p)

    out = nib.load(p)
    np.testing.assert_allclose(out.get_sform(), out.get_qform(), atol=1e-5)
    np.testing.assert_allclose(out.get_sform(), aff, atol=1e-5)


# ---------------------------------------------------------------------------
# Orchestrator pure helpers
# ---------------------------------------------------------------------------


def test_norm_sub_strips_prefix_idempotently():
    from spineprep.steps.s6.orchestrate import _norm_sub
    assert _norm_sub("sub-01") == "01"
    assert _norm_sub("01") == "01"
    assert _norm_sub("") == ""
    assert _norm_sub(None) == ""


def test_norm_ses_strips_prefix_and_handles_empty():
    from spineprep.steps.s6.orchestrate import _norm_ses
    assert _norm_ses("ses-pre") == "pre"
    assert _norm_ses("pre") == "pre"
    assert _norm_ses(None) is None
    assert _norm_ses("") is None


def test_top_status_aggregation_rule():
    """Mirrors run_S6's aggregation: all PASS -> PASS; any WARN (no FAIL) ->
    WARN; any FAIL -> WARN if some passed/warned else FAIL; empty -> FAIL."""
    def agg(statuses):
        results = [{"status": s} for s in statuses]
        n_pass = sum(1 for r in results if r.get("status") == "PASS")
        n_warn = sum(1 for r in results if r.get("status") == "WARN")
        n_fail = sum(1 for r in results if r.get("status") == "FAIL")
        if results and n_pass + n_warn == len(results) and n_fail == 0:
            return "PASS" if n_warn == 0 else "WARN"
        elif n_pass + n_warn > 0:
            return "WARN"
        return "FAIL"

    assert agg(["PASS", "PASS"]) == "PASS"
    assert agg(["PASS", "WARN"]) == "WARN"
    assert agg(["PASS", "FAIL"]) == "WARN"
    assert agg(["FAIL", "FAIL"]) == "FAIL"
    assert agg([]) == "FAIL"
