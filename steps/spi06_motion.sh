#!/usr/bin/env bash
set -euo pipefail
# Wrapper for motion correction. Analysis-agnostic, idempotent, provenance-aware.
# ENV:
#   IN_BOLD        : input nifti (required) — typically *_desc-mppca_bold.nii.gz
#   MOTION_ENABLE  : 0/1 toggle (required)
# Behavior:
#   - If steps/original/spi06_motion_orig.sh exists and MOTION_ENABLE=1,
#     call it with IN_BOLD and OUT_BOLD (temp path), then move into place.
#   - Else, copy IN_BOLD -> *_desc-motioncorr_bold.nii.gz to preserve DAG continuity.
# Outputs:
#   *_desc-motioncorr_bold.nii.gz
#   *_desc-motionparams.tsv        (minimal header if missing)
#   *_desc-motioncorr_bold.prov.json

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./_common/step_contract_header.sh
source "${HERE}/_common/step_contract_header.sh"

: "${IN_BOLD:?IN_BOLD is required}"
: "${MOTION_ENABLE:?MOTION_ENABLE is required}"

require_file "$IN_BOLD"

in_dir="$(dirname "$IN_BOLD")"
in_base="$(basename "$IN_BOLD" .nii.gz)"
base_no_bold="${in_base%_bold}"
out="${in_dir}/${base_no_bold}_desc-motioncorr_bold.nii.gz"
params_tsv="${in_dir}/${base_no_bold}_desc-motionparams.tsv"

if [[ -f "$out" ]]; then
  log "Output exists, skipping: $out"
  exit 0
fi

log "Motion wrapper start | input=${IN_BOLD} | enable=${MOTION_ENABLE}"
start="$(date +%s)"

orig="${HERE}/original/spi06_motion_orig.sh"
tmp_out="${out}.tmp"

if [[ "${MOTION_ENABLE}" == "1" && -x "$orig" ]]; then
  IN_BOLD="$IN_BOLD" OUT_BOLD="$tmp_out" bash "$orig"
  [[ -f "$tmp_out" ]] || { log "Original motion script did not produce output: $tmp_out"; exit 3; }
else
  cp -f "$IN_BOLD" "$tmp_out"
fi

mv -f "$tmp_out" "$out"

# Ensure params TSV exists
if [[ ! -f "$params_tsv" ]]; then
  printf "trans_x\ttrans_y\ttrans_z\trot_x\trot_y\trot_z\n" > "${params_tsv}.tmp"
  mv -f "${params_tsv}.tmp" "$params_tsv"
fi

end="$(date +%s)"
dur="$((end-start))"
log "Motion wrapper done in ${dur}s → $out"

tools_json='{"motion":"unknown"}'
inputs_json="$(printf '{"IN_BOLD": "%s"}' "$IN_BOLD")"
params_json="$(printf '{"MOTION_ENABLE": %s}' "${MOTION_ENABLE}")"
write_prov "$out" "spi06_motion" "$inputs_json" "$params_json" "$tools_json"
