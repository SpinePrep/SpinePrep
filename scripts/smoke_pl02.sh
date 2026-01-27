#!/usr/bin/env bash
set -euo pipefail

# Smoke test for S2_anat_cordref on one T1w and one T2w dataset (v1_validation).

# Use canonical workfolder naming if not specified
if [ -z "${1:-}" ]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    OUT_ROOT=$(python3 "$SCRIPT_DIR/get_next_workfolder.py" smoke)
    if [ $? -ne 0 ]; then
        echo "ERROR: Failed to get next workfolder" >&2
        exit 1
    fi
else
    OUT_ROOT="$1"
fi

DATASETS_LOCAL="${2:-config/datasets_local.yaml}"

poetry run spinalfmriprep run S2_anat_cordref \
  --dataset-key openneuro_ds005884_cospine_motor \
  --datasets-local "${DATASETS_LOCAL}" \
  --out "${OUT_ROOT}/openneuro_ds005884_cospine_motor"

poetry run spinalfmriprep run S2_anat_cordref \
  --dataset-key openneuro_ds005883_cospine_pain \
  --datasets-local "${DATASETS_LOCAL}" \
  --out "${OUT_ROOT}/openneuro_ds005883_cospine_pain"
