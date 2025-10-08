# Grouped Motion Analysis

This guide explains how to perform grouped motion analysis across multiple subjects and sessions using SpinePrep.

## Overview

Grouped motion analysis allows you to:

- Compare motion patterns across subjects
- Identify systematic motion issues
- Generate group-level QC reports
- Perform motion-based quality control

## Configuration

### Basic Grouped Analysis

```yaml
# config_grouped.yaml
bids_dir: /data/bids
output_dir: /data/derivatives/spineprep

# Grouped motion analysis
grouped_motion:
  enabled: true
  subjects: ["sub-01", "sub-02", "sub-03"]
  sessions: ["ses-01", "ses-02"]
  tasks: ["rest", "task"]
  runs: ["run-01", "run-02"]
```

### Advanced Configuration

```yaml
# config_grouped_advanced.yaml
bids_dir: /data/bids
output_dir: /data/derivatives/spineprep

# Grouped motion analysis
grouped_motion:
  enabled: true
  subjects: ["sub-01", "sub-02", "sub-03"]
  sessions: ["ses-01", "ses-02"]
  tasks: ["rest", "task"]
  runs: ["run-01", "run-02"]

  # Motion parameters
  motion:
    fd_threshold: 0.5
    dvars_threshold: 75
    scrub: true

  # Group analysis
  group_analysis:
    mean_fd: true
    max_fd: true
    outlier_percentage: true
    motion_summary: true

  # Output options
  output:
    group_report: true
    individual_reports: true
    motion_plots: true
    quality_metrics: true
```

## Grouped Motion Metrics

### Individual Metrics

For each subject/session/task/run:

- **Mean FD**: Average framewise displacement
- **Max FD**: Maximum framewise displacement
- **Outlier percentage**: Percentage of time points above threshold
- **Motion summary**: Overall motion quality score

### Group Metrics

Across all subjects:

- **Group mean FD**: Average motion across group
- **Group max FD**: Maximum motion across group
- **Motion distribution**: Distribution of motion metrics
- **Quality ranking**: Subjects ranked by motion quality

## Output Files

### Group Report

**File**: `group_motion_report.html`

Interactive HTML report containing:

- Group motion summary
- Individual subject metrics
- Motion distribution plots
- Quality rankings
- Recommendations

### Individual Reports

**File**: `sub-{id}_ses-{id}_motion_report.html`

Individual motion reports for each subject/session combination.

### Motion Plots

**File**: `group_motion_plots.png`

Visualization of:

- FD distribution across group
- DVARS distribution across group
- Motion over time for each subject
- Quality metric comparisons

## Quality Control

### Group-Level QC

SpinePrep performs group-level quality control:

1. **Motion distribution analysis**: Identify outliers
2. **Quality ranking**: Rank subjects by motion quality
3. **Systematic issues**: Detect systematic motion problems
4. **Recommendations**: Suggest data exclusion or reprocessing

### Quality Thresholds

```yaml
grouped_motion:
  quality:
    mean_fd_threshold: 0.3
    max_fd_threshold: 1.0
    outlier_threshold: 10
    group_outlier_threshold: 2.0
```

### Quality Assessment

```python
# Group motion analysis
group_motion = analyze_group_motion(
    subjects=subjects,
    sessions=sessions,
    tasks=tasks,
    runs=runs
)

# Quality assessment
quality_scores = assess_motion_quality(group_motion)
outliers = identify_motion_outliers(group_motion)
recommendations = generate_recommendations(group_motion)
```

## Motion Analysis Methods

### Descriptive Statistics

```python
# Calculate group statistics
group_stats = {
    'mean_fd': group_motion['fd'].mean(),
    'std_fd': group_motion['fd'].std(),
    'median_fd': group_motion['fd'].median(),
    'iqr_fd': group_motion['fd'].quantile(0.75) - group_motion['fd'].quantile(0.25)
}
```

### Outlier Detection

```python
# Identify motion outliers
fd_outliers = group_motion['fd'] > (group_motion['fd'].mean() + 2 * group_motion['fd'].std())
dvars_outliers = group_motion['dvars'] > (group_motion['dvars'].mean() + 2 * group_motion['dvars'].std())
```

### Quality Ranking

```python
# Rank subjects by motion quality
quality_scores = calculate_quality_scores(group_motion)
subject_ranking = quality_scores.sort_values('overall_score', ascending=False)
```

## Visualization

### Motion Distribution Plots

SpinePrep generates distribution plots:

