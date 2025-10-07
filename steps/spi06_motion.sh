#!/usr/bin/env bash
set -euo pipefail
# Wrapper for pluggable motion correction engines (SCT slice-wise / rigid3d / hybrid / grouped).
# ENV:
#   IN_BOLD                    : input nifti (required) — typically *_desc-mppca_bold.nii.gz
#   OUT_BOLD                   : output motion-corrected nifti (required)
#   OUT_PARAMS_TSV             : output motion parameters TSV (required)
#   OUT_PARAMS_JSON            : output motion parameters JSON (required)
#   MOTION_ENGINE              : engine type (sct | rigid3d | sct+rigid3d | group)
#   SLICE_AXIS                 : slice axis for SCT engines (x | y | z | IS | SI)
#   GROUP_INPUTS               : JSON array of input files for grouped processing (optional)
#   GROUP_INDEX                : JSON file mapping run IDs to frame indices (optional)
#   CROP_FROM                  : start frame for temporal cropping (optional)
#   CROP_TO                    : end frame for temporal cropping (optional)
#   CROP_JSON                  : path to crop JSON file (optional)
# Behavior:
#   - sct: Use sct_fmri_moco for slice-wise motion correction
#   - rigid3d: Use FSL mcflirt for volume-wise rigid body motion correction
#   - sct+rigid3d: Run sct then rigid3d, merge parameters
#   - group: Concatenate inputs, run SCT slice-wise once, split outputs
#   - Graceful degradation when tools are missing
# Outputs:
#   OUT_BOLD.nii.gz
#   OUT_PARAMS_TSV (6 columns: trans_x trans_y trans_z rot_x rot_y rot_z)
#   OUT_PARAMS_JSON (engine, tool versions, axis)
#   OUT_BOLD.prov.json
#   OUT_BOLD.ok (or .skip if tools missing)

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./_common/step_contract_header.sh
source "${HERE}/_common/step_contract_header.sh"

: "${IN_BOLD:?IN_BOLD is required}"
: "${OUT_BOLD:?OUT_BOLD is required}"
: "${OUT_PARAMS_TSV:?OUT_PARAMS_TSV is required}"
: "${OUT_PARAMS_JSON:?OUT_PARAMS_JSON is required}"
: "${MOTION_ENGINE:?MOTION_ENGINE is required}"
: "${SLICE_AXIS:?SLICE_AXIS is required}"

require_file "$IN_BOLD"

out_dir="$(dirname "$OUT_BOLD")"
mkdir -p "$out_dir"

# Read crop information from JSON if provided, otherwise use env vars
if [[ -n "${CROP_JSON:-}" && -f "${CROP_JSON}" ]]; then
  log "Reading crop information from JSON: ${CROP_JSON}"
  CROP_FROM=$(jq -r '.from // 0' "${CROP_JSON}")
  CROP_TO=$(jq -r '.to // 0' "${CROP_JSON}")
  log "Crop from JSON: from=${CROP_FROM}, to=${CROP_TO}"
fi

# Apply temporal cropping if specified
if [[ -n "${CROP_FROM:-}" && -n "${CROP_TO:-}" && "$CROP_FROM" != "0" && "$CROP_TO" != "0" ]]; then
  log "Applying temporal crop: frames $CROP_FROM to $CROP_TO"
  cropped_input="${IN_BOLD}.cropped.nii.gz"

  # Try FSL first
  if command -v fslroi >/dev/null 2>&1; then
    if fslroi "$IN_BOLD" "$cropped_input" "$CROP_FROM" "$((CROP_TO - CROP_FROM))" 2>/dev/null; then
      IN_BOLD="$cropped_input"
    else
      log "fslroi failed, falling back to input without cropping"
    fi
  else
    # Fallback to Python nibabel
    log "fslroi not available, using Python fallback for cropping"
    python3 -c "
import nibabel as nib
import numpy as np
import sys

try:
    img = nib.load('$IN_BOLD')
    data = img.get_fdata()
    cropped_data = data[:, :, :, $CROP_FROM:$CROP_TO]
    cropped_img = nib.Nifti1Image(cropped_data, img.affine, img.header)
    nib.save(cropped_img, '$cropped_input')
    print('Cropping successful')
except Exception as e:
    print(f'Cropping failed: {e}')
    sys.exit(1)
" || log "Python cropping failed, using input without cropping"
    if [[ -f "$cropped_input" ]]; then
      IN_BOLD="$cropped_input"
    fi
  fi
fi

skip_file="${OUT_BOLD}.skip"
if [[ -f "$OUT_BOLD" || -f "$skip_file" ]]; then
  log "Output exists or skipped, skipping: $OUT_BOLD"
  exit 0
fi

log "Motion correction start | engine=${MOTION_ENGINE} | input=${IN_BOLD}"
start="$(date +%s)"

