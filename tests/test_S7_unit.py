"""Unit tests for S7 template-normalization pure helpers.

Covers the deterministic logic in s7/process.py (Dice, per-level Dice,
status classification, refinement param string) and the pure path
normalizers + aggregation rule in s7/orchestrate.py. No SCT/FSL binaries
and no real data: synthetic numpy/nibabel masks written into tmp_path.
"""
from __future__ import annotations

import nibabel as nib
import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Dice (_binarize / _dice)
# ---------------------------------------------------------------------------


def test_dice_identical_masks_is_one():
    from spineprep.steps.s7.process import _dice
    a = np.zeros((8, 8, 4))
    a[2:6, 2:6, :] = 1.0
    assert _dice(a, a.copy()) == 1.0


def test_dice_disjoint_masks_is_zero():
    from spineprep.steps.s7.process import _dice
    a = np.zeros((8, 8, 4)); a[0:2, 0:2, :] = 1.0
    b = np.zeros((8, 8, 4)); b[6:8, 6:8, :] = 1.0
    assert _dice(a, b) == 0.0


def test_dice_both_empty_is_zero_not_nan():
    """Empty-vs-empty must short-circuit to 0.0, not divide by zero."""
    from spineprep.steps.s7.process import _dice
    z = np.zeros((4, 4, 2))
    val = _dice(z, z)
    assert val == 0.0
    assert not np.isnan(val)


def test_dice_half_overlap_value():
    """Two equal-size masks overlapping in half their voxels -> Dice 0.5.

    a = 8 voxels, b = 8 voxels (4 shared). Dice = 2*4 / (8+8) = 0.5.
    """
    from spineprep.steps.s7.process import _dice
    a = np.zeros((8, 1, 1)); a[0:8] = 1.0  # voxels 0..7
    b = np.zeros((8, 1, 1)); b[4:8] = 1.0  # voxels 4..7 (4 shared, b has 4)
    # a=8, b=4, overlap=4 -> 2*4/(8+4) = 8/12
    assert _dice(a, b) == pytest.approx(8 / 12)


def test_binarize_threshold_is_strict_greater_than():
    from spineprep.steps.s7.process import _binarize
    arr = np.array([0.0, 0.5, 0.51, 1.0])
    out = _binarize(arr, threshold=0.5)
    # 0.5 is NOT > 0.5, so it stays False
    assert out.tolist() == [False, False, True, True]
    assert out.dtype == bool


# ---------------------------------------------------------------------------
# Status classification (_classify)
# ---------------------------------------------------------------------------


_THR = {"pass_dice_min": 0.80, "fail_dice_below": 0.65}


def test_classify_pass_above_pass_floor():
    from spineprep.steps.s7.process import _classify
    status, reasons = _classify({"cord_dice_native_func": 0.85}, _THR)
    assert status == "PASS"
    assert reasons == []


def test_classify_warn_between_fail_and_pass_floors():
    from spineprep.steps.s7.process import _classify
    # 0.70 is >= fail_below (0.65) but < pass_min (0.80) -> WARN
    status, reasons = _classify({"cord_dice_native_func": 0.70}, _THR)
    assert status == "WARN"
    assert any("WARN" in r for r in reasons)


def test_classify_pass_floor_boundary_is_inclusive_pass():
    """Exactly at pass_dice_min must PASS (the WARN branch is `< pass_dice`)."""
    from spineprep.steps.s7.process import _classify
    status, _ = _classify({"cord_dice_native_func": 0.80}, _THR)
    assert status == "PASS"


def test_classify_fail_floor_boundary_is_inclusive_warn():
    """Exactly at fail_dice_below must NOT fail (the FAIL branch is
    `< fail_below`); it lands in WARN instead."""
    from spineprep.steps.s7.process import _classify
    status, _ = _classify({"cord_dice_native_func": 0.65}, _THR)
    assert status == "WARN"


