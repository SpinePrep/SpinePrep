# SpinePrep

SpinePrep is a spine fMRI/structural preprocessing and QC pipeline.

## Repo hygiene (important)

- Large datasets live in `datasets/` and are **ignored by git**.
- Runtime artifacts live in `work/` and `logs/` and are **ignored by git**.

## Work Directory Naming

Work directories follow a canonical naming convention:
- `wf_smoke_XXX`: Smoke tests (quick validation on minimal test data)
- `wf_reg_XXX`: Regression validation (runs on regression dataset keys)
- `wf_full_XXX`: Full runs (v1 validation datasets, acceptance tests)

Scripts automatically use the next available number (e.g., `wf_full_001`, `wf_full_002`, etc.).

## Development workflow (minimal)

- Create a branch per step: `step/S{N}-short-desc`
- Commit messages: `S{N}: summary` (optionally include ticket ids in the body)
- Open a PR early and push often


