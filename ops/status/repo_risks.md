# Repository Risks & Mitigations — Pre-Phase-A

**Generated:** 2025-10-09
**Assessment scope:** Branch consolidation, tree hygiene, test health
**Risk horizon:** Ticket 1 (merge execution) through Phase A gate

---

## 🔴 Critical Risks

### R1: Test Suite Broken (Import Errors)

**Impact:** Cannot validate merges, regression risk
**Likelihood:** CERTAIN (already failing)
**Evidence:**
```
ERROR tests/test_confounds.py
ImportError: cannot import name 'compute_censor' from 'spineprep.confounds'
```

**Root cause:**
- `tests/test_confounds.py` expects `compute_censor` function
- `spineprep/confounds/__init__.py` may not export it, or it's in a submodule
- Different branches have different confounds structures

**Mitigation:**
1. After merge, immediately inspect `spineprep/confounds/__init__.py` exports
2. Check if `compute_censor` moved to `spineprep/confounds/censor.py`
3. Update test imports to match new module structure
4. Add to merge checklist: "Fix confounds test imports"
5. Run `pytest tests/test_confounds.py -v` after merge to verify

**Fallback:**
- Skip broken tests temporarily, create hotfix ticket
- Document known test failures in merge commit

---

### R2: Merge Conflicts in Core CLI (High Complexity)

**Impact:** CLI may be broken or have duplicate logic
**Likelihood:** HIGH (4+ branches modify `spineprep/cli.py`)
**Conflict zones:**
- `spineprep/cli.py` (M in 5+ branches)
- `spineprep/_version.py` (M in 5+ branches)
- `configs/base.yaml` (M in 5+ branches)

**Evidence:**
- feat/spi-A1-doctor-json-snapshot: adds doctor JSON command
- feat/spi-002-snakemake-dag-provenance: may add DAG commands
- feat/spi-cli-scaffold: older doctor implementation

**Mitigation:**
1. Choose **feat/spi-A1-doctor-json-snapshot** as canonical (most recent, most complete)
2. Before merge, manually diff other branches' cli.py to identify unique commands
3. Extract unique functionality from other branches before archiving
4. After merge, run `spineprep --help` to ensure all expected commands present
5. Test each CLI command manually: `spineprep doctor`, `spineprep version`, etc.

**Fallback:**
- Keep backup branches (`backup/spi-*`) for 30 days to extract lost functionality

---

### R3: Large Tracked Files (.venv, __pycache__, site/)

**Impact:** Bloated repo size, slow clones, accidental secrets exposure
**Likelihood:** CERTAIN (already tracked)
**Evidence:**
- `.venv/lib/` contains 25MB+ of Python packages (numpy, scipy, pandas)
- `site/` contains generated MkDocs output (~5MB+)
- `__pycache__/` directories throughout

**Current state:**
- Largest tracked file: 25MB `libscipy_openblas64_`
- Total .venv size: ~100MB+
- These should NEVER be in git

**Mitigation (urgent, do in Ticket 1):**
1. **Before any merge**, add to `.gitignore`:
   ```
   .venv/
   __pycache__/
   *.pyc
   site/
   .snakemake/
   .coverage
   *.egg-info/
   ```
2. Remove from git history (careful!):
   ```bash
   git rm -r --cached .venv/
   git rm -r --cached site/
   git rm -r --cached **/__pycache__/
   git rm -r --cached **/*.egg-info/
   git commit -m "chore: remove build artifacts and venv from tracking"
   ```
3. Verify removal: `git ls-tree -r -l HEAD | grep venv` should be empty
4. Force push to rewrite history (ONLY if no other collaborators):
   ```bash
   # DO NOT RUN without CEO approval
   # git push origin main --force
   ```

**Fallback:**
- If force-push not allowed, accept bloated history and add `.gitignore` going forward
- Use `git-filter-repo` for deep clean (destructive, needs coordination)

---

## 🟡 Medium Risks

### R4: Confounds Module Structure Inconsistency

**Impact:** API instability, test fragility
**Likelihood:** MEDIUM
**Evidence:**
- Branch `spi-002` has `confounds/censor.py` and `confounds/compcor.py`
- Branch `spi-A1` has `confounds/io.py`, `confounds/motion.py`, `confounds/plot.py`
- Different branches may have different `__init__.py` exports

**Mitigation:**
1. After merge, audit `spineprep/confounds/__init__.py`
2. Ensure all submodules are properly exported
3. Run full test suite: `pytest tests/confounds/ -v`
4. Document public API in `spineprep/confounds/README.md`

---

### R5: Version String Conflicts

**Impact:** Incorrect version displayed, changelog confusion
**Likelihood:** MEDIUM (5 branches modify `_version.py`)
**Evidence:**
- Multiple branches bump version independently
- `CITATION.cff` also has version strings and dates

**Mitigation:**
1. After merge, manually set version to `0.2.0-dev` or similar
2. Sync version across: `_version.py`, `CITATION.cff`, `pyproject.toml`
3. Update `CHANGELOG.md` with consolidated entry for all merged work
4. Verify: `spineprep version` shows expected string

---

### R6: Duplicate Branches (Same SHA)

**Impact:** Confusion, wasted merge effort
**Likelihood:** CERTAIN (already exists)
**Evidence:**
- `feat/spi-confounds-acompcor-tcompcor-censor` @ 81712fac
- `feat/spi-masking-cord-csf-qc` @ 81712fac
- `feat/spi-xxx-registration-pam50-wrapper` @ 81712fac

