#!/usr/bin/env bash
set -euo pipefail
# Confounds builder (placeholder) — idempotent, provenance-aware.
# ENV:
#   IN_BOLD : input nifti (required) — typically *_desc-motioncorr_bold.nii.gz
#   TR_S    : optional TR in seconds (default 1.0)
#
# Outputs next to IN_BOLD:
#   *_desc-confounds_timeseries.tsv
#   *_desc-confounds_timeseries.json
#   *_desc-confounds_timeseries.prov.json

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./_common/step_contract_header.sh
source "${HERE}/_common/step_contract_header.sh"

: "${IN_BOLD:?IN_BOLD is required}"
TR_S="${TR_S:-1.0}"

require_file "$IN_BOLD"

in_dir="$(dirname "$IN_BOLD")"
in_base="$(basename "$IN_BOLD" .nii.gz)"
base_no_bold="${in_base%_bold}"

out_tsv="${in_dir}/${base_no_bold}_desc-confounds_timeseries.tsv"
out_json="${in_dir}/${base_no_bold}_desc-confounds_timeseries.json"

if [[ -f "$out_tsv" && -f "$out_json" ]]; then
  log "Confounds already exist, skipping: $out_tsv"
  exit 0
fi

# Determine nvols using fslval if available; otherwise 1.
nvols=1
if command -v fslval >/dev/null 2>&1; then
  set +e
  tdim="$(fslval "$IN_BOLD" dim4 2>/dev/null | tr -d '[:space:]')"
  set -e
  if [[ "$tdim" =~ ^[0-9]+$ && "$tdim" -gt 0 ]]; then
    nvols="$tdim"
  fi
fi

params_tsv="${in_dir}/${base_no_bold}_desc-motionparams.tsv"

tmp_tsv="${out_tsv}.tmp"
{
  printf "trans_x\ttrans_y\ttrans_z\trot_x\trot_y\trot_z\tframewise_displacement\tdvars\tnon_steady_state_outlier00\n"
  if [[ -f "$params_tsv" ]]; then
    awk 'BEGIN{FS="\t"; OFS="\t"} NR==1{next} {print $1,$2,$3,$4,$5,$6,0,0,0}' "$params_tsv"
  else
    awk -v nvols="$nvols" 'BEGIN{OFS="\t"} {for(i=1;i<=nvols;i++) print 0,0,0,0,0,0,0,0,0; exit}'
  fi
} > "$tmp_tsv"

tmp_json="${out_json}.tmp"
cat > "$tmp_json" <<JSON
{
  "trans_x": {"Description": "Rigid-body translation (x), placeholder mm"},
  "trans_y": {"Description": "Rigid-body translation (y), placeholder mm"},
  "trans_z": {"Description": "Rigid-body translation (z), placeholder mm"},
  "rot_x": {"Description": "Rigid-body rotation (x), placeholder rad"},
  "rot_y": {"Description": "Rigid-body rotation (y), placeholder rad"},
  "rot_z": {"Description": "Rigid-body rotation (z), placeholder rad"},
  "framewise_displacement": {"Description": "FD (Power), placeholder", "Units": "mm"},
  "dvars": {"Description": "DVARS, placeholder", "Units": "a.u."},
  "non_steady_state_outlier00": {"Description": "NSS outlier flag (placeholder)", "Levels": [0,1]},
  "RepetitionTime": {"Description": "TR in seconds", "Value": ${TR_S}}
}
JSON

mv -f "$tmp_tsv" "$out_tsv"
mv -f "$tmp_json" "$out_json"

tools='{"confounds":"placeholder"}'
inputs_json="$(printf '{"IN_BOLD": "%s"}' "$IN_BOLD")"
params_json="$(printf '{"TR_S": %.6f}' "$TR_S")"
write_prov "$out_tsv" "spi07_confounds" "$inputs_json" "$params_json" "$tools"

log "Wrote confounds: $out_tsv"
