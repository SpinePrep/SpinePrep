"""A run that applied NO correction ships NO S5 reportlets.

All three S5 reportlets are correction diagnostics. With mode="none" nothing was
corrected, so on the cohort the effectiveness panel showed Before against an
identical After (373 of 386 runs matched EXACTLY, the rest to <0.01 mm) and both
per-slice traces drew a curve against its own duplicate. A step that did not act
must not illustrate an action.

The measured distortion is NOT lost: it stays in the qc.json metrics and in the
distortion-limited WARN, which is where a number belongs when there is no
before/after to draw.
"""
import inspect

from spineprep.steps.s5 import process as s5_process


def test_all_three_reportlets_gated_on_a_correction():
    src = inspect.getsource(s5_process)
    assert 'corrected = (mode != "none")' in src, \
        "S5 must decide reportlets on whether a correction ran"
    assert "if corrected:" in src, "the render block must be gated"


def test_nothing_offered_or_required_when_uncorrected():
    """An uncorrected run must not be downgraded for missing a diagnostic it was
    never meant to produce."""
    src = inspect.getsource(s5_process)
    i = src.index("_candidates = (")
    block = src[i:i + 800]
    assert "if corrected else {}" in block, \
        "no reportlets may be offered for an uncorrected run"
    assert "if corrected else ()" in block, \
        "nothing may be REQUIRED for an uncorrected run"
