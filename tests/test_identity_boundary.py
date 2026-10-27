"""Two identities, one working tree. This guard keeps them apart.

  spineprep      the PUBLIC TOOLBOX. A containerised BIDS-App: code, policy, schemas,
                 docs, packaging. Published to PyPI, spineprep.com and Zenodo.
  p2-spineprep   the PAPER. Manuscript, claims, retractions, analyses, strategy.
                 A separate PRIVATE repository, living at paper/.

They share a working tree because the analyses read the pipeline's outputs and every
script and document refers to `analysis/...` paths. Paper-side trees are therefore
symlinks into `paper/`, and this repository must never track them.

WHY A GUARD AND NOT A CONVENTION. The two identities were conflated for months and nobody
noticed, because nothing checked. As of 2026-08-15 the public repository had published
`analysis/FLAGSHIP_FINDINGS.md` — the paper's core findings — since 27 July, along with
`private/`, the exploration trees, and a `CLAUDE.md` naming the target venue and pointing
at the locked-claims specs. Separately, a ledger migration put all 43 retractions in a
tracked file at the repository root.

Each of those was one `git push` from being permanent. Conventions do not catch this;
a test that fails does.

The dependency direction is the reason the split is clean: `src/` imports nothing from
`analysis/`, and `analysis/` imports nothing from `spineprep`. Test 4 keeps it that way.
"""
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

#: Trees belonging to the paper. Symlinks into paper/ are expected; tracking is not.
PAPER_TREES = ["analysis", "exploration", "private", "research", "paper"]

#: Words that only appear when a document is arguing about the PAPER rather than
#: documenting the TOOL. A public toolbox has no target venue.
STRATEGY_MARKERS = re.compile(
    r"\b(target venue|venue pivot(ed)?|the eLife plan|locked claims|claims ledger|"
    r"CLAIMS_LEDGER|LEDGER_SOURCE)\b", re.I)

#: Files a public toolbox legitimately ships that may mention the paper in passing
#: (a citation, a "how to cite us"). Checked for markers but allowed a small budget.
PROSE_BUDGET = 1

#: The guards themselves must name what they guard, so they cannot obey their own rule.
EXEMPT = {"tests/test_identity_boundary.py", "tests/test_paper_stays_private.py"}


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True,
                          text=True, check=False)


def _tracked() -> list[str]:
    return [ln for ln in _git("ls-files").stdout.splitlines() if ln.strip()]


def test_no_paper_tree_is_tracked():
    """The paper's trees must not be in the public repository's index."""
    tracked = _tracked()
    offenders = {t: [f for f in tracked if f == t or f.startswith(t + "/")]
                 for t in PAPER_TREES}
    offenders = {k: v for k, v in offenders.items() if v}
    assert not offenders, (
        "paper-side trees are TRACKED by the public toolbox repository: "
        + "; ".join(f"{k} ({len(v)} files, e.g. {v[0]})" for k, v in offenders.items())
        + ". They belong to p2-spineprep, the private paper repository at paper/."
    )


def test_paper_trees_are_ignored():
    """And they must be ignored, so a later `git add -A` cannot re-add them."""
    missing = [t for t in PAPER_TREES
               if (REPO / t).exists() and _git("check-ignore", "-q", t).returncode != 0]
    assert not missing, (
        f"{missing} exist in the working tree but are NOT gitignored. Note that a "
        "directory pattern such as `analysis/` does NOT match a symlink named "
        "`analysis` — write the pattern without a trailing slash."
    )


def test_no_tracked_file_argues_about_the_paper():
    """A public toolbox documents a tool. It does not carry publication strategy."""
    offenders = []
    for rel in _tracked():
        if rel in EXEMPT:
            continue
        p = REPO / rel
        if not p.is_file() or p.is_symlink() or p.suffix not in {".md", ".py", ".yaml",
                                                                 ".yml", ".json", ".toml"}:
            continue
        try:
            hits = STRATEGY_MARKERS.findall(p.read_text(errors="ignore"))
        except OSError:
            continue
        if len(hits) > PROSE_BUDGET:
            found = sorted({h[0] if isinstance(h, tuple) else h for h in hits})
            offenders.append(f"{rel} ({len(hits)} mentions: {found[:3]})")
    assert not offenders, (
        "tracked files in the public toolbox carry paper strategy: "
        f"{offenders}. Move the discussion to the paper repository."
    )


def test_toolbox_does_not_depend_on_the_paper():
    """src/ must never import analysis/. The split is only clean while this holds."""
    bad = []
    for p in (REPO / "src").rglob("*.py"):
        text = p.read_text(errors="ignore")
        if re.search(r"^\s*(from|import)\s+analysis\b", text, re.M):
            bad.append(str(p.relative_to(REPO)))
    assert not bad, (
        f"toolbox source imports the paper's analysis package: {bad}. The toolbox must "
        "stand alone; it is installed by people who will never have paper/."
    )
