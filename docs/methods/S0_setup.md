---
search:
  boost: 2
---

# S0: Setup

Environment validation, container bootstrapping, and policy gate verification.

## Purpose

S0 ensures the processing environment is properly configured before any data processing begins. It validates:

1. **Container runtime** availability (Docker or Apptainer)
2. **Required container images** are present and functional
3. **Dataset policy** passes the v1 gate
4. **Template data** (PAM50) is accessible

## Inputs

| Input | Source | Required |
|-------|--------|----------|
| `policy/datasets.yaml` | Project root | Yes |
| Container runtime | System PATH | Yes |
| PAM50 templates | `$PAM50_PATH` or SCT installation | Yes |

## Outputs

| Output | Path | Description |
|--------|------|-------------|
| QC JSON | `logs/S0_setup_qc.json` | Detailed check results |
| State YAML | `state/setup_state.yaml` | Environment fingerprint |
| Evidence | `logs/S0_evidence/` | Audit trail artifacts |

## Algorithm

### 1. Policy Gate

Loads `policy/datasets.yaml` and validates against the v1 schema:

- All required fields present
- Dataset keys are unique
- Selection constraints are valid
- Spec fields (has_fmap, has_physio) are boolean

### 2. Container Runtime Detection

Checks for available container runtimes in order:

1. `docker` — preferred
2. `apptainer` — fallback for HPC environments

### 3. Container Image Verification

For each required image, verifies:

| Image | Purpose | Verification Command |
|-------|---------|---------------------|
| `spinalfmriprep` | Main pipeline | `spinalfmriprep --version` |
| `vnmd/spinalcordtoolbox_7.2` | SCT tools | `sct_version` |
| `vnmd/fsl_6.0.7.18` | FSL tools | `fslversion` |
| `vnmd/ants_2.6.0` | ANTs registration | `antsRegistration --version` |

### 4. PAM50 Template Check

Searches for PAM50 templates in order:

1. `$PAM50_PATH` environment variable
2. `$SCT_DIR/data/PAM50`
3. `~/sct_7.1/data/PAM50`

## CLI Usage

```bash
# Run S0 setup
spinalfmriprep run S0_SETUP --project-root /path/to/project

# Check S0 (verify artifacts exist)
spinalfmriprep check S0_SETUP --project-root /path/to/project
```

## QC Status Schema

```json
{
  "step": "S0_SETUP",
  "status": "PASS | FAIL",
  "failure_message": null,
  "checks": [
    {
      "name": "dataset_policy_gate",
      "passed": true,
      "message": "Dataset policy gate passed.",
      "details": { ... }
    },
    {
      "name": "container_runtime",
      "passed": true,
      "message": "Container runtime available.",
      "info": { "runtime": "docker", "version": "24.0.7" }
    }
  ]
}
```

## Edge Cases

| Condition | Behavior |
|-----------|----------|
| No container runtime | FAIL with "No container runtime found" |
| Missing image | FAIL with "Required image not found locally" |
| Policy validation error | FAIL with specific schema violation |
| PAM50 not found | FAIL with "PAM50 templates not found" |

## Dependencies

- Docker Engine ≥ 20.10 or Apptainer ≥ 1.0
- Python 3.11+
- Valid `policy/datasets.yaml`
