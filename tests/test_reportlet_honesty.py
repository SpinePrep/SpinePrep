"""A step may not claim a diagnostic it did not produce.

Regression for the pipeline-wide pattern found on 2026-07-18/19. Two shapes:

  * S4, S5 and S6 built their `reportlets` dict unconditionally, so a failed
    render left qc.json naming a PNG that does not exist -- the QC record
    pointing at missing evidence.
  * Every step computed `status` before rendering and never revisited it, so a
    render failure appended a reason and changed nothing. On the cohort this
    let 336 S8 runs report PASS with zero diagnostic images on disk.

Both are now handled by one shared helper, so the fix cannot drift apart
across steps again.
"""
from pathlib import Path

import pytest

from spineprep.reportlets_common import resolve_reportlets


def _png(p: Path) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"\x89PNG\r\n\x1a\n")
    return p


def test_existing_reportlets_are_recorded_relative(tmp_path):
    a = _png(tmp_path / "figures" / "a.png")
    reasons = []
    out, status = resolve_reportlets({"a": a}, tmp_path, "PASS", reasons,
                                     required=("a",))
    assert out["a"] == "figures/a.png"
    assert status == "PASS" and reasons == []


def test_missing_required_reportlet_downgrades_pass_to_warn(tmp_path):
    reasons = []
    out, status = resolve_reportlets({"a": tmp_path / "nope.png"}, tmp_path,
                                     "PASS", reasons, required=("a",))
    assert out["a"] == "", "must not name a file that does not exist"
    assert status == "WARN"
    assert any("not visually verifiable" in r for r in reasons)


def test_missing_reportlet_never_masks_a_fail(tmp_path):
    reasons = []
    _, status = resolve_reportlets({"a": tmp_path / "nope.png"}, tmp_path,
                                   "FAIL", reasons, required=("a",))
    assert status == "FAIL"


def test_missing_optional_reportlet_does_not_downgrade(tmp_path):
    """S9's smoothness chart is correctly absent when smoothing is off."""
    reasons = []
    _, status = resolve_reportlets({"opt": tmp_path / "nope.png"}, tmp_path,
                                   "PASS", reasons, required=())
    assert status == "PASS" and reasons == []


def test_partial_render_reports_only_the_missing_one(tmp_path):
    a = _png(tmp_path / "a.png")
    reasons = []
    out, status = resolve_reportlets({"a": a, "b": tmp_path / "b.png"},
                                     tmp_path, "PASS", reasons,
                                     required=("a", "b"))
    assert out["a"] and out["b"] == ""
    assert status == "WARN"
    assert "b" in reasons[0] and "a," not in reasons[0]


def test_none_path_is_empty_not_an_error(tmp_path):
    out, status = resolve_reportlets({"a": None}, tmp_path, "PASS", [],
                                     required=())
    assert out["a"] == "" and status == "PASS"


# --- every step must use the shared helper --------------------------------


@pytest.mark.parametrize("module", [
    "spineprep.steps.s4.process",
    "spineprep.steps.s5.process",
    "spineprep.steps.s6.process",
    "spineprep.steps.s7.process",
    "spineprep.steps.s8.process",
    "spineprep.steps.s9.process",
    "spineprep.steps.s2b.orchestrate",
])
def test_step_guards_its_reportlets(module):
    """Each step either calls the shared helper or carries its own guard."""
    import importlib
    from pathlib import Path as P
    src = P(importlib.import_module(module).__file__).read_text()
    assert ("resolve_reportlets" in src
            or "not visually verifiable" in src), \
        f"{module} does not guard against claiming an unrendered reportlet"
