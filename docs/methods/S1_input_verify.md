# S1: Input verify

S1 inventories a BIDS dataset and reports whether it can be processed. It reads
only the raw input and writes no derivative images, producing a per-dataset
inventory, a set of checks, and a diagnostic report. It runs before every other
step and gates the rest of the chain.

## What it does

S1 runs first in the participant-level chain, on the BIDS dataset passed to
SpinePrep. Every file under the dataset root is enumerated, excluding
`derivatives/`, and classified by modality. For each functional and
fieldmap run, the relevant BIDS sidecar fields are read following the inheritance
principle: the same-directory sidecar first, then each parent directory up to the
dataset root, with `sub-` and `ses-` entities dropped so that a dataset-level
`task-rest_bold.json` applies to all matching runs. A fixed set of checks is then
evaluated over the inventory, and the dataset is graded by the worst check
severity.

S1 has no `policy/S1_input_verify.yaml`. Its checks encode the BIDS specification
(Gorgolewski et al., 2016) rather than tunable preferences, so there is nothing
to configure.

## Classification

Each file is assigned a modality from its BIDS location and suffix. A NIfTI under
`func/` whose name contains `bold` is a functional run; any NIfTI under `anat/` is
anatomical; any NIfTI under `fmap/` is a fieldmap; a `_physio.tsv[.gz]` file is a
physiological recording.

A functional run is labelled `cord_likely`. The label marks the presence of a
BOLD run, not the presence of cord signal; whether a run images the cord is
determined at S3, where cord localization fails on brain-only runs. Anatomical
classification accepts every contrast under `anat/`, including T2\*/MEGRE, PSIR,
and MP2RAGE, not only T1w and T2w, so the inventory reflects the contrasts S2
uses.

## Checks

| Check | Severity | Condition |
|---|---|---|
| `any_runs_present` | FAIL | the BIDS root yields at least one run |
| `<sub>_<ses>_func_present` | FAIL | the session contains a BOLD run |
| `<sub>_<ses>_anat_present` | WARN | the session contains an anatomical image |
| `fmap_expected` | WARN | an expected fieldmap's `IntendedFor` matches a BOLD run |
| `physio_expected` | WARN | expected physiological recordings are found |
| `bold_repetition_time_present` | WARN | every BOLD run declares `RepetitionTime` |
| per-run NIfTI | FAIL / WARN | file exists; BOLD is 4D with more than one volume; affine and pixdim are finite; qform/sform codes are set (WARN) |
| per-run fieldmap | WARN | `PhaseEncodingDirection` and `TotalReadoutTime` are present |
| per-run physiology | WARN | the sidecar declares `SamplingFrequency` |

`RepetitionTime`, `PhaseEncodingDirection`, and `TotalReadoutTime` are checked at
S1 rather than left to fail later. A dataset missing them is reported before S5,
which cannot build its FSL topup parameters without the phase-encoding direction
and readout time (Andersson et al., 2003). These are warnings, since a
SyN-based fallback may still apply.

S1 supplements bids-validator (Markiewicz et al., 2021) rather than replacing it,
and assumes it has been run on the raw dataset first. bids-validator is not
called, because its derivatives support is incomplete and S1 additionally records
the cord-pipeline-specific information downstream steps consume: fieldmap-to-BOLD
matching for distortion correction, physiology presence, the T2\*/MEGRE
anatomical inventory, and the extracted acquisition fields.

## Inputs and outputs

The input is a read-only BIDS dataset. Under the output root, S1 writes the
inventory (`work/S1_input_verify/<ds>/bids_inventory.json`, listing files and runs
with their acquisition metadata), a fix plan (`fix_plan.yaml`), per-run records
(`logs/S1_input_verify/<ds>/runs.jsonl`), a QC summary (`qc.json`), and the
reportlet.

## Quality control

`qc.json.metrics` records counts that quantify input completeness across datasets:
the number of checks total, passed, warned, and failed; the number of runs total,
valid, and flagged; and the number of functional, anatomical, and fieldmap runs.
The dataset status is the worst check severity.

The reportlet, at
`derivatives/spineprep/_S1/<ds>/reports/<ds>_desc-S1_dataset_summary.html`, is an
HTML page of three tables: a counts summary, a subject-by-modality grid of file
counts, and the check table with per-check status. A missing modality appears as
an empty cell, and a failed or warned check appears in the check table. The human
reads it to accept or reject the dataset, consistent with visual QC as the
validator.

## Limitations

S1 verifies file presence, NIfTI geometry, and sidecar metadata, not image
quality; signal-to-noise ratio, motion, and cord coverage are assessed by the
per-step QC later in the chain. It does not determine whether a functional run
images the cord, which S3 does. It assumes BIDS validity and does not
re-implement full BIDS conformance, so `bids-validator` should be run on the
dataset first.

## References

- Gorgolewski, K. J., et al. (2016). The Brain Imaging Data Structure. Scientific
  Data 3, 160044.
- Markiewicz, C. J., et al. (2021). The OpenNeuro resource for sharing of
  neuroscience data. eLife 10, e71774.
- Andersson, J. L. R., Skare, S., Ashburner, J. (2003). How to correct
  susceptibility distortions in spin-echo echo-planar images. NeuroImage 20(2),
  870–888.
- NiBabel. https://nipy.org/nibabel/

Running S1: see the [CLI reference](../reference/cli.md).

---
*S1 has no tunable parameters by design; its checks are fixed in code. Verified
against the implementation on 2026-07-15.*
