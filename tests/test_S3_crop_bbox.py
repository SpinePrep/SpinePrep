"""S3 crop box must enclose the whole cord.

Regression for the 2026-07-19 cohort finding: the box was built as
``coords.max() + pad`` and then used as a Python slice stop, which excludes the
stop index -- so the most superior cord slice of EVERY run was discarded. 40/40
runs sampled from the 469-run cohort had lost exactly one cord slice, always at
the superior (rostral) end. No metric could see it, so the containment check is
part of the fix.
"""
import numpy as np
import pytest

from spineprep.steps.s3.localize import (
    CROP_PAD_XY,
    CROP_PAD_Z,
    _cord_crop_bbox,
    _crop_contains_cord,
)


def _coords(rs, cs, ss):
    return np.array([[r, c, s] for r in rs for c in cs for s in ss])


def test_crop_keeps_every_cord_slice():
    """The exact cohort failure: a cord spanning z=5..14 must keep 10 slices."""
    coords = _coords([30], [30], range(5, 15))
    shape = (64, 64, 40)
    bbox = _cord_crop_bbox(coords, shape)
    s0, s1 = bbox[4], bbox[5]
    assert s1 - s0 == 10, "all 10 cord slices must survive the crop"
    assert s0 == 5 and s1 == 15, "half-open box must span z=5..14 inclusive"


def test_crop_keeps_superior_slice_specifically():
    """Before the fix the TOP slice was dropped while the bottom was kept."""
    coords = _coords([30], [30], range(5, 15))
    bbox = _cord_crop_bbox(coords, (64, 64, 40))
    kept = np.zeros(40, bool)
    kept[bbox[4]:bbox[5]] = True
    assert kept[5], "inferior-most cord slice must be kept"
    assert kept[14], "superior-most cord slice must be kept (this was the bug)"


def test_crop_padding_is_symmetric_in_plane():
    """The missing +1 also made in-plane padding 10 low / 9 high."""
    coords = _coords([30], [30], [10])
    bbox = _cord_crop_bbox(coords, (64, 64, 40))
    assert 30 - bbox[0] == CROP_PAD_XY
    assert bbox[1] - 1 - 30 == CROP_PAD_XY
    assert 30 - bbox[2] == CROP_PAD_XY
    assert bbox[3] - 1 - 30 == CROP_PAD_XY


def test_crop_z_has_no_padding_by_design():
    coords = _coords([30], [30], range(5, 15))
    bbox = _cord_crop_bbox(coords, (64, 64, 40))
    assert 5 - bbox[4] == CROP_PAD_Z
    assert bbox[5] - 1 - 14 == CROP_PAD_Z


def test_crop_clips_to_image_bounds():
    """A cord touching the slab edge must not produce an out-of-range box."""
    coords = _coords([0, 63], [0, 63], [0, 39])
    shape = (64, 64, 40)
    bbox = _cord_crop_bbox(coords, shape)
    assert bbox[0] >= 0 and bbox[2] >= 0 and bbox[4] >= 0
    assert bbox[1] <= shape[0] and bbox[3] <= shape[1] and bbox[5] <= shape[2]


def test_crop_actually_slices_all_cord_voxels():
    """End-to-end: apply the box to a volume and count surviving cord voxels."""
    shape = (64, 64, 40)
    vol = np.zeros(shape)
    vol[28:33, 28:33, 5:15] = 1
    coords = np.argwhere(vol > 0)
    bbox = _cord_crop_bbox(coords, shape)
    cropped = vol[bbox[0]:bbox[1], bbox[2]:bbox[3], bbox[4]:bbox[5]]
    assert cropped.sum() == vol.sum(), "no cord voxel may be lost"
    z_before = np.where(vol.any(axis=(0, 1)))[0]
    z_after = np.where(cropped.any(axis=(0, 1)))[0]
    assert len(z_after) == len(z_before) == 10


# --- the containment guard ------------------------------------------------


def test_containment_accepts_a_correct_box():
    coords = _coords([30], [30], range(5, 15))
    bbox = _cord_crop_bbox(coords, (64, 64, 40))
    ok, msg = _crop_contains_cord(coords, bbox)
    assert ok and msg == ""


def test_containment_catches_the_original_off_by_one():
    """The guard must reject the pre-fix box that dropped the top slice."""
    coords = _coords([30], [30], range(5, 15))
    bad = [20, 41, 20, 41, 5, 14]          # old behaviour: stop == max, not max+1
    ok, msg = _crop_contains_cord(coords, bad)
    assert not ok
    assert "S-I high edge" in msg


def test_containment_catches_a_low_edge_loss():
    coords = _coords([30], [30], range(5, 15))
    bad = [20, 41, 20, 41, 6, 15]
    ok, msg = _crop_contains_cord(coords, bad)
    assert not ok
    assert "S-I low edge" in msg


def test_containment_is_vacuously_true_for_empty_segmentation():
    ok, msg = _crop_contains_cord(np.empty((0, 3), int), [0, 1, 0, 1, 0, 1])
    assert ok and msg == ""
