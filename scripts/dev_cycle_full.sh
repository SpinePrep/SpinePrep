#!/bin/bash
# Full development cycle runner
# Usage: ./scripts/dev_cycle_full.sh --step S3_func_init_and_crop

set -e

STEP=""
OUT=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --step)
            STEP="$2"
            shift 2
            ;;
        --out)
            OUT="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

if [ -z "$STEP" ]; then
    echo "ERROR: --step required"
    exit 1
fi

# Use canonical workfolder naming if --out not specified
if [ -z "$OUT" ]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    OUT=$(python3 "$SCRIPT_DIR/get_next_workfolder.py" full)
    if [ $? -ne 0 ]; then
        echo "ERROR: Failed to get next workfolder" >&2
        exit 1
    fi
fi

echo "=========================================="
echo "SpinalfMRIprep Development Cycle"
echo "=========================================="
echo "Step: $STEP"
echo "Output: $OUT"
echo ""

# 1. Unit tests
echo "1. Running unit tests..."
poetry run pytest tests/test_*.py -v --tb=short || exit 1

# 2. Smoke test
echo ""
echo "2. Running smoke test..."
SMOKE_SCRIPT="scripts/smoke_${STEP}.py"

if [ -f "$SMOKE_SCRIPT" ]; then
    python3 "$SMOKE_SCRIPT" || exit 1
else
    echo "  ⚠ Smoke test script not found: $SMOKE_SCRIPT"
    echo "  Skipping smoke test..."
fi

# 3. Validation (regression)
echo ""
echo "3. Running validation on regression datasets..."
python3 scripts/validate_regression.py --step "$STEP" --out "$OUT" || exit 1

# 4. Acceptance
echo ""
echo "4. Running acceptance tests..."
# Extract ticket from step (simplified)
# S3_func_init_and_crop -> BUILD-S3-T1
STEP_NUM=$(echo "$STEP" | sed 's/S\([0-9]\).*/\1/')
TICKET="BUILD-S${STEP_NUM}-T1"

python3 scripts/acceptance_test.py --ticket "$TICKET" --step "$STEP" --out "$OUT" || exit 1

echo ""
echo "=========================================="
echo "✓ Development cycle completed successfully"
echo "=========================================="

