# Getting Started

This guide will help you get up and running with SpinePrep quickly.

## Installation

### Prerequisites

SpinePrep requires Python 3.8+ and the following system dependencies:

- FSL (version 6.0+)
- Spinal Cord Toolbox (SCT)
- ANTs (optional, for advanced registration)

### Install SpinePrep

```bash
# Install from PyPI (recommended)
pip install spineprep

# Or install from source
git clone https://github.com/spineprep/spineprep.git
cd spineprep
pip install -e .
```

### Verify Installation

```bash
spineprep --version
```

## Minimal Example

Here's the simplest way to run SpinePrep:

### 1. Prepare Your Data

Ensure your data follows the BIDS specification:

```
bids/
├── dataset_description.json
├── participants.tsv
└── sub-01/
    ├── func/
    │   └── sub-01_task-rest_bold.nii.gz
    └── anat/
        └── sub-01_T2w.nii.gz
```

### 2. Create Configuration

Create a minimal configuration file:

```yaml
# config.yaml
bids_dir: /path/to/your/bids
output_dir: /path/to/output
```

### 3. Run SpinePrep

```bash
spineprep config.yaml
```

## Configuration Profiles

SpinePrep supports different execution profiles for various computing environments.

### Local Profile

For running on your local machine:

```yaml
# profiles/local/config.yaml
bids_dir: /data/bids
output_dir: /data/derivatives/spineprep
n_procs: 4
memory_gb: 8
```

### SLURM Profile

For HPC clusters with SLURM:

```yaml
# profiles/slurm/config.yaml
bids_dir: /data/bids
output_dir: /data/derivatives/spineprep
execution:
  backend: slurm
  slurm:
    account: your_account
    partition: compute
    time: "2:00:00"
    mem: "8G"
    cpus: 4
```

### Docker Profile

For containerized execution:

```yaml
# profiles/docker/config.yaml
bids_dir: /data/bids
output_dir: /data/derivatives/spineprep
execution:
  backend: docker
  docker:
    image: spineprep/spineprep:latest
```

## Next Steps

Now that you have SpinePrep running, explore:

- [User Guide](user-guide/usage.md) - Learn about advanced configuration and usage
- [Outputs](user-guide/outputs.md) - Understand what SpinePrep produces
- [Quality Control](user-guide/qc.md) - Learn about QC metrics and reports
- [Configuration Reference](reference/config.md) - Complete configuration options

## Troubleshooting

### Common Issues

**Issue**: `spineprep: command not found`
**Solution**: Ensure SpinePrep is installed and in your PATH. Try `pip install --user spineprep` or activate your virtual environment.

**Issue**: `FSL not found`
**Solution**: Install FSL and ensure it's in your PATH. On Ubuntu/Debian: `sudo apt install fsl-complete`.

**Issue**: `SCT not found`
**Solution**: Install Spinal Cord Toolbox following the [official instructions](https://spinalcordtoolbox.com/user_section/installation.html).

### Getting Help

- Check the [troubleshooting section](user-guide/usage.md#troubleshooting)
- Search [existing issues](https://github.com/spineprep/spineprep/issues)
- Ask a question in [discussions](https://github.com/spineprep/spineprep/discussions)
