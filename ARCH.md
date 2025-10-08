# SpinePrep Architecture

## Overview

SpinePrep is a BIDS-compliant preprocessing pipeline for spinal cord functional MRI data. It provides a modular, configurable workflow for denoising, motion correction, and confounds extraction.

## Core Components

### Configuration System
- **Base Configuration**: `configs/base.yaml` - Global defaults
- **Study Configuration**: `configs/study.yaml` - Study-specific overrides
- **Schema Validation**: `schemas/config.schema.json` - JSON Schema validation

### Data Discovery
- **BIDS Adapter**: `adapters/bids.py` - BIDS dataset discovery and validation
- **Manifest Generation**: Creates normalized manifests from discovered data

### Processing Pipeline
- **MP-PCA Denoising**: `steps/spi05_mppca.sh` - MP-PCA denoising wrapper
- **Motion Correction**: `steps/spi06_motion.sh` - Pluggable motion correction engines
- **Confounds Extraction**: `steps/spi07_confounds.sh` - Confounds extraction wrapper

### Quality Control
- **Subject Reports**: HTML reports with motion metrics and confounds visualization
- **Provenance Tracking**: JSON metadata for all processing steps

## Registration & Masks Architecture

### Overview
The registration system provides SCT-guided spatial normalization and mask generation for spinal cord data. It's designed as an opt-in feature that gracefully degrades when SCT tools are unavailable.

### Data Flow
1. **Input Discovery**: Locate EPI and T2w anatomical images from BIDS structure
2. **Cord Segmentation**: Segment spinal cord using `sct_deepseg_sc`
3. **Vertebral Labeling**: Label vertebral levels using `sct_label_vertebrae`
4. **Registration Chain**:
   - EPI → T2w registration (`sct_register_multimodal`)
   - T2w → PAM50 template registration (`sct_register_to_template`)
5. **Mask Generation**: Warp PAM50 masks to native and PAM50 spaces

### Warps
- **EPI to T2w**: `sub-XX/xfm/from-epi_to-t2.h5`
- **T2w to PAM50**: `sub-XX/xfm/from-t2_to-pam50.h5`

### Masks
- **Native Space**: `.../func/..._space-native_desc-{cord,wm,csf}mask.nii.gz`
- **PAM50 Space**: `.../func/..._space-PAM50_desc-{cord,wm,csf}mask.nii.gz`

### Provenance
Each registration step generates:
- **Output Files**: Primary outputs (masks, warps, transformed images)
- **Provenance JSON**: `.prov.json` files with inputs, parameters, and tool versions
- **Status Markers**: `.ok` or `.skip` files indicating completion status

### Failure/Skip Behavior
- **Missing SCT Tools**: Creates `.skip` markers and dummy outputs
- **Missing Anatomical Images**: Falls back to EPI mean for registration
- **Tool Failures**: Graceful degradation with skip markers

### Configuration
```yaml
registration:
  enable: true                    # Enable/disable registration
  template: PAM50                 # Template space
  guidance: SCT                   # Registration guidance method
  levels: auto                    # Vertebral levels (auto-detect)
  use_gm_wm_masks: true          # Generate GM/WM masks
  rootlets:
    enable: false                 # Rootlet segmentation
    mode: atlas                   # Rootlet mode
```

### Integration
- **Conditional Execution**: Only runs when `registration.enable: true`
- **QC Integration**: Registration status included in subject reports
- **BIDS Compliance**: All outputs follow BIDS-derivatives naming

## Motion Engines Architecture

### Overview
The motion correction system provides three configurable engines for different motion correction strategies, with graceful degradation when tools are unavailable.

### Engine Types
1. **SCT Slice-wise** (`sct`): Uses `sct_fmri_moco` for slice-wise motion correction
2. **Rigid 3D** (`rigid3d`): Uses FSL `mcflirt` for volume-wise rigid body motion correction
3. **Hybrid** (`sct+rigid3d`): Combines SCT slice-wise followed by rigid 3D correction