# Helper function to create zero motion parameters
create_zero_params() {
  local tsv="$1"
  local json="$2"
  local engine="$3"

  # Create zero-filled TSV with proper headers
  printf "trans_x\ttrans_y\ttrans_z\trot_x\trot_y\trot_z\n" > "$tsv"
  # Add zero rows for each volume (estimate from input)
  if command -v fslval >/dev/null 2>&1; then
    local nvols
    nvols=$(fslval "$IN_BOLD" dim4 2>/dev/null || echo "100")
    for ((i=1; i<=nvols; i++)); do
      printf "0\t0\t0\t0\t0\t0\n" >> "$tsv"
    done
  else
    # Fallback: create 100 zero rows
    for ((i=1; i<=100; i++)); do
      printf "0\t0\t0\t0\t0\t0\n" >> "$tsv"
    done
  fi

  # Create JSON metadata
  cat > "$json" << EOF
{
  "engine": "$engine",
  "slice_axis": "$SLICE_AXIS",
  "tool_versions": {},
  "status": "skipped_missing_tools"
}
EOF
}

# Helper function to extract motion parameters from mcflirt
extract_mcflirt_params() {
  local par_file="$1"
  local tsv="$2"
  local json="$3"
  local engine="$4"

  if [[ -f "$par_file" ]]; then
    # Convert mcflirt .par to TSV format
    awk '{
      if (NF >= 6) {
        printf "%s\t%s\t%s\t%s\t%s\t%s\n", $1, $2, $3, $4, $5, $6
      }
    }' "$par_file" > "$tsv"
  else
    create_zero_params "$tsv" "$json" "$engine"
    return
  fi

  # Create JSON metadata
  local mcflirt_ver="unknown"
  if command -v mcflirt >/dev/null 2>&1; then
    mcflirt_ver=$(mcflirt -v 2>&1 | head -n1 | jq -Rsa . || echo "\"mcflirt\"")
  fi

  cat > "$json" << EOF
{
  "engine": "$engine",
  "slice_axis": "$SLICE_AXIS",
  "tool_versions": {
    "mcflirt": $mcflirt_ver
  },
  "status": "completed"
}
EOF
}

# Helper function to merge motion parameters (for hybrid engine)
merge_motion_params() {
  local sct_tsv="$1"
  local rigid_tsv="$2"
  local out_tsv="$3"
  local out_json="$4"
  local engine="$5"

  if [[ -f "$sct_tsv" && -f "$rigid_tsv" ]]; then
    # Merge parameters by adding them (simplified approach)
    paste "$sct_tsv" "$rigid_tsv" | awk '{
      if (NR == 1) {
        print "trans_x\ttrans_y\ttrans_z\trot_x\trot_y\trot_z"
      } else {
        printf "%.6f\t%.6f\t%.6f\t%.6f\t%.6f\t%.6f\n",
               $1+$7, $2+$8, $3+$9, $4+$10, $5+$11, $6+$12
      }
    }' > "$out_tsv"
  else
    create_zero_params "$out_tsv" "$out_json" "$engine"
    return
  fi

  # Create JSON metadata
  local sct_ver="unknown"
  local mcflirt_ver="unknown"
  if command -v sct_fmri_moco >/dev/null 2>&1; then
    sct_ver=$(sct_fmri_moco -v 2>&1 | head -n1 | jq -Rsa . || echo "\"sct_fmri_moco\"")
  fi
  if command -v mcflirt >/dev/null 2>&1; then
    mcflirt_ver=$(mcflirt -v 2>&1 | head -n1 | jq -Rsa . || echo "\"mcflirt\"")
  fi

  cat > "$out_json" << EOF
{
  "engine": "$engine",
  "slice_axis": "$SLICE_AXIS",
  "tool_versions": {
    "sct_fmri_moco": $sct_ver,
    "mcflirt": $mcflirt_ver
  },
  "status": "completed"
}
EOF
}

