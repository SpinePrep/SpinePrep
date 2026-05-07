# SpinalfMRIprep Development Cycle Contract

> **Authority**: This document is the single source of truth for the SpinalfMRIprep development cycle.
> Scope definitions are canonical in `private/SPEC/HEADER.md`.

---

## Principles

1. **No skipping** — Every stage must complete or fail explicitly
2. **Checkpoints require confirmation** — User must confirm before proceeding past checkpoints
3. **SCT is mandatory** — Fail immediately if SCT is not installed
4. **Chain model** — Each step depends on previous; done steps are referenced via symlinks
5. **3 parallel chains** — Separate chains for smoke, reg, full scopes
6. **Expensive steps** — Only run processing when needed; use `--reportlets-only` for visualization changes

---

## Development Scopes

> Canonical definitions: `private/SPEC/HEADER.md` § Development Scopes

| Scope | Purpose | Datasets | Subjects | CLI Flag |
|-------|---------|----------|----------|----------|
| **smoke** | Verify step is correctly implemented | 1 regression subset | 1 | `--dataset-key` |
| **reg** | Verify step works across all datasets | 5 regression subsets | 5 (1 per dataset) | `--scope regression` |
| **full** | Complete validation for v1 acceptance | 5 v1_validation | 146 (all subjects) | `--scope full` |

### smoke (1 subject)
- Purpose: Quick sanity check that a step is correctly implemented
- Dataset: `reg_openneuro_ds005884_cospine_motor_subset` (1 subject)
- Use: `scripts/smoke_s{n}.py`

### reg (5 subjects)
- Purpose: Verify step works on 1 subject from each of 5 datasets
- Datasets: 5 regression subsets (1 subject each)
- Use: `--scope regression`

### full (146 subjects)
- Purpose: Complete validation for v1 acceptance
- Datasets: 5 v1_validation datasets (all subjects)
- Use: `--scope full` (alias for `--scope v1_validation`)

---

## Chain Model

### Concept

Each step in a chain references the previous step's "done" outputs via symlinks:

```
work/done/reg/S1/ → work/wf_reg_015/   (S1 done)
work/done/reg/S2/ → work/wf_reg_018/   (S2 done)
work/done/reg/S3/ → (not done yet)

New S3 run:
- Reads S1 inventory from work/done/reg/S1/
- Reads S2 outputs from work/done/reg/S2/
- Writes S3 outputs to work/wf_reg_022/
```

### Chain Structure

| Scope | Done Path | Workfolder Pattern |
|-------|-----------|-------------------|
| smoke | `work/done/smoke/S{N}/` | `wf_smoke_XXX` |
| reg | `work/done/reg/S{N}/` | `wf_reg_XXX` |
| full | `work/done/full/S{N}/` | `wf_full_XXX` |

### Step Dependencies

| Step | Depends On | Creates |
|------|------------|---------|
| S1_input_verify | none | `bids_inventory.json` per dataset |
| S2_anat_cordref | S1 | cordref, cord mask, vertebral labels |
| S3_func_init_and_crop | S1, S2 | functional reference, crop |
| S4+ | S3 | ... |

**Note**: S0_SETUP is a one-time bootstrap, not part of the dev-cycle chain.

---

## Stages

| # | Stage | Type | Required |
|---|-------|------|----------|
| 1 | Unit Tests | automated | yes |
| 2 | Smoke Test | automated | yes |
| 2.1 | Smoke Dashboard QC | checkpoint | yes |
| 3 | Regression | automated | yes |
| 3.1 | Regression Dashboard QC | checkpoint | yes |
| 4 | Mark Done | checkpoint | yes |
| 5 | Report | automated | yes |

---

## Stage Definitions

### Stage 1: Unit Tests

| Property | Value |
|----------|-------|
| type | automated |
| command | `poetry run pytest tests/test_S{N}_*.py -v --tb=short` |
| on_success | proceed to Stage 2 |
| on_failure | STOP, report failures |

### Stage 2: Smoke Test

| Property | Value |
|----------|-------|
| type | automated |
| prerequisite | `scripts/smoke_s{n}.py` must exist |
| command | `python3 scripts/smoke_s{n}.py` |
| chain | smoke |
| reads_from | `work/done/smoke/S{N-1}/` (previous step) |
| writes_to | `work/wf_smoke_XXX/` |
| on_success | proceed to Stage 2.1 |
| on_failure | STOP, report failures |

