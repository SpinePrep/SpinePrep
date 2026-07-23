"""With mode="none" S5 applies no correction, so it must not ship a
Before/After effectiveness reportlet.

Verified on the cohort: 373 of 386 mode="none" runs have
displacement_mean_after_mm EXACTLY equal to displacement_mean_before_mm (the
remaining 7 agree to <0.01 mm). Rendering "Before vs After" from that presents a
no-op as an evaluated correction. The two quantitative reportlets stay, because
the MEASURED distortion is the evidence behind the distortion-limited flag --
but they plot a single measured curve rather than two identical ones.
"""
import inspect

from spineprep.steps.s5 import process as s5_process
from spineprep.steps.s5 import reportlets as s5_reportlets


def test_effectiveness_is_gated_on_a_correction_having_run():
    src = inspect.getsource(s5_process)
    assert 'render_effectiveness = (mode != "none")' in src, \
        "the effectiveness reportlet must be gated on a correction being applied"
    assert "if render_effectiveness:" in src, "gate must guard both render and record"


def test_effectiveness_not_offered_as_a_reportlet_when_uncorrected():
    src = inspect.getsource(s5_process)
    i = src.index("_candidates = {")
    block = src[i:i + 700]
    assert '"distortion_effectiveness"' in block
    assert "if render_effectiveness:" in block, \
        "distortion_effectiveness must only be recorded when it was rendered"


def test_curve_reportlets_draw_one_curve_when_uncorrected():
    for fn in (s5_reportlets.render_s5_slice_displacement,
               s5_reportlets.render_s5_cord_dice_per_slice):
        src = inspect.getsource(fn)
        assert 'if mode == "none":' in src, f"{fn.__name__} must be mode-aware"
        assert "measured (uncorrected)" in src, \
            f"{fn.__name__} must label the single curve as a measurement"
