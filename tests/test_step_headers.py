"""Every step module opens with the toolbox header, and the README Pipeline table lists every step."""

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "spineprep"

STEP_MODULES = {
    "S0": SRC / "S0_setup.py",
    **{f"S{n.upper()}": SRC / "steps" / f"s{n}" / "__init__.py"
       for n in ("1", "2", "2b", "3", "4", "5", "6", "7", "8", "9", "10")},
}
LABELS = ("Input:", "Output:", "QC picture:", "Usage:")


def missing_labels(docstring):
    """Labels absent from a docstring, or out of the required order."""
    if not docstring:
        return list(LABELS)
    missing = [label for label in LABELS if not re.search(rf"^{re.escape(label)}", docstring, re.M)]
    if missing:
        return missing
    positions = [re.search(rf"^{re.escape(label)}", docstring, re.M).start() for label in LABELS]
    return [] if positions == sorted(positions) else ["labels out of order"]


def pipeline_table_steps(readme):
    """Step names in the first column of the table inside the README Pipeline section."""
    section = re.search(r"^## Pipeline\n(.*?)(?=^## )", readme, re.S | re.M)
    if not section:
        return set()
    return {m.group(1) for m in re.finditer(r"^\|\s*(S\d+B?)\s*\|", section.group(1), re.M)}


@pytest.mark.parametrize("step", sorted(STEP_MODULES))
def test_step_docstring_has_header(step):
    doc = ast.get_docstring(ast.parse(STEP_MODULES[step].read_text()))
    assert doc and doc.splitlines()[0].strip(), f"{step}: no one-line summary"
    assert not missing_labels(doc), f"{step}: {missing_labels(doc)}"


def test_readme_pipeline_table_lists_every_step():
    steps = pipeline_table_steps((ROOT / "README.md").read_text())
    assert not set(STEP_MODULES) - steps, sorted(set(STEP_MODULES) - steps)


def test_checks_fail_on_broken_input():
    good = "Does a thing.\n\nInput: a\n\nOutput: b\n\nQC picture: c\n\nUsage: d\n"
    assert not missing_labels(good)
    assert missing_labels(good.replace("QC picture:", "QC:")) == ["QC picture:"]
    assert missing_labels(None)
    readme = "## Pipeline\n\n| Step | x |\n|---|---|\n| S1 | a |\n\n## Next\n"
    assert pipeline_table_steps(readme) == {"S1"}
