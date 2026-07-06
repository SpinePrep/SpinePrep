#!/bin/bash
# Container integration smoke test (T2.1 / T3.2).
#
# Runs the SpinalfMRIprep container end-to-end (participant + group) on ONE
# subject and asserts the expected BIDS-Derivatives + QC + reproducibility
# artifacts are produced. Use this to verify a fresh build or a new install
# reproduces known-good outputs. Not a CI unit test — it needs the built image
# and the neuro toolchain inside it.
#
# Usage:
#   scripts/container_smoke_test.sh <IMAGE> <BIDS_DIR> <SUBJECT_LABEL> [OUT_DIR] [docker|apptainer]
# Example:
#   scripts/container_smoke_test.sh spinalfmriprep:7.1 /data/ds004616 06

set -euo pipefail

IMAGE="${1:?usage: container_smoke_test.sh IMAGE BIDS SUBJECT [OUT] [docker|apptainer]}"
BIDS="${2:?BIDS dir required}"
SUB="${3:?subject label required (without sub-)}"
OUT="${4:-$(mktemp -d)/out}"
RUNTIME="${5:-docker}"
mkdir -p "$OUT"

run() {  # run <level>
  local level="$1"
  case "$RUNTIME" in
    docker)
      sudo docker run --rm -v "$BIDS":/bids:ro -v "$OUT":/out \
        "$IMAGE" /bids /out "$level" --participant-label "$SUB" ;;
    apptainer)
      apptainer run --cleanenv --writable-tmpfs --pwd /app \
        --bind "$BIDS":/bids:ro --bind "$OUT":/out \
        "$IMAGE" /bids /out "$level" --participant-label "$SUB" ;;
    *) echo "unknown runtime: $RUNTIME" >&2; exit 2 ;;
  esac
}

echo "== participant =="; run participant
echo "== group =="; run group

D="$OUT/derivatives/spinalfmriprep"
fail=0
check() {  # check <glob-description> <path-or-glob>
  if compgen -G "$2" > /dev/null; then echo "  OK   $1"; else echo "  MISS $1 ($2)"; fail=1; fi
}
echo "== asserting outputs =="
check "GLM-ready preproc BOLD"        "$D/*/sub-$SUB/**/func/*desc-preproc_bold.nii.gz"
check "confounds timeseries"          "$D/*/sub-$SUB/**/func/*desc-confounds_timeseries.tsv"
check "PAM50 spinal-level atlas"      "$D/*/sub-$SUB/**/func/*desc-PAM50spinallevels.nii.gz"
check "per-level tSNR"                "$D/*/sub-$SUB/**/func/*desc-tsnr_per_level.tsv"
check "dataset_description.json"      "$D/dataset_description.json"
check "reproducibility receipt"       "$D/reproducibility_receipt.json"
check "release report"               "$D/release_report.html"
check "run manifest"                 "$OUT/spinalfmriprep_run_manifest.json"

if [ "$fail" -eq 0 ]; then
  echo "SMOKE TEST PASSED  (outputs in $OUT)"
else
  echo "SMOKE TEST FAILED  (see MISS lines above; outputs in $OUT)"; exit 1
fi
