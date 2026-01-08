# SpinePrep Development Workflow

## Overview
This document describes the integrated development cycle for SpinePrep. The workflow ensures code quality, correctness, and adherence to acceptance criteria through systematic testing and validation.

## Development Cycle

### 1. Plan
- Define ticket in `private/ROADMAP.md` with:
  - Subtasks (S{N}.k) - for documentation only
  - Inputs/Outputs
  - Acceptance criteria
  - Testable commands

**Example:**
```markdown
### BUILD-S3-T1: Dummy drop + func cord localization

Subtask: S3.1, S3.2

Goal:
- Drop dummy volumes per policy, compute fast median reference...

Inputs:
- `{OUT}/run_XX/runs/S1_input_verify/bids_inventory.json`
- ...

Acceptance (testable):
- All acceptance commands exit with code 0.
- Required artifacts present and validated...
```

### 2. Implement
- Code in `src/spineprep/S{N}_*.py`
- Follow step contracts and QC requirements
- Ensure deterministic outputs
- Add proper error handling

**Key Principles:**
- Validity-first: Spinal cord measurement validity comes first
- Determinism: Same inputs + policy → identical outputs
- Fail fast: No silent downgrades, clear error messages

### 3. Test
```bash
# Unit tests
poetry run pytest tests/test_*.py -v

# Smoke test for specific step
python3 scripts/smoke_s{N}.py
```

**Test Types:**
- **Unit tests**: Test individual functions and components
- **Smoke tests**: Quick validation on minimal test data
- **Integration tests**: Test step execution end-to-end

### 4. Validate
```bash
# Run on regression datasets (auto-creates wf_reg_XXX)
python3 scripts/validate_regression.py --step S{N}_func_init_and_crop

# Check QC outputs
poetry run spineprep check S{N}_func_init_and_crop --dataset-key <key> --out <out>
```

**Validation Process:**
- Runs step on all regression dataset keys
- Automatically uses canonical workfolder naming (`wf_reg_XXX`)
- Verifies QC outputs are generated
- Checks QC JSON structure and required fields
- Reports any failures

### 5. Accept
```bash
# Run acceptance tests (auto-creates wf_full_XXX)
python3 scripts/acceptance_test.py --ticket BUILD-S{N}-T{i}

# Verify acceptance criteria met
python3 scripts/acceptance_test.py --ticket BUILD-S{N}-T{i} --step S{N}_func_init_and_crop
```

**Acceptance Criteria:**
- Required artifacts exist
- QC JSON is valid and contains required fields
- All acceptance commands exit with code 0
- QC status is PASS or WARN (not FAIL)
- Automatically uses canonical workfolder naming (`wf_full_XXX`)

## Quick Reference

### Run a step
```bash
poetry run spineprep run S{N}_func_init_and_crop --dataset-key <key> --out <out>
```

### Run full development cycle
```bash
./scripts/dev_cycle_full.sh --step S{N}_func_init_and_crop
```

### Individual workflow steps
```bash
# 1. Unit tests
poetry run pytest tests/test_*.py -v

# 2. Smoke test
python3 scripts/smoke_s{N}.py

# 3. Validation
python3 scripts/validate_regression.py --step S{N}_func_init_and_crop

# 4. Acceptance
python3 scripts/acceptance_test.py --ticket BUILD-S{N}-T{i} --step S{N}_func_init_and_crop
```

## Workflow Examples

### Example 1: Implementing a New Step Feature

1. **Plan**: Add ticket to ROADMAP with acceptance criteria
2. **Implement**: Write code in step file
3. **Test**: 
   ```bash
   poetry run pytest tests/test_s{N}_*.py -v
   python3 scripts/smoke_s{N}.py
   ```
4. **Validate**:
   ```bash
   python3 scripts/validate_regression.py --step S{N}_func_init_and_crop
   ```
5. **Accept**: Verify acceptance criteria met

### Example 2: Fixing a Bug

1. **Plan**: Document bug in ticket/issue
2. **Implement**: Fix the bug
3. **Test**: Run relevant unit tests
4. **Validate**: Run on regression datasets to ensure no regressions
5. **Accept**: Verify fix works and no new issues introduced

### Example 3: Full Cycle for New Step

```bash
# Run complete cycle
./scripts/dev_cycle_full.sh --step S{N}_func_init_and_crop
```

This automatically runs:
1. Unit tests
2. Smoke test (if available)
3. Validation on regression datasets
4. Acceptance tests

## QC Requirements

Every step must produce:
- **QC JSON**: Machine-readable status (`{OUT}/logs/{STEP}/{DATASET_KEY}/qc_status.json`)
- **Reportlets**: Human-readable figures (PNG files in `derivatives/spineprep/.../figures/`)
- **Artifacts**: Required outputs as specified in ROADMAP

## Work Directory Naming

Work directories follow a canonical naming convention:
- **`wf_smoke_XXX`**: Smoke tests (quick validation on minimal test data)
- **`wf_reg_XXX`**: Regression validation (runs on regression dataset keys)
- **`wf_full_XXX`**: Full runs (v1 validation datasets, acceptance tests)

Scripts automatically use the next available number (e.g., `wf_full_001`, `wf_full_002`, etc.).
You can override with `--out` if needed.

To migrate existing directories to the new naming:
```bash
python3 scripts/migrate_workfolders.py --dry-run  # Preview changes
python3 scripts/migrate_workfolders.py            # Apply migration
```

## Regression Datasets

Regression testing uses dataset keys marked with `"regression"` in `intended_use`:
- `reg_openneuro_ds005884_cospine_motor_subset`
- `reg_openneuro_ds005883_cospine_pain_subset`
- `reg_openneuro_ds004386_rest_subset`
- `reg_openneuro_ds004616_handgrasp_subset`
- `reg_internal_balgrist_motor_11_subset`

## Troubleshooting

### Tests Fail
- Check error messages for specific failures
- Verify test data is available
- Check that dependencies are installed

### Validation Fails
- Check QC JSON for specific error messages
- Verify regression datasets are accessible
- Check `config/datasets_local.yaml` is configured

### Acceptance Tests Fail
- Review ROADMAP acceptance criteria
- Verify all required artifacts are generated
- Check QC JSON structure matches schema

## Related Documentation

- `private/ROADMAP.md` - Implementation plan and tickets
- `private/BLUEPRINT.md` - Scope and guarantees
- `private/PILLAR.md` - Development principles