def test_classify_fail_below_fail_floor():
    from spineprep.steps.s7.process import _classify
    status, reasons = _classify({"cord_dice_native_func": 0.50}, _THR)
    assert status == "FAIL"
    assert any("FAIL" in r for r in reasons)


def test_classify_missing_dice_warns_not_fails():
    """No cord_dice metric -> WARN with an explanatory reason, never PASS."""
    from spineprep.steps.s7.process import _classify
    status, reasons = _classify({}, _THR)
    assert status == "WARN"
    assert any("not computed" in r for r in reasons)


def test_classify_uses_default_thresholds_when_empty():
    """Empty thresholds fall back to pass=0.80 / fail=0.65 defaults."""
    from spineprep.steps.s7.process import _classify
    assert _classify({"cord_dice_native_func": 0.90}, {})[0] == "PASS"
    assert _classify({"cord_dice_native_func": 0.70}, {})[0] == "WARN"
    assert _classify({"cord_dice_native_func": 0.40}, {})[0] == "FAIL"


# ---------------------------------------------------------------------------
# Per-vertebral-level Dice (_cord_dice_per_level) on synthetic NIfTI files
# ---------------------------------------------------------------------------


def _save(arr, path, zooms=(1.0, 1.0, 1.0)):
    img = nib.Nifti1Image(arr, np.eye(4))
    img.header.set_zooms(zooms)
    nib.save(img, str(path))
    return path


def test_per_level_perfect_overlap_gives_dice_one(tmp_path):
    """Two identical cord masks split across two vertebral levels -> Dice 1.0
    on each level, coverage = both level ids."""
    from spineprep.steps.s7.process import _cord_dice_per_level
    shape = (6, 6, 4)
    cord = np.zeros(shape, dtype=np.float32)
    cord[2:4, 2:4, :] = 1.0  # cord present in every Z slice
    levels = np.zeros(shape, dtype=np.float32)
    levels[:, :, 0:2] = 1  # level 1 occupies Z 0..1
    levels[:, :, 2:4] = 2  # level 2 occupies Z 2..3

    cp = _save(cord, tmp_path / "cord_pam50.nii.gz")
    cf = _save(cord.copy(), tmp_path / "cord_func.nii.gz")
    lv = _save(levels, tmp_path / "levels.nii.gz")

    per_level, coverage = _cord_dice_per_level(cp, cf, lv)
    assert coverage == [1, 2]
    assert per_level[1] == pytest.approx(1.0)
    assert per_level[2] == pytest.approx(1.0)


def test_per_level_disjoint_cords_give_dice_zero(tmp_path):
    """When the two cord masks never co-occur, per-level Dice is 0 wherever
    both masks contribute voxels, and the level is dropped when one mask is
    empty there (denom==0)."""
    from spineprep.steps.s7.process import _cord_dice_per_level
    shape = (8, 8, 2)
    cord_a = np.zeros(shape, dtype=np.float32); cord_a[1:3, 1:3, :] = 1.0
    cord_b = np.zeros(shape, dtype=np.float32); cord_b[5:7, 5:7, :] = 1.0
    levels = np.ones(shape, dtype=np.float32)  # single level covering all Z

    ca = _save(cord_a, tmp_path / "a.nii.gz")
    cb = _save(cord_b, tmp_path / "b.nii.gz")
    lv = _save(levels, tmp_path / "lv.nii.gz")

    per_level, coverage = _cord_dice_per_level(ca, cb, lv)
    assert coverage == [1]
    # Both masks have voxels in level 1's slices, but they never overlap.
    assert per_level.get(1) == pytest.approx(0.0)


def test_per_level_shape_mismatch_returns_empty(tmp_path):
    """Mismatched array shapes are a guard condition -> ({}, [])."""
    from spineprep.steps.s7.process import _cord_dice_per_level
    cp = _save(np.ones((6, 6, 4), np.float32), tmp_path / "cp.nii.gz")
    cf = _save(np.ones((6, 6, 4), np.float32), tmp_path / "cf.nii.gz")
    lv = _save(np.ones((6, 6, 3), np.float32), tmp_path / "lv.nii.gz")  # wrong Z
    per_level, coverage = _cord_dice_per_level(cp, cf, lv)
    assert per_level == {} and coverage == []


