"""Tests for FD and DVARS computation."""

from __future__ import annotations

import numpy as np

from spineprep.confounds.basic import compute_dvars, compute_fd_power, detect_spikes


def test_fd_power_zero_motion():
    """Test FD with no motion (all zeros)."""
    motion = np.zeros((10, 6))
    fd = compute_fd_power(motion, radius=50.0)

    assert len(fd) == 10
    assert np.all(fd == 0), "FD should be all zeros for zero motion"


def test_fd_power_pure_translation():
    """Test FD with pure translation."""
    motion = np.zeros((5, 6))
    # Add 1mm translation in each direction at t=2
    motion[2, 0] = 1.0  # tx
    motion[2, 1] = 1.0  # ty
    motion[2, 2] = 1.0  # tz

    fd = compute_fd_power(motion, radius=50.0)

    # FD at t=0 should be 0 (first volume)
    assert fd[0] == 0

    # FD at t=1 should be 0 (no change yet)
    assert fd[1] == 0

    # FD at t=2 should be 3.0 (|1| + |1| + |1|)
    assert np.isclose(fd[2], 3.0)

    # FD at t=3 should be 3.0 (return to zero: |-1| + |-1| + |-1|)
    assert np.isclose(fd[3], 3.0)


def test_fd_power_with_rotation():
    """Test FD with rotation component."""
    motion = np.zeros((5, 6))
    # Add rotation at t=2
    motion[2, 3] = 0.01  # rx (radians)

    fd = compute_fd_power(motion, radius=50.0)

    # FD at t=2 should be 50 * 0.01 = 0.5
    assert np.isclose(fd[2], 0.5)


def test_dvars_constant_signal():
    """Test DVARS with constant signal (no change)."""
    # Constant value across time
    data = np.ones((4, 4, 2, 10), dtype=np.float32) * 100.0

    dvars = compute_dvars(data)

    assert len(dvars) == 10
    # All DVARS should be 0 (no temporal derivative)
    assert np.allclose(dvars, 0)


def test_dvars_single_jump():
    """Test DVARS with a single volume jump."""
    data = np.ones((4, 4, 2, 10), dtype=np.float32) * 100.0

    # Add jump at volume 5
    data[:, :, :, 5] += 10.0

    dvars = compute_dvars(data)

    # DVARS at t=0 should be 0 (first volume)
    assert dvars[0] == 0

    # DVARS at t=5 should be non-zero (jump up)
    assert dvars[5] > 0

    # DVARS at t=6 should be non-zero (jump down)
    assert dvars[6] > 0


def test_detect_spikes_fd_threshold():
    """Test spike detection based on FD threshold."""
    fd = np.array([0.0, 0.2, 0.6, 0.3, 0.8, 0.1])  # Spikes at t=2, t=4
    dvars = np.zeros(6)

    spike = detect_spikes(fd, dvars, fd_thr=0.5, dvars_z=10.0)

    assert spike[0] == 0  # First volume always 0
    assert spike[1] == 0  # Below threshold
    assert spike[2] == 1  # Above threshold (0.6 > 0.5)
    assert spike[3] == 0  # Below threshold
    assert spike[4] == 1  # Above threshold (0.8 > 0.5)
    assert spike[5] == 0  # Below threshold


def test_detect_spikes_dvars_zscore():
    """Test spike detection based on DVARS Z-score."""
    fd = np.zeros(10)
    # Create DVARS with outlier
    dvars = np.array([0.0, 1.0, 1.1, 1.0, 5.0, 1.0, 1.1, 1.0, 1.05, 1.0])

    spike = detect_spikes(fd, dvars, fd_thr=10.0, dvars_z=2.5)

    # t=4 should be spike (DVARS=5.0 is outlier)
    assert spike[4] == 1

    # Most other volumes should be 0
    assert spike[1] == 0


def test_detect_spikes_combined():
    """Test spike detection with both FD and DVARS."""
    fd = np.array([0.0, 0.1, 0.6, 0.2, 0.1, 0.1])  # Spike at t=2
    dvars = np.zeros(6)  # No DVARS spikes

    spike = detect_spikes(fd, dvars, fd_thr=0.5, dvars_z=2.0)

    assert spike[0] == 0  # First volume
    assert spike[1] == 0  # No spike
    assert spike[2] == 1  # FD spike
    assert spike[3] == 0  # No spike (FD and DVARS both low)
    assert spike[4] == 0  # No spike

    # Verify FD detection works independently
    assert np.sum(spike) == 1  # Only one spike from FD
