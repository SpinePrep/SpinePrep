# Derivatives

SpinePrep outputs follow the BIDS-Derivatives specification for maximum interoperability.

## Directory Structure

```
derivatives/spineprep/
├── dataset_description.json        # BIDS-Derivatives metadata
├── sub-01/
│   ├── func/
│   │   ├── sub-01_task-rest_run-01_desc-confounds_timeseries.tsv
│   │   ├── sub-01_task-rest_run-01_desc-confounds_timeseries.json
│   │   ├── sub-01_task-rest_run-01_desc-motion_params.tsv
│   │   ├── sub-01_task-rest_run-01_desc-motion_params.json
│   │   ├── sub-01_task-rest_run-01_desc-motion_bold.nii.gz
│   │   ├── sub-01_task-rest_run-01_desc-mppca_bold.nii.gz (optional)
│   │   └── sub-01_task-rest_run-01_space-PAM50_desc-ref_bold.nii.gz (optional)
│   ├── xfm/ (optional, if registration enabled)
│   │   └── from-epi_to-pam50_warp.nii.gz
│   └── reports/
│       └── sub-01_desc-qc.html
└── logs/
    ├── samples.tsv                 # Run manifest
    ├── manifest_deriv.tsv          # Derivative paths
    ├── discover.json               # BIDS discovery summary
    └── provenance/
        ├── dag.svg                 # Workflow DAG
        ├── doctor-TIMESTAMP.json   # Environment snapshot
        └── provenance.json         # Full provenance

```

## Core Outputs

### Confounds Timeseries

**File:** `*_desc-confounds_timeseries.tsv`

BIDS-compliant confounds table with columns:
- `framewise_displacement` - Power FD in mm
- `dvars` - Standardized DVARS
- `frame_censor` - Binary censoring mask (0=kept, 1=censored)
- `acomp_{tissue}_pc{N}` - aCompCor components (if enabled)

**Sidecar JSON:** `*_desc-confounds_timeseries.json`
- `GeneratedBy`: Pipeline name, version, code URL
- `Sources`: Original BIDS files
- `confounds`: Column descriptions with units and methods
- `Parameters`: Processing parameters (TR, thresholds, etc.)

### Motion Parameters

**File:** `*_desc-motion_params.tsv`

Six rigid-body motion parameters:
- `trans_x`, `trans_y`, `trans_z` (mm)
- `rot_x`, `rot_y`, `rot_z` (radians)

**Sidecar JSON:** `*_desc-motion_params.json`
- `GeneratedBy`: Pipeline info
- `Sources`: Input BOLD file(s)
- `Parameters`: Engine, slice axis, temporal crop info

### Processed BOLD

- **Motion-corrected**: `*_desc-motion_bold.nii.gz`
- **Denoised (optional)**: `*_desc-mppca_bold.nii.gz`
- **PAM50 space (optional)**: `*_space-PAM50_desc-ref_bold.nii.gz`

All have JSON sidecars with `GeneratedBy`, `Sources`, and `Parameters`.

## Provenance

### Dataset Description

**File:** `dataset_description.json`

Required fields per BIDS-Derivatives:
- `Name`: "SpinePrep Derivatives"
- `BIDSVersion`: "1.8.0"
- `DatasetType`: "derivative"
- `GeneratedBy`: Array with pipeline info
- `SourceDatasets`: Original BIDS dataset(s)

**Example:**

```json
{
  "Name": "SpinePrep Derivatives",
  "BIDSVersion": "1.8.0",
  "DatasetType": "derivative",
  "GeneratedBy": [{
    "Name": "SpinePrep",
    "Version": "0.1.0-dev",
    "Description": "Spinal cord fMRI preprocessing pipeline",
    "CodeURL": "https://github.com/SpinePrep/SpinePrep"
  }],
  "SourceDatasets": [{
    "URL": "/data/my-study-bids",
    "Version": "unknown"
  }]
}
```

### Full Provenance Snapshot

**File:** `logs/provenance/provenance.json`

Comprehensive processing record:
- `pipeline_version` - SpinePrep version
- `timestamp` - ISO 8601 timestamp
- `environment` - Python version, OS, kernel, PYTHONPATH
- `paths` - Absolute paths to BIDS root, derivatives, config, DAG
- `tools` - SCT version, other tool versions

**Example:**

```json
{
  "pipeline_version": "0.1.0-dev",
  "timestamp": "2025-10-08T18:00:00+00:00",
  "environment": {
    "python_version": "3.11.0",
    "os": "Linux",
    "kernel": "6.14.0-29-generic",
    "pythonpath": "/path/to/spineprep:/usr/lib/python3.11"
  },
  "paths": {
    "bids_root": "/data/study/bids",
    "deriv_root": "/data/study/derivatives/spineprep",
    "config_path": "/data/study/config.yaml",
    "dag_svg": "/data/study/derivatives/spineprep/logs/provenance/dag.svg"
  },
  "tools": {
    "sct": "7.1"
  }
}
```

## Validation

All sidecars conform to `schemas/derivatives.sidecar.schema.json`:

```bash
# Validate a sidecar
jsonschema -i derivatives/spineprep/sub-01/func/*_confounds.json \
          schemas/derivatives.sidecar.schema.json
```

## IntendedFor Field

Some derivatives include `IntendedFor` to link outputs:

```json
{
  "IntendedFor": [
    "sub-01/func/sub-01_task-rest_run-01_bold.nii.gz"
  ]
}
```

Paths are BIDS-relative (relative to BIDS root).

## Naming Conventions

SpinePrep follows BIDS-Derivatives naming:

- **Descriptors**: `desc-confounds`, `desc-motion`, `desc-mppca`
- **Spaces**: `space-native`, `space-PAM50`
- **Entities order**: `sub-XX_[ses-YY_]task-ZZ_run-NN_[space-SS_]desc-DD_suffix.ext`

## Per-File Provenance

Each output can have a `.prov.json` file with processing details:

```
sub-01_task-rest_run-01_desc-motion_bold.nii.gz
sub-01_task-rest_run-01_desc-motion_bold.nii.gz.prov.json
```

These are **optional** and contain step-specific details beyond the main JSON sidecar.