def test_per_level_ignores_background_label_zero(tmp_path):
    """Label value 0 is background and must not become a 'level'."""
    from spineprep.steps.s7.process import _cord_dice_per_level
    shape = (6, 6, 4)
    cord = np.zeros(shape, dtype=np.float32); cord[2:4, 2:4, :] = 1.0
    levels = np.zeros(shape, dtype=np.float32)
    levels[:, :, 2:4] = 3  # only Z 2..3 labelled (level 3); Z 0..1 = background 0
    cp = _save(cord, tmp_path / "cp.nii.gz")
    cf = _save(cord.copy(), tmp_path / "cf.nii.gz")
    lv = _save(levels, tmp_path / "lv.nii.gz")
    per_level, coverage = _cord_dice_per_level(cp, cf, lv)
    assert coverage == [3]
    assert 0 not in per_level


# ---------------------------------------------------------------------------
# Refinement param string (_build_refine_param)
# ---------------------------------------------------------------------------


def test_build_refine_param_defaults_match_sct_recipe():
    """Empty cfg -> SCT canonical fMRI recipe: slicereg(seg) then bsplinesyn(im)."""
    from spineprep.steps.s7.process import _build_refine_param
    s = _build_refine_param({})
    step1, step2 = s.split(":")
    assert step1 == "step=1,type=seg,algo=slicereg,metric=MeanSquares,smooth=2"
    assert step2 == "step=2,type=im,algo=bsplinesyn,metric=MeanSquares,iter=5,gradStep=0.5"


def test_build_refine_param_overrides_apply():
    """Per-step overrides replace the defaults in place."""
    from spineprep.steps.s7.process import _build_refine_param
    s = _build_refine_param({"step2": {"iter": 10, "gradStep": 0.2}})
    _, step2 = s.split(":")
    assert "iter=10" in step2
    assert "gradStep=0.2" in step2
    assert "iter=5" not in step2


# ---------------------------------------------------------------------------
# Orchestrate path normalizers (_norm_sub / _norm_ses)
# ---------------------------------------------------------------------------


def test_norm_sub_strips_prefix_only_once():
    from spineprep.steps.s7.orchestrate import _norm_sub
    assert _norm_sub("sub-01") == "01"
    assert _norm_sub("01") == "01"
    assert _norm_sub("") == ""
    assert _norm_sub(None) == ""


def test_norm_ses_handles_none_and_prefix():
    from spineprep.steps.s7.orchestrate import _norm_ses
    assert _norm_ses("ses-baseline") == "baseline"
    assert _norm_ses("baseline") == "baseline"
    assert _norm_ses(None) is None
    assert _norm_ses("") is None


# ---------------------------------------------------------------------------
# Top-level aggregation rule (mirrors run_S7 in orchestrate.py)
# ---------------------------------------------------------------------------


def _agg(results):
    """Replicates the PASS/WARN/FAIL aggregation in run_S7."""
    n_pass = sum(1 for r in results if r.get("status") == "PASS")
    n_warn = sum(1 for r in results if r.get("status") == "WARN")
    n_fail = sum(1 for r in results if r.get("status") == "FAIL")
    if results and n_pass + n_warn == len(results) and n_fail == 0:
        return "PASS" if n_warn == 0 else "WARN"
    if n_pass + n_warn > 0:
        return "WARN"
    return "FAIL"


def test_aggregate_all_pass_is_pass():
    assert _agg([{"status": "PASS"}, {"status": "PASS"}]) == "PASS"


def test_aggregate_any_warn_is_warn():
    assert _agg([{"status": "PASS"}, {"status": "WARN"}]) == "WARN"


def test_aggregate_mixed_with_fail_is_warn_when_some_ok():
    assert _agg([{"status": "PASS"}, {"status": "FAIL"}]) == "WARN"