### Data Flow
1. **Input**: Preprocessed BOLD data (from MP-PCA or original)
2. **Engine Selection**: Based on `options.motion.engine` configuration
3. **Motion Correction**: Apply selected engine with appropriate parameters
4. **Parameter Extraction**: Extract motion parameters from tool outputs
5. **Output Generation**: Motion-corrected BOLD + motion parameters

### Artifacts
- **Motion-Corrected BOLD**: `*_desc-motioncorr_bold.nii.gz`
- **Motion Parameters**: `*_desc-motion_params.tsv` (6 columns: trans_x, trans_y, trans_z, rot_x, rot_y, rot_z)
- **Parameter Metadata**: `*_desc-motion_params.json` (engine, tool versions, axis)
- **Provenance**: `*_motion.prov.json` and `*_motion.ok` markers

### Engine Matrix
| Engine | Tool | Slice-wise | Volume-wise | Fallback |
|--------|------|------------|-------------|----------|
| `sct` | `sct_fmri_moco` | ✓ | ✗ | Skip + zeros |
| `rigid3d` | `mcflirt` | ✗ | ✓ | Copy input |
| `sct+rigid3d` | Both | ✓ | ✓ | rigid3d only |

### Failure Modes
- **Missing SCT Tools**: Creates `.skip` markers and zero-filled parameter files
- **Missing FSL Tools**: Falls back to input copy with zero parameters
- **Hybrid with Missing SCT**: Falls back to rigid3d only
- **Tool Failures**: Graceful degradation with appropriate fallbacks

### Configuration
```yaml
options:
  motion:
    engine: rigid3d        # sct, rigid3d, or sct+rigid3d
    slice_axis: z          # x, y, or z (for SCT engines)
```

### Integration
- **QC Integration**: Motion parameters used for FD computation in QC reports
- **Confounds Integration**: Motion parameters available for confounds extraction
- **BIDS Compliance**: All outputs follow BIDS-derivatives naming conventions

## Temporal Crop (TRIM)

### Overview
The temporal crop module automatically detects and removes head/tail volumes with artifacts using robust z-statistics on cord ROI mean signal. This helps improve data quality by removing volumes with motion artifacts, scanner startup effects, or other temporal artifacts.

### Detector Strategy
- **Input**: 4D BOLD data, optional cord mask, confounds TSV
- **Method**: Compute per-volume mean within cord mask (if available) or whole-FOV mean
- **Robust z-statistics**: Use median and MAD (median absolute deviation) for robust outlier detection
- **Threshold**: Trim leading/trailing contiguous volumes with |z| > z_thresh (default 2.5)
- **Bounds**: Clamp trimming to max_trim_start/max_trim_end (default 10 volumes each)

### Order of Operations
1. **Crop Detection**: `crop_detect[{id}]` rule analyzes BOLD data and writes crop indices
2. **Motion Correction**: `motion[{id}]` rule applies temporal crop before motion correction
3. **Confounds**: `confounds[{id}]` rule uses cropped data for confound extraction
4. **Registration**: All downstream processing uses cropped volumes

### Provenance
- Crop indices stored in `*_desc-crop.json` with fields: `{from, to, nvols, reason}`
- Motion correction provenance includes crop information
- QC reports show trim badges per run

### Failure Modes
- **No FSL**: Falls back to Python nibabel for cropping operations
- **Missing cord mask**: Uses whole-FOV mean signal for detection
- **Detection failure**: Defaults to no cropping (from=0, to=nvols)
- **Invalid bounds**: Clamps to valid ranges [0, nvols]

### Configuration
```yaml
options:
  temporal_crop:
    enable: true                    # Enable/disable temporal cropping
    method: cord_mean_robust_z       # Detection method
    max_trim_start: 10              # Maximum volumes to trim from start
    max_trim_end: 10                # Maximum volumes to trim from end
    z_thresh: 2.5                   # Z-score threshold for outlier detection
```

### Integration
- **QC Integration**: Trim badges shown in subject reports
- **Motion Integration**: Cropping applied before motion correction
- **BIDS Compliance**: All outputs follow BIDS-derivatives naming conventions

### Temporal Crop Contract

