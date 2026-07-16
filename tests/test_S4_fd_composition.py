"""S4 FD composition: matched units, per-slice reduction, LAS-verified signs.

Audit 2026-07-16 found two defects in the old reduction
(`params_total['tx'] += mx.mean(axis=(0,1,2))`):

  1. Stage 1 is in VOXELS (FLIRT runs on a projection written with an identity
     affine, so its world-mm are the fake 1mm grid). Stage 2 is in MM (ANTs warp
     components, per SCT's moco.py). The two were summed and thresholded in mm,
     so Stage-1 motion was under-counted by the in-plane voxel size on every
     dataset that is not 1.0mm -- FD was not comparable across datasets.
  2. The SIGNED slice field was averaged, so opposing rostral/caudal slice shifts
     cancelled. SCT's own convention takes magnitude first for this reason.

Signs were verified by synthetic test at the cohort's real LAS geometry: both
stages agree per axis there, so they compose by addition. (Under RAS the X
components disagree -- hence the orientation guard.)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import numpy as np
from spineprep.lib.moco import compose_cord_fd


def _slicewise(nz, nt, val_per_slice):
    """(1,1,nz,nt) ANTs-style field."""
    a = np.zeros((1, 1, nz, nt))
    for z, v in enumerate(val_per_slice):
        a[0, 0, z, :] = v
    return a


def test_stage1_is_scaled_from_voxels_to_mm():
    """A 1-voxel bulk step on a 1.5mm grid is 1.5mm of motion, not 1.0."""
    tx = np.array([0.0, 1.0])       # 1 voxel between frames
    ty = np.zeros(2)
    fd, info = compose_cord_fd(tx, ty, None, None, voxsize_x=1.5, voxsize_y=1.5)
    assert fd[0] == 0.0                       # Power 2014 convention
    assert abs(fd[1] - 1.5) < 1e-9, f"expected 1.5mm, got {fd[1]}"
    assert info["stage1_scaled_to_mm_by"] == [1.5, 1.5]


def test_fd_is_now_comparable_across_voxel_sizes():
    """The same PHYSICAL motion must give the same FD on 1.0mm and 1.5mm grids.
    This is what the old code got wrong."""
    # 3mm of physical motion = 3 voxels at 1.0mm, or 2 voxels at 1.5mm
    fd_1mm, _ = compose_cord_fd(np.array([0.0, 3.0]), np.zeros(2), None, None, 1.0, 1.0)
    fd_15mm, _ = compose_cord_fd(np.array([0.0, 2.0]), np.zeros(2), None, None, 1.5, 1.5)
    assert abs(fd_1mm[1] - 3.0) < 1e-9
    assert abs(fd_15mm[1] - 3.0) < 1e-9
    assert abs(fd_1mm[1] - fd_15mm[1]) < 1e-9, (
        "same physical motion must give the same FD regardless of voxel size; "
        "the old code reported 2.0 vs 3.0 here")


def test_opposing_slice_shifts_do_not_cancel():
    """The old mean-of-signed-shifts cancelled opposing rostral/caudal motion.
    Slice 0 moves +1mm while slice 1 moves -1mm: signed mean is 0, but the cord
    genuinely moved in both slices, so FD must be 1.0, not 0."""
    nt = 2
    sx = np.zeros((1, 1, 2, nt))
    sx[0, 0, 0, 1] = +1.0    # slice 0 moves +1mm at t=1
    sx[0, 0, 1, 1] = -1.0    # slice 1 moves -1mm at t=1
    sy = np.zeros((1, 1, 2, nt))
    fd, info = compose_cord_fd(np.zeros(nt), np.zeros(nt), sx, sy, 1.0, 1.0)
    assert abs(fd[1] - 1.0) < 1e-9, (
        f"opposing slice shifts cancelled: FD={fd[1]} (old signed-mean bug)")
    assert "no cancellation" in info["reduction"]


def test_both_stages_compose_additively():
    """Bulk 1 voxel (=1mm here) + slice-wise 0.5mm -> 1.5mm total."""
    nt = 2
    sx = _slicewise(3, nt, [0.0, 0.0, 0.0])
    sx[0, 0, :, 1] = 0.5
    sy = np.zeros((1, 1, 3, nt))
    fd, _ = compose_cord_fd(np.array([0.0, 1.0]), np.zeros(nt), sx, sy, 1.0, 1.0)
    assert abs(fd[1] - 1.5) < 1e-9


def test_non_las_orientation_is_flagged():
    """Stage-2's sign follows the affine; the composition is verified for LAS
    only, so anything else must be reported rather than silently trusted."""
    fd, info = compose_cord_fd(np.zeros(2), np.zeros(2), None, None, 1.0, 1.0,
                               axcodes=("R", "A", "S"))
    assert "orientation_warning" in info
    fd, info = compose_cord_fd(np.zeros(2), np.zeros(2), None, None, 1.0, 1.0,
                               axcodes=("L", "A", "S"))
    assert "orientation_warning" not in info


def test_fd_first_frame_is_zero_per_power_2014():
    rng = np.random.default_rng(0)
    tx = rng.normal(0, 1, 20)
    fd, _ = compose_cord_fd(tx, np.zeros(20), None, None, 1.0, 1.0)
    assert fd[0] == 0.0
    assert len(fd) == 20
