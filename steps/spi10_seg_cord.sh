#!/usr/bin/env bash
set -euo pipefail

# Wrapper for spinal cord segmentation
# ENV in: IN_T2, OUT_CORDMASK
# Behavior: If sct_deepseg_sc available, use it; else create .skip

: "${IN_T2:?IN_T2 is required}"
: "${OUT_CORDMASK:?OUT_CORDMASK is required}"

out_dir="$(dirname "$OUT_CORDMASK")"
mkdir -p "$out_dir"

skip_file="${OUT_CORDMASK}.skip"
if [[ -f "$OUT_CORDMASK" || -f "$skip_file" ]]; then
    echo "Output exists or skipped, skipping: $OUT_CORDMASK"
    exit 0
fi

if command -v sct_deepseg_sc >/dev/null 2>&1; then
    echo "Running sct_deepseg_sc..."
    if sct_deepseg_sc -i "$IN_T2" -c t2 -o "$OUT_CORDMASK" 2>/dev/null; then
        touch "${OUT_CORDMASK}.ok"
    else
        echo "sct_deepseg_sc failed. Creating skip marker."
        if command -v fslmaths >/dev/null 2>&1; then
            fslmaths "$IN_T2" -mul 0 "$OUT_CORDMASK" 2>/dev/null || cp "$IN_T2" "$OUT_CORDMASK"
        else
            cp "$IN_T2" "$OUT_CORDMASK"
        fi
        touch "$skip_file"
    fi
else
    echo "sct_deepseg_sc not found. Creating skip marker."
    if command -v fslmaths >/dev/null 2>&1; then
        fslmaths "$IN_T2" -mul 0 "$OUT_CORDMASK" 2>/dev/null || cp "$IN_T2" "$OUT_CORDMASK"
    else
        cp "$IN_T2" "$OUT_CORDMASK"
    fi
    touch "$skip_file"
fi

# Write provenance
meta='{"step": "spi10_seg_cord", "inputs": {"IN_T2": "'"$IN_T2"'"}, "timestamp": "'$(date -Iseconds)'"}'
echo "$meta" > "${OUT_CORDMASK}.prov.json"