def test_aggregate_all_fail_is_fail():
    assert _agg([{"status": "FAIL"}, {"status": "FAIL"}]) == "FAIL"
    assert _agg([]) == "FAIL"


# ---------------------------------------------------------------------------
# Per-level Dice gate: three-banded PASS / WARN / FAIL
#
# Regression for the cohort finding (9 datasets / 456 runs): a single hard FAIL
# cliff at the 0.90 PASS level sat inside the distribution's own low tail and
# split runs of the SAME subject and acquisition. 0.85 is the FAIL floor; the
# band between routes to visual inspection instead of discarding the run.
# ---------------------------------------------------------------------------


_PLTHR = {
    "per_level_pass_min": 0.90,
    "per_level_fail_below": 0.85,
    "per_level_broken_below": 0.50,
    "pass_dice_min": 0.80,
    "fail_dice_below": 0.65,
}


def _pl(*vals):
    return {"cord_dice_per_level": {str(i): v for i, v in enumerate(vals)}}


def test_per_level_pass_above_pass_floor():
    from spineprep.steps.s7.process import _classify
    status, _ = _classify(_pl(0.97, 0.98, 0.99), _PLTHR)
    assert status == "PASS"


def test_per_level_warn_band_between_fail_and_pass():
    """The band that motivated the change: 0.88 is no longer a FAIL."""
    from spineprep.steps.s7.process import _classify
    status, reasons = _classify(_pl(0.87, 0.88, 0.89), _PLTHR)
    assert status == "WARN"
    assert any("WARN" in r for r in reasons)


def test_per_level_sibling_runs_no_longer_split_across_fail():
    """0.8997 and 0.9019 differ by run-to-run noise; neither may FAIL."""
    from spineprep.steps.s7.process import _classify
    lo, _ = _classify(_pl(0.8997, 0.8997, 0.8997), _PLTHR)
    hi, _ = _classify(_pl(0.9019, 0.9019, 0.9019), _PLTHR)
    assert lo == "WARN" and hi == "PASS"
    assert "FAIL" not in (lo, hi)


def test_per_level_genuine_outlier_still_fails():
    """The cohort's real failure group (<=0.82) must still FAIL."""
    from spineprep.steps.s7.process import _classify
    for med in (0.688, 0.805, 0.821):
        status, _ = _classify(_pl(med, med, med), _PLTHR)
        assert status == "FAIL", med


def test_per_level_pass_floor_boundary_is_inclusive_pass():
    from spineprep.steps.s7.process import _classify
    status, _ = _classify(_pl(0.90, 0.90, 0.90), _PLTHR)
    assert status == "PASS"


def test_per_level_fail_floor_boundary_is_inclusive_warn():
    from spineprep.steps.s7.process import _classify
    status, _ = _classify(_pl(0.85, 0.85, 0.85), _PLTHR)
    assert status == "WARN"


def test_per_level_broken_level_reported_inside_warn_band():
    """A broken level is its own diagnostic and must survive the WARN band."""
    from spineprep.steps.s7.process import _classify
    status, reasons = _classify(_pl(0.0, 0.88, 0.89), _PLTHR)
    assert status == "WARN"
    assert any("exclude that level" in r for r in reasons)


def test_per_level_broken_level_still_warns_when_median_passes():
    from spineprep.steps.s7.process import _classify
    status, reasons = _classify(_pl(0.0, 0.97, 0.98), _PLTHR)
    assert status == "WARN"
    assert any("exclude that level" in r for r in reasons)


# ---------------------------------------------------------------------------
# Native-space atlas export (added 2026-07-21 for the analysis endpoints)
#
# sct_warp_template already produced the full PAM50 atlas, vertebral levels and
# rootlets on every run; they were left in the work tree and never emitted.
# Exporting them is a file copy, not a recomputation. The grey-matter parcels
# are what the cord literature reports on (dorsal/ventral horn), so the label
# table must make them unambiguous.
# ---------------------------------------------------------------------------


