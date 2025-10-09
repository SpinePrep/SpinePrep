# Merge Plan — Pre-Phase-A Repository Consolidation

**Generated:** 2025-10-09
**Current HEAD:** b2ed3dd9 (feat/spi-A1-doctor-json-snapshot)
**Target:** Consolidate all feature work into `main` and prepare clean baseline for Phase A

---

## Summary

- **12 local branches** (including `main`)
- **8 remote branches** on origin
- **Current divergence:** 0 commits ahead, 6 commits behind `origin/main`
- **Key conflict zones:** `spineprep/cli.py`, `spineprep/_version.py`, `configs/base.yaml`, `CITATION.cff`
- **Test status:** ❌ pytest failing (import error in confounds)
- **Lint status:** ✅ ruff clean, ⚠️  snakefmt needs 1 file

---

## Branch Analysis & Strategy

### 1. Already merged or at main (DELETE)

**Branches:**
- `feat/doctor-environment-diagnostics` — no commits ahead of main
- `feat/spi-001-scaffold-cli-config` — no commits ahead of main

**Action:** Delete locally and on remote (if present)

```bash
git branch -d feat/doctor-environment-diagnostics
git branch -d feat/spi-001-scaffold-cli-config
```

---

### 2. Active development - linear merge (FAST-FORWARD or SQUASH-MERGE)

**Branch:** `feat/spi-A1-doctor-json-snapshot` (CURRENT HEAD)
**Commits ahead:** 6
**Key changes:** Doctor JSON snapshot, QC HTML scaffold, masking, registration, confounds
**Conflicts:** High (multiple overlapping changes with other branches)
**Strategy:** This is the most advanced branch. After merging other branches into main first, rebase this onto updated main, then squash-merge.

**Branch:** `feat/spi-a7-qc-html-scaffold`
**Commits ahead:** 5
**Key changes:** QC HTML scaffold, masking, registration, confounds
**Conflicts:** High (shares many commits with A1, but missing the final doctor snapshot)
**Strategy:** This is a subset of spi-A1. ARCHIVE (covered by A1).

**Branch:** `feat/spi-002-snakemake-dag-provenance`
**Commits ahead:** 4
**Key changes:** Snakemake DAG with provenance, includes censor/compcor
**Conflicts:** Medium (confounds structure differs from A1)
**Strategy:** Cherry-pick DAG changes if not in A1, otherwise ARCHIVE.

**Branch:** `feat/spi-confounds-fd-dvars-tsv-json-v1`
**Commits ahead:** 2
**Key changes:** FD/DVARS confounds TSV/JSON
**Conflicts:** Low (superseded by later work)
**Strategy:** ARCHIVE (functionality included in A1).

**Branch:** `feat/spi-confounds-acompcor-tcompcor-censor`
**Commits ahead:** 3
**Key changes:** Registration wrapper, confounds
**Conflicts:** Medium
**Strategy:** Check if registration code is in A1; if not, cherry-pick specific commits. Otherwise ARCHIVE.

**Branch:** `feat/spi-masking-cord-csf-qc`
**Commits ahead:** 3
**Key changes:** Same as spi-confounds-acompcor (same SHA)
**Conflicts:** Medium
**Strategy:** ARCHIVE (duplicate/covered by A1).

**Branch:** `feat/spi-xxx-registration-pam50-wrapper`
**Commits ahead:** 3
**Key changes:** Same as above (same SHA)
**Conflicts:** Medium
**Strategy:** ARCHIVE (duplicate/covered by A1).

---

### 3. Old experimental branches (ARCHIVE)

**Branch:** `feat/spi-cli-scaffold`
**Commits ahead:** 2
**Key changes:** Doctor diagnostics (older version)
**Strategy:** ARCHIVE (superseded by A1).

**Branch:** `feat/spi-011a-docs-ci-pages`
**Commits ahead:** 3
**Key changes:** Docs CI and GitHub Pages setup
**Conflicts:** Low (isolated to CI/docs)
**Strategy:** Keep docs changes if valuable; likely ARCHIVE since docs workflow exists.

---

## Step-by-Step Merge Sequence

### Phase 1: Pre-flight checks

```bash
# 1. Tag current main for rollback
git checkout main
git tag pre-phaseA-20251009
git push origin pre-phaseA-20251009

# 2. Ensure main is synced
git fetch origin
git pull origin main --ff-only

# 3. Create backup branches for any uncertain merges
git branch backup/spi-A1 feat/spi-A1-doctor-json-snapshot
git branch backup/spi-002 feat/spi-002-snakemake-dag-provenance
```

### Phase 2: Delete already-merged branches

```bash
git branch -d feat/doctor-environment-diagnostics
git branch -d feat/spi-001-scaffold-cli-config
```

### Phase 3: Main merge - feat/spi-A1-doctor-json-snapshot

This branch contains the most complete work. Strategy: rebase then squash-merge.

