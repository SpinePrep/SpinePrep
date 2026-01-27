# Quick Start

Get SpinalfMRIprep running in 5 minutes.

## Prerequisites

- Docker Engine 20.10+ or Apptainer 1.0+
- Python 3.11+
- A BIDS-formatted spinal cord fMRI dataset

## Installation

```bash
git clone https://github.com/spinalfmriprep/spinalfmriprep.git
cd spinalfmriprep
pip install poetry
poetry install
```

## Pull Container Images

```bash
docker pull vnmd/spinalcordtoolbox_7.2:20251215
docker pull vnmd/fsl_6.0.7.18_20250928
docker pull vnmd/ants_2.6.0_20250424
```

## Run the Pipeline

### Step 1: Verify Environment

```bash
poetry run spinalfmriprep run S0_SETUP --project-root .
```

### Step 2: Validate Inputs

```bash
poetry run spinalfmriprep run S1_input_verify \
  --bids-root /path/to/bids \
  --out wf_test_001
```

### Step 3: Process Anatomical

```bash
poetry run spinalfmriprep run S2_anat_cordref \
  --bids-root /path/to/bids \
  --out wf_test_001
```

### Step 4: Process Functional

```bash
poetry run spinalfmriprep run S3_func_init_and_crop \
  --bids-root /path/to/bids \
  --out wf_test_001
```

## View QC Dashboard

After processing, open the QC dashboard:

```bash
open wf_test_001/derivatives/spinalfmriprep/qc_dashboard.html
```

## Next Steps

- See [Full Tutorial](tutorial.md) for detailed walkthrough
- See [Methods](methods/overview.md) for algorithm details
- See [Reference](reference/cli.md) for CLI options
