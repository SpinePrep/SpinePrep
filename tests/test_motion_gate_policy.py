"""Motion no longer rejects runs; censoring is on intensity metrics.

Decision 2026-07-16, evidence in .claude/specs/s4-fd-threshold.md:
  * S4's job is motion CORRECTION, so its gate asks whether the correction
    succeeded (cord tSNR), not whether the subject moved.
  * Censoring moves to the intensity metrics (dVARS/refRMS, within-run Tukey) --
    the cord field's design (Kaptan 2023 uses no FD at all) and the only metric
    here with a principled null (Afyouni & Nichols 2018).
  * The old absolute FD>0.5mm flagged a median 48% of frames while post-moco
    residual DVARS is flat below 0.5mm, and its FAIL pattern tracked TR
    (1.55-3.26s across the cohort) rather than motion.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import numpy as np
import pandas as pd
import yaml

from spineprep.steps.s8.process import (
    _build_outlier_columns, _opt_float, _outlier_family_description,
)

REPO = Path(__file__).parent.parent


def _frames(n=100, dvars_spike_at=None):
    rng = np.random.default_rng(0)
    dvars = rng.normal(100, 3, n)
    refrms = rng.normal(50, 2, n)
    if dvars_spike_at is not None:
        dvars[dvars_spike_at] = 400.0
    return pd.DataFrame({"dvars": dvars, "ref_rms": refrms})


# --- policy defaults --------------------------------------------------------

def test_s8_policy_fd_censoring_is_off_by_default():
    pol = yaml.safe_load((REPO / "policy" / "S8_confounds.yaml").read_text())
    assert pol["motion"]["fd_outlier_threshold_mm"] is None
    # the intensity rules stay on, data-relative
    assert pol["motion"]["dvars_outlier_iqr_k"] == 1.5
    assert pol["motion"]["refrms_outlier_iqr_k"] == 1.5


def test_s4_policy_motion_fail_gate_is_off_by_default():
    pol = yaml.safe_load((REPO / "policy" / "S4_func_motion_correction.yaml").read_text())
    qt = pol["qc_thresholds"]
    assert qt["max_high_motion_fraction"] is None, "S4 must not FAIL runs on motion"
    assert qt["min_tsnr"] == 3.0, "the technical-failure gate stays"


# --- the censoring rule -----------------------------------------------------

def test_fd_does_not_censor_by_default():
    """A run with huge FD but clean intensities must lose NO frames."""
    fm = _frames(100)
    fd = np.full(100, 5.0)          # every frame far over the old 0.5mm gate
    cols, n = _build_outlier_columns(fm, fd, fd_thresh=None)
    assert n == 0, f"FD alone censored {n} frames; it must not censor by default"


def test_intensity_spike_still_censors():
    """The metric that should censor still does."""
    fm = _frames(100, dvars_spike_at=42)
    fd = np.zeros(100)
    cols, n = _build_outlier_columns(fm, fd, fd_thresh=None)
    assert n >= 1
    assert cols["motion_outlier_00"][42] == 1.0


def test_fd_censoring_can_be_re_enabled_by_an_operator():
    fm = _frames(100)
    fd = np.zeros(100); fd[7] = 5.0
    cols, n = _build_outlier_columns(fm, fd, fd_thresh=0.5)
    assert n >= 1 and cols["motion_outlier_00"][7] == 1.0


def test_opt_float_handles_null_policy():
    assert _opt_float(None) is None
    assert _opt_float("") is None
    assert _opt_float(0.5) == 0.5


# --- the sidecar must not lie ----------------------------------------------

def test_sidecar_description_matches_actual_rule():
    """The BIDS sidecar ships in the derivatives; it must state what ran.
    The old string hardcoded 'FD > %.2f mm OR ...' and would also raise on null."""
    pol = {"motion": {"fd_outlier_threshold_mm": None,
                      "dvars_outlier_iqr_k": 1.5, "refrms_outlier_iqr_k": 1.5}}
    d = _outlier_family_description(pol)
    assert "FD >" not in d
    assert "DVARS" in d and "refRMS" in d
    assert "does not censor by default" in d
    # and when an operator turns it on, it must say so
    pol["motion"]["fd_outlier_threshold_mm"] = 0.5
    d2 = _outlier_family_description(pol)
    assert "FD > 0.50 mm (operator-enabled)" in d2
