"""Statements the project has verified to be false must not reappear in
shipped text (docs, README, policy comments, source).

Each pattern is a correction recorded in the agent contract:
- Kaptan 2023 never uses FD; the 0.5 mm FD threshold is Power 2012.
- ds005883 does ship GRE fieldmaps (corrected 2026-08-12).
- Eippert 2017's main pipeline is high-pass only; its band-pass was a
  robustness variant and never 0.1 Hz.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

SPAN = r"(?:[^.\n]|al\.|\d\.\d){0,150}"  # same sentence; "et al." and "0.5" do not end it
NEGATION = re.compile(r"\b(no|not|never|without)\b", re.IGNORECASE)

FALSE_STATEMENTS = {
    "Kaptan 2023 cited for an FD threshold": re.compile(
        rf"kaptan{SPAN}\b(FD|framewise)\b|\b(FD|framewise)\b{SPAN}kaptan",
        re.IGNORECASE,
    ),
    "claims the cohort has no GRE fieldmap data": re.compile(
        r"\bno GRE(-fieldmap)?( fieldmap)? data\b", re.IGNORECASE
    ),
    "attributes a 0.1 Hz cutoff to Eippert": re.compile(
        rf"eippert{SPAN}\b0\.1\s*Hz|\b0\.1\s*Hz{SPAN}eippert",
        re.IGNORECASE,
    ),
}


def _shipped_files():
    yield ROOT / "README.md"
    yield from (ROOT / "docs").rglob("*.md")
    yield from (ROOT / "policy").glob("*.yaml")
    yield from (ROOT / "src" / "spineprep").rglob("*.py")


def _violations(text):
    """A match negated in its own span or close by ("Kaptan never uses FD";
    a note quoting the old error and saying it was wrong) is a correct
    statement. The GRE rule is itself a negation and is exempt."""
    found = []
    for name, rx in FALSE_STATEMENTS.items():
        for m in rx.finditer(text):
            near = text[max(0, m.start() - 120): m.end() + 200]
            if "GRE" in name or not NEGATION.search(near):
                found.append(name)
                break
    return found


@pytest.mark.parametrize(
    "planted, expected",
    [
        ("FD threshold of 0.5 mm (Kaptan et al., 2023).", "Kaptan 2023 cited for an FD threshold"),
        ("FUGUE was dropped: no GRE-fieldmap data exists.", "claims the cohort has no GRE fieldmap data"),
        ("band-pass 0.01-0.1 Hz as in Eippert 2017.", "attributes a 0.1 Hz cutoff to Eippert"),
    ],
)
def test_patterns_catch_planted_statement(planted, expected):
    assert expected in _violations(planted)


def test_correct_statements_pass():
    ok = ("High-pass 100 s (0.01 Hz; Eippert 2017). FD threshold 0.5 mm (Power 2012). "
          "Kaptan 2023 never uses FD; it censors on dVARS.")
    assert _violations(ok) == []


def test_shipped_text_has_no_known_false_statement():
    found = []
    for path in _shipped_files():
        if path.is_file():
            for name in _violations(path.read_text(errors="ignore")):
                found.append(f"{path.relative_to(ROOT)}: {name}")
    assert not found, "\n".join(found)
