# SpinePrep

![Status](https://img.shields.io/badge/status-UNDER_DEVELOPMENT-orange)

> ⚠️ **Under development** — Not ready for use. Interfaces and outputs may change without notice. Do not rely on current behavior.

[![Docs Latest](https://img.shields.io/badge/docs-latest-blue)](https://spineprep.github.io/)
[![Docs Stable](https://img.shields.io/badge/docs-stable-brightgreen)](https://spineprep.github.io/stable/)
[![Docs CI](https://github.com/spineprep/SpinePrep/actions/workflows/docs.yml/badge.svg)](https://github.com/spineprep/SpinePrep/actions/workflows/docs.yml)

SpinePrep is a BIDS-first spinal cord fMRI preprocessing pipeline built around the PAM50 template, optional modules such as MP-PCA denoising and spatial smoothing, FSL FEAT-based modeling for now with a Python GLM planned, Snakemake orchestration, and profiles for both local execution and SLURM clusters.

## Quick Start

```bash
# clone and enter
git clone https://github.com/kiomarssharifi/SpinePrep && cd SpinePrep

# optional: create venv and install package (CLI will be added next step)
python -m venv .venv && source .venv/bin/activate
pip install -e .

# coming next: spineprep validate / plan / run (CLI to be added)
```

## Dev Quickstart

```bash
# 1. Clone and setup
git clone https://github.com/kiomarssharifi/SpinePrep && cd SpinePrep

# 2. Create venv (Python 3.11 recommended)
python3.11 -m venv .venv && source .venv/bin/activate

# 3. Install in editable mode
pip install -e ".[dev]"

# 4. Run health checks
./ops/status/health_check.sh
```

## How to cite

See the [CITATION.cff](./CITATION.cff) file and forthcoming Zenodo record (DOI: 10.5281/zenodo.xxxxxxx) for citation details.

## Registration (Experimental)

SpinePrep includes experimental support for SCT-guided spatial normalization and mask generation. This feature is disabled by default and can be enabled in the configuration.

### Requirements

- **SCT (Spinal Cord Toolbox)**: Version 5.8 or higher
- **FSL**: For image processing utilities
- **ANTs**: For advanced registration (optional)

### Configuration

Enable registration in your config file:

```yaml
registration:
  enable: true
  template: PAM50
  guidance: SCT
  levels: auto
  use_gm_wm_masks: true
  rootlets:
    enable: false
    mode: "atlas"
```

### Usage

Run the registration pipeline:

```bash
# Dry run to see what will be executed
snakemake -n --profile profiles/local registration_all

# Run registration for all subjects
snakemake --profile profiles/local registration_all

# Run registration for a specific run
snakemake --profile profiles/local warp_masks_0
```

### Outputs

The registration pipeline generates:

- **Cord masks**: `*_space-native_desc-cordmask.nii.gz`
- **Vertebral levels**: `*_space-native_desc-levels.nii.gz` (if SCT available)
- **Registration warps**: `xfm/from-epi_to-t2.h5`, `xfm/from-t2_to-pam50.h5`
- **PAM50 masks**: `*_space-PAM50_desc-{cord,wm,csf}mask.nii.gz`

### Graceful Degradation

If SCT is not available, the pipeline will:
- Create zero masks as placeholders
- Write `.skip` markers for missing components
- Continue processing with available tools
- Report status in QC reports

### Disabling Registration

To disable registration, set `registration.enable: false` in your config or remove the registration target from your Snakemake run.

## License

Code is provided under the [Apache License 2.0](./LICENSE). Documentation and media assets, when added, may be released under the Creative Commons Attribution 4.0 International (CC BY 4.0) license.
# Trigger docs workflow
# Trigger fresh deploy
# Trigger deploy with public target repo
