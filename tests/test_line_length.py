"""Toolbox standard: no source line longer than 179 characters (the SCT flake8 limit)."""

from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "spineprep"


def test_no_line_over_179_characters():
    long = [f"{p.relative_to(SRC)}:{i}"
            for p in SRC.rglob("*.py")
            for i, line in enumerate(p.read_text(errors="ignore").splitlines(), 1)
            if len(line) > 179]
    assert not long, long
