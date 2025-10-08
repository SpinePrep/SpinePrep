# Physiological Data Integration

This guide explains how to integrate physiological data (cardiac and respiratory) with SpinePrep for advanced confound regression.

## Overview

Physiological data can be used to:

- Extract cardiac and respiratory regressors
- Perform physiological noise correction
- Improve signal quality in spinal cord data

## Supported Formats

SpinePrep supports physiological data in the following formats:

- **BIDS physiological files**: `*_physio.tsv.gz` and `*_physio.json`
- **Text files**: Tab-separated or comma-separated values
- **JSON metadata**: Physiological recording parameters

## Configuration

### Basic Setup

```yaml
# config.yaml
physio:
  enabled: true
  cardiac_channel: 0  # Channel index for cardiac signal
  respiratory_channel: 1  # Channel index for respiratory signal
  sampling_rate: 500  # Hz
  method: "retroicor"  # or "rvhr", "rvt"
```

### Advanced Configuration

```yaml
# config.yaml
physio:
  enabled: true
  cardiac_channel: 0
  respiratory_channel: 1
  sampling_rate: 500
  method: "retroicor"
  parameters:
    cardiac:
      order: 3
      threshold: 0.3
    respiratory:
      order: 4
      threshold: 0.1
  output:
    regressors: true
    plots: true
    quality_metrics: true
```

## Data Preparation

### BIDS Format

Place physiological data in the BIDS structure:

```
bids/
└── sub-01/
    └── ses-01/
        └── func/
            ├── sub-01_ses-01_task-rest_run-01_bold.nii.gz
            ├── sub-01_ses-01_task-rest_run-01_bold.json
            ├── sub-01_ses-01_task-rest_run-01_physio.tsv.gz
            └── sub-01_ses-01_task-rest_run-01_physio.json
```

### Physiological Data File

**File**: `*_physio.tsv.gz`

```tsv
cardiac	respiratory
0.123	0.456
0.124	0.457
0.125	0.458
```

### Metadata File

**File**: `*_physio.json`

```json
{
  "SamplingFrequency": 500,
  "StartTime": 0.0,
  "Columns": ["cardiac", "respiratory"],
  "Cardiac": {
    "Description": "Cardiac pulse signal",
    "Units": "V"
  },
  "Respiratory": {
    "Description": "Respiratory signal",
    "Units": "V"
  }
}
```

## Processing Methods

### Retroicor

Retrospective Image Correction (Retroicor) models physiological noise:

```python
# Retroicor regressors
retroicor_regressors = retroicor(
    cardiac_signal=cardiac,
    respiratory_signal=respiratory,
    cardiac_order=3,
    respiratory_order=4,
    sampling_rate=500,
    tr=2.0
)
```

### RVT (Respiratory Volume per Time)

Respiratory Volume per Time models respiratory variations:

```python
# RVT regressors
rvt_regressors = rvt(
    respiratory_signal=respiratory,
    sampling_rate=500,
    tr=2.0
)
```

### RVHR (Respiratory Volume Heart Rate)

Respiratory Volume Heart Rate models cardiorespiratory interactions:

```python
# RVHR regressors
rvhr_regressors = rvhr(
    cardiac_signal=cardiac,
    respiratory_signal=respiratory,
    sampling_rate=500,
    tr=2.0
)
```

## Output Files

### Physiological Regressors

**File**: `*_desc-physio_timeseries.tsv`

```tsv
cardiac_sin_01	cardiac_cos_01	cardiac_sin_02	cardiac_cos_02	cardiac_sin_03	cardiac_cos_03	resp_sin_01	resp_cos_01	resp_sin_02	resp_cos_02	resp_sin_03	resp_cos_03	resp_sin_04	resp_cos_04	rvt	rvhr
0.123	0.456	0.789	0.012	0.345	0.678	0.901	0.234	0.567	0.890	0.123	0.456	0.789	0.012	0.345	0.678
```

### Quality Metrics

**File**: `*_desc-physio_quality.json`

```json
{
  "cardiac": {
    "mean_hr": 72.5,
    "hr_std": 5.2,
    "signal_quality": 0.85
  },
  "respiratory": {
    "mean_rr": 16.2,
    "rr_std": 2.1,
    "signal_quality": 0.78
  },
  "regressors": {
    "cardiac_variance": 0.123,
    "respiratory_variance": 0.456,
    "total_variance": 0.789
  }
}
```

## Quality Control

### Signal Quality Assessment

SpinePrep assesses physiological signal quality:

- **Cardiac signal**: Heart rate variability, signal-to-noise ratio
- **Respiratory signal**: Respiratory rate variability, signal quality
- **Synchronization**: Timing alignment with BOLD data

### Quality Plots

SpinePrep generates quality plots:

- **Time series**: Raw physiological signals
- **Power spectra**: Frequency domain analysis
- **Regressor plots**: Extracted regressors over time
- **Quality metrics**: Signal quality assessment

## Troubleshooting

### Common Issues

**Issue**: No physiological data found
**Solutions**:
- Check file naming convention
- Verify BIDS structure
- Check file permissions

**Issue**: Poor signal quality
**Solutions**:
- Check sensor placement
- Verify sampling rate
- Check for artifacts

**Issue**: Synchronization problems
**Solutions**:
- Check timing parameters
- Verify start times
- Check sampling rates

### Debug Mode

Enable debug mode for detailed physiological processing:

```bash
spineprep --debug config.yaml
```

This will show:
- Physiological data loading
- Signal processing steps
- Regressor extraction
- Quality metric calculations

## Best Practices

### Data Collection

1. **Sensor placement**: Ensure good contact and minimal movement
2. **Sampling rate**: Use high sampling rate (≥500 Hz)
3. **Synchronization**: Record start times accurately
4. **Quality monitoring**: Monitor signal quality during acquisition

### Processing

1. **Signal preprocessing**: Filter and detrend signals
2. **Artifact detection**: Identify and handle artifacts
3. **Quality assessment**: Evaluate signal quality
4. **Regressor validation**: Check extracted regressors

### Analysis

1. **Regressor inclusion**: Include physiological regressors in analysis
2. **Quality control**: Exclude poor quality data
3. **Validation**: Verify physiological correction effectiveness

## Example Workflow

### Complete Example

```yaml
# config_physio.yaml
bids_dir: /data/bids
output_dir: /data/derivatives/spineprep

# Physiological processing
physio:
  enabled: true
  cardiac_channel: 0
  respiratory_channel: 1
  sampling_rate: 500
  method: "retroicor"
  parameters:
    cardiac:
      order: 3
      threshold: 0.3
    respiratory:
      order: 4
      threshold: 0.1
  output:
    regressors: true
    plots: true
    quality_metrics: true

# Confound regression
confounds:
  motion: true
  acompcor: true
  physio: true  # Include physiological regressors
```

### Running with Physiological Data

```bash
# Run with physiological processing
spineprep config_physio.yaml

# Check physiological outputs
ls derivatives/spineprep/sub-01/ses-01/func/*physio*
```

### Using Physiological Regressors

```python
import pandas as pd

# Load confounds including physiological regressors
confounds = pd.read_csv('desc-confounds_timeseries.tsv', sep='\t')

# Select physiological regressors
physio_regressors = confounds.filter(regex='cardiac_|resp_|rvt|rvhr')

# Use in analysis
from nilearn.glm import first_level_models
model = first_level_models.FirstLevelModel()
model.fit(confounds[['trans_x', 'trans_y', 'trans_z'] + physio_regressors.columns.tolist()])
```
