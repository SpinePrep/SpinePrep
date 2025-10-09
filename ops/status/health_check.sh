#!/usr/bin/env bash
#
# health_check.sh — SpinePrep repository health checks
# Run this before and after major changes (merges, refactors, releases)
#
# Usage: ./ops/status/health_check.sh
# Exit: 0 if all checks pass, 1 if any fail

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Counters
PASS=0
FAIL=0
WARN=0

# Output directory
OUT_DIR="ops/status"
mkdir -p "$OUT_DIR"

echo -e "${BLUE}======================================${NC}"
echo -e "${BLUE}SpinePrep Repository Health Check${NC}"
echo -e "${BLUE}======================================${NC}\n"

# Helper functions
check_pass() {
    echo -e "${GREEN}✓${NC} $1"
    PASS=$((PASS + 1))
}

check_fail() {
    echo -e "${RED}✗${NC} $1"
    FAIL=$((FAIL + 1))
}

check_warn() {
    echo -e "${YELLOW}⚠${NC} $1"
    WARN=$((WARN + 1))
}

# 1. Git branch and commit status
echo -e "${BLUE}[1/10] Git Status${NC}"
if git rev-parse --git-dir > /dev/null 2>&1; then
    CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
    CURRENT_SHA=$(git rev-parse --short HEAD)
    check_pass "Git repository detected (branch: $CURRENT_BRANCH @ $CURRENT_SHA)"

    # Check if main exists
    if git show-ref --verify --quiet refs/heads/main; then
        check_pass "Branch 'main' exists"
    else
        check_fail "Branch 'main' not found"
    fi

    # Check divergence from origin/main
    if git show-ref --verify --quiet refs/remotes/origin/main; then
        DIVERGENCE=$(git rev-list --left-right --count origin/main...HEAD 2>/dev/null || echo "? ?")
        BEHIND=$(echo "$DIVERGENCE" | awk '{print $1}')
        AHEAD=$(echo "$DIVERGENCE" | awk '{print $2}')
        if [[ "$BEHIND" -eq 0 && "$AHEAD" -eq 0 ]]; then
            check_pass "In sync with origin/main"
        else
            check_warn "Diverged from origin/main ($BEHIND behind, $AHEAD ahead)"
        fi
    else
        check_warn "origin/main not found (local-only repo?)"
    fi
else
    check_fail "Not a git repository"
fi
echo ""

# 2. Largest tracked files (potential cleanup targets)
echo -e "${BLUE}[2/10] Large Tracked Files${NC}"
git ls-tree -r -l HEAD | sort -k4 -n | tail -n 5 > "$OUT_DIR/largest_tracked.txt"
LARGEST_SIZE=$(git ls-tree -r -l HEAD | awk '{print $4}' | sort -n | tail -n 1)
if [[ "$LARGEST_SIZE" -gt 10000000 ]]; then  # 10MB
    check_warn "Large files detected (largest: $((LARGEST_SIZE / 1024 / 1024))MB) — see $OUT_DIR/largest_tracked.txt"
elif [[ "$LARGEST_SIZE" -gt 1000000 ]]; then  # 1MB
    check_warn "Moderately large files detected (largest: $((LARGEST_SIZE / 1024))KB)"
else
    check_pass "No unusually large tracked files"
fi
echo ""

# 3. Untracked/ignored files
echo -e "${BLUE}[3/10] Untracked Files${NC}"
git status --porcelain=v1 > "$OUT_DIR/status_porcelain.txt"
UNTRACKED_COUNT=$(grep -c "^??" "$OUT_DIR/status_porcelain.txt" || echo 0)
MODIFIED_COUNT=$(grep -c "^ M" "$OUT_DIR/status_porcelain.txt" || echo 0)

if [[ "$UNTRACKED_COUNT" -eq 0 ]]; then
    check_pass "No untracked files"
else
    check_warn "$UNTRACKED_COUNT untracked files (see $OUT_DIR/status_porcelain.txt)"
fi

if [[ "$MODIFIED_COUNT" -eq 0 ]]; then
    check_pass "No modified unstaged files"