**Note**: Smoke scripts internally handle S1 prerequisite for their step.

### Stage 2.1: Smoke Dashboard QC

| Property | Value |
|----------|-------|
| type | checkpoint |
| dashboard_url | `https://balgrist.tail184bba.ts.net/dashboard/` |
| dashboard_content | merged view: done smoke steps + current step |
| verify | reportlets look correct, QC status is PASS |
| on_confirm | proceed to Stage 3 |
| on_decline | STOP, user fixes issues |

### Stage 3: Regression

| Property | Value |
|----------|-------|
| type | automated |
| chain | reg |
| scope | `regression` (5 datasets, 5 subjects) |
| reads_from | `work/done/reg/S{N-1}/` (previous step) |
| writes_to | `work/wf_reg_XXX/` |
| s1_prerequisite | S1 must be done for all 5 datasets in reg chain |
| command | `poetry run spinalfmriprep run S{N}_{step} --scope regression --datasets-local config/datasets_local.yaml --out work/${WF}` |
| on_success | proceed to Stage 3.1 |
| on_failure | STOP, report per-dataset status |

### Stage 3.1: Regression Dashboard QC

| Property | Value |
|----------|-------|
| type | checkpoint |
| dashboard_url | `https://balgrist.tail184bba.ts.net/dashboard/` |
| dashboard_content | merged view: done reg steps + current step |
| verify | all 5 datasets visible, images grouped by dataset |
| on_confirm | proceed to Stage 4 |
| on_decline | STOP, user fixes issues |

### Stage 4: Mark Done

| Property | Value |
|----------|-------|
| type | checkpoint |
| command | `python3 scripts/mark_done.py {scope} S{N} {workfolder}` |
| validates | QC status is PASS before creating symlink |
| creates | `work/done/{scope}/S{N}/` → `{workfolder}` |
| on_success | proceed to Stage 5 |
| on_failure | STOP, cannot mark failed run as done |

### Stage 5: Report

| Property | Value |
|----------|-------|
| type | automated |
| output | summary table with stage statuses |
| artifacts | workfolder, done symlink, dashboard URL |

---

## Regression Datasets

> See `private/SPEC/HEADER.md` § Development Scopes for full list.

5 regression subsets (1 subject each, 5 total):
- `reg_openneuro_ds005884_cospine_motor_subset`
- `reg_openneuro_ds005883_cospine_pain_subset`
- `reg_openneuro_ds004386_rest_subset`
- `reg_openneuro_ds004616_handgrasp_subset`
- `reg_internal_balgrist_motor_11_subset`

---

## Workfolders

| Prefix | Scope | Pattern |
|--------|-------|---------|
| `wf_smoke_` | smoke | `wf_smoke_XXX` |
| `wf_reg_` | reg | `wf_reg_XXX` |
| `wf_full_` | full | `wf_full_XXX` |

Command to get next number:
```
python3 scripts/get_next_workfolder.py {smoke|reg|full}
```

---

## Done Symlinks

### Structure

```
work/done/
├── smoke/
│   ├── S1/ → ../wf_smoke_008/
│   ├── S2/ → ../wf_smoke_012/
│   └── S3/ → (not done yet)
├── reg/
│   ├── S1/ → ../wf_reg_015/
│   ├── S2/ → ../wf_reg_018/
│   └── S3/ → (not done yet)
└── full/
    ├── S1/ → ../wf_full_003/
    └── S2/ → (not done yet)
```

### Mark Done Command

```bash
python3 scripts/mark_done.py {scope} S{N} {workfolder}

# Example:
python3 scripts/mark_done.py reg S2 work/wf_reg_018
```

**Behavior**:
1. Validates QC status is PASS in workfolder
2. Creates symlink: `work/done/{scope}/S{N}/` → `{workfolder}`
3. Reports success or failure

---

## Dashboard

| Property | Value |
|----------|-------|
| URL | `https://balgrist.tail184bba.ts.net/dashboard/` |
| Content | Merged view of done chain + current workfolder |
| Scope selector | Switch between smoke/reg/full chains |
| Workfolder selector | Switch between runs within scope |
| Dataset grouping | Images grouped by `dataset_key` |

### Regeneration

