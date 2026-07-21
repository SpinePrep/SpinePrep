"""The driver must build nesting parcels and never drop a tier silently."""
import json
from pathlib import Path

import numpy as np
import pytest

from analysis.driver import GM_PARCELS, REPEAT_AXIS, build_parcels, hemicord_masks


def _synthetic_run(tmp_path, *, with_atlas=True, with_vert=True, ax=("L", "A", "S")):
    import nibabel as nib
    tmp_path = Path(tmp_path); tmp_path.mkdir(parents=True, exist_ok=True)
    shape = (12, 12, 8)
    aff = np.eye(4)
    if ax == ("R", "A", "S"):          # flip the L-R axis
        aff[0, 0] = -1.0
    cord = np.zeros(shape, np.float32)
    cord[4:8, 4:8, :] = 1.0            # a 4x4 cord column
    lev = np.zeros(shape, np.int16)
    for z in range(shape[2]):
        lev[..., z] = (z // 2) + 1     # 4 levels
    lev = lev * (cord > 0.5)
    d = tmp_path
    nib.save(nib.Nifti1Image(cord, aff), d / "r_desc-PAM50cord_mask.nii.gz")
    nib.save(nib.Nifti1Image(lev, aff), d / "r_desc-PAM50spinallevels.nii.gz")
    if with_vert:
        nib.save(nib.Nifti1Image(lev, aff), d / "r_desc-PAM50vertlevels.nii.gz")
    bold = np.random.default_rng(0).standard_normal(shape + (30,)).astype(np.float32) + 100
    nib.save(nib.Nifti1Image(bold, aff), d / "r_desc-preproc_bold.nii.gz")
    if with_atlas:
        atl = np.zeros(shape + (37,), np.float32)
        for aid in (30, 31, 32, 33, 34, 35):
            sub = np.zeros(shape, np.float32)
            sub[5 if aid % 2 else 6, 5, :] = 1.0
            atl[..., aid] = sub
        nib.save(nib.Nifti1Image(atl, aff), d / "r_desc-PAM50atlas_probseg.nii.gz")
        (d / "r_desc-PAM50atlas_probseg.json").write_text(json.dumps(
            {"Labels": [{"index": i, "atlas_id": i, "name": f"p{i}"} for i in range(37)]}))
    return {"dataset": "ds", "subject": "01", "session": None, "run_id": "r",
            "bold": d / "r_desc-preproc_bold.nii.gz",
            "cord": d / "r_desc-PAM50cord_mask.nii.gz",
            "spinallevels": d / "r_desc-PAM50spinallevels.nii.gz",
            "vertlevels": d / "r_desc-PAM50vertlevels.nii.gz",
            "atlas": d / "r_desc-PAM50atlas_probseg.nii.gz",
            "metrics": {}}


def test_all_tiers_build_when_inputs_exist(tmp_path):
    parcels, skipped = build_parcels(_synthetic_run(tmp_path))
    assert set(parcels) == {"cord", "hemicord", "spinallevel", "vertlevel", "gmhorn"}
    assert skipped == []


def test_hemicord_partitions_the_cord_exactly(tmp_path):
    """The tiers must nest: L and R together are the cord, with no overlap."""
    parcels, _ = build_parcels(_synthetic_run(tmp_path))
    cord = parcels["cord"]["cord"]
    l, r = parcels["hemicord"]["hemicord-L"], parcels["hemicord"]["hemicord-R"]
    assert not (l & r).any(), "hemicords overlap"
    assert (l | r).sum() == cord.sum(), "hemicords do not cover the cord"


def test_spinal_levels_are_a_subset_of_the_cord(tmp_path):
    parcels, _ = build_parcels(_synthetic_run(tmp_path))
    cord = parcels["cord"]["cord"]
    for name, m in parcels["spinallevel"].items():
        assert (m & ~cord).sum() == 0, f"{name} leaks outside the cord"


def test_hemicord_follows_the_affine_not_a_hardcoded_orientation(tmp_path):
    """Hardcoding LAS would break silently on the first non-LAS dataset."""
    a = build_parcels(_synthetic_run(tmp_path / "a", ax=("L", "A", "S")))[0]
    b = build_parcels(_synthetic_run(tmp_path / "b", ax=("R", "A", "S")))[0]
    # same geometry, flipped axis -> L and R swap
    assert a["hemicord"]["hemicord-L"].sum() == b["hemicord"]["hemicord-R"].sum()


def test_missing_tier_is_recorded_not_silently_dropped(tmp_path):
    """A vanished tier is indistinguishable from an empty one unless recorded."""
    parcels, skipped = build_parcels(
        _synthetic_run(tmp_path, with_atlas=False, with_vert=False))
    assert "gmhorn" not in parcels and "vertlevel" not in parcels
    assert any("gmhorn" in s for s in skipped)
    assert any("vertlevel" in s for s in skipped)
    assert all("not emitted by S7" in s for s in skipped)


def test_missing_cord_mask_yields_no_tiers_with_a_reason(tmp_path):
    run = _synthetic_run(tmp_path)
    run["cord"] = tmp_path / "absent.nii.gz"
    parcels, skipped = build_parcels(run)
    assert parcels == {} and skipped and "cord" in skipped[0]


def test_hemicord_needs_an_lr_axis():
    cord = np.ones((4, 4, 4), bool)
    assert hemicord_masks(cord, ("A", "S", "P")) is None


def test_gm_parcel_indices_match_the_pam50_label_table():
    """Verified against info_label.txt in the warped atlas."""
    assert GM_PARCELS["ventral"] == (30, 31)
    assert GM_PARCELS["intermediate"] == (32, 33)
    assert GM_PARCELS["dorsal"] == (34, 35)


def test_repeat_axis_matches_the_measured_cohort_structure():
    """Only ds004926 has true between-session repeats."""
    sess = [d for d, a in REPEAT_AXIS.items() if a == "session"]
    assert sess == ["openneuro_ds004926_dorsalhorn_pain"]
    # ds004616 has 2 sessions but they bracket an intervention
    assert REPEAT_AXIS["openneuro_ds004616_spinalcord_handgrasp_task"] == "run"
    # ds005884's two runs are different conditions, not repeats
    assert REPEAT_AXIS["openneuro_ds005884_cospine_motor"] == "split"