else
    check_warn "$MODIFIED_COUNT modified files not staged"
fi
echo ""

# 4. Ruff linting
echo -e "${BLUE}[4/10] Ruff Linting${NC}"
if command -v ruff &> /dev/null; then
    RUFF_VERSION=$(ruff --version | head -n 1)
    if ruff check --output-format=github . > "$OUT_DIR/ruff.txt" 2>&1; then
        check_pass "Ruff clean ($RUFF_VERSION)"
    else
        VIOLATION_COUNT=$(wc -l < "$OUT_DIR/ruff.txt")
        check_fail "Ruff violations detected ($VIOLATION_COUNT) — see $OUT_DIR/ruff.txt"
    fi
else
    check_warn "Ruff not installed (skip linting)"
fi
echo ""

# 5. Snakefmt formatting
echo -e "${BLUE}[5/10] Snakefmt Formatting${NC}"
if command -v snakefmt &> /dev/null; then
    SNAKEFMT_VERSION=$(snakefmt --version | head -n 1)
    if snakefmt --check . > "$OUT_DIR/snakefmt.txt" 2>&1; then
        check_pass "Snakefmt clean ($SNAKEFMT_VERSION)"
    else
        # Extract number of files that would be changed
        FILES_CHANGED=$(grep -c "would be changed" "$OUT_DIR/snakefmt.txt" || echo 0)
        if [[ "$FILES_CHANGED" -le 1 ]]; then
            check_warn "Snakefmt needs formatting ($FILES_CHANGED file)"
        else
            check_fail "Snakefmt needs formatting ($FILES_CHANGED files)"
        fi
    fi
else
    check_warn "Snakefmt not installed (skip formatting check)"
fi
echo ""

# 6. Codespell
echo -e "${BLUE}[6/10] Codespell${NC}"
if command -v codespell &> /dev/null; then
    CODESPELL_VERSION=$(codespell --version 2>&1 | head -n 1)
    # Ignore common false positives and generated files
    if codespell --ignore-words-list="te,hist,trys,ue,ot,fo" --skip="site/,*.min.js,*.map,.venv/" . > "$OUT_DIR/codespell.txt" 2>&1; then
        check_pass "Codespell clean ($CODESPELL_VERSION)"
    else
        TYPO_COUNT=$(wc -l < "$OUT_DIR/codespell.txt")
        if [[ "$TYPO_COUNT" -lt 10 ]]; then
            check_warn "Codespell found $TYPO_COUNT potential typos — see $OUT_DIR/codespell.txt"
        else
            check_fail "Codespell found $TYPO_COUNT potential typos — see $OUT_DIR/codespell.txt"
        fi
    fi
else
    check_warn "Codespell not installed (skip spell check)"
fi
echo ""

# 7. Pytest
echo -e "${BLUE}[7/10] Pytest${NC}"
if command -v pytest &> /dev/null; then
    if pytest -q --tb=no > "$OUT_DIR/pytest.txt" 2>&1; then
        TEST_COUNT=$(grep -c "passed" "$OUT_DIR/pytest.txt" || echo "?")
        check_pass "Pytest passed ($TEST_COUNT tests)"
    else
        ERROR_COUNT=$(grep -c "ERROR\|FAILED" "$OUT_DIR/pytest.txt" || echo "?")
        check_fail "Pytest failed ($ERROR_COUNT errors/failures) — see $OUT_DIR/pytest.txt"
    fi
else
    check_warn "Pytest not installed (skip tests)"
fi
echo ""

# 8. MkDocs strict build
echo -e "${BLUE}[8/10] MkDocs Strict Build${NC}"
if command -v mkdocs &> /dev/null; then
    MKDOCS_VERSION=$(mkdocs --version | head -n 1)
    if mkdocs build --strict > "$OUT_DIR/mkdocs.txt" 2>&1; then
        check_pass "MkDocs build passed ($MKDOCS_VERSION)"
    else
        check_fail "MkDocs build failed — see $OUT_DIR/mkdocs.txt"
    fi
