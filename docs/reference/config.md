# Configuration Reference

This page documents all configuration options available in SpinePrep.

## Configuration Options

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `bids_root` | ['string', 'null'] | None | Path to BIDS dataset root directory |
### confounds

No description available

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
### confounds.acompcor

No description available

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `confounds.acompcor.n_components` | integer | None | Number of aCompCor components to extract |

### confounds.censor

No description available

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `confounds.censor.method` | string | None | Censoring method for high-motion frames |

### confounds.tcompcor

No description available

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `confounds.tcompcor.n_components` | integer | None | Number of tCompCor components to extract |


### motion

No description available

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
### motion.dvars

No description available

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `motion.dvars.threshold` | number | None | DVARS threshold for motion detection |

### motion.fd

No description available

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `motion.fd.threshold` | number | None | Framewise displacement threshold in mm |

### motion.highpass

No description available

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `motion.highpass.hz` | number | None | Highpass filter cutoff frequency in Hz |


| `output_dir` | string | None | Path to output directory for derivatives |
### qc

No description available

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
### qc.psnr

No description available

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `qc.psnr.min` | number | None | Minimum acceptable PSNR in dB for QC |

### qc.report

No description available

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `qc.report.embed_assets` | boolean | None | Embed assets directly in QC HTML reports |

### qc.ssim

No description available

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `qc.ssim.min` | number | None | Minimum acceptable SSIM for QC |


### registration

No description available

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
### registration.deformable

No description available

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `registration.deformable.enabled` | boolean | None | Enable deformable (non-linear) registration |

### registration.pam50

No description available

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `registration.pam50.spacing` | string | None | PAM50 template spacing (e.g., '0.5mm', '1mm') |

### registration.resample

No description available

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `registration.resample.to` | string | None | Target space for resampling |



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
