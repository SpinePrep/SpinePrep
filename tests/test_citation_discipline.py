"""Citations that the project has already retracted must not come back.

SpinePrep has a documented history of attributing bespoke choices to papers
that do not support them. CLAUDE.md invariant 1 records the corrections; this
test enforces them across every user-visible surface, so a fix applied in one
file cannot silently fail to propagate -- which is exactly what happened with
the FD threshold (S4 removed it 2026-07-16; S10 was still rendering
"exceeds 0.5 mm (Kaptan 2023)" into every subject report three days later).
"""
import re
from pathlib import Path

import pytest

# Files a reader or reviewer actually sees.
_SURFACES = sorted(
    [p for p in Path("src/spineprep").rglob("*.py")]
    + [p for p in Path("docs").rglob("*.md")]
    + [p for p in Path("policy").glob("*.yaml")]
    + [Path("README.md"), Path("paper/DRAFT.md")]
    + [p for p in Path("validation").glob("*.py")]
)


def _lines(path):
    try:
        return path.read_text().splitlines()
    except Exception:
        return []


def _offending(pattern, allow_substr=()):
    """Lines matching `pattern`, excluding ones that are explicitly corrective."""
    hits = []
    rx = re.compile(pattern, re.I)
    for f in _SURFACES:
        if not f.exists():
            continue
        for i, ln in enumerate(_lines(f), 1):
            if not rx.search(ln):
                continue
            if any(s.lower() in ln.lower() for s in allow_substr):
                continue
            hits.append(f"{f}:{i}: {ln.strip()[:110]}")
    return hits


def test_kaptan_is_never_cited_for_an_fd_threshold():
    """Kaptan 2023 computes no FD at all -- it censors on DVARS/refRMS."""
    bad = _offending(
        r"FD[^.\n]{0,60}Kaptan|Kaptan[^.\n]{0,60}\bFD\b",
        # Text that explains the retraction is the point, not a violation.
        allow_substr=("does not use fd", "no fd", "not use fd", "never uses fd",
                      "uses no fd", "does not", "do not attribute", "not attribute",
                      "wrong", "removed", "retract", "old ", "former", "previously",
                      "uses NO FD"),
    )
    assert not bad, "Kaptan 2023 cited for FD:\n" + "\n".join(bad)


def test_s6_recipe_is_not_attributed_to_kaptan():
    """The three-stage chain is SpinePrep's own; Kaptan's is two steps."""
    bad = _offending(
        r"(centermassrot|cord-driven recipe|columnwise)[^\n]{0,80}Kaptan",
        allow_substr=("not ", "own", "retract"),
    )
    assert not bad, "S6 recipe attributed to Kaptan:\n" + "\n".join(bad)


def test_episeg_is_credited_to_banerjee_not_valosek():
    bad = _offending(r"EPISeg[^\n]{0,60}Valo", allow_substr=("not ",))
    assert not bad, "EPISeg mis-attributed:\n" + "\n".join(bad)


def test_no_surface_claims_fd_censoring_while_it_is_disabled():
    """FD censoring is off; text saying otherwise misdescribes the pipeline."""
    import yaml
    pol = yaml.safe_load(Path("policy/S8_confounds.yaml").read_text())
    if (pol.get("motion") or {}).get("fd_outlier_threshold_mm") is not None:
        pytest.skip("FD censoring is enabled; the claim would be accurate")
    bad = _offending(
        r"FD > 0\.5 mm \+|censor[^\n]{0,40}FD > 0\.5",
        allow_substr=("does not", "no longer", "removed", "not a criterion"),
    )
    assert not bad, "claims FD censoring while it is disabled:\n" + "\n".join(bad)


def test_cohort_numbers_are_consistent():
    """The docs contradicted themselves within one build: nine-dataset in the
    methods pages, eight-dataset on the validation page and README."""
    bad = _offending(r"eight datasets|8 datasets / 384|~360 functional",
                     allow_substr=("was ", "previously", "note"))
    assert not bad, "stale cohort size still published:\n" + "\n".join(bad)
