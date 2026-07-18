---
search:
  boost: 1
---

# Reference analysis (demonstration)

This is a worked example of how to analyze SpinePrep's derivatives, not part of
the pipeline. SpinePrep is a preprocessing tool: it stops at GLM-ready derivatives
and leaves the analysis to you, as fMRIPrep does. This page and its command exist
only so the intended native-space workflow is self-explanatory. Nothing here is
validated, and it never runs during a normal `participant` call.

## What it demonstrates

The canonical cord resting-state analysis (Barry et al., 2014; Kaptan et al.,
2023): native-space, per-segmental-level connectivity. Given one run's outputs it

1. loads the primary derivative `desc-preproc_bold` (native space) and the S8
   confounds table;
2. residualizes the BOLD against the whole confound matrix in a single
   simultaneous regression, which is what the S8 design is built for;
3. extracts the mean residual time-course per PAM50 spinal level, using the
   spinal-level atlas S7 already placed in native space, restricted to the cord;
4. computes the level-by-level Pearson correlation and writes it as a matrix, a
   heatmap, and a provenance record under `reference_analysis/`.

Every output is stamped as a demonstration.

## What it teaches

The confounds are applied once, together, not in sequence. The analysis stays in
native space; the atlas came to the data. The result is illustrative: the choice
of confounds, the ROI scheme, and the connectivity measure are all yours, and
SpinePrep does not make them for you. It runs no task GLM, no group statistics, no
thresholding, and pushes nothing to template.

## Running it

```bash
spineprep reference-analysis <out_dir> --subject 01 --run-id sub-01_task-rest
```

It reads the run's `desc-preproc_bold`, `desc-confounds_timeseries.tsv`, and
`desc-PAM50spinallevels` from the derivatives, and writes the matrix, heatmap, and
JSON to `reference_analysis/sub-01/`.

## References

- Barry, R. L., et al. (2014). Resting-state functional connectivity in the human
  spinal cord. eLife 3, e02812.
- Kaptan, M., et al. (2023). Reliability of resting-state functional connectivity
  in the human spinal cord. NeuroImage 275, 120152.
