# Ingest

`spineprep run` indexes your BIDS dataset and writes `manifest.csv`.

## What it does
- Walks the BIDS root (skipping `derivatives/`, `code/`, `sourcedata/`)
- Indexes imaging and metadata files
- Computes size and sha256 (files ≤ 50 MB by default)
- Infers basic BIDS fields (subject, session, modality, suffix)

## Output
`<out>/manifest.csv` with columns:
`path, relpath, size, sha256, subject, session, modality, suffix, ext`

## CLI
```bash
spineprep run --bids /data/bids --out /data/derivatives/spineprep
```

