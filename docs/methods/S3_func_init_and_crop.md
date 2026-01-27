---
search:
  boost: 2
---

# S3: Functional Initialization & Crop

Dummy volume drop, cord localization in functional space, outlier gating, and cord-focused cropping.

## Purpose

S3 prepares functional data for motion correction by:

1. **Dropping dummy volumes** (initial unstable frames)
2. **Localizing the cord** in functional space
3. **Gating outlier frames** using cord-centric metrics
4. **Cropping** to cord-focused field of view

## Subtasks

S3 is divided into three subtasks:

| Subtask | Name | Description |
|---------|------|-------------|
| S3.1 | Dummy Drop & Localization | Remove dummies, compute fast reference, localize cord |
| S3.2 | Outlier Gating | Compute DVARS/RefRMS, identify bad frames, create robust reference |
| S3.3 | Crop & QC | Apply cord-focused crop, generate reportlets |

## Inputs

| Input | Source | Required |
|-------|--------|----------|
| BOLD images | BIDS `/func/*_bold.nii.gz` | Yes |
| S2 cord reference | `work/S2_anat_cordref/{run_id}/cordref_std.nii.gz` | Yes |
| S2 cord mask | `derivatives/.../anat/*_desc-cordmask_dseg.nii.gz` | Yes |
| Policy | `policy/S3_func_init_and_crop.yaml` | Yes |

## Outputs

| Output | Path | Description |
|--------|------|-------------|
| Fast reference | `work/.../init/func_ref_fast.nii.gz` | Median of all frames |
| Robust reference | `work/.../func_ref.nii.gz` | Median of non-outlier frames |
| Cropped BOLD | `work/.../funccrop_bold.nii.gz` | Cord-focused 4D data |
| Crop mask | `work/.../funccrop_mask.nii.gz` | Cylindrical crop ROI |
| Frame metrics | `work/.../metrics/frame_metrics.tsv` | Per-frame DVARS, RefRMS |
| Outlier mask | `work/.../metrics/outlier_mask.json` | Flagged frame indices |
| QC reportlets | `derivatives/.../figures/` | Visual QC images |

## Algorithm

### S3.1: Dummy Drop & Localization

#### Dummy Volume Drop

Removes initial frames that haven't reached steady-state:

```python
dummy_count = policy["dummy"]["drop_count"]  # default: 4
bold_data = bold_data[..., dummy_count:]
```

#### Fast Reference

Computes initial reference as median across all remaining frames:

```python
func_ref_fast = np.median(bold_data, axis=3)
```

#### Cord Localization

Segments cord directly in functional space:

```bash
sct_deepseg spinalcord -i func_ref_fast.nii.gz -o func_cord_seg.nii.gz -largest 1
```

This provides an independent cord detection without relying on anatomical registration.

### S3.2: Outlier Gating

#### Metric Computation

Within the cord mask, computes:

**DVARS** (Derivative of RMS Variance):
```python
dvars[t] = sqrt(mean((vol[t] - vol[t-1])^2))  # within mask
```

**RefRMS** (Reference RMS):
```python
refrms[t] = sqrt(mean((vol[t] - ref)^2))  # within mask
```

#### Outlier Detection

Uses boxplot-based cutoff:

```python
threshold = P75 + 1.5 * IQR
outliers = (dvars > dvars_threshold) | (refrms > refrms_threshold)
```

#### Robust Reference

Computes final reference from non-outlier frames only:

```python
good_frames = ~outliers
func_ref = np.median(bold_data[..., good_frames], axis=3)
```

### S3.3: Crop & QC

#### Cylindrical Crop Mask

Creates a cylindrical mask around the cord centerline:

```bash
sct_create_mask -i func_ref.nii.gz -p centerline,cord_seg.nii.gz -size 40mm
```

#### Apply Crop

Crops 4D BOLD to the cord-focused region:

```bash
sct_crop_image -i bold.nii.gz -m crop_mask.nii.gz -o funccrop_bold.nii.gz
```

## Policy Configuration

```yaml
version: 1

dummy:
  drop_count: 4

coarse_reference:
  method: median

func_localization:
  enabled: true
  method: deepseg
  task: spinalcord

outlier_gating:
  iqr_multiplier: 1.5
  metrics: [dvars, refrms]
  outlier_fraction_warn: 0.30
  outlier_fraction_fail: 0.50
  min_good_frames: 10

robust_reference:
  method: median

crop:
  mask_diameter_mm: 40
  dilate_xyz: [2, 2, 0]
  min_z_slices: 10
```

## QC Reportlets

| Reportlet | Description |
|-----------|-------------|
| `*_desc-S3_func_localization_crop_box_sagittal.png` | Cord localization with crop box overlay |
| `*_desc-S3_frame_metrics.png` | DVARS and RefRMS time series with thresholds |
| `*_desc-S3_crop_box_sagittal.png` | Final crop region visualization |
| `*_desc-S3_funcref_montage.png` | Axial slice montage of robust reference |

## CLI Usage

```bash
# Run S3 for a dataset
spinalfmriprep run S3_func_init_and_crop \
  --dataset-key ds005884 \
  --datasets-local config/datasets_local.yaml \
  --out wf_reg_001

# Parallel processing
spinalfmriprep run S3_func_init_and_crop \
  --dataset-key ds005884 \
  --out wf_reg_001 \
  --batch-workers 8
```

## QC Status Logic

```
status = FAIL if:
  - Cord localization fails
  - Outlier fraction > 50%
  - Fewer than 10 good frames
  - Crop produces < 10 Z slices

status = WARN if:
  - Outlier fraction > 30%

status = PASS otherwise
```

## Edge Cases

| Condition | Behavior |
|-----------|----------|
| Very short run (< 15 frames) | WARN, may fail outlier gating |
| Cord not detected in func | FAIL: "Cord localization failed" |
| All frames are outliers | FAIL: "No good frames for reference" |
| Crop too small | FAIL: "Insufficient Z coverage" |
| Missing S2 outputs | FAIL: "Missing S2 cordref_std" |

## Performance

- ~30-60 seconds per run (depending on run length)
- Parallelization at session level
- Memory usage scales with 4D volume size
