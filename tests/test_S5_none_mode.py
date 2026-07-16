"""S5 `none` passthrough: measure distortion, correct nothing.

`none` is the cord field's own default — most cord fMRI performs no
retrospective SDC and addresses distortion at acquisition (z-shimming: Eippert
2017, Kaptan 2023; cord-focused shim: Kinany 2022; distortion-resistant readout:
Powers 2018). Oliva 2025 had reversed-PE data and still corrected only the
brain. On this cohort 82% of runs fall back to SyN, which is unprecedented in
the cord and which cord Dice cannot validate (the metric rewards the alignment
SyN optimizes), so `none` must be a first-class, selectable mode.
See .claude/specs/s5-algorithm-audit-v3.md.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from spineprep.steps.s5.mode import select_mode
from spineprep.steps.s5.process import _classify_run_status

BOLD = {"subject": "01", "session": None, "path": "sub-01/func/sub-01_task-rest_bold.nii.gz"}


def test_fallback_none_when_no_reversed_pe_pair():
    assert select_mode(BOLD, [], fallback_mode="none") == ("none", [])


def test_fallback_syn_remains_the_default():
    assert select_mode(BOLD, [])[0] == "syn"
    assert select_mode(BOLD, [], fallback_mode="syn")[0] == "syn"


def test_unknown_fallback_degrades_to_syn():
    assert select_mode(BOLD, [], fallback_mode="bogus")[0] == "syn"


def _fmap(pe, name):
    return {"subject": "01", "session": None,
            "path": f"sub-01/fmap/{name}",
            "acquisition": {"PhaseEncodingDirection": pe}}


def test_reversed_pe_pair_still_wins_over_none_fallback():
    """A fieldmap must beat the fallback: `none` only applies with no pair."""
    fmaps = [_fmap("j-", "sub-01_dir-AP_epi.nii.gz"), _fmap("j", "sub-01_dir-PA_epi.nii.gz")]
    mode, eligible = select_mode(BOLD, fmaps, fallback_mode="none")
    assert mode == "topup" and len(eligible) == 2


# --- the gate ---------------------------------------------------------------

THRESH = {"pass_dice_min": 0.50, "warn_dice_min": 0.30,
          "pass_displacement_max_mm": 1.0, "warn_displacement_max_mm": 2.0}


def test_none_never_fails_for_carrying_distortion():
    """The gates score a CORRECTION. A passthrough that honestly reports 2.73 mm
    of uncorrected distortion (CoSpine's uncorrected figure) must not FAIL —
    it did exactly what was asked."""
    m = {"displacement_mean_after_mm": 2.73, "dice_mean_after": 0.35}
    status, reasons = _classify_run_status(m, "none", THRESH)
    assert status == "WARN"
    assert "not corrected" in reasons[0]
    assert "2.73" in reasons[0]


def test_none_never_passes_either():
    """Even pristine geometry must not PASS in `none` — a PASS would read as
    'undistorted', which the step never established."""
    m = {"displacement_mean_after_mm": 0.10, "dice_mean_after": 0.90}
    status, _ = _classify_run_status(m, "none", THRESH)
    assert status == "WARN"


def test_syn_still_fails_on_bad_geometry():
    """The none-branch must not have disarmed the real gates."""
    m = {"dice_mean_after": 0.10, "displacement_mean_after_mm": 0.5}
    status, _ = _classify_run_status(m, "syn", THRESH)
    assert status == "FAIL"