The temporal crop system uses a **sidecar JSON file** as the single source of truth for crop information:

- **Crop Sidecar**: `*_desc-crop.json` contains `{"from": X, "to": Y, "nvols": Z, "reason": "..."}`
- **Runtime Contract**: Motion and confounds wrappers read crop information from the sidecar at runtime
- **No Circular Dependencies**: Crop detection runs as a per-run wildcard rule, avoiding startup manifest access
- **Graceful Fallback**: If crop sidecar is missing, wrappers use environment variables or default to no cropping
- **Provenance Tracking**: Motion correction provenance includes crop information and source

## Confounds & Censoring

### Confounds Pipeline

The confounds pipeline extracts motion and quality metrics from BOLD data:

1. **FD Computation**: Framewise Displacement from motion parameters using Power et al. (2012) method
2. **DVARS Computation**: Root mean square of BOLD signal changes between consecutive volumes
3. **Censoring**: Optional frame censoring (scrubbing) based on FD/DVARS thresholds

### Censor Algorithm

The censoring system identifies and marks problematic frames for exclusion from statistical modeling:

#### Step 1: Threshold-based Censoring
- Frame censored if `FD > fd_thresh_mm` OR `DVARS > dvars_thresh`
- Default thresholds: FD = 0.5mm, DVARS = 1.5

#### Step 2: Padding
- Add `pad_vols` frames before and after each censored frame
- Default padding: 1 frame (total 3-frame window around each outlier)

#### Step 3: Contiguity Filtering
- Remove kept segments shorter than `min_contig_vols`
- Default minimum: 5 consecutive non-censored volumes
- Prevents isolated "islands" of kept data

#### Outputs
- **TSV Columns**: `framewise_displacement`, `dvars`, `frame_censor` (0=kept, 1=censored)
- **JSON Metadata**: Censor thresholds, counts (`n_censored`, `n_kept`)
- **QC Integration**: Censored frames overlaid on FD/DVARS plots

### Configuration

```yaml
options:
  censor:
    enable: true                  # enable frame censoring
    fd_thresh_mm: 0.5            # FD threshold in mm (0.1-2.0)
    dvars_thresh: 1.5            # DVARS threshold (0.5-5.0)
    min_contig_vols: 5           # minimum consecutive non-censored volumes (3-50)
    pad_vols: 1                  # padding around censored frames (0-3)
```

### Integration with Temporal Crop

- Censoring operates on **cropped** BOLD data (after temporal crop)
- Crop information preserved in confounds JSON metadata

## Masks & aCompCor

### Overview

The masks and aCompCor system provides anatomical component-based noise correction using tissue-specific masks. This system integrates with the registration pipeline to generate masks and extract principal components for physiological noise removal.

### Mask Sources

#### SCT-Generated Masks (Default)
- **Cord Mask**: Spinal cord segmentation from T2w anatomical image
- **White Matter Mask**: White matter regions within cord mask
- **CSF Mask**: Cerebrospinal fluid regions within cord mask
- **Source**: SCT registration pipeline (`sct_deepseg_sc`, `sct_register_multimodal`)
- **Space**: EPI (functional) space for aCompCor computation

#### Provided Masks (Alternative)
- **User-supplied**: Pre-computed masks in EPI space
- **Path**: Specified in configuration or manifest
- **Format**: Binary NIfTI masks (0/1 values)

#### Disabled Masks
- **Fallback**: When SCT unavailable or masks disabled
- **Behavior**: aCompCor skipped, confounds contain only FD/DVARS/censor

### aCompCor Algorithm

#### Step 1: Time Series Extraction
- Load BOLD data with temporal cropping applied
- Extract time series from each tissue mask
- Standardize time series (optional, default: true)

#### Step 2: Preprocessing
- **Detrending**: Linear detrending (optional, default: true)
- **High-pass Filtering**: Butterworth filter (default: 0.008 Hz)
- **Standardization**: Z-score normalization (optional, default: true)

