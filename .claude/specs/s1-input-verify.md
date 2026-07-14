---
status: implemented
---

# S1 input verify — audit against dev principles

This is the *step-local* spec for S1, written when applying the
SpinePrep development principles (`CLAUDE.md`) to each step in
turn. It records the audit findings, the literature backing, and the
remaining gaps.

## Objective

Walk a BIDS dataset root, inventory its files by modality, run a
minimal set of sanity checks on the imaging + sidecar metadata, and
emit a per-dataset PASS/WARN/FAIL with a diagnostic reportlet that lets
a human eyeball the outcome.

## Literature backing

- **BIDS spec** (Gorgolewski et al., Sci Data 2016) for the file layout,
  filename entities, sidecar conventions, and IntendedFor matching.
- **bids-validator** is the field-standard tool for BIDS conformance.
  SpinePrep does **not** call it because (a) its derivatives support is
  incomplete (issue tracked since 2023) and (b) S1 does cord-pipeline-specific
  bookkeeping bids-validator doesn't — fmap→BOLD IntendedFor matching for TopUp
  eligibility, physio presence, MEGRE/T2* anat inventory, and the acquisition
  fields downstream steps need. S1 supplements bids-validator, it does not
  replace it; users are expected to have run bids-validator on the raw BIDS
  root first.
  NOTE (truthfulness, per s1-algorithm-audit.md F1): the `cord_likely` label is
  NOT a cord-vs-brain classifier — it marks any `func/` BOLD. The real
  cord-vs-not determination happens at S3 (cord localization), where brain-only
  runs fail. Do not describe S1 as performing cord-specific image classification.

## Constraints

- No chain dependencies (principle §7). S1 only reads from the raw
  BIDS root and the policy YAML; it produces logs/inventory/qc/fix_plan
  and emits no derivative imaging files.
- No tunable algorithm knobs. The checks encode BIDS-spec sanity, not
  preferences. No `policy/S1_input_verify.yaml` exists by design.

## Deliverables

| Artefact | Path (under `out_dir`) | Purpose |
|---|---|---|
| Inventory | `work/S1_input_verify/<ds>/bids_inventory.json` | All files + modality classification |
| Runs JSONL | `logs/S1_input_verify/<ds>/runs.jsonl` | Per-run records |
| QC JSON | `logs/S1_input_verify/<ds>/qc.json` | Status, checks, counts, metrics, reportlets |
| Fix plan | `work/S1_input_verify/<ds>/fix_plan.yaml` | Actionable issue list |
| Reportlet | `derivatives/spineprep/_S1/<ds>/reports/<ds>_desc-S1_dataset_summary.html` | HTML tables: subject×modality grid + check badges + counts (principle §4) |

## Step-local truth metric (principle §3)

Aggregate gauges in `qc.json.metrics`:

- `n_checks_total`, `n_checks_passed`, `n_checks_warned`, `n_checks_failed`.
- `n_runs_total`, `n_runs_ok`, `n_runs_with_issues`.
- `n_func_cord_runs`, `n_anat_runs`, `n_fmap_runs`.

These are aggregable across datasets and give a single quantitative
gauge of input quality. `status` (PASS/WARN/FAIL) is derived from the
worst severity across checks.

## Checks performed

| Check | Severity | Source |
|---|---|---|
| `any_runs_present` | FAIL | trivial: cohort empty |
| `<sub>_<ses>_func_present` | FAIL | session has ≥1 cord-likely BOLD |
| `<sub>_<ses>_anat_present` | WARN | session has ≥1 anat (T1w / T2w) |
| `fmap_expected` | WARN | policy says fmap expected ⇒ IntendedFor matches a BOLD |
| `physio_expected` | WARN | policy says physio expected ⇒ files found |
| Per-run: file exists, 4D for BOLD, finite affine, qform/sform set | FAIL/WARN | NIfTI header sanity |
| Per-run physio sidecar: SamplingFrequency present | WARN | BIDS spec for physio |

## Diagnostic reportlet (principle §4)

Three panels in one PNG (`render_s1_dataset_summary`):

- **Left** — subject × modality presence matrix (`anat`/`func`/`fmap`/`physio`),
  cell value = file count.
- **Centre** — check status table with PASS/WARN/FAIL badges.
- **Right** — counts summary (files, runs, subjects, sessions, classification).

The title carries dataset_key + overall status. A human can tell from
this single image whether the BIDS root looks right.

## Decisions

| # | Choice | Rationale |
|---|---|---|
| 1 | No `policy/S1.yaml` | BIDS-spec checks are not tuning knobs; encoding them in code + this spec is the locking mechanism (principle §6) |
| 2 | Roll our own checks, don't shell out to bids-validator | Derivatives coverage gap + need for cord-likely classification |
| 3 | Emit one PNG per dataset, not per run | S1 is a dataset-level verification; per-run granularity adds noise |
| 4 | Add synthetic `runs[].summary` entry for the reportlet | Dashboard's reportlet scanner iterates per-run; a single synthetic entry is the minimum surface to surface a dataset-level PNG |
| 5 | Carry MI metrics aggregates in qc.json | Comparable across datasets without re-parsing the check list |

## Remaining gaps (acceptable / deferred)

- `bids-validator` integration as a pre-flight check could be added if
  the BIDS team's derivatives support lands.
- A per-subject (not just per-dataset) check breakdown would help
  large-N datasets. Defer until S1 runs on >50-subject release cohorts.
