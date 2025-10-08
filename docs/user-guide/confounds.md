# Confounds and Quality Metrics

SpinePrep computes comprehensive confound regressors and quality metrics for spinal cord fMRI data.

## Overview

The confounds pipeline generates a BIDS-compliant `*_desc-confounds_timeseries.tsv` file for each BOLD run, along with a JSON sidecar describing each column.

## Standard Columns

### Motion Metrics

- **framewise_displacement**: Frame-to-frame motion (Power et al., 2012)
  - Units: mm
  - Method: `power_fd`
  - First volume: 0 (no prior frame)
  - Computed from 6 rigid-body parameters (3 translations + 3 rotations)
  - Rotation converted to mm using 50mm radius

- **dvars**: Root mean square of BOLD signal changes
  - Units: normalized intensity
  - Method: `std_dvars`
  - First volume: 0
  - Computed within mask (cord or whole brain)

### Frame Censoring

- **frame_censor**: Binary censoring mask
  - Values: `0` = kept, `1` = censored
  - Thresholds: Configurable FD and DVARS cutoffs
  - Padding: Optional frames around outliers
  - Contiguity: Minimum consecutive kept volumes

#### Censoring Algorithm

1. **Threshold**: Mark frames where `FD > fd_thresh_mm` OR `DVARS > dvars_thresh`
2. **Padding**: Extend censoring by `pad_vols` frames before/after each outlier
3. **Contiguity**: Remove kept segments shorter than `min_contig_vols`

**Example Configuration:**

```yaml
options:
  censor:
    enable: true
    fd_thresh_mm: 0.5      # 0.5mm threshold
    dvars_thresh: 1.5      # 1.5 SD threshold
    min_contig_vols: 5     # Keep runs of 5+ consecutive frames
    pad_vols: 1            # Pad ±1 frame around outliers
```

### aCompCor (Anatomical Component Correction)

SpinePrep extracts principal components from anatomical tissue masks to capture physiological noise.

**Supported Tissues:**
- **cord**: Full spinal cord mask
- **wm**: White matter mask
- **csf**: CSF mask

**Column Naming:**
- `acomp_cord_pc01`, `acomp_cord_pc02`, ... (up to `n_components`)
- `acomp_wm_pc01`, `acomp_wm_pc02`, ...
- `acomp_csf_pc01`, `acomp_csf_pc02`, ...

**Preprocessing Pipeline:**
1. Extract voxel time series from tissue mask
2. Detrend (optional, default: true)
3. High-pass filter (optional, default: 0.008 Hz)
4. Standardize (optional, default: true)
5. PCA extraction (up to available rank)

**Configuration:**

```yaml
options:
  acompcor:
    enable: true
    tissues: ["cord", "wm", "csf"]
    n_components_per_tissue: 5
    highpass_hz: 0.008
    detrend: true
    standardize: true
```

## JSON Sidecar

The `*_desc-confounds_timeseries.json` sidecar contains:

- **Column descriptions**: Metadata for each confound
- **Processing parameters**: Thresholds, filters, settings
- **aCompCor metadata**: Components extracted, explained variance per component
- **Censor statistics**: Counts of censored/kept frames, kept segments
- **Provenance**: Input files, processing timestamp

**Example JSON:**

```json
{
  "confounds": {
    "framewise_displacement": {
      "description": "Framewise Displacement (Power)",
      "units": "mm",
      "method": "power_fd"
    },
    "frame_censor": {
      "description": "Frame censoring mask",
      "values": {"0": "kept", "1": "censored"}
    }
  },
  "parameters": {
    "censor": {
      "fd_thresh_mm": 0.5,
      "dvars_thresh": 1.5,
      "n_censored": 12,
      "n_kept": 188
    },
    "acompcor": {
      "cord": {
        "n_components": 5,
        "explained_variance": [0.42, 0.18, 0.12, 0.08, 0.05]
      }
    }
  }
}
```

## Integration with Temporal Cropping

Confounds are computed on cropped BOLD data (temporal crop feature):

1. Temporal crop detection identifies artifacts at run start/end
2. Motion correction uses cropped timepoints
3. Confounds computed on motion-corrected, cropped data
4. Final TSV reflects cropped timepoints only

## Quality Control

Confounds are visualized in QC reports:

- **FD plot**: Time series with censor mask overlay
- **DVARS plot**: Time series with censor mask overlay
- **aCompCor explained variance**: Bar plot per tissue
- **Censor statistics**: Summary table

## Column Order

Canonical column order in TSV:

1. `framewise_displacement`
2. `dvars`
3. `frame_censor`
4. aCompCor columns (tissue alphabetically, then PC number)
5. Additional confounds (if any)

## Empty Mask Handling

If a tissue mask contains no voxels:
- No PC columns generated for that tissue
- Logged in JSON with `n_components: 0`
- No error raised (graceful skip)

## Determinism

- Fixed random seed for PCA ensures reproducible components
- FD computation is deterministic
- DVARS computation is deterministic
- Censoring logic is deterministic