#### Step 3: Principal Component Analysis
- **PCA**: Extract principal components from tissue time series
- **Components**: Up to `n_components_per_tissue` (default: 5)
- **Rank Limiting**: Automatically cap at available rank
- **Empty Masks**: Skip tissues with no voxels

#### Step 4: Output Generation
- **TSV Columns**: `acomp_{tissue}_pc{01..N}` (e.g., `acomp_cord_pc01`)
- **JSON Metadata**: Component counts, explained variance per tissue
- **Canonical Order**: aCompCor columns after `frame_censor`

### Configuration

```yaml
options:
  masks:
    enable: true                  # require masks for aCompCor
    source: "sct"                 # enum: sct|provided|none
    binarize_thr: 0.5            # threshold for probabilistic masks (0-1)
  acompcor:
    enable: true
    tissues: ["cord", "wm", "csf"]  # tissues to include
    n_components_per_tissue: 5      # max components per tissue (1-10)
    highpass_hz: 0.008            # high-pass filter frequency (0-0.2)
    detrend: true                  # detrend time series
    standardize: true              # standardize time series
    explained_variance_min: 0.0    # minimum explained variance (0-1)
```

### Outputs

#### TSV Files
- **Path**: `*_desc-confounds_timeseries.tsv`
- **Columns**: `framewise_displacement`, `dvars`, `frame_censor`, `acomp_{tissue}_pc{01..N}`
- **Format**: Tab-separated values with headers

#### JSON Metadata
- **Path**: `*_desc-confounds_timeseries.json`
- **Structure**:
  ```json
  {
    "aCompCor": {
      "cord": {
        "n_components": 5,
        "explained_variance": [0.45, 0.23, 0.15, 0.10, 0.07]
      },
      "wm": {
        "n_components": 3,
        "explained_variance": [0.38, 0.22, 0.18]
      },
      "csf": {
        "n_components": 0,
        "explained_variance": []
      }
    }
  }
  ```

### Quality Control Integration

#### Subject Reports
- **EV Plots**: Explained variance plots per run and tissue
- **PC Counts**: Number of components extracted per tissue
- **Table Display**: aCompCor PC counts in run summary table
- **Graceful Degradation**: Reports work with or without aCompCor data

#### Provenance
- **Mask Paths**: Source mask files for each tissue
- **Parameters**: aCompCor settings (components, filtering, etc.)
- **Tissue Status**: Which tissues had successful PC extraction

### Integration Points

#### Registration Pipeline
- **Mask Generation**: SCT pipeline creates EPI-space masks
- **Path Resolution**: `mask_paths()` function maps manifest rows to mask files
- **Fallback Handling**: Empty strings when masks disabled/unavailable

#### Confounds Pipeline
- **Input**: Cropped BOLD data and tissue masks
- **Processing**: Time series extraction and PCA computation
- **Output**: Enhanced confounds with aCompCor columns

#### Temporal Crop Integration
- **Input**: aCompCor uses cropped BOLD data
- **Consistency**: Same temporal window as motion correction and confounds
- **Metadata**: Crop information preserved in JSON sidecar
- QC plots show both temporal crop and censoring effects

## Documentation Architecture

### Site Goals
The SpinePrep documentation site provides a first-class user experience that surpasses fMRIPrep in clarity and scientific rigor. The site serves as the primary interface for users to understand, configure, and troubleshoot the SpinePrep pipeline.

### Site Structure
- **Landing Page**: Value proposition, quickstart, and sample reports
- **Getting Started**: Installation, minimal configuration, and first run
- **User Guide**: Comprehensive usage documentation including CLI, configuration, outputs, QC, and registration
- **How-tos**: Common recipes and advanced workflows
- **Reference**: Auto-generated API and configuration documentation
- **Contributing**: Development setup, CI gates, and contribution guidelines

### CI/Deploy Policy
- **Build**: MkDocs Material with strict mode enabled
- **Quality Gates**: Linting (ruff), formatting (ruff format), spell checking (codespell), link checking (lychee)
- **Generation**: Auto-generate reference docs from schema and source code
- **Deployment**: Automatic deployment to GitHub Pages on main branch
- **Versioning**: Support for versioned documentation using mike
