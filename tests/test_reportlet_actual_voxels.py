"""Reportlets must show ACTUAL VOXELS, never an interpolated image.

reportlet-visual-standard requires actual-voxel rendering. Two ways a renderer
breaks it, and both were live in the cohort until 2026-07-22:

  * a PIL/scipy resize with an interpolating filter (BILINEAR, LANCZOS, ...)
    when building a montage. This is the worse one -- it changes the VALUES the
    figure is reporting, so a tSNR montage showed numbers never measured, and it
    blurs the cord edge into the surrounding CSF.
  * an imshow() without interpolation="nearest", which smooths on display.

These tests scan the rendering code so a regression cannot land quietly.
"""
import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "spineprep"

# Filters that invent values between samples. NEAREST/BOX are value-preserving.
SMOOTHING_FILTERS = ("BILINEAR", "BICUBIC", "LANCZOS", "HAMMING", "ANTIALIAS")


def _py_files():
    return sorted(SRC.rglob("*.py"))


def _imshow_calls(text):
    """Yield (line_no, argument_text) for every .imshow(...) call."""
    for m in re.finditer(r"\.imshow\(", text):
        i, depth = m.end(), 1
        while i < len(text) and depth:
            if text[i] == "(":
                depth += 1
            elif text[i] == ")":
                depth -= 1
            i += 1
        yield text[: m.start()].count("\n") + 1, text[m.end(): i - 1]


def test_no_imshow_without_nearest_interpolation():
    offenders = []
    for p in _py_files():
        text = p.read_text()
        for line, args in _imshow_calls(text):
            if "nearest" not in args:
                offenders.append(f"{p.relative_to(SRC)}:{line}")
    assert not offenders, (
        "imshow() without interpolation='nearest' smooths the QC image: "
        + ", ".join(offenders))


def test_no_interpolating_resample_in_renderers():
    offenders = []
    for p in _py_files():
        text = p.read_text()
        for filt in SMOOTHING_FILTERS:
            for m in re.finditer(rf"resample\s*=\s*Image\.(?:Resampling\.)?{filt}", text):
                offenders.append(f"{p.relative_to(SRC)}:{text[:m.start()].count(chr(10)) + 1} ({filt})")
    assert not offenders, (
        "an interpolating resample changes the voxel values the figure reports: "
        + ", ".join(offenders))


def _render_tsnr_body():
    src = (SRC / "lib" / "viz_s4.py").read_text()
    body = src[src.index("def render_tsnr_comparison"):]
    return body[: body.index("\ndef ", 1)] if "\ndef " in body[1:] else body


def test_s4_tsnr_montage_is_cord_masked():
    """The tSNR montage must colour only cord voxels: non-cord becomes NaN so
    whatever sits underneath shows through."""
    body = _render_tsnr_body()
    assert "set_bad" in body, "colormap must define how masked voxels render"
    assert "np.nan" in body, "non-cord voxels must be set to NaN, not drawn"
    assert "mont_mask" in body, "the cord mask must ride through the same montage geometry"


def test_s4_tsnr_shows_the_image_underneath():
    """A black surround hides the anatomy needed to judge whether the cord mask
    sits on the actual cord, so the mean EPI is drawn in greyscale beneath the
    overlay and the masked-out region must be TRANSPARENT, not filled."""
    body = _render_tsnr_body()
    assert "bg_before" in body and "bg_after" in body, "renderer must accept backdrops"
    assert "cmap='gray'" in body or 'cmap="gray"' in body, "backdrop is greyscale"
    assert "set_bad(alpha=0" in body.replace(" ", "").replace("set_bad(alpha=0.0", "set_bad(alpha=0"), \
        "masked voxels must be transparent so the image shows through"


def test_s4_callers_pass_a_backdrop():
    """Both call sites must supply the backdrop, or the fix only lands in one."""
    for rel in (("steps", "s4", "process.py"), ("steps", "s4", "orchestrate.py")):
        text = (SRC.joinpath(*rel)).read_text()
        assert "bg_before=" in text and "bg_after=" in text, f"{rel[-1]} passes no backdrop"
