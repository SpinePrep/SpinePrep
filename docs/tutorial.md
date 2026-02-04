# Install & Use

A complete guide to installing SpinalfMRIprep and processing your own data.

## System Requirements

| Component | Requirement |
|-----------|-------------|
| **OS** | Linux (recommended), macOS, Windows with WSL2 |
| **Python** | 3.11+ |
| **Container** | Docker 20.10+ or Apptainer 1.0+ |
| **RAM** | 8 GB minimum, 16 GB recommended |
| **Disk** | 20 GB for containers + space for data |

## Installation

### Step 1: Clone Repository

```bash
git clone https://github.com/SpinalfMRIprep/SpinalfMRIprep.git
cd SpinalfMRIprep
```

### Step 2: Install Python Dependencies

```bash
# Install Poetry (if not already installed)
pip install poetry

# Install SpinalfMRIprep
poetry install
```

### Step 3: Pull Container Images

SpinalfMRIprep uses containerized neuroimaging tools:

```bash
# Required: Spinal Cord Toolbox
docker pull vnmd/spinalcordtoolbox_7.2:20251215

# Optional: Additional tools for advanced processing
docker pull vnmd/fsl_6.0.7.18_20250928
docker pull vnmd/ants_2.6.0_20250424
```

### Step 4: Verify Installation

```bash
poetry run spinalfmriprep run S0_SETUP --project-root .
```

Expected output: `status: PASS`

---

## Prepare Your Data

### BIDS Format

Your data must be in [BIDS format](https://bids.neuroimaging.io/):

```
my_dataset/
├── dataset_description.json
├── participants.tsv
├── sub-01/
│   ├── anat/
│   │   └── sub-01_T2w.nii.gz
│   └── func/
│       ├── sub-01_task-motor_bold.nii.gz
│       └── sub-01_task-motor_bold.json
└── sub-02/
    └── ...
```

### Minimum Requirements

- At least one anatomical image (T2w preferred, T1w accepted)
- At least one functional run (4D NIfTI)
- Valid JSON sidecar with acquisition parameters

---

## Run the Pipeline

### Option A: Process Ad-Hoc Dataset

For a one-off dataset not in the manifest:

```bash
# Step 1: Validate inputs
poetry run spinalfmriprep run S1_input_verify \
  --bids-root /path/to/my_dataset \
  --out work/my_analysis

# Step 2: Anatomical processing
poetry run spinalfmriprep run S2_anat_cordref \
  --bids-root /path/to/my_dataset \
  --out work/my_analysis

# Step 3: Functional initialization
poetry run spinalfmriprep run S3_func_init_and_crop \
  --bids-root /path/to/my_dataset \
  --out work/my_analysis
```

### Option B: Process Registered Dataset

For datasets registered in `policy/datasets.yaml`:

```bash
# Configure local path
echo "my_dataset_key: /path/to/my_dataset" >> config/datasets_local.yaml

# Run with dataset key
poetry run spinalfmriprep run S1_input_verify \
  --dataset-key my_dataset_key \
  --datasets-local config/datasets_local.yaml \
  --out work/my_analysis
```

---

## Sample Datasets

SpinalfMRIprep includes built-in access to OpenNeuro validation datasets:

| Dataset | Task | Download Command |
|---------|------|------------------|
| ds005884 | Motor | `poetry run spinalfmriprep download-sample --dataset ds005884` |
| ds005883 | Pain | `poetry run spinalfmriprep download-sample --dataset ds005883` |
| ds004386 | Rest | `poetry run spinalfmriprep download-sample --dataset ds004386` |
| ds004616 | Hand Grasp | `poetry run spinalfmriprep download-sample --dataset ds004616` |

---

## Understanding Outputs

### Directory Structure

```
work/my_analysis/
├── derivatives/
│   └── spinalfmriprep/
│       ├── dataset_description.json
│       ├── qc_dashboard.html          # Interactive QC viewer
│       └── sub-01/
│           ├── anat/
│           │   ├── sub-01_desc-cordref_T2w.nii.gz
│           │   ├── sub-01_desc-cord_dseg.nii.gz
│           │   └── sub-01_desc-vertebral_labels.nii.gz
│           ├── func/
│           │   └── (after S4+)
│           └── figures/
│               ├── sub-01_desc-S2_crop_box_sagittal.png
│               └── sub-01_desc-S2_cordmask_montage.png
├── logs/
│   └── S{N}_{step}/
│       ├── qc.json                     # Machine-readable QC
│       └── runs.jsonl                  # Per-run records
└── work/
    └── S{N}_{step}/                    # Intermediate files
```

### QC Dashboard

Open `qc_dashboard.html` in your browser for interactive QC:

- Overview of all subjects and steps
- Click to expand individual reportlets
- Filter by status (PASS/WARN/FAIL)

### QC Status Codes

| Status | Action |
|--------|--------|
| **PASS** | Proceed to next step |
| **WARN** | Review reportlets, may proceed with caution |
| **FAIL** | Investigate issue before proceeding |

---

## Troubleshooting

### Container Not Found

```
Error: Cannot find container image vnmd/spinalcordtoolbox_7.2
```

**Solution**: Pull the required images:
```bash
docker pull vnmd/spinalcordtoolbox_7.2:20251215
```

### Cord Segmentation Fails

```
FAIL: Discovery segmentation has 5 slices, but minimum 20 slices required
```

**Solution**: Check that anatomical image covers sufficient spinal cord. May need to acquire with larger FOV.

### Memory Error

```
MemoryError: Unable to allocate array
```

**Solution**: Close other applications or use a machine with more RAM.

---

## Next Steps

| Goal | Page |
|------|------|
| Understand algorithms | [Methods Overview](methods/overview.md) |
| CLI options | [CLI Reference](reference/cli.md) |
| Contribute | [Contribute](contributing.md) |
