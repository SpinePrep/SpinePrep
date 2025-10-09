# Repository Status — CEO Summary

**Date:** October 9, 2025
**Assessment:** Pre-Phase-A baseline audit
**Overall Health:** 🟡 FAIR (actionable, not critical)

---

## Current State

**HEAD:** `feat/spi-A1-doctor-json-snapshot` @ b2ed3dd9 (Oct 9, 18:01)
**Main:** `e2955226` (Oct 8, 22:21)
**Divergence:** 0 behind, 6 commits ahead

### Branch Landscape

| Status | Count | Branches |
|--------|-------|----------|
| ✅ Already merged | 2 | `feat/spi-001-scaffold-cli-config`, `feat/doctor-environment-diagnostics` |
| 🔵 Active (consolidate) | 1 | `feat/spi-A1-doctor-json-snapshot` (PRIMARY) |
| 🟡 Check for unique code | 1 | `feat/spi-002-snakemake-dag-provenance` (DAG export?) |
| 🗑️  Archive (duplicates) | 7 | `spi-a7`, `spi-cli-scaffold`, `spi-confounds-*`, `spi-masking`, `spi-xxx-registration`, `spi-011a-docs-ci-pages` |

**Recommendation:** Merge `feat/spi-A1-doctor-json-snapshot` to main, cherry-pick any unique DAG code from `spi-002`, archive the rest.

---

## Health Scorecard

| Check | Status | Notes |
|-------|--------|-------|
| Ruff linting | ✅ PASS | Clean |
| MkDocs build | ✅ PASS | Strict mode OK |
| Snakefmt | ⚠️  WARN | 1 file needs formatting (trivial) |
| Pytest | ❌ FAIL | 1 import error in `test_confounds.py` |
| Codespell | ❌ FAIL | 1202 false positives (site/ minified JS) |

**Blockers:** None critical. Test error fixable post-merge; codespell noise from generated files (will remove).

---

## Critical Issues (Must Fix in Ticket 1)

### 1. Git Bloat — 100MB+ of Build Artifacts Tracked

**Problem:** `.venv/` (Python packages), `site/` (generated docs), `__pycache__/` are in git history.

**Impact:** Slow clones, bloated repo size, violates best practices.

**Fix:**
```bash
# Add to .gitignore
echo ".venv/\nsite/\n__pycache__/\n*.pyc\n.snakemake/" >> .gitignore

# Remove from tracking (safe, non-destructive)
git rm -r --cached .venv/ site/ **/__pycache__/ **/*.egg-info/
git commit -m "chore: remove build artifacts from tracking"
```

**Risk:** None (only removes from future tracking, doesn't delete files locally).

---

### 2. Test Suite Broken

**Problem:** `tests/test_confounds.py` tries to import `compute_censor` which doesn't exist in new module structure.

**Impact:** Cannot validate changes with pytest.

**Fix:** Update test imports after merge to match new `spineprep/confounds/` structure.

---

### 3. Merge Conflicts Expected

**Problem:** 4+ branches modify same files (`cli.py`, `_version.py`, `configs/base.yaml`).

**Impact:** Manual conflict resolution needed.

**Mitigation:** Use `feat/spi-A1-doctor-json-snapshot` as canonical (most recent, most complete). Manually verify no functionality lost from other branches.

---

## Merge Strategy Summary

### Step 1: Tag for Rollback
```bash
git tag pre-phaseA-20251009
git push origin pre-phaseA-20251009
```

### Step 2: Merge Primary Branch
```bash
git checkout main
git merge --squash feat/spi-A1-doctor-json-snapshot
git commit -m "feat: consolidate Phase-A baseline [pre-A1]"
```

### Step 3: Cherry-pick Unique Code (if any)
```bash
# Check if spi-002 has unique DAG export code
git log feat/spi-A1-doctor-json-snapshot..feat/spi-002-snakemake-dag-provenance
# If unique commits, cherry-pick them
```

### Step 4: Clean Up
```bash
# Delete merged/duplicate branches
git branch -D feat/spi-001-scaffold-cli-config feat/doctor-environment-diagnostics
git branch -D feat/spi-a7-qc-html-scaffold feat/spi-cli-scaffold ...
# Remove from remote
git push origin --delete <branch-name>
```

### Step 5: Push & Verify
```bash
git push origin main
./ops/status/health_check.sh
```

**Rollback if needed:** `git reset --hard pre-phaseA-20251009`

---

## What Gets Merged

`feat/spi-A1-doctor-json-snapshot` includes (6 commits):
- ✅ Doctor JSON snapshot with full diagnostics
- ✅ QC HTML scaffold (per-subject reports)
- ✅ Cord & CSF masking with QC overlays
- ✅ SCT EPI→PAM50 registration wrapper
- ✅ FD/DVARS confounds (TSV/JSON schema v1)
- ✅ CLI scaffolding (config loader, doctor command)

**LOC impact:** ~3000-4000 lines added/modified across 50-70 files.

---

## Risks & Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| Test suite broken | 🔴 HIGH | Fix imports post-merge (30 min) |
| CLI merge conflicts | 🔴 HIGH | Use A1 as canonical, manual verify (1-2 hrs) |
| .venv tracked (bloat) | 🔴 HIGH | Remove from tracking immediately |
| Version string drift | 🟡 MED | Manually set to `0.2.0-dev` post-merge |
| Confounds API inconsistency | 🟡 MED | Audit `__init__.py` exports, run tests |
| Missing DAG code | 🟡 MED | Check spi-002, cherry-pick if needed |
| Duplicate branches | 🟢 LOW | Just delete, no merge needed |

**Overall risk:** 🟡 MEDIUM — Manageable with 4-6 hours allocated for Ticket 1.

---

## Timeline

**Ticket 0 (DONE):** Status snapshot ✅
**Ticket 1 (Next):** Execute merge plan (~4-6 hrs)
**Ticket 2:** Tree hygiene, CI bootstrap (~3-4 hrs)
**Ticket 3:** Gate review, start Phase A (~1 hr)

**Total to Phase A gate:** ~8-11 hours

---

## Decision Points for CEO

1. **Approve force-push to clean git history?**
   ⚠️  Destructive, requires coordination if others have clones.
   **Recommend:** Defer to post-v1.0, accept bloated history for now.

2. **Accept broken tests temporarily?**
   Test import errors will be fixed in Ticket 1 after merge.
   **Recommend:** Yes, document known failures.

3. **Proceed with Ticket 1 merge execution?**
   All risks documented, rollback strategy in place.
   **Recommend:** ✅ PROCEED

---

## Bottom Line

✅ Repository is healthy enough to proceed
✅ Merge plan is comprehensive and safe
✅ Rollback strategy in place
⚠️  Allocate 4-6 hours for Ticket 1 (merge execution + fixes)
🎯 Ready to consolidate and start Phase A

**Next action:** Review merge_plan.md and approve Ticket 1 execution.
