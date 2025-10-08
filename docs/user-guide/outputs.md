# Outputs

SpinePrep produces BIDS-compliant derivatives following the BIDS-Derivatives specification. This page describes the output structure and file naming conventions.

## Output Structure

```
derivatives/
└── spineprep/
    ├── dataset_description.json
    ├── participants.tsv
    ├── logs/
    │   ├── manifest_deriv.tsv
    │   └── samples.tsv
    └── sub-01/
        ├── ses-01/
        │   ├── func/
        │   │   ├── sub-01_ses-01_task-rest_run-01_bold.nii.gz
        │   │   ├── sub-01_ses-01_task-rest_run-01_bold.json
        │   │   ├── sub-01_ses-01_task-rest_run-01_desc-confounds_timeseries.tsv
        │   │   ├── sub-01_ses-01_task-rest_run-01_desc-confounds_timeseries.json
        │   │   ├── sub-01_ses-01_task-rest_run-01_desc-censor_mask.nii.gz
        │   │   └── sub-01_ses-01_task-rest_run-01_desc-censor_mask.json
        │   └── anat/
        │       ├── sub-01_ses-01_T2w.nii.gz
        │       ├── sub-01_ses-01_T2w.json
        │       ├── sub-01_ses-01_desc-cord_mask.nii.gz
        │       └── sub-01_ses-01_desc-cord_mask.json
        └── reports/
            ├── sub-01_ses-01_task-rest_run-01_desc-qc_report.html
            └── sub-01_ses-01_task-rest_run-01_desc-qc_report.json
```

## File Naming Convention

SpinePrep follows BIDS naming conventions with the following pattern:

```
{entity}_{label}_{suffix}_{desc}_{ext}
```

### Entities

- `sub-{participant_id}`: Subject identifier
- `ses-{session_id}`: Session identifier (optional)
- `task-{task_id}`: Task identifier
- `run-{run_id}`: Run identifier (optional)
- `space-{space_id}`: Space identifier (e.g., `orig`, `PAM50`)

### Suffixes

- `bold`: Preprocessed BOLD data
- `T2w`: T2-weighted anatomical data
- `mask`: Binary mask files
- `timeseries`: Time series data (confounds)

### Descriptors

- `preproc`: Preprocessed data
- `confounds`: Confound regressors
- `censor`: Censor mask
- `cord`: Spinal cord mask
- `qc`: Quality control data

## Preprocessed Data

### BOLD Data

**File**: `sub-{id}_ses-{id}_task-{id}_run-{id}_bold.nii.gz`

Preprocessed BOLD data with the following processing steps applied:

- Motion correction
- Slice timing correction (if specified)
- Spatial smoothing (if specified)
- Intensity normalization

**Sidecar**: `sub-{id}_ses-{id}_task-{id}_run-{id}_bold.json`

```json
{
  "RepetitionTime": 2.0,
  "SliceTiming": [0.0, 0.5, 1.0, 1.5],
  "ProcessingSoftware": "SpinePrep",
  "ProcessingSoftwareVersion": "0.1.0",
  "ProcessingSteps": [
    "Motion correction",
    "Slice timing correction",
    "Spatial smoothing"
  ]
}
```

### Anatomical Data

**File**: `sub-{id}_ses-{id}_T2w.nii.gz`

Preprocessed T2-weighted anatomical data with:

- Bias field correction
- Intensity normalization
- Registration to standard space (if specified)

## Confound Regressors

### Motion Parameters

**File**: `sub-{id}_ses-{id}_task-{id}_run-{id}_desc-confounds_timeseries.tsv`

Tab-separated file containing motion parameters and other confounds:

```tsv
framewise_displacement	trans_x	trans_y	trans_z	rot_x	rot_y	rot_z	global_signal	white_matter	csf	acompcor_00	acompcor_01	acompcor_02	acompcor_03	acompcor_04	acompcor_05
0.1234	0.001	0.002	0.003	0.0001	0.0002	0.0003	1234.5	234.5	345.6	0.123	0.456	0.789	0.012	0.345	0.678
```

**Columns**:
- `framewise_displacement`: Framewise displacement (FD)
- `trans_x/y/z`: Translation parameters
- `rot_x/y/z`: Rotation parameters
- `global_signal`: Global signal
- `white_matter`: White matter signal
- `csf`: CSF signal
- `acompcor_00` to `acompcor_05`: aCompCor components

### Censor Mask

**File**: `sub-{id}_ses-{id}_task-{id}_run-{id}_desc-censor_mask.nii.gz`

Binary mask indicating which time points to censor based on motion thresholds.

## Masks

### Spinal Cord Mask

**File**: `sub-{id}_ses-{id}_desc-cord_mask.nii.gz`

Binary mask of the spinal cord region.

### Vertebral Level Masks

**File**: `sub-{id}_ses-{id}_desc-level-{level}_mask.nii.gz`

Binary masks for specific vertebral levels (C1, C2, etc.).

## Quality Control

### QC Report

**File**: `sub-{id}_ses-{id}_task-{id}_run-{id}_desc-qc_report.html`

Interactive HTML report containing:

- Motion plots (FD, DVARS)
- aCompCor component plots
- Censor mask visualization
- Processing summary

### QC Metrics

**File**: `sub-{id}_ses-{id}_task-{id}_run-{id}_desc-qc_report.json`

JSON file containing quantitative QC metrics:

```json
{
  "motion": {
    "mean_fd": 0.1234,
    "max_fd": 0.5678,
    "outlier_frames": 5,
    "outlier_percentage": 2.5
  },
  "signal": {
    "mean_dvars": 45.6,
    "max_dvars": 123.4,
    "snr": 12.3
  },
  "processing": {
    "total_time": 1234.5,
    "steps_completed": ["motion", "confounds", "registration"],
    "warnings": [],
    "errors": []
  }
}
```

## Logs and Manifests

### Samples File

**File**: `logs/samples.tsv`

```tsv
participant_id	session_id	task_id	run_id	space	desc	path
sub-01	ses-01	task-rest	run-01	orig	preproc	sub-01/ses-01/func/sub-01_ses-01_task-rest_run-01_bold.nii.gz
```

### Manifest File

**File**: `logs/manifest_deriv.tsv`

```tsv
path	desc	space	res	den	tr	ts	acq	rec	dir	run	modality	chunk	part	ext
sub-01/ses-01/func/sub-01_ses-01_task-rest_run-01_bold.nii.gz	preproc	orig	2.0	0.0	2.0	0.0	0.0	0.0	0.0	1.0	func	0.0	0.0	.nii.gz
```

## Dataset Description

**File**: `dataset_description.json`

```json
{
  "Name": "SpinePrep derivatives",
  "BIDSVersion": "1.6.0",
  "DatasetType": "derivatives",
  "GeneratedBy": [
    {
      "Name": "SpinePrep",
      "Version": "0.1.0",
      "Description": "Spinal cord preprocessing pipeline",
      "CodeURL": "https://github.com/spineprep/spineprep",
      "Container": {
        "Type": "docker",
        "Tag": "spineprep/spineprep:0.1.0"
      }
    }
  ],
  "PipelineDescription": {
    "Name": "SpinePrep",
    "Version": "0.1.0",
    "CodeURL": "https://github.com/spineprep/spineprep"
  }
}
```