```bash
# Checkout and rebase onto latest main
git checkout feat/spi-A1-doctor-json-snapshot
git rebase origin/main

# If conflicts, resolve them, then:
# git rebase --continue

# Once clean, merge to main
git checkout main
git merge --squash feat/spi-A1-doctor-json-snapshot
git commit -m "feat: consolidate Phase-A baseline (doctor, QC, confounds, registration, masking)  [pre-A1]

Squashed commits:
- feat(cli): add doctor JSON snapshot with complete diagnostics  [spi-A1]
- feat(qc): scaffold per-subject QC HTML with overlays, motion, aCompCor, and env  [spi-a7]
- feat(preproc): add cord and CSF masking with QC overlays
- feat(registration): implement SCT EPI→PAM50 wrapper with metrics and rule  [spi-xxx]
- feat(confounds): implement FD/DVARS + confounds TSV/JSON (schema v1) and motion plot  [spi-confounds]
- feat(core): scaffold CLI with config loader and doctor command  [spi-001]

Co-authored-by: Developer <dev@example.com>
"
```

### Phase 4: Check for unique commits in other branches

```bash
# Check if spi-002 has unique DAG/provenance code not in A1
git log feat/spi-A1-doctor-json-snapshot..feat/spi-002-snakemake-dag-provenance

# If unique commits exist, cherry-pick:
git checkout main
git cherry-pick <commit-sha>

# Otherwise, just delete the branch
```

### Phase 5: Archive remaining branches

```bash
# Archive branches that are subsets or superseded
git branch -D feat/spi-a7-qc-html-scaffold
git branch -D feat/spi-confounds-fd-dvars-tsv-json-v1
git branch -D feat/spi-confounds-acompcor-tcompcor-censor
git branch -D feat/spi-masking-cord-csf-qc
git branch -D feat/spi-xxx-registration-pam50-wrapper
git branch -D feat/spi-cli-scaffold
git branch -D feat/spi-011a-docs-ci-pages
git branch -D feat/spi-002-snakemake-dag-provenance  # if no unique commits

# Remove from remote (only if they exist and you're sure)
git push origin --delete feat/spi-a7-qc-html-scaffold 2>/dev/null || true
git push origin --delete feat/spi-cli-scaffold 2>/dev/null || true
git push origin --delete feat/spi-confounds-fd-dvars-tsv-json-v1 2>/dev/null || true
git push origin --delete feat/spi-A1-doctor-json-snapshot 2>/dev/null || true
git push origin --delete feat/spi-002-snakemake-dag-provenance 2>/dev/null || true
```

### Phase 6: Push consolidated main

```bash
git push origin main

# Update remote tags
git push origin pre-phaseA-20251009
```

### Phase 7: Verify and clean up

```bash
# List remaining branches
git branch -a

# Should see:
# - main (local and remote)
# - backup/* branches (local only, for safety)

# Clean up local tracking of deleted remote branches
git fetch --all --prune

# Verify health
./ops/status/health_check.sh
```

---

## Conflict Resolution Strategy

### High-probability conflicts

1. **`spineprep/cli.py`**
   - Multiple branches modify CLI structure
   - Resolution: Accept latest (A1) version, verify all commands present

2. **`spineprep/_version.py`**
   - Version bumps in multiple branches
   - Resolution: Use chronologically latest version string

3. **`configs/base.yaml`**
   - Config schema changes across branches
   - Resolution: Merge all new fields, validate with schema

4. **`CITATION.cff`**
   - Date/version updates in multiple branches
   - Resolution: Use latest date, consolidate authors

### Mitigation steps

- For each conflict file:
  1. Accept theirs (A1 version)
  2. Manually verify no missing functionality from other branches
  3. Run tests after each resolution
  4. If tests fail, inspect what was lost and manually add back

---

## Rollback Procedure

If the merge process goes wrong:

```bash
# Reset main to pre-merge state
git checkout main
git reset --hard pre-phaseA-20251009

# Restore branches from backups if needed
git checkout -b feat/spi-A1-doctor-json-snapshot backup/spi-A1
git checkout -b feat/spi-002-snakemake-dag-provenance backup/spi-002

# Force push main (ONLY if you're certain)
# git push origin main --force  # DANGER: only if solo developer
```

---

## Post-Merge Checklist

- [ ] `git branch -a` shows only `main` and `origin/main` (plus backups)
- [ ] `ruff check .` passes
- [ ] `snakefmt --check .` passes (or 1 acceptable file)
- [ ] `pytest -q` passes (or known failures documented)
- [ ] `mkdocs build --strict` passes
- [ ] All desired features from branches present in main
- [ ] Tag `pre-phaseA-20251009` exists and is pushed
- [ ] CI passing on main
- [ ] README updated to reflect consolidated state

---

## Estimated Impact

- **Files changed:** ~50-70 files (including new modules, tests, configs)
- **LOC touched:** ~3000-4000 lines (estimate)
- **Test coverage impact:** Some tests may need fixes (confounds import errors)
- **Breaking changes:** None (internal refactor only)
- **Migration needed:** No (pre-release consolidation)

---

## Notes

- The `feat/spi-A1-doctor-json-snapshot` branch is the most comprehensive and should be the primary merge source.
- Several branches share identical commits (e.g., 81712fac appears in 3 branches), indicating parallel development on same features.
- The `.venv` directory is being tracked (should be in .gitignore) — will be addressed in tree hygiene ticket.
- `site/` directory (built docs) is tracked — should be in .gitignore or explicitly kept out of repo.
- Many `__pycache__` files are staged — need .gitignore update.