Dashboard auto-regenerates on step completion. For visualization-only changes:

```bash
# Regenerate reportlets without re-running expensive processing
poetry run spinalfmriprep run S{N}_{step} --reportlets-only --out {workfolder}
```

---

## Error Handling

| Error | Stage | Action |
|-------|-------|--------|
| Unit test failure | 1 | STOP, show failures |
| Smoke script missing | 2 | STOP, report "Not implemented" |
| Smoke test failure | 2 | STOP, show failures |
| SCT not installed | any | STOP, show "SCT required: https://spinalcordtoolbox.com" |
| Regression failure | 3 | STOP, show per-dataset status |
| User declines QC | 2.1, 3.1 | STOP, wait for fixes |
| Done symlink exists | 4 | WARN, ask to overwrite |
| QC not PASS | 4 | STOP, cannot mark as done |
| Previous step not done | 2, 3 | STOP, "Run S{N-1} first" |

---

## Prerequisites

| Prerequisite | Check Command | Required |
|--------------|---------------|----------|
| SCT installed | `which sct_version && sct_version` | yes |
| Poetry environment | `poetry run python --version` | yes |
| Previous step done | `test -L work/done/{scope}/S{N-1}` | yes (except S1) |

---

## Artifacts

### Per Workfolder

| Artifact | Path |
|----------|------|
| runs.jsonl | `{wf}/logs/S{N}_*_runs.jsonl` |
| per-dataset QC | `{wf}/logs/S{N}_*/{dataset_key}/qc.json` |
| dashboard | `{wf}/dashboard/` |
| derivatives | `{wf}/derivatives/spinalfmriprep/{dataset_key}/` |

### Done Symlinks

| Artifact | Path |
|----------|------|
| done marker | `work/done/{scope}/S{N}/` → workfolder |

---

## Report Format

```
## Dev Cycle Complete: S{N} ({scope})

| Stage | Status | Details |
|-------|--------|---------|
| Unit Tests | PASS/FAIL | N tests |
| Smoke Test | PASS/FAIL | wf_smoke_XXX |
| Smoke QC | CONFIRMED | user confirmed |
| Regression | PASS/FAIL | N/5 datasets |
| Regression QC | CONFIRMED | user confirmed |
| Mark Done | PASS | work/done/{scope}/S{N}/ created |

### Chain Status
- S1: done (work/done/{scope}/S1/)
- S2: done (work/done/{scope}/S2/)
- S{N}: **just completed**

### Artifacts
- Workfolder: work/wf_{scope}_XXX/
- Done symlink: work/done/{scope}/S{N}/
- Dashboard: https://balgrist.tail184bba.ts.net/dashboard/
```

---

## Revision History

| Date | Change |
|------|--------|
| 2026-01-29 | v3: Canonical scope definitions (smoke=1, reg=5, full=146 subjects) |
| 2026-01-29 | v2: Chain model with 3 scopes, done symlinks, mark-done validation |
| 2026-01-29 | v1: Initial declarative contract |

---

## Reportlets-Only Mode

### Purpose

Regenerate visualizations without re-running expensive processing. Useful when:
- Changing reportlet rendering code
- Fixing styling/layout issues
- Adding/modifying visualization types
- Debugging dashboard display

### Usage

```bash
# Single dataset
poetry run spinalfmriprep run S2_anat_cordref --dataset-key {key} --reportlets-only --out {workfolder}

# Batch mode (reg scope)
poetry run spinalfmriprep run S2_anat_cordref --scope reg --reportlets-only --out {workfolder}

# Batch mode (full scope)
poetry run spinalfmriprep run S2_anat_cordref --scope full --reportlets-only --out {workfolder}
```

### Requirements

- Existing `runs.jsonl` with processing results (run full step first)
- S1 inventory in workfolder or done chain

### What it does

1. Reads existing `runs.jsonl` (no SCT commands run)
2. Re-renders reportlet PNGs from existing NIfTI outputs
3. Updates `runs.jsonl` with new reportlet paths
4. Regenerates per-dataset QC JSON
5. Regenerates dashboard

### Contract

Per SPEC/HEADER.md § Step Requirements, all steps S2+ MUST implement:
- `run_S{N}_{step}_reportlets_only()` for single-dataset mode
- `run_S{N}_{step}_reportlets_only_batch()` for batch mode
