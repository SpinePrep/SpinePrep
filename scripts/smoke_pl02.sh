#!/usr/bin/env bash
set -euo pipefail

# Smoke test for S2_anat_cordref on one T1w and one T2w dataset (v1_validation).

OUT_ROOT="${1:-work/s2_smoke}"
DATASETS_LOCAL="${2:-config/datasets_local.yaml}"

poetry run spineprep run S2_anat_cordref \
  --dataset-key openneuro_ds005884_cospine_motor \
  --datasets-local "${DATASETS_LOCAL}" \
  --out "${OUT_ROOT}/openneuro_ds005884_cospine_motor"

poetry run spineprep run S2_anat_cordref \
  --dataset-key openneuro_ds005883_cospine_pain \
  --datasets-local "${DATASETS_LOCAL}" \
  --out "${OUT_ROOT}/openneuro_ds005883_cospine_pain"
