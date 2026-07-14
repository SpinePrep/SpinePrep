# S1 — Input Verify

> **Step code:** `S1_input_verify` · **Depends on:** S0 (Setup) · **Required by:** S2–S10

Walk a BIDS dataset, inventory every file by modality, sanity-check the images and
their sidecar metadata, and emit one per-dataset PASS / WARN / FAIL verdict with a
single diagnostic figure — so problems are caught at the front door, not five steps
downstream.

## At a glance

- **What it does (plain):** S1 reads the raw BIDS folder, lists what's there
  (which subjects/sessions have anatomical, functional, fieldmap, and physio
  files), checks each image opens and has a sane header, checks the sidecars carry
  the acquisition fields later steps need, and grades the dataset.
- **Key tools:** [nibabel](https://nipy.org/nibabel/) for NIfTI headers; the
  [BIDS](https://bids-specification.readthedocs.io/) filename + sidecar
  conventions. No external segmentation or registration — S1 only reads.
- **No tunable parameters:** S1 has **no `policy/` file** by design. Its checks
  encode the BIDS spec, not preferences, so there is nothing to tune.
- **Step-local QC:** the `status` (worst severity across all checks) plus the
  `S1_dataset_summary` reportlet — an HTML page with a counts table, a
  subject × modality grid, and the check table with PASS/WARN/FAIL badges.

## What it does

S1 is the pipeline's front door. It does not change any data; it produces an
**inventory** and a **verdict**.

1. **Resolve the dataset** — from a `--dataset-key` (looked up in
   `policy/datasets.yaml` and mapped to a local path via `datasets_local.yaml`)
   or a direct `--bids-root` (ad-hoc mode).
2. **Inventory** — recursively list every file under the BIDS root (skipping
   `derivatives/`), classify each by modality, and pull the relevant sidecar
   metadata for functional and fieldmap runs.
3. **Check** — run a fixed set of BIDS-spec and downstream-readiness checks over
   the inventory.
4. **Report** — write the inventory, per-run records, a QC summary, an
   actionable `fix_plan.yaml`, and one diagnostic PNG. The overall `status` is the
   worst severity across all checks.

## Algorithm & parameters

S1 has **no `policy/S1_input_verify.yaml`** — the behaviour below is fixed in code.

### Modality classification

Each file is classified by its BIDS location and suffix:

| File | Modality | Classification |
|---|---|---|
| `func/…_bold.nii[.gz]` | `func` | `cord_likely` |
| `func/…*.nii[.gz]` (non-BOLD) | `func` | `unknown` |
| any `anat/…*.nii[.gz]` | `anat` | `non_cord_likely` |
| any `fmap/…*.nii[.gz]` | `fmap` | `non_cord_likely` |
| `…physio.tsv[.gz]` | `physio` | `non_cord_likely` |

Two points of honesty:

- **`cord_likely` is not a cord-vs-brain classifier.** It marks *any* functional
  BOLD run. Whether a run actually images the cord is only determined later, at
  **S3** (cord localization), where brain-only runs fail.
- **Any NIfTI under `anat/` counts as anatomical** — including T2\*/MEGRE, PSIR,
  MP2RAGE, and MTS, not just T1w/T2w — so the inventory is complete for the
  contrasts S2 actually uses.

### Sidecar metadata

For every cord fMRI run and every fieldmap, S1 reads a small allowlist of BIDS
fields, following **BIDS inheritance** (it checks the same-directory sidecar first,
then walks up to the dataset root, dropping `sub-`/`ses-` entities so a
dataset-level `task-rest_bold.json` applies to all matching runs):
`RepetitionTime`, `SliceTiming`, `PhaseEncodingDirection`, `TotalReadoutTime`,
`EffectiveEchoSpacing`, `EchoTime`, and a few acceleration/matrix fields. These are
stored in the inventory so downstream steps need not re-parse BIDS.

### Checks

| Check | Severity | Meaning |
|---|---|---|
| `any_runs_present` | FAIL | The BIDS root yielded at least one run |
| `<sub>_<ses>_func_present` | FAIL | The session has ≥1 cord fMRI (BOLD) run |
| `<sub>_<ses>_anat_present` | WARN | The session has ≥1 anatomical image |
| `fmap_expected` | WARN | If a fieldmap is expected, its `IntendedFor` matches a BOLD |
| `physio_expected` | WARN | If physio is expected, recordings are found |
| `bold_repetition_time_present` | WARN | Every cord fMRI run declares `RepetitionTime` |
| per-run: file exists | FAIL | The listed file is on disk |
| per-run: BOLD is 4D with >1 volume | FAIL | A functional run is a real timeseries |
| per-run: finite affine + pixdim | FAIL | The NIfTI geometry is valid |
| per-run: qform/sform set | WARN | Orientation is defined (not code 0/0) |
| per-run fmap: `PhaseEncodingDirection` + `TotalReadoutTime` present | WARN | Fieldmap can drive FSL topup |
| per-run physio: `SamplingFrequency` present | WARN | Physio sidecar is usable |

## Why these choices

- **BIDS as the contract.** Filenames, entities, sidecars, and `IntendedFor`
  matching follow the BIDS spec (Gorgolewski et al., 2016), so any BIDS dataset
  is understood without per-dataset configuration.
- **S1 supplements, but does not replace, `bids-validator`.** Users are expected
  to run `bids-validator` (Markiewicz et al., 2021) on the raw dataset first. S1
  deliberately does **not** call it, for two reasons: its derivatives support is
  incomplete, and S1 needs cord-pipeline-specific bookkeeping that a general
  validator does not produce — fieldmap→BOLD `IntendedFor` matching for TopUp
  eligibility, physio presence, MEGRE/T2\* anat inventory, and extraction of the
  acquisition fields the later steps consume.
- **Pre-flight the fields that break things silently.** `RepetitionTime` (needed
  everywhere) and a fieldmap's `PhaseEncodingDirection` + `TotalReadoutTime`
  (needed to build FSL topup acqparams; Andersson et al., 2003) are checked *here*
  so a dataset missing them is flagged at S1 with a clear message, rather than
  failing cryptically at S5. These are WARN, not FAIL, because a fallback path
  (e.g. S5 SyN distortion correction) may still apply.
- **No tuning knobs.** BIDS-spec checks are not preferences, so encoding them in
  code (and this page) is the locking mechanism — there is no `policy/S1.yaml` to
  drift.

## Inputs → Outputs

**Input:** a raw BIDS dataset (read-only). S1 writes no derivative images.

**Outputs** (under `{out}/`):

| Artefact | Path | Contents |
|---|---|---|
| Inventory | `work/S1_input_verify/{ds}/bids_inventory.json` | `{ dataset_key, bids_root, files[], runs[] }`; each run = `{ path, subject, session, modality, classification, acquisition? }` |
| Fix plan | `work/S1_input_verify/{ds}/fix_plan.yaml` | Actionable list of issues to resolve |
| Per-run records | `logs/S1_input_verify/{ds}/runs.jsonl` | One JSON object per run, with its issues |
| QC summary | `logs/S1_input_verify/{ds}/qc.json` | `status`, `checks[]`, `counts`, `metrics`, `issues` |
| Reportlet | `derivatives/spineprep/_S1/{ds}/reports/{ds}_desc-S1_dataset_summary.html` | The diagnostic report (HTML tables) |

## Quality control

**Step-local metric.** `qc.json.metrics` carries aggregable gauges that quantify
input quality without re-parsing the checks:
`n_checks_total / passed / warned / failed`,
`n_runs_total / ok / with_issues`, and
`n_func_cord_runs / n_anat_runs / n_fmap_runs`.
The overall `status` is the worst severity across all checks.

**Reportlet — `S1_dataset_summary`.** One HTML page per dataset (S1 emits purely
tabular data — no imaging — so the report is plain tables), with three tables:

- **Counts** — files, runs, subjects, sessions, and the classification breakdown.
- **Subject × modality grid** — a cell per (subject, `anat`/`func`/`fmap`/`physio`)
  showing the file count.
- **Checks** — every check with a PASS / WARN / FAIL badge.

**What failure looks like:** an empty cell in the grid (a modality missing for a
subject), a red badge in the check table (e.g. a session with no cord fMRI ⇒ FAIL,
or a BOLD run missing `RepetitionTime` ⇒ WARN). The report is designed so a human
can accept or reject a dataset at a glance. See the [Gallery](../reports.md) for
live examples.

## Limitations & assumptions

- **Not a cord detector.** S1 assumes any `func/` BOLD may be cord fMRI; runs that
  do not actually cover the cord are caught downstream at S3, not here.
- **Assumes valid BIDS.** S1 supplements `bids-validator`; it does not re-implement
  full BIDS conformance. Run `bids-validator` first.
- **Subject-ID matching for subset selection** currently normalizes a few naming
  variants (a known, dataset-specific accommodation being generalized).
- **Header sanity, not image quality.** S1 verifies geometry and metadata, not
  SNR, motion, or coverage — those are the job of the per-step QC further down the
  chain.

## References

1. Gorgolewski, K. J., et al. (2016). *The Brain Imaging Data Structure (BIDS).*
   Scientific Data 3, 160044.
2. Markiewicz, C. J., et al. (2021). *The OpenNeuro resource for sharing of
   neuroscience data.* eLife 10, e71774. (bids-validator)
3. Andersson, J. L. R., Skare, S., Ashburner, J. (2003). *How to correct
   susceptibility distortions in spin-echo echo-planar images.* NeuroImage 20(2),
   870–888. (FSL topup acqparams: `PhaseEncodingDirection`, `TotalReadoutTime`)
4. NiBabel — [nipy.org/nibabel](https://nipy.org/nibabel/).

**Running S1:** see the [CLI reference](../reference/cli.md).

---
*Parameters and checks reflect `src/spineprep/steps/s1/` (no `policy/` file by
design); verified against code 2026-07-14. See
`.claude/specs/s1-algorithm-audit.md` for the full audit trail.*
