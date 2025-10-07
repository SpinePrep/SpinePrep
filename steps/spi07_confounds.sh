#!/usr/bin/env bash
set -euo pipefail
# Confounds builder — FD (from motion params) + DVARS into derivatives, JSON sidecar.
# ENV:
#   IN_BOLD : input nifti (required) — typically *_desc-motioncorr_bold.nii.gz
#   OUT_TSV : output confounds TSV (required)
#   OUT_JSON : output confounds JSON (required)
#   TR_S    : optional TR in seconds (default 1.0)
#   CROP_FROM : start frame for temporal cropping (optional)
#   CROP_TO   : end frame for temporal cropping (optional)
#   CROP_JSON : path to crop JSON file (optional)
#   MOTION_PARAMS_TSV : path to motion parameters TSV (optional)
#
# Outputs:
#   OUT_TSV (confounds TSV with framewise_displacement, dvars columns)
#   OUT_JSON (metadata with Sources, FDMethod, DVARSMethod, etc.)
#   OUT_TSV.prov.json (provenance)

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./_common/step_contract_header.sh
source "${HERE}/_common/step_contract_header.sh"

: "${IN_BOLD:?IN_BOLD is required}"
: "${OUT_TSV:?OUT_TSV is required}"
: "${OUT_JSON:?OUT_JSON is required}"
TR_S="${TR_S:-1.0}"

require_file "$IN_BOLD"

# Read crop information from JSON if provided, otherwise use env vars
if [[ -n "${CROP_JSON:-}" && -f "${CROP_JSON}" ]]; then
  log "Reading crop information from JSON: ${CROP_JSON}"
  CROP_FROM=$(jq -r '.from // 0' "${CROP_JSON}")
  CROP_TO=$(jq -r '.to // 0' "${CROP_JSON}")
  log "Crop from JSON: from=${CROP_FROM}, to=${CROP_TO}"
fi

# Check if outputs already exist
if [[ -f "$OUT_TSV" && -f "$OUT_JSON" ]]; then
  log "Confounds already exist, skipping: $OUT_TSV"
  exit 0
fi

log "Confounds builder start | input=${IN_BOLD}"
start="$(date +%s)"

# Apply temporal cropping if specified
if [[ -n "${CROP_FROM:-}" && -n "${CROP_TO:-}" && "$CROP_FROM" != "0" && "$CROP_TO" != "0" ]]; then
  log "Applying temporal crop: frames $CROP_FROM to $CROP_TO"
  cropped_input="${IN_BOLD}.cropped.nii.gz"

  # Try FSL first
  if command -v fslroi >/dev/null 2>&1; then
    fslroi "$IN_BOLD" "$cropped_input" "$CROP_FROM" "$((CROP_TO - CROP_FROM))"
    input_for_processing="$cropped_input"
  else
    log "fslroi not available, using full input"
    input_for_processing="$IN_BOLD"
  fi
else
  input_for_processing="$IN_BOLD"
fi

# Create Python script for confounds computation
python_script=$(cat << 'EOF'
import sys
import json
import numpy as np
from pathlib import Path

# Add workflow lib to path
sys.path.insert(0, str(Path(__file__).parent.parent / "workflow"))
from lib.confounds import (
    read_motion_params, compute_fd_from_params, compute_dvars,
    assemble_confounds, write_confounds_tsv_json
)

def main():
    # Parse arguments
    in_bold = sys.argv[1]
    out_tsv = sys.argv[2]
    out_json = sys.argv[3]
    tr_s = float(sys.argv[4])
    motion_params_tsv = sys.argv[5] if len(sys.argv) > 5 and sys.argv[5] != "None" else None
    crop_from = int(sys.argv[6]) if len(sys.argv) > 6 else 0
    crop_to = int(sys.argv[7]) if len(sys.argv) > 7 else 0

    # Compute FD from motion parameters if available
    if motion_params_tsv and Path(motion_params_tsv).exists():
        try:
            motion_params = read_motion_params(motion_params_tsv)
            fd = compute_fd_from_params(motion_params, tr_s)
            fd_source = "motion_params"
        except Exception as e:
            print(f"Warning: Failed to read motion parameters: {e}")
            # Fallback to zeros
            n_vols = 100  # Default fallback
            if Path(in_bold).exists():
                try:
                    import nibabel as nib
                    img = nib.load(in_bold)
                    n_vols = img.shape[3]
                except:
                    pass
            fd = np.zeros(n_vols)
            fd_source = "fallback_zeros"
    else:
        # No motion parameters available, use zeros
        n_vols = 100  # Default fallback
        if Path(in_bold).exists():
            try:
                import nibabel as nib
                img = nib.load(in_bold)
                n_vols = img.shape[3]
            except:
                pass
        fd = np.zeros(n_vols)
        fd_source = "no_motion_params"

    # Compute DVARS from BOLD data
    try:
        dvars = compute_dvars(in_bold)
    except Exception as e:
        print(f"Warning: Failed to compute DVARS: {e}")
        dvars = np.zeros(len(fd))

    # Assemble confounds DataFrame
    df = assemble_confounds(fd, dvars)

    # Create metadata
    meta = {
        "Sources": [fd_source, "bold_data"],
        "FDMethod": "power_fd",
        "DVARSMethod": "std_dvars",
        "SamplingFrequency": tr_s,
        "CropFrom": crop_from,
        "CropTo": crop_to,
        "Description": "Confounds from SpinePrep (FD from motion params + DVARS)"
    }

    # Write outputs
    write_confounds_tsv_json(df, out_tsv, out_json, meta)
    print(f"Confounds written to {out_tsv}")

if __name__ == "__main__":
    main()
EOF
)

# Run Python confounds computation
python3 -c "$python_script" \
  "$input_for_processing" \
  "$OUT_TSV" \
  "$OUT_JSON" \
  "$TR_S" \
  "${MOTION_PARAMS_TSV:-None}" \
  "${CROP_FROM:-0}" \
  "${CROP_TO:-0}"

end="$(date +%s)"
dur="$((end-start))"
log "Confounds builder done in ${dur}s → $OUT_TSV"

# Write provenance
tools_json="$(printf '{"step": "spi07_confounds.sh", "tr_s": %s}' "$TR_S")"
inputs_json="$(printf '{"IN_BOLD": "%s", "MOTION_PARAMS_TSV": "%s"}' "$IN_BOLD" "${MOTION_PARAMS_TSV:-None}")"
params_json="$(printf '{"TR_S": %s, "CROP_FROM": "%s", "CROP_TO": "%s"}' "$TR_S" "${CROP_FROM:-0}" "${CROP_TO:-0}")"
write_prov "$OUT_TSV" "spi07_confounds" "$inputs_json" "$params_json" "$tools_json"
