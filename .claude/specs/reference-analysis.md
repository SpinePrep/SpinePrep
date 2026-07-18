---
status: approved
---

# Reference analysis — a non-canonical demonstration (decision 3B)

Written 2026-07-18. Decision 3B: add an OPTIONAL reference-analysis step that
demonstrates how to consume SpinePrep's derivatives. This is explicitly **not**
part of the validated preprocessing pipeline and is **not** in `PARTICIPANT_STEPS`
— it never runs during a normal `spineprep <bids> <out> participant` call. It is a
worked example, opt-in only.

## Why it exists, and why it is walled off

The landscape review was unambiguous: a preprocessing BIDS-App should stop at
GLM-ready derivatives and leave the GLM, connectivity, and group statistics to the
analyst (fMRIPrep's "analysis-agnostic" doctrine). Crossing that line turns a
preprocessing tool into an analysis framework (that is what CoSpine is) and makes
it no longer analysis-agnostic.

3B threads that needle: SpinePrep keeps its preprocessing scope, but ships one
runnable, clearly-labelled example so a new user can see the intended native-space
workflow end to end — how to apply the S8 confounds, how to use the PAM50
spinal-level atlas already in native space, and what a first-level output looks
like. It answers "now what do I do with these files?" without pretending to be the
analysis.

Guardrails:
- Not in `PARTICIPANT_STEPS`; invoked only by an explicit opt-in
  (`spineprep reference-analysis <out_dir>` or `--reference-analysis`).
- Every output is written under `reference_analysis/` and every file/report is
  stamped "REFERENCE ANALYSIS — demonstration, not validated preprocessing".
- Does not feed S10 or the release manifest.

## What it demonstrates

The canonical cord resting-state analysis (Barry et al., 2014; Kaptan et al.,
2023): native-space, per-segmental-level ROI connectivity.

1. Load the primary derivative `desc-preproc_bold` (native, unsmoothed) and the S8
   confounds TSV.
2. Build the confound design matrix (the numeric confound columns), add an
   intercept, and residualize the BOLD by ordinary least squares — the single
   simultaneous regression S8's design is built for, which is where the Carp 2013
   order-of-operations concern is structurally avoided.
3. Extract the mean residual time-course per PAM50 spinal level, using S7's
   `desc-PAM50spinallevels` atlas already in native space, restricted to the cord
   mask.
4. Compute the level x level Pearson correlation matrix.
5. Write the matrix as a TSV, a heatmap reportlet, and a provenance JSON.

It deliberately does NOT: run a task GLM, do group statistics, threshold or
interpret connectivity, or push anything to template. Those are the analyst's.

## What it teaches (documented in the output)

- The confounds are applied in ONE simultaneous regression, not sequentially.
- The analysis is in native space; the atlas came to the data, not the reverse.
- Spike/outlier columns censor by soaking up flagged frames in the same GLM.
- The result is illustrative — the kernel, the ROI scheme, and the connectivity
  measure are all analyst choices SpinePrep is not making for them.

## Status

Optional, non-canonical, opt-in. Ships as a reference so the derivatives are
self-explanatory; it is not validated and carries no QC gate on the science.
