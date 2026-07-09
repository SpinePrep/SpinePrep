# CLI Reference

SpinePrep installs a single command, `spineprep` (defined as the package entry
point in `pyproject.toml`). It has two interfaces:

- The **BIDS-App interface** — the standard, supported way to run the pipeline
  on a dataset. Use this.
- The **per-step interface** — an advanced/internal way to run or check one
  pipeline step at a time. You normally do not need it.

Check the installed version at any time:

```bash
spineprep --version
```

---

## BIDS-App interface

SpinePrep follows the [BIDS-Apps](https://bids-apps.neuroimaging.io/) convention
(Gorgolewski et al. 2017): three positional arguments — an input dataset, an
output directory, and an analysis level — followed by options.

```
spineprep <bids_dir> <output_dir> {participant,group} [options]
```

- **participant** — runs the per-subject preprocessing chain (steps S1 through
  S9) and writes BIDS-Derivatives plus QC reports into `<output_dir>`.
- **group** — runs the cross-subject aggregation and release step (S10) over the
  outputs already in `<output_dir>`.

Every step writes into the *same* `<output_dir>` tree, so each step finds its
predecessor's outputs there. Run `participant` first, then `group`.

### Positional arguments

| Argument | Meaning |
|----------|---------|
| `bids_dir` | Root of the BIDS dataset to process. |
| `output_dir` | Where BIDS-Derivatives and QC reports are written (created if missing). |
| `analysis_level` | `participant` (runs S1–S9) or `group` (runs S10 aggregation). |

### Options

These are the flags actually parsed by the BIDS-App entry point
(`src/spineprep/bids_app.py`). No others exist.

| Option | Argument(s) | Default | Meaning |
|--------|-------------|---------|---------|
| `--participant-label` (alias `--participant_label`) | one or more subject labels, without the `sub-` prefix | all subjects in `bids_dir` | Process only these subjects. |
| `--batch-workers` | integer | `1` | Per-step subject/run parallelism. |
| `--smoothing-sigma-mm` | three floats: `RL AP SI` | from policy (S9) | Override the S9 cord-smoothing kernel width (in millimetres, order right–left, anterior–posterior, superior–inferior) without editing policy YAML. |
| `--skip-bids-validator` | (flag) | off | Skip the built-in input checks (subjects present; each has readable functional and anatomical images). Bypass at your own risk. |
| `--version` | (flag) | — | Print the version and exit. |

!!! note "What the input check does"
    Unless you pass `--skip-bids-validator`, participant runs start with a fast
    structural check of the input: it verifies there are `sub-*` directories,
    that any subjects you named exist, and that each subject has a functional
    BOLD and an anatomical image that load as valid NIfTI. It reports every
    problem it finds at once and stops before any heavy processing. It is a
    lightweight front-door check, not the full BIDS validator.

### Examples

Process every subject, then aggregate:

```bash
spineprep /data/bids /data/out participant
spineprep /data/bids /data/out group
```

Process three subjects with more parallelism:

```bash
spineprep /data/bids /data/out participant \
  --participant-label 01 07 12 --batch-workers 8
```

Override the cord-smoothing kernel for this run only:

```bash
spineprep /data/bids /data/out participant --smoothing-sigma-mm 1.0 1.0 8.0
```

For running the containerised image with Docker or Apptainer, see the
[Quickstart](../quickstart.md).

### Exit codes and outputs

The participant run isolates per-subject failures: a subject that fails a step's
QC is dropped and reported, while the other subjects continue. The run stops only
if a step actually crashes, or if *every* run failed QC at a step (nothing left
to process downstream). A machine-readable `spineprep_run_manifest.json` is
written to `<output_dir>` recording per-step pass/fail/skip counts and the final
exit code. At group level, a BIDS-Derivatives compliance check is run over the
output tree and any problems are printed as warnings.

---

## Per-step interface (advanced)

The same `spineprep` command also exposes an internal per-step interface
(`src/spineprep/cli.py`) used during development to run or inspect one step in
isolation. The BIDS-App interface above is a thin wrapper over it. You only need
this if you are debugging a single step or driving the chain by hand.

```
spineprep run   <STEP> [options]
spineprep check <STEP> [options]
```

- `run` executes the step and writes its outputs.
- `check` inspects an already-run step and re-evaluates its QC without writing
  new processing outputs.

### Step codes

| Code | Step |
|------|------|
| `S0_SETUP` | Bootstrap / policy validation. |
| `S1_input_verify` | Input inventory and verification. |
| `S2_anat_cordref` | Anatomical cord reference, segmentation, labeling, PAM50 registration. |
| `S2B_func_denoise` | Optional MP-PCA thermal-noise denoising of raw BOLD. |
| `S3_func_init_and_crop` | Functional reference, outlier gating, cord-focused crop. |
| `S4_func_motion_correction` | Motion correction. |
| `S5_func_distortion_correction` | Distortion correction (topup or SyN fallback). |
| `S6_func_to_anat_registration` | Functional-to-anatomical registration. |
| `S7_template_normalization` | Template (PAM50) normalization. |
| `S8_confounds_and_physio_regressors` | Confound and physiological regressor extraction. |
| `S9_primary_functional_derivatives` | Final preprocessed BOLD, tSNR, smoothing. |
| `S10_qc_aggregation_and_release` | Cross-subject QC aggregation and release reports (group level). |

### Options

Not every option applies to every step; the ones a step ignores are accepted for
uniformity. These are the flags defined in `cli.py`.

| Option | Argument | Meaning |
|--------|----------|---------|
| `--project-root` | path | Project root containing `policy/` and `logs/` (required for `S0_SETUP`). |
| `--dataset-key` | string | A dataset key from `policy/datasets.yaml`. |
| `--dataset-keys` | one or more strings | Multiple dataset keys for batch processing. |
| `--scope` | string | Process datasets by scope: `reg`/`regression`, `full`/`v1_validation`, or a comma-separated list of dataset keys. |
| `--datasets-local` | path | A `datasets_local.yaml` mapping dataset keys to local BIDS roots. |
| `--bids-root` | path | Explicit BIDS root (overrides the datasets-local mapping). |
| `--out` | path | Output root for step artifacts. |
| `--reportlets-only` | (flag) | Regenerate only the QC reportlets from existing outputs (skip processing). |
| `--batch-workers` | integer | Number of datasets/runs to process in parallel (default `32`). |

Each step prints a compact JSON summary (`status`, `failure_message`) and exits
`0` on `PASS`/`WARN`, `1` on `FAIL`.

### Example

Run one step against an explicit BIDS root and output directory:

```bash
spineprep run S2_anat_cordref \
  --bids-root /data/bids --dataset-key my_dataset --out /data/out
```

Re-check a step's QC without reprocessing:

```bash
spineprep check S6_func_to_anat_registration --out /data/out
```

!!! warning "Internal interface"
    The per-step interface, its flags, and the dataset-scope machinery are
    development conveniences and may change between versions. For normal use,
    prefer the BIDS-App interface.
