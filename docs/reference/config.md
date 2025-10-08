# Configuration Reference

This page documents all configuration options available in SpinePrep.

**Schema**: SpinePrep configuration

## Configuration Options

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
### acq

No description available

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `acq.echo_spacing_s` | ['number', 'null'] | None | No description available |
| `acq.pe_dir` | string | None | No description available |
| `acq.slice_timing` | string | None | No description available |
| `acq.tr` | number | None | No description available |

### dataset

No description available

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `dataset.runs_per_subject` | any | None | No description available |
| `dataset.sessions` | any | None | No description available |

### options

No description available

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
### options.acompcor

No description available

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `options.acompcor.detrend` | boolean | None | No description available |
| `options.acompcor.enable` | boolean | None | No description available |
| `options.acompcor.explained_variance_min` | number | None | No description available |
| `options.acompcor.highpass_hz` | number | None | No description available |
| `options.acompcor.n_components_per_tissue` | integer | None | No description available |
| `options.acompcor.standardize` | boolean | None | No description available |
| `options.acompcor.tissues` | array of string | None | No description available |

### options.censor

No description available

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `options.censor.dvars_thresh` | number | None | No description available |
| `options.censor.enable` | boolean | None | No description available |
| `options.censor.fd_thresh_mm` | number | None | No description available |
| `options.censor.min_contig_vols` | integer | None | No description available |
| `options.censor.pad_vols` | integer | None | No description available |

### options.cleanup

No description available

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `options.cleanup.keep_only_latest_stage` | boolean | None | No description available |

### options.confounds

No description available

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `options.confounds.dvars_method` | string | None | No description available |
| `options.confounds.fd_method` | string | None | No description available |

| `options.denoise_mppca` | boolean | None | No description available |
### options.first_level

No description available

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `options.first_level.engine` | string | None | No description available |
| `options.first_level.feat_variant` | string | None | No description available |

### options.ingest

No description available

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `options.ingest.enable` | boolean | None | No description available |

### options.masks

No description available

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `options.masks.binarize_thr` | number | None | No description available |
| `options.masks.enable` | boolean | None | No description available |
| `options.masks.source` | string | None | No description available |

### options.motion

No description available

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
### options.motion.concat

No description available

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `options.motion.concat.mode` | string | None | No description available |
| `options.motion.concat.require_same` | array of string | None | No description available |

| `options.motion.engine` | string | None | No description available |
| `options.motion.slice_axis` | string | None | No description available |

### options.sdc

No description available

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `options.sdc.enable` | boolean | None | No description available |
| `options.sdc.mode` | string | None | No description available |

### options.smoothing

No description available

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `options.smoothing.enable` | boolean | None | No description available |
| `options.smoothing.fwhm_mm` | number | None | No description available |

### options.temporal_crop

No description available

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `options.temporal_crop.enable` | boolean | None | No description available |
| `options.temporal_crop.max_trim_end` | integer | None | No description available |
| `options.temporal_crop.max_trim_start` | integer | None | No description available |
| `options.temporal_crop.method` | string | None | No description available |
| `options.temporal_crop.z_thresh` | number | None | No description available |


### paths

No description available

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `paths.bids_dir` | string | None | No description available |
| `paths.deriv_dir` | string | None | No description available |
| `paths.logs_dir` | string | None | No description available |
| `paths.root` | string | None | No description available |
| `paths.work_dir` | string | None | No description available |

| `pipeline_version` | string | None | No description available |
| `project_name` | string | None | No description available |
### qc

No description available

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `qc.cohort_report` | boolean | None | No description available |
| `qc.subject_report` | boolean | None | No description available |

### registration

No description available

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `registration.enable` | boolean | None | No description available |
| `registration.guidance` | string | None | No description available |
| `registration.levels` | string | None | No description available |
### registration.rootlets

No description available

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `registration.rootlets.enable` | boolean | None | No description available |
| `registration.rootlets.mode` | string | None | No description available |

| `registration.template` | string | None | No description available |
| `registration.use_gm_wm_masks` | boolean | None | No description available |

### resources

No description available

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `resources.default_mem_gb` | integer | None | No description available |
| `resources.default_threads` | integer | None | No description available |

### runtime

No description available

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `runtime.container_engine` | ['string', 'null'] | None | No description available |

### study

No description available

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `study.name` | string | None | No description available |

### templates

No description available

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `templates.pam50_version` | string | None | No description available |

### tools

No description available

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `tools.ants` | string | None | No description available |
| `tools.dcm2niix` | string | None | No description available |
| `tools.fsl` | string | None | No description available |
| `tools.sct` | string | None | No description available |
| `tools.sct_min_version` | string | None | No description available |


## Example Configuration

```yaml
# Basic configuration
bids_dir: /path/to/bids
output_dir: /path/to/output
n_procs: 4

# Advanced configuration
motion:
  fd_threshold: 0.5
  dvars_threshold: 75

confounds:
  acompcor: true
  censor: true

registration:
  method: sct
  template: PAM50
```
