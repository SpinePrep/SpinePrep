"""The manuscript's claims must never be tracked by this public repository.

This repository is public: PyPI `spineprep`, spineprep.com, a Zenodo DOI. The claims ledger
is not. It holds the manuscript, the publication strategy, and 43 retractions — the one
record in the project that cannot be reconstructed from the analysis outputs. That material
was deliberately purged from public git history during the 2026 migration.

WHY THIS FILE WAS REWRITTEN ON 2026-08-15, AND IT IS THE WHOLE POINT.

The first version of this guard checked one thing: that `paper/` was gitignored. It passed
every run. Then the global ledger standard changed, the migration created
`LEDGER_SOURCE.md` **at the repository root** and turned `paper/CLAIMS_LEDGER.md` into a
symlink pointing up to it, and all 43 retractions became a tracked file in a public repo,
committed locally in 33408ce. Three more followed it: `PROJECT_LEDGER.md`,
`PROJECT_LEDGER.json` and a migration backup under `.ledger/`.

The guard passed throughout. It was watching a *location*, and the content moved.

So this version checks the content as well as the locations. A path list can only ever
protect the paths somebody thought of; the retraction-marker scan below protects against the
next reorganisation nobody has thought of yet. Nothing was pushed, which is the only reason
this was recoverable.
"""
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

#: Files known to carry manuscript claims. Symlinks into paper/ are fine; tracking is not.
CLAIM_BEARING = ["LEDGER_SOURCE.md", "PROJECT_LEDGER.md", "PROJECT_LEDGER.json"]


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, check=False
    )


def _tracked() -> list[str]:
    return [ln for ln in _git("ls-files").stdout.splitlines() if ln.strip()]


def test_paper_directory_is_gitignored():
    if not (REPO / "paper").exists():
        return  # paper/ is never distributed, so a clone has nothing to protect
    assert _git("check-ignore", "-v", "paper/").returncode == 0, (
        "paper/ is NOT ignored by this public repository. It holds the manuscript, the "
        "publication strategy and the claims ledger. Restore the `paper/` line in "
        ".gitignore before committing anything."
    )


def test_no_paper_file_is_tracked():
    tracked = [f for f in _tracked() if f.startswith("paper/")]
    assert not tracked, (
        f"files under paper/ are TRACKED by the public repository: {tracked[:10]}"
    )


def test_claim_bearing_ledgers_are_not_tracked():
    """The root ledger files are symlinks into paper/. Tracking them publishes the claims."""
    tracked = set(_tracked())
    exposed = [f for f in CLAIM_BEARING if f in tracked]
    assert not exposed, (
        f"{exposed} are TRACKED by the public repository. They carry the manuscript's "
        "claims and retractions. They must be symlinks into paper/ and listed in "
        ".gitignore. This is exactly the failure of 2026-08-15."
    )


def test_ledger_migration_backups_are_not_tracked():
    tracked = [f for f in _tracked() if f.startswith(".ledger/")]
    assert not tracked, (
        f".ledger/ contains tracked files: {tracked[:5]}. Ledger migrations write backup "
        "copies of the claims ledger there; they must not enter the public repository."
    )


def test_no_tracked_file_contains_retraction_rows():
    """The content check — the one that would have caught the 2026-08-15 failure.

    A retraction row looks like `| X41 | ...` and only ever appears in the claims ledger.
    If any *tracked* file has several, the ledger has leaked into the public repo under
    some name nobody added to the list above.
    """
    import re
    marker = re.compile(r"^\|\s*(?:\*\*)?X\d+(?:\*\*)?\s*\|", re.M)
    offenders = []
    for rel in _tracked():
        p = REPO / rel
        if not p.is_file() or p.is_symlink() or p.suffix not in {".md", ".json", ".txt", ".csv"}:
            continue
        try:
            hits = len(marker.findall(p.read_text(errors="ignore")))
        except OSError:
            continue
        if hits >= 3:          # a stray mention is prose; several rows is the ledger
            offenders.append(f"{rel} ({hits} retraction rows)")
    assert not offenders, (
        "tracked files carry the claims ledger's retraction table: "
        f"{offenders}. The manuscript's retraction record must not be in the public "
        "repository under any filename."
    )