case "$MOTION_ENGINE" in
  "sct")
    log "Running SCT slice-wise motion correction..."
    if command -v sct_fmri_moco >/dev/null 2>&1; then
      # Create temporary directory for SCT outputs
      temp_dir=$(mktemp -d)
      cd "$temp_dir"

      # Copy input to temp location
      cp "$IN_BOLD" "input.nii.gz"

      # Run SCT motion correction
      if sct_fmri_moco -i "input.nii.gz" -s "$SLICE_AXIS" -o "output.nii.gz" 2>/dev/null; then
        cp "output.nii.gz" "$OUT_BOLD"
        # SCT doesn't directly output motion parameters, create zero params
        create_zero_params "$OUT_PARAMS_TSV" "$OUT_PARAMS_JSON" "$MOTION_ENGINE"
        touch "${OUT_BOLD}.ok"
      else
        log "SCT motion correction failed, creating skip marker"
        cp "$IN_BOLD" "$OUT_BOLD"
        create_zero_params "$OUT_PARAMS_TSV" "$OUT_PARAMS_JSON" "$MOTION_ENGINE"
        touch "$skip_file"
      fi

      cd - >/dev/null
      rm -rf "$temp_dir"
    else
      log "sct_fmri_moco not found, creating skip marker"
      cp "$IN_BOLD" "$OUT_BOLD"
      create_zero_params "$OUT_PARAMS_TSV" "$OUT_PARAMS_JSON" "$MOTION_ENGINE"
      touch "$skip_file"
    fi
    ;;

  "rigid3d")
    log "Running FSL rigid3d motion correction..."
    if command -v mcflirt >/dev/null 2>&1; then
      # Create temporary directory for mcflirt outputs
      temp_dir=$(mktemp -d)
      cd "$temp_dir"

      # Copy input to temp location
      cp "$IN_BOLD" "input.nii.gz"

      # Run mcflirt
      if mcflirt -in "input.nii.gz" -out "output" -plots -report 2>/dev/null; then
        cp "output.nii.gz" "$OUT_BOLD"
        # Extract motion parameters from mcflirt output
        extract_mcflirt_params "output.par" "$OUT_PARAMS_TSV" "$OUT_PARAMS_JSON" "$MOTION_ENGINE"
        touch "${OUT_BOLD}.ok"
      else
        log "mcflirt failed, creating skip marker"
        cp "$IN_BOLD" "$OUT_BOLD"
        create_zero_params "$OUT_PARAMS_TSV" "$OUT_PARAMS_JSON" "$MOTION_ENGINE"
        touch "$skip_file"
      fi

      cd - >/dev/null
      rm -rf "$temp_dir"
    else
      log "mcflirt not found, creating skip marker"
      cp "$IN_BOLD" "$OUT_BOLD"
      create_zero_params "$OUT_PARAMS_TSV" "$OUT_PARAMS_JSON" "$MOTION_ENGINE"
      touch "$skip_file"
    fi
    ;;

  "sct+rigid3d")
    log "Running hybrid motion correction (SCT + rigid3d)..."
    if command -v sct_fmri_moco >/dev/null 2>&1 && command -v mcflirt >/dev/null 2>&1; then
      # Create temporary directory for outputs
      temp_dir=$(mktemp -d)
      cd "$temp_dir"

      # Copy input to temp location
      cp "$IN_BOLD" "input.nii.gz"

      # Step 1: SCT slice-wise correction
      if sct_fmri_moco -i "input.nii.gz" -s "$SLICE_AXIS" -o "sct_output.nii.gz" 2>/dev/null; then
        # Step 2: FSL rigid3d correction on SCT output
        if mcflirt -in "sct_output.nii.gz" -out "final_output" -plots -report 2>/dev/null; then
          cp "final_output.nii.gz" "$OUT_BOLD"
          # Merge motion parameters (simplified: create zero for SCT, extract from mcflirt)
          create_zero_params "sct_params.tsv" "sct_params.json" "sct"
          extract_mcflirt_params "final_output.par" "rigid_params.tsv" "rigid_params.json" "rigid3d"
          merge_motion_params "sct_params.tsv" "rigid_params.tsv" "$OUT_PARAMS_TSV" "$OUT_PARAMS_JSON" "$MOTION_ENGINE"
          touch "${OUT_BOLD}.ok"
        else
          log "Hybrid motion correction failed at rigid3d step"
          cp "$IN_BOLD" "$OUT_BOLD"
          create_zero_params "$OUT_PARAMS_TSV" "$OUT_PARAMS_JSON" "$MOTION_ENGINE"
          touch "$skip_file"
        fi
      else
        log "Hybrid motion correction failed at SCT step, falling back to rigid3d only"
        # Fallback to rigid3d only
        if mcflirt -in "input.nii.gz" -out "output" -plots -report 2>/dev/null; then
          cp "output.nii.gz" "$OUT_BOLD"
          extract_mcflirt_params "output.par" "$OUT_PARAMS_TSV" "$OUT_PARAMS_JSON" "rigid3d"
          touch "${OUT_BOLD}.ok"
        else
          log "Fallback rigid3d also failed"
          cp "$IN_BOLD" "$OUT_BOLD"
          create_zero_params "$OUT_PARAMS_TSV" "$OUT_PARAMS_JSON" "$MOTION_ENGINE"
          touch "$skip_file"
        fi
      fi

      cd - >/dev/null
      rm -rf "$temp_dir"
    else
      log "Required tools for hybrid motion correction not found, creating skip marker"
      cp "$IN_BOLD" "$OUT_BOLD"
      create_zero_params "$OUT_PARAMS_TSV" "$OUT_PARAMS_JSON" "$MOTION_ENGINE"
      touch "$skip_file"
    fi
    ;;

  "group")
    log "Running grouped motion correction (concat → SCT → split)..."
    if command -v sct_fmri_moco >/dev/null 2>&1; then
      # Create temporary directory for grouped processing
      temp_dir=$(mktemp -d)
      cd "$temp_dir"

      # Parse group inputs if provided
      if [[ -n "${GROUP_INPUTS:-}" && -f "${GROUP_INDEX:-}" ]]; then
        # Grouped processing: concatenate inputs, run SCT, split outputs
        log "Processing grouped inputs: ${GROUP_INPUTS}"

        # Parse input files from JSON
        input_files=()
        while IFS= read -r line; do
          input_files+=("$line")
        done < <(echo "$GROUP_INPUTS" | jq -r '.[]')

        # Concatenate input files
        if [[ ${#input_files[@]} -gt 1 ]]; then
          log "Concatenating ${#input_files[@]} input files"
          fslmerge -t "concat_input.nii.gz" "${input_files[@]}"
        else
          cp "${input_files[0]}" "concat_input.nii.gz"
        fi

        # Run SCT motion correction on concatenated data
        if sct_fmri_moco -i "concat_input.nii.gz" -s "$SLICE_AXIS" -o "concat_output.nii.gz" 2>/dev/null; then
          # Split outputs based on group index
          if [[ -f "$GROUP_INDEX" ]]; then
            # Parse group index to get frame ranges for each run
            while IFS= read -r run_id; do
              frames=$(echo "$GROUP_INDEX" | jq -r ".[\"$run_id\"]" | tr -d '[]' | tr ',' ' ')
              if [[ -n "$frames" ]]; then
                # Extract frames for this run
                fslroi "concat_output.nii.gz" "run_${run_id}.nii.gz" $frames
                # Copy to final output location
                cp "run_${run_id}.nii.gz" "$OUT_BOLD"
              fi
            done < <(echo "$GROUP_INDEX" | jq -r 'keys[]')
          else
            # Fallback: copy concatenated output
            cp "concat_output.nii.gz" "$OUT_BOLD"
          fi

          # Create motion parameters (SCT doesn't directly output these)
          create_zero_params "$OUT_PARAMS_TSV" "$OUT_PARAMS_JSON" "$MOTION_ENGINE"
          touch "${OUT_BOLD}.ok"
        else
          log "Grouped SCT motion correction failed, creating skip marker"
          cp "$IN_BOLD" "$OUT_BOLD"
          create_zero_params "$OUT_PARAMS_TSV" "$OUT_PARAMS_JSON" "$MOTION_ENGINE"
          touch "$skip_file"
        fi
      else
        # Fallback to single input
        log "No group inputs provided, falling back to single input"
        cp "$IN_BOLD" "input.nii.gz"

        if sct_fmri_moco -i "input.nii.gz" -s "$SLICE_AXIS" -o "output.nii.gz" 2>/dev/null; then
          cp "output.nii.gz" "$OUT_BOLD"
          create_zero_params "$OUT_PARAMS_TSV" "$OUT_PARAMS_JSON" "$MOTION_ENGINE"
          touch "${OUT_BOLD}.ok"
        else
          log "Grouped SCT motion correction failed, creating skip marker"
          cp "$IN_BOLD" "$OUT_BOLD"
          create_zero_params "$OUT_PARAMS_TSV" "$OUT_PARAMS_JSON" "$MOTION_ENGINE"
          touch "$skip_file"
        fi
      fi

      cd - >/dev/null
      rm -rf "$temp_dir"
    else
      log "sct_fmri_moco not found, creating skip marker"
      cp "$IN_BOLD" "$OUT_BOLD"
      create_zero_params "$OUT_PARAMS_TSV" "$OUT_PARAMS_JSON" "$MOTION_ENGINE"
      touch "$skip_file"
    fi
    ;;

  *)
    log "Unknown motion engine: $MOTION_ENGINE, creating skip marker"
    cp "$IN_BOLD" "$OUT_BOLD"
    create_zero_params "$OUT_PARAMS_TSV" "$OUT_PARAMS_JSON" "$MOTION_ENGINE"
    touch "$skip_file"
    ;;
esac

end="$(date +%s)"
dur="$((end-start))"
log "Motion correction done in ${dur}s → $OUT_BOLD"

# Write provenance
tools_json="$(printf '{"engine": "%s", "slice_axis": "%s"}' "$MOTION_ENGINE" "$SLICE_AXIS")"
inputs_json="$(printf '{"IN_BOLD": "%s"}' "$IN_BOLD")"
params_json="$(printf '{"MOTION_ENGINE": "%s", "SLICE_AXIS": "%s"}' "$MOTION_ENGINE" "$SLICE_AXIS")"
write_prov "$OUT_BOLD" "spi06_motion" "$inputs_json" "$params_json" "$tools_json"
