# Full Tutorial

A complete walkthrough of SpinalfMRIprep processing.

## Overview

This tutorial guides you through processing a spinal cord fMRI dataset from start to finish, including:

1. Setting up your environment
2. Downloading sample data
3. Running each pipeline step
4. Interpreting QC outputs
5. Understanding the derivatives

## Sample Dataset

We will use OpenNeuro dataset ds005884 (Motor task spinal cord fMRI).

### Download Sample Data

```bash
# Install datalad
pip install datalad

# Clone the dataset
datalad clone https://github.com/OpenNeuroDatasets/ds005884.git

# Get a single subject for testing
cd ds005884
datalad get sub-01/
```

## Project Setup

### Create Work Directory

```bash
mkdir spinalfmriprep_tutorial
cd spinalfmriprep_tutorial

# Clone SpinalfMRIprep
git clone https://github.com/spinalfmriprep/spinalfmriprep.git
cd spinalfmriprep
poetry install
```

### Configure Dataset Location

Create config/datasets_local.yaml:

```yaml
ds005884: /path/to/ds005884
```

## Step-by-Step Processing

### S0: Environment Setup

Verify your environment is ready:

```bash
poetry run spinalfmriprep run S0_SETUP --project-root .
```

Expected output: PASS status with all container images available.

### S1: Input Verification

Scan and validate the BIDS dataset:

```bash
poetry run spinalfmriprep run S1_input_verify \
  --dataset-key ds005884 \
  --datasets-local config/datasets_local.yaml \
  --out wf_tutorial_001
```

This creates:
- Inventory of all files
- Classification of cord-likely runs
- Issues to address

### S2: Anatomical Cord Reference

Create the anatomical cord reference:

```bash
poetry run spinalfmriprep run S2_anat_cordref \
  --dataset-key ds005884 \
  --datasets-local config/datasets_local.yaml \
  --out wf_tutorial_001
```

This creates:
- Standardized anatomical image
- Cord segmentation
- Vertebral labels
- Template registration

### S3: Functional Initialization

Initialize functional processing:

```bash
poetry run spinalfmriprep run S3_func_init_and_crop \
  --dataset-key ds005884 \
  --datasets-local config/datasets_local.yaml \
  --out wf_tutorial_001
```

This creates:
- Functional reference image
- Cord localization in functional space
- Outlier-gated robust reference
- Cropped cord-focused data

## Interpreting Results

### QC Dashboard

Open the interactive dashboard:

```bash
open wf_tutorial_001/derivatives/spinalfmriprep/qc_dashboard.html
```

### QC Status Files

Each step produces logs/S{N}_*_qc.json with:

- status: PASS, WARN, or FAIL
- failure_message: Explanation if not PASS
- checks: Individual verification results

### Reportlets

Visual QC figures are in derivatives/.../figures/:

- Cord segmentation overlays
- Crop box visualizations
- Motion/outlier plots

## Output Structure

```
wf_tutorial_001/
  derivatives/
    spinalfmriprep/
      dataset_description.json
      sub-01/
        anat/
          *_desc-cord_dseg.nii.gz
          *_desc-cordmask_dseg.nii.gz
        func/
          (after S4+)
        figures/
          *_desc-S2_*.png
          *_desc-S3_*.png
      qc_dashboard.html
  logs/
    S1_input_verify_qc.json
    S2_anat_cordref_qc.json
    S3_func_init_and_crop_qc.json
  work/
    S1_input_verify/
    S2_anat_cordref/
    ...
```

## Troubleshooting

### Common Issues

**Container not found**: Pull the required images (see Quick Start)

**Cord segmentation fails**: Check input image quality and orientation

**Outlier fraction too high**: Review motion during acquisition

## Next Steps

- Process remaining subjects with batch mode
- Run statistical analysis on preprocessed data
- See [Validation](validation/index.md) for expected results