**Mitigation:**
1. Identify duplicates: already done (see merge_plan.md)
2. Keep one, archive others immediately
3. No merge needed, just delete redundant branches

---

### R7: Untracked Generated Files (doctor.json, out/, test_work*)

**Impact:** Repo clutter, potential sensitive data leak
**Likelihood:** LOW (only local, not pushed)
**Evidence:**
```
?? doctor.json
?? out/
?? test_work/
?? test_work2/ ... test_work8/
```

**Mitigation:**
1. Add to `.gitignore`:
   ```
   doctor.json
   out/
   test_work*/
   *.ok
   ```
2. Delete locally:
   ```bash
   rm -rf test_work* out/ doctor.json *.ok
   ```
3. Verify not staged: `git status --porcelain` should show no untracked files

---

## 🟢 Low Risks

### R8: Snakefmt Formatting (1 file)

**Impact:** CI may fail on formatting checks
**Likelihood:** LOW
**Evidence:** `snakefmt --check .` reports 1 file needs formatting

**Mitigation:**
1. Run `snakefmt .` to auto-fix
2. Commit: `style: apply snakefmt`
3. Add pre-commit hook (optional, in Ticket 2)

---

### R9: Codespell False Positives (site/ minified JS)

**Impact:** Noisy CI logs, mask real typos
**Likelihood:** LOW (cosmetic)
**Evidence:** 50+ false positives in `site/assets/javascripts/bundle.*.min.js`

**Mitigation:**
1. Add to `.codespellrc` or `pyproject.toml`:
   ```toml
   [tool.codespell]
   skip = 'site/,*.min.js,*.map'
   ignore-words-list = 'te,hist,trys,ue,ot'
   ```
2. Or, remove `site/` from repo (already recommended in R3)

---

### R10: Missing DAG/Provenance Code in A1

**Impact:** Loss of Snakemake DAG export functionality
**Likelihood:** MEDIUM
**Evidence:** `feat/spi-002-snakemake-dag-provenance` has unique DAG work

**Mitigation:**
1. Before archiving spi-002, check if its DAG code is in A1
2. If not, cherry-pick commit `58dff246` to main
3. Verify DAG works: `snakemake -n -p --dag | dot -Tsvg > test.svg`

---

## Risk Scoring Matrix

| Risk | Impact | Likelihood | Severity | Ticket |
|------|--------|-----------|----------|--------|
| R1 - Test suite broken | Critical | Certain | 🔴 10/10 | Ticket 1 |
| R2 - CLI merge conflicts | High | High | 🔴 8/10 | Ticket 1 |
| R3 - Tracked .venv/site | Medium | Certain | 🔴 7/10 | Ticket 1 |
| R4 - Confounds API drift | Medium | Medium | 🟡 5/10 | Ticket 1 |
| R5 - Version conflicts | Medium | Medium | 🟡 4/10 | Ticket 1 |
| R6 - Duplicate branches | Low | Certain | 🟢 2/10 | Ticket 1 |
| R7 - Untracked clutter | Low | Low | 🟢 2/10 | Ticket 1 |
| R8 - Snakefmt | Low | Low | 🟢 1/10 | Ticket 2 |
| R9 - Codespell noise | Low | Low | 🟢 1/10 | Ticket 2 |
| R10 - Missing DAG code | Medium | Medium | 🟡 5/10 | Ticket 1 |

---

## Recommended Action Sequence (for Ticket 1)

1. **Immediate (before any merge):**
   - Update `.gitignore` (R3, R7)
   - Remove `.venv`, `site/`, `__pycache__` from tracking (R3)
   - Tag `pre-phaseA-20251009` for rollback

2. **During merge:**
   - Use feat/spi-A1-doctor-json-snapshot as base (R2)
   - Cherry-pick DAG commits from spi-002 if missing (R10)
   - Resolve conflicts by accepting A1 version, manually verify (R2)

3. **After merge:**
   - Fix confounds test imports (R1)
   - Sync version strings (R5)
   - Run full test suite and fix failures (R1, R4)
   - Run `snakefmt .` (R8)

4. **Verification:**
   - `pytest -q` passes (or document known failures)
   - `ruff check .` clean
   - `snakefmt --check .` clean
   - `mkdocs build --strict` clean
   - `spineprep --help` shows all commands
   - `spineprep doctor` runs without error

---

## Rollback Triggers

Abort merge and rollback if:
- ✅ More than 5 test files have import errors after merge
- ✅ CLI commands entirely missing (not just broken)
- ✅ Merge conflicts take >2 hours to resolve
- ✅ Main branch becomes unbuildable (import errors in core modules)

Use: `git reset --hard pre-phaseA-20251009`

---

## Long-term Debt (defer to Ticket 2 or later)

- Add pre-commit hooks for ruff, snakefmt, codespell
- Set up branch protection on `main` (require PR, CI pass)
- Add `mypy` type checking to CI
- Clean git history with `git-filter-repo` (if CEO approves force-push)
- Document branching strategy in CONTRIBUTING.md

---

## Confidence Assessment

**Overall confidence in merge success:** 🟡 MEDIUM (60%)

**Blockers:**
- Test suite must be fixed post-merge (not a blocker to merge, but to validation)
- Confounds module structure must be reconciled

**Enablers:**
- Good commit history and messages
- Clear feature separation across branches
- Rollback tag in place

**Recommendation:** Proceed with Ticket 1, but allocate 4-6 hours for merge + fixes.
