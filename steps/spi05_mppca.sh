#!/usr/bin/env bash
set -euo pipefail
# Wrapper for MP-PCA denoising. Keeps logic analysis-agnostic and idempotent.
# ENV in:
#   IN_BOLD          : input bold nifti (required)
#   DENOISE_MPPCA    : 0/1 toggle (required)
# Behavior:
#   - If steps/original/spi05_mppca_orig.sh exists and DENOISE_MPPCA=1, call it.
#   - Else, copy IN_BOLD -> *_mppca.nii.gz (no-op) to preserve pipeline continuity.
# Output:
#   <same dir>/<basename>_mppca.nii.gz + .prov.json

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./_common/step_contract_header.sh
source "${HERE}/_common/step_contract_header.sh"

: "${IN_BOLD:?IN_BOLD is required}"
: "${DENOISE_MPPCA:?DENOISE_MPPCA is required}"

require_file "$IN_BOLD"

in_dir="$(dirname "$IN_BOLD")"
in_base="$(basename "$IN_BOLD" .nii.gz)"
out="${in_dir}/${in_base%_bold}_mppca_bold.nii.gz"

if [[ -f "$out" ]]; then
  log "Output exists, skipping: $out"
  exit 0
fi

start="$(date +%s)"
log "MP-PCA wrapper start | input=${IN_BOLD} | denoise=${DENOISE_MPPCA}"

orig="${HERE}/original/spi05_mppca_orig.sh"
tmp_out="${out}.tmp"

if [[ "${DENOISE_MPPCA}" == "1" && -x "$orig" ]]; then
  # Use original script; it must read IN_BOLD and write to $out or stdout.
  # We standardize by capturing to tmp then move.
  IN_BOLD="$IN_BOLD" OUT_BOLD="$tmp_out" bash "$orig"
  [[ -f "$tmp_out" ]] || { log "Original MP-PCA script did not produce output: $tmp_out"; exit 3; }
else
  # No-op denoise: copy input to mppca output
  cp -f "$IN_BOLD" "$tmp_out"
fi

mv -f "$tmp_out" "$out"

end="$(date +%s)"
dur="$((end-start))"
log "MP-PCA wrapper done in ${dur}s → $out"

# Minimal tool version capture (best-effort)
ver_mppca="\"unknown\""
if command -v dwidenoise >/dev/null 2>&1; then ver_mppca="$(dwidenoise -version 2>/dev/null | head -n1 | jq -Rsa . || echo "\"dwidenoise\"")"; fi

inputs_json="$(printf '{"IN_BOLD": "%s"}' "$IN_BOLD")"
params_json="$(printf '{"DENOISE_MPPCA": %s}' "${DENOISE_MPPCA}")"
tools_json="$(printf '{"mppca": %s}' "${ver_mppca}")"
write_prov "$out" "spi05_mppca" "$inputs_json" "$params_json" "$tools_json"
