# Configuration

SpinePrep reads a YAML config, merges it with defaults, then applies CLI overrides, and validates the result.

## Precedence
`CLI > YAML file > defaults`

## Usage
```bash
spineprep run --bids /data/bids --out /data/derivatives/spineprep \
  --config configs/base.yaml --print-config
```

If invalid, you will see a schema error message and a non-zero exit code.

