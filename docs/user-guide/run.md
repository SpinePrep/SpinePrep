# Running SpinePrep

## Basic Execution

To run the SpinePrep workflow on your BIDS dataset:

```bash
spineprep run --bids /path/to/bids --out /path/to/output
```

This will:
1. Scan the BIDS directory and generate a manifest
2. Execute the preprocessing workflow
3. Write outputs to the specified directory

## DAG Export

To visualize the workflow DAG without executing:

```bash
spineprep run --bids /path/to/bids --out /path/to/output --save-dag dag.svg
```

Supported formats:
- **SVG** (`.svg`): Rendered graph (requires graphviz `dot`)
- **DOT** (`.dot`): Plain text graph description

The DAG export shows the dependency graph of all workflow rules and can be useful for:
- Understanding workflow structure
- Debugging execution order
- Documentation and presentations

## Dry Run

To validate BIDS and generate manifest without executing the workflow:

```bash
spineprep run --bids /path/to/bids --out /path/to/output --dry-run
```

This performs:
- BIDS directory validation
- Manifest CSV generation
- No workflow execution

## Options

- `--bids PATH`: BIDS dataset directory (required)
- `--out PATH`: Output directory (required)
- `--config PATH`: Optional YAML configuration file
- `-n, --dry-run`: Generate manifest only, no execution
- `--save-dag PATH`: Export workflow DAG and exit
- `--print-config`: Display resolved configuration

## Denoising (A4)

SpinePrep applies MP-PCA (Marchenko-Pastur PCA) denoising to BOLD series using DIPY if available:

- **Input:** Raw BOLD series from BIDS
- **Output:** `<out>/denoised/*_desc-mppca_bold.nii.gz`
- **Fallback:** If DIPY is not installed, data is copied through without denoising (with warning)

The denoising step:
- Uses patch radius of 5 and stride of 3 by default
- Preserves image shape and affine
- Runs automatically for all functional series in the manifest

## Examples

```bash
# Full run (includes MP-PCA denoising)
spineprep run --bids /data/study --out /data/derivatives

# Dry-run to check BIDS and manifest
spineprep run --bids /data/study --out /data/derivatives --dry-run

# Export DAG visualization
spineprep run --bids /data/study --out /data/derivatives --save-dag workflow.svg

# With custom config
spineprep run --bids /data/study --out /data/derivatives --config study.yaml
```
