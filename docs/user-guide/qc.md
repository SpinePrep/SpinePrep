# Quality Control

SpinePrep provides comprehensive quality control (QC) metrics to assess data quality and preprocessing effectiveness. This guide explains the QC metrics, how to interpret them, and how to use the QC reports.

## QC Metrics Overview

SpinePrep generates several types of QC metrics:

- **Motion metrics**: Framewise displacement (FD) and DVARS
- **Signal quality**: Signal-to-noise ratio (SNR), global signal
- **Confound metrics**: aCompCor components, censor masks
- **Processing metrics**: Success/failure rates, processing times

## Motion Metrics

### Framewise Displacement (FD)

Framewise displacement measures the total movement between consecutive volumes:

```
FD = |Δx| + |Δy| + |Δz| + |Δα| + |Δβ| + |Δγ|
```

Where:
- `Δx, Δy, Δz`: Translation changes (mm)
- `Δα, Δβ, Δγ`: Rotation changes (radians)

**Interpretation**:
- `FD < 0.2 mm`: Excellent motion
- `FD 0.2-0.5 mm`: Good motion
- `FD 0.5-1.0 mm`: Moderate motion
- `FD > 1.0 mm`: Poor motion

### DVARS

DVARS measures the temporal derivative of the variance across voxels:

```
DVARS = √(Σ(voxel_variance_change)²)
```

**Interpretation**:
- `DVARS < 50`: Excellent signal stability
- `DVARS 50-75`: Good signal stability
- `DVARS 75-100`: Moderate signal stability
- `DVARS > 100`: Poor signal stability

## Signal Quality Metrics

### Signal-to-Noise Ratio (SNR)

SNR is calculated as the ratio of signal mean to noise standard deviation:

```
SNR = mean(signal) / std(noise)
```

**Interpretation**:
- `SNR > 20`: Excellent signal quality
- `SNR 10-20`: Good signal quality
- `SNR 5-10`: Moderate signal quality
- `SNR < 5`: Poor signal quality

### Global Signal

Global signal is the mean signal across all voxels in the brain mask.

**Interpretation**:
- Stable global signal indicates good data quality
- Sudden changes may indicate motion or artifacts

## Confound Metrics

### aCompCor Components

Anatomical CompCor (aCompCor) identifies noise components from white matter and CSF regions:

- **aCompCor_00 to aCompCor_05**: First 6 principal components
- **Variance explained**: Percentage of variance explained by each component

**Interpretation**:
- High variance in first components indicates significant noise
- Components should be included as regressors in analysis

### Censor Masks

Censor masks identify time points with excessive motion:

```python
# Censor criteria
censor_fd = fd > fd_threshold  # Default: 0.5 mm
censor_dvars = dvars > dvars_threshold  # Default: 75
censor_mask = censor_fd | censor_dvars
```

**Interpretation**:
- `censor_percentage < 5%`: Excellent motion
- `censor_percentage 5-10%`: Good motion
- `censor_percentage 10-20%`: Moderate motion
- `censor_percentage > 20%`: Poor motion

## QC Reports

### HTML Report

SpinePrep generates interactive HTML reports with:

- **Motion plots**: FD and DVARS over time
- **aCompCor plots**: Component time series and variance
- **Censor visualization**: Time points marked for exclusion
- **Processing summary**: Steps completed, warnings, errors

### Report Anatomy

```
reports/
└── sub-01_ses-01_task-rest_run-01_desc-qc_report.html
```

The report contains:

1. **Header**: Subject information, processing parameters
2. **Motion Section**: FD and DVARS plots
3. **Signal Section**: SNR, global signal plots
4. **Confounds Section**: aCompCor components
5. **Censor Section**: Censor mask visualization
6. **Summary**: Quantitative metrics and recommendations

## QC Gallery

Here are examples of QC visualizations from the SpinePrep test fixture:

### Motion Plots

<div class="grid cards" markdown>

-   :material-chart-line:{ .feature-icon } **Framewise Displacement**

    ---

    Shows motion over time with threshold lines

    ![FD Plot](../_assets/examples/fd_plot.png)

-   :material-chart-line:{ .feature-icon } **DVARS**

    ---

    Shows signal stability over time

    ![DVARS Plot](../_assets/examples/dvars_plot.png)

</div>

### Signal Quality

<div class="grid cards" markdown>

-   :material-chart-line:{ .feature-icon } **Global Signal**

    ---

    Mean signal across all voxels

    ![Global Signal](../_assets/examples/global_signal.png)

-   :material-chart-line:{ .feature-icon } **SNR Map**

    ---

    Signal-to-noise ratio across the image

    ![SNR Map](../_assets/examples/snr_map.png)

</div>

### Confound Components

<div class="grid cards" markdown>

-   :material-chart-line:{ .feature-icon } **aCompCor Components**

    ---

    First 6 anatomical CompCor components

    ![aCompCor](../_assets/examples/acompcor_plot.png)

-   :material-chart-line:{ .feature-icon } **Censor Mask**

    ---

    Time points marked for exclusion

    ![Censor Mask](../_assets/examples/censor_mask.png)

</div>

## QC Thresholds

### Default Thresholds

```yaml
qc:
  motion:
    fd_threshold: 0.5  # mm
    dvars_threshold: 75
  signal:
    snr_threshold: 10
  confounds:
    acompcor_n_components: 6
    censor_threshold: 0.5
```

### Customizing Thresholds

You can adjust QC thresholds in your configuration:

```yaml
# config.yaml
qc:
  motion:
    fd_threshold: 0.3  # More strict
    dvars_threshold: 50
  signal:
    snr_threshold: 15
  confounds:
    acompcor_n_components: 8
    censor_threshold: 0.3
```

## QC Recommendations

### Good Quality Data

- FD < 0.3 mm for > 90% of time points
- DVARS < 50 for > 90% of time points
- SNR > 15
- Censor percentage < 5%

### Moderate Quality Data

- FD < 0.5 mm for > 80% of time points
- DVARS < 75 for > 80% of time points
- SNR > 10
- Censor percentage < 15%

### Poor Quality Data

- FD > 0.5 mm for > 20% of time points
- DVARS > 75 for > 20% of time points
- SNR < 10
- Censor percentage > 20%

## Troubleshooting QC Issues

### High Motion

**Symptoms**: High FD, many censored time points
**Solutions**:
- Check for participant movement during scanning
- Consider motion correction parameters
- Use stricter motion thresholds

### Poor Signal Quality

**Symptoms**: Low SNR, high DVARS
**Solutions**:
- Check for scanner artifacts
- Verify preprocessing steps
- Consider different preprocessing parameters

### Excessive Censoring

**Symptoms**: High censor percentage
**Solutions**:
- Adjust motion thresholds
- Check for systematic issues
- Consider excluding problematic runs

## QC in Analysis

### Using QC Metrics

Include QC metrics in your analysis:

```python
import pandas as pd

# Load confounds
confounds = pd.read_csv('desc-confounds_timeseries.tsv', sep='\t')

# Use motion parameters as regressors
motion_regressors = confounds[['trans_x', 'trans_y', 'trans_z',
                              'rot_x', 'rot_y', 'rot_z']]

# Use aCompCor components
acompcor_regressors = confounds[['acompcor_00', 'acompcor_01',
                                 'acompcor_02', 'acompcor_03']]
```

### Excluding Poor Quality Data

```python
# Load censor mask
censor_mask = nib.load('desc-censor_mask.nii.gz').get_fdata()

# Apply censor mask to data
data_censored = data[~censor_mask.astype(bool)]
```
