"""Censoring logic for motion-based frame exclusion."""

from __future__ import annotations

import numpy as np


def make_censor_columns(
    fd: np.ndarray, dvars: np.ndarray, cfg: dict
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Create censoring columns based on FD and DVARS thresholds.

    Args:
        fd: Framewise displacement array (n_timepoints,)
        dvars: DVARS array (n_timepoints,)
        cfg: Configuration dict with keys:
             - fd_thresh: FD threshold in mm
             - dvars_thresh: DVARS threshold

    Returns:
        Tuple of (censor_fd, censor_dvars, censor_any):
        - censor_fd: binary array (1=censor, 0=keep) for FD
        - censor_dvars: binary array (1=censor, 0=keep) for DVARS
        - censor_any: binary array (1=censor, 0=keep) for ANY condition
        All arrays are int8 with values 0 or 1
    """
    if len(fd) != len(dvars):
        raise ValueError(
            f"FD and DVARS must have same length: {len(fd)} vs {len(dvars)}"
        )

    len(fd)

    # Get thresholds from config
    fd_thresh = cfg.get("fd_thresh", 0.5)
    dvars_thresh = cfg.get("dvars_thresh", 1.5)

    # Create censoring masks (boolean)
    censor_fd_bool = fd > fd_thresh
    censor_dvars_bool = dvars > dvars_thresh
    censor_any_bool = censor_fd_bool | censor_dvars_bool

    # Convert to int8 (0/1)
    censor_fd = censor_fd_bool.astype(np.int8)
    censor_dvars = censor_dvars_bool.astype(np.int8)
    censor_any = censor_any_bool.astype(np.int8)

    return censor_fd, censor_dvars, censor_any