def _fake_label_tree(tmp_path):
    import nibabel as nib
    import numpy as np
    lab = tmp_path / "label"
    (lab / "template").mkdir(parents=True)
    (lab / "atlas").mkdir(parents=True)
    aff = np.eye(4)
    for stem in ("PAM50_cord", "PAM50_gm", "PAM50_spinal_levels",
                 "PAM50_levels", "PAM50_rootlets"):
        nib.save(nib.Nifti1Image(np.ones((4, 4, 3), np.float32), aff),
                 lab / "template" / f"{stem}.nii.gz")
    rows = [(30, "GM left ventral horn"), (34, "GM left dorsal horn"),
            (4, "WM left lateral corticospinal tract")]
    for idx, _ in rows:
        nib.save(nib.Nifti1Image(np.full((4, 4, 3), 0.5, np.float32), aff),
                 lab / "atlas" / f"PAM50_atlas_{idx:02d}.nii.gz")
    (lab / "atlas" / "info_label.txt").write_text(
        "# comment line\n" +
        "\n".join(f"{i}, {n}, PAM50_atlas_{i:02d}.nii.gz" for i, n in rows))
    return lab


def test_atlas_export_emits_vertebral_levels_and_rootlets(tmp_path):
    """Vertebral levels are a DIFFERENT parcellation from spinal levels."""
    from spineprep.steps.s7.process import _copy_native_atlas
    lab = _fake_label_tree(tmp_path)
    out = tmp_path / "func"; out.mkdir()
    paths = _copy_native_atlas(lab, ["PAM50_cord", "PAM50_spinal_levels",
                                     "PAM50_levels", "PAM50_rootlets"], out, "sub-01")
    assert "PAM50vertlevels" in paths
    assert "PAM50spinallevels" in paths
    assert paths["PAM50vertlevels"] != paths["PAM50spinallevels"]
    assert "PAM50rootlets" in paths


def test_atlas_export_writes_one_4d_file_with_a_label_table(tmp_path):
    import json
    import nibabel as nib
    from spineprep.steps.s7.process import _copy_native_atlas
    lab = _fake_label_tree(tmp_path)
    out = tmp_path / "func"; out.mkdir()
    paths = _copy_native_atlas(lab, ["PAM50_cord"], out, "sub-01")
    p = paths.get("PAM50atlas_probseg")
    assert p, "probabilistic atlas not emitted"
    img = nib.load(p)
    assert img.ndim == 4 and img.shape[3] == 3
    meta = json.loads(open(p.replace(".nii.gz", ".json")).read())
    assert len(meta["Labels"]) == 3
    # index must address the 4th dimension; atlas_id is the PAM50 number
    assert [l["index"] for l in meta["Labels"]] == [0, 1, 2]
    assert {l["atlas_id"] for l in meta["Labels"]} == {4, 30, 34}


def test_atlas_export_identifies_the_grey_matter_horn_parcels(tmp_path):
    """These are the parcels the cord literature reports on."""
    import json
    from spineprep.steps.s7.process import _copy_native_atlas
    lab = _fake_label_tree(tmp_path)
    out = tmp_path / "func"; out.mkdir()
    paths = _copy_native_atlas(lab, [], out, "sub-01")
    meta = json.loads(open(paths["PAM50atlas_probseg"].replace(".nii.gz", ".json")).read())
    gm = [l for l in meta["Labels"] if l["name"].startswith("GM")]
    assert len(gm) == 2
    assert any("dorsal horn" in l["name"] for l in gm)


def test_atlas_export_is_optional_and_never_fails_the_run(tmp_path):
    """A missing atlas directory must not break S7."""
    from spineprep.steps.s7.process import _copy_native_atlas
    lab = tmp_path / "label"; (lab / "template").mkdir(parents=True)
    out = tmp_path / "func"; out.mkdir()
    paths = _copy_native_atlas(lab, ["PAM50_cord"], out, "sub-01")
    assert "PAM50atlas_probseg" not in paths
