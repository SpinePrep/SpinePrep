# S1: Input Verify

**Step Code:** `S1_input_verify`  
**Depends on:** S0 (Setup)  
**Required by:** S2-S11 (all downstream steps)

---

## Purpose

S1 validates the input dataset and creates a deterministic inventory of all runs to be processed. This step ensures:

1. **BIDS compliance** - Dataset follows BIDS specification
2. **Required files exist** - All necessary anatomical and functional images are present
3. **NIfTI integrity** - Image files are readable and have valid headers
4. **Session consistency** - Multi-session datasets have matching structure
5. **Fieldmap availability** - Distortion correction inputs are identified (if present)
6. **Physio data pairing** - Physiological recordings are matched to functional runs

---

## Algorithm

### 1. Dataset Key Resolution

Resolves the BIDS root directory from either:
- `--dataset-key` referencing an entry in `policy/datasets.yaml`
- `--bids-root` pointing directly to a BIDS directory

```
If dataset_key provided:
    Look up entry in policy/datasets.yaml
    Resolve local path via datasets_local.yaml
Else:
    Use bids_root directly (ad-hoc mode)
```

### 2. Inventory Building

Scans the BIDS directory to enumerate all processable runs:

- Discovers all subjects (optionally filtered by policy selection)
- Identifies sessions per subject
- Catalogs anatomical images (T1w, T2w) with priority ordering
- Catalogs functional runs with task labels
- Records associated metadata (JSON sidecars)

### 3. NIfTI Validation

For each discovered image file:

| Check | Validation |
|-------|------------|
| **Readability** | File can be opened with nibabel |
| **Header integrity** | Valid NIfTI-1/NIfTI-2 header |
| **Dimensions** | 3D (anat) or 4D (func) as expected |
| **Data type** | Numeric dtype (int16, float32, etc.) |
| **Affine** | Valid 4×4 transformation matrix |

### 4. Session Requirements

For multi-session datasets:

- Verifies each session has required modalities
- Flags sessions missing anatomical reference
- Reports session-level completeness

### 5. Fieldmap Matching

When fieldmaps are present:

| Fieldmap Type | Matching Rule |
|---------------|---------------|
| **Pepolar (AP/PA)** | Match by `IntendedFor` or acquisition time proximity |
| **Phase-difference** | Match magnitude + phasediff pairs |
| **Direct field map** | Match to functional by acquisition |

### 6. Physio Checks

For datasets with physiological recordings:

- Matches `_physio.tsv.gz` files to functional runs
- Validates column structure (cardiac, respiratory)
- Reports timing synchronization metadata

---

## Outputs

### Work Directory

```
{out}/work/S1_input_verify/{dataset_key}/
├── bids_inventory.json    # Complete dataset inventory
└── fix_plan.yaml          # Issues requiring attention
```

### Logs Directory

```
{out}/logs/S1_input_verify/{dataset_key}/
├── runs.jsonl             # Per-run status records
├── qc.json                # Aggregate QC summary
└── S1_evidence/           # Evidence for QC decisions
```

### Inventory Schema

The `bids_inventory.json` contains:

```json
{
  "dataset_key": "openneuro_ds005884",
  "bids_root": "/path/to/bids",
  "subjects": [
    {
      "subject": "02",
      "sessions": ["ses-01"],
      "anat": {
        "T2w": "/path/to/sub-02_T2w.nii.gz"
      },
      "func": [
        {
          "task": "motor",
          "run": "01",
          "path": "/path/to/sub-02_task-motor_run-01_bold.nii.gz"
        }
      ]
    }
  ]
}
```

### QC Summary Schema

The `qc.json` contains:

```json
{
  "status": "PASS",
  "dataset_key": "openneuro_ds005884",
  "total_subjects": 38,
  "total_runs": 152,
  "issues": [],
  "warnings": []
}
```

---

## QC Status Codes

| Status | Meaning |
|--------|---------|
| **PASS** | All validation checks passed |
| **WARN** | Non-blocking issues detected (e.g., missing optional files) |
| **FAIL** | Critical issues prevent processing (e.g., no anatomical image) |

---

## CLI Usage

```bash
# Validate a single dataset by key
poetry run spinalfmriprep run S1_input_verify \
  --dataset-key openneuro_ds005884 \
  --datasets-local config/datasets_local.yaml \
  --out work/wf_001

# Validate an ad-hoc BIDS directory
poetry run spinalfmriprep run S1_input_verify \
  --bids-root /path/to/my/bids \
  --out work/wf_001

# Check existing validation artifacts
poetry run spinalfmriprep check S1_input_verify \
  --dataset-key openneuro_ds005884 \
  --out work/wf_001
```

---

## Common Issues

### Missing Anatomical Image

```
FAIL: No T1w or T2w found for subject sub-XX
```

**Fix**: Ensure BIDS directory contains `sub-XX/anat/sub-XX_T{1,2}w.nii.gz`

### Invalid NIfTI Header

```
FAIL: Cannot read NIfTI header for sub-XX_bold.nii.gz
```

**Fix**: Verify file integrity; re-download or re-convert from DICOM

### Session Mismatch

```
WARN: Subject sub-XX has sessions [ses-01] but expected [ses-01, ses-02]
```

**Fix**: Check if data collection was incomplete or files are in wrong location

---

## References

1. **BIDS Specification:** [bids-specification.readthedocs.io](https://bids-specification.readthedocs.io/)
2. **NiBabel:** [nipy.org/nibabel](https://nipy.org/nibabel/)

---

*Last updated: January 2026*
