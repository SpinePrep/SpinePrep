# Motion Metrics

SpinePrep computes **FD** (framewise displacement) and **DVARS** (temporal derivative variance) for quality control and confound modeling.

## Definitions

### FD (Power et al.)

**Framewise Displacement** quantifies subject motion between consecutive timepoints:

$$
\text{FD}_t = \sum_{d \in \{x,y,z\}} | \Delta \text{trans}_d(t) | + r \sum_{d \in \{x,y,z\}} | \Delta \text{rot}_d(t) |
$$

where:
- Translations are in **mm**
- Rotations are in **radians**
- Head radius \( r = 50 \) mm (converts rotations to arc length)
- \( \text{FD}_0 = 0 \) (first timepoint has no preceding frame)

### DVARS

**DVARS** measures voxelwise intensity changes over time:

1. Compute temporal difference: \( \Delta V_t = V_t - V_{t-1} \)
2. Apply brain mask (defaults to voxels above median of first volume)
3. \( \text{DVARS}_t = \sqrt{\text{mean}(\Delta V_t^2 \text{ over masked voxels})} \)
4. \( \text{DVARS}_0 = 0 \)

## Outputs

For each functional run, SpinePrep writes:

### Confounds TSV

`*_desc-confounds_timeseries.tsv` with columns (in order):

```
trans_x  trans_y  trans_z  rot_x  rot_y  rot_z  fd     dvars
0.0      0.0      0.0      0.0    0.0    0.0    0.0    0.0
0.12     -0.05    0.03     0.001  0.002  0.000  0.25   12.3
...
```

### QC Plots

- `*_fd.png`: FD over time
- `*_dvars.png`: DVARS over time

## Usage

Motion metrics are computed automatically during `spineprep run`:

```bash
spineprep run --bids /data/bids --out /data/derivatives/spineprep
```

Output location:
```
derivatives/spineprep/
  sub-01/
    func/
      sub-01_task-rest_desc-confounds_timeseries.tsv
      sub-01_task-rest_fd.png
      sub-01_task-rest_dvars.png
```

## Quality Thresholds

Typical QC thresholds (configurable):
- **FD**: Flag volumes with FD > 0.5 mm
- **DVARS**: Flag volumes with DVARS > 1.5 (standardized units)

## See Also

- [Confounds](confounds.md) - Additional confound regressors
- [QC Reports](qc.md) - Quality control summaries