else
    check_warn "MkDocs not installed (skip docs build)"
fi
echo ""

# 9. Branch inventory
echo -e "${BLUE}[9/10] Branch Inventory${NC}"
BRANCH_COUNT=$(git branch | wc -l)
REMOTE_BRANCH_COUNT=$(git branch -r | wc -l)

if [[ "$BRANCH_COUNT" -le 3 ]]; then
    check_pass "Clean local branches ($BRANCH_COUNT branches)"
else
    check_warn "Multiple local branches ($BRANCH_COUNT) — consider cleanup"
fi

if [[ "$REMOTE_BRANCH_COUNT" -le 5 ]]; then
    check_pass "Clean remote branches ($REMOTE_BRANCH_COUNT branches)"
else
    check_warn "Multiple remote branches ($REMOTE_BRANCH_COUNT) — consider cleanup"
fi

# Save branch info
git branch --format='%(refname:short)|%(objectname:short)|%(committerdate:iso8601)' > "$OUT_DIR/branches.txt"
echo ""

# 10. JSON status artifact
echo -e "${BLUE}[10/10] Generate Status JSON${NC}"
python3 - <<'PY'
import json, subprocess, os, pathlib, sys

def sh(x):
    try:
        return subprocess.check_output(x, shell=True, text=True, stderr=subprocess.DEVNULL).strip()
    except:
        return ""

try:
    data = {
        "timestamp": sh("date -Iseconds"),
        "head": sh("git rev-parse --short HEAD"),
        "head_branch": sh("git rev-parse --abbrev-ref HEAD"),
        "main_exists": os.system("git show-ref --verify --quiet refs/heads/main") == 0,
        "origin_main_exists": os.system("git show-ref --verify --quiet refs/remotes/origin/main") == 0,
        "branches": {
            "local": sh("git branch --format='%(refname:short)'").splitlines(),
            "remote": sh("git branch -r --format='%(refname:short)'").splitlines(),
        },
        "tags": sh("git tag").splitlines(),
        "health": {
            "pytest_passed": os.system("pytest -q --tb=no >/dev/null 2>&1") == 0,
            "mkdocs_strict_passed": os.system("mkdocs build --strict >/dev/null 2>&1") == 0,
            "ruff_clean": os.system("ruff check --quiet . 2>/dev/null") == 0,
            "snakefmt_clean": os.system("snakefmt --check . >/dev/null 2>&1") == 0,
        },
        "divergence_from_main": sh("git rev-list --left-right --count origin/main...HEAD 2>/dev/null || echo '0 0'"),
    }
    pathlib.Path('ops/status').mkdir(parents=True, exist_ok=True)
    with open('ops/status/repo_status.json', 'w') as f:
        json.dump(data, f, indent=2)
    sys.exit(0)
except Exception as e:
    print(f"Error: {e}", file=sys.stderr)
    sys.exit(1)
PY

if [[ $? -eq 0 ]]; then
    check_pass "Status JSON generated → $OUT_DIR/repo_status.json"
else
    check_fail "Failed to generate status JSON"
fi
echo ""

# Summary
echo -e "${BLUE}======================================${NC}"
echo -e "${BLUE}Summary${NC}"
echo -e "${BLUE}======================================${NC}"
echo -e "${GREEN}Passed:${NC}  $PASS"
echo -e "${YELLOW}Warnings:${NC} $WARN"
echo -e "${RED}Failed:${NC}  $FAIL"
echo ""

if [[ "$FAIL" -eq 0 ]]; then
    echo -e "${GREEN}✓ Repository health: GOOD${NC}"
    echo "All critical checks passed. Warnings are acceptable."
    exit 0
elif [[ "$FAIL" -le 2 ]]; then
    echo -e "${YELLOW}⚠ Repository health: FAIR${NC}"
    echo "Some checks failed. Review $OUT_DIR/ for details."
    exit 1
else
    echo -e "${RED}✗ Repository health: POOR${NC}"
    echo "Multiple critical issues detected. Fix before proceeding."
    exit 1
fi