- **FD histogram**: Distribution of framewise displacement
- **DVARS histogram**: Distribution of DVARS values
- **Box plots**: Motion metrics across subjects
- **Scatter plots**: Motion vs. other metrics

### Time Series Plots

- **FD over time**: Motion patterns across runs
- **DVARS over time**: Signal stability patterns
- **Group comparisons**: Motion across subjects

### Quality Plots

- **Quality scores**: Overall quality assessment
- **Outlier identification**: Subjects with poor motion
- **Recommendations**: Data exclusion suggestions

## Troubleshooting

### Common Issues

**Issue**: No grouped motion data found
**Solutions**:
- Check subject/session/task/run specifications
- Verify BIDS structure
- Check file permissions

**Issue**: Inconsistent motion metrics
**Solutions**:
- Check preprocessing parameters
- Verify motion correction settings
- Check for systematic issues

**Issue**: Poor group quality
**Solutions**:
- Review acquisition parameters
- Check for systematic motion issues
- Consider data exclusion

### Debug Mode

Enable debug mode for detailed grouped motion analysis:

```bash
spineprep --debug config_grouped.yaml
```

This will show:
- Subject/session/task/run selection
- Motion metric calculations
- Group analysis steps
- Quality assessment details

## Best Practices

### Data Collection

1. **Consistent acquisition**: Use consistent acquisition parameters
2. **Motion monitoring**: Monitor motion during acquisition
3. **Quality control**: Perform real-time quality control
4. **Documentation**: Document any acquisition issues

### Processing

1. **Consistent preprocessing**: Use consistent preprocessing parameters
2. **Motion correction**: Apply appropriate motion correction
3. **Quality assessment**: Assess motion quality for each subject
4. **Group analysis**: Perform group-level quality control

### Analysis

1. **Motion inclusion**: Include motion as a covariate
2. **Quality control**: Exclude poor quality data
3. **Group analysis**: Consider group-level motion effects
4. **Validation**: Verify motion correction effectiveness

## Example Workflow

### Complete Example

```yaml
# config_grouped_complete.yaml
bids_dir: /data/bids
output_dir: /data/derivatives/spineprep

# Grouped motion analysis
grouped_motion:
  enabled: true
  subjects: ["sub-01", "sub-02", "sub-03", "sub-04", "sub-05"]
  sessions: ["ses-01", "ses-02"]
  tasks: ["rest", "task"]
  runs: ["run-01", "run-02"]

  # Motion parameters
  motion:
    fd_threshold: 0.5
    dvars_threshold: 75
    scrub: true

  # Group analysis
  group_analysis:
    mean_fd: true
    max_fd: true
    outlier_percentage: true
    motion_summary: true

  # Quality control
  quality:
    mean_fd_threshold: 0.3
    max_fd_threshold: 1.0
    outlier_threshold: 10
    group_outlier_threshold: 2.0

  # Output options
  output:
    group_report: true
    individual_reports: true
    motion_plots: true
    quality_metrics: true
```

### Running Grouped Analysis

```bash
# Run grouped motion analysis
spineprep config_grouped_complete.yaml

# Check grouped outputs
ls derivatives/spineprep/group_motion/
```

### Using Grouped Results

```python
import pandas as pd
import matplotlib.pyplot as plt

# Load group motion data
group_motion = pd.read_csv('group_motion_summary.tsv', sep='\t')

# Plot motion distribution
plt.figure(figsize=(10, 6))
plt.hist(group_motion['mean_fd'], bins=20, alpha=0.7)
plt.xlabel('Mean FD (mm)')
plt.ylabel('Number of subjects')
plt.title('Group Motion Distribution')
plt.show()

# Identify outliers
outliers = group_motion[group_motion['mean_fd'] > 0.5]
print(f"Found {len(outliers)} subjects with high motion")

# Generate recommendations
for _, subject in outliers.iterrows():
    print(f"Subject {subject['participant_id']}: Consider exclusion or reprocessing")
```

## Advanced Features

### Motion-Based Grouping

```yaml
# Group subjects by motion quality
grouped_motion:
  grouping:
    low_motion: "mean_fd < 0.2"
    moderate_motion: "mean_fd >= 0.2 and mean_fd < 0.5"
    high_motion: "mean_fd >= 0.5"
```

### Motion-Based Quality Control

```yaml
# Automatic quality control
grouped_motion:
  quality_control:
    auto_exclude: true
    exclusion_threshold: 0.5
    reprocess_threshold: 0.3
```

### Motion-Based Analysis

```yaml
# Motion-based analysis
grouped_motion:
  analysis:
    motion_covariate: true
    motion_interaction: true
    motion_mediation: true
```
