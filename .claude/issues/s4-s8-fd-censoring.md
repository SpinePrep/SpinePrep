---
status: candidate
title: "S4/S8: framewise displacement no longer censors frames or rejects runs"
repo: SpinePrep/SpinePrep
url:
drafted: 2026-07-16
implements: 5cf8e32
evidence: .claude/specs/s4-fd-threshold.md
---

Frame censoring now uses the intensity metrics (DVARS and reference RMS) against
a within-run box-plot fence, and the motion estimates are carried as nuisance
regressors rather than thresholded. This follows the cord-fMRI literature and
removes an acquisition artifact from the QC. The change landed in 5cf8e32; the
evidence is in `.claude/specs/s4-fd-threshold.md`. This issue records the
investigation.

## What was wrong

S4 failed a run when more than half its frames exceeded `FD > 0.5 mm`. On the
466-run validation cohort that rejected 12% of runs, rising to 49% once the
displacement was composed correctly. The threshold has four separate problems.

### The threshold inverts the criterion that produced it

Power et al. (2012) selected 0.5 mm by inspecting plots, to mark "values well
above the norm found in still subjects". Cord framewise displacement, composed
correctly, has a median of 0.50 mm. The value sits at the centre of the cord
distribution rather than in its tail, so importing it retains the number while
discarding the reasoning behind it.

### It censored frames that carry no artifact

Power's reasoning applied to this cohort, scoring post-correction residual DVARS
against displacement. DVARS is normalised per run, so 1.0 is that run's typical
frame.

| FD bin (mm) | frames | median residual DVARS |
|---|---|---|
| 0.00 to 0.25 | 5182 | 0.97 |
| 0.25 to 0.50 | 6911 | 0.97 |
| 0.75 to 1.00 | 3104 | 1.05 |
| 1.50 to 2.00 | 334 | 1.21 |
| above 3.00 | 141 | 2.01 |

Residual DVARS is flat below 0.5 mm. Motion correction already absorbs
displacement that small, so the frames censored there are indistinguishable from
still frames. The gate discarded a median 48% of frames, and the degrees of
freedom they carry, without measurable benefit. Signal disruption appears near
0.95 mm.

### It is not comparable across the cohort

Three acquisition properties move the value independently, each measured here.
Repetition time spans 1.55 to 3.26 s, a factor of 2.1, and slower sampling yields
larger displacement for identical motion (Jones et al., 2022). In-plane voxel
size spans 1.0 to 1.6 mm. The definition itself shifts the number twofold:
bulk-only displacement has a median of 0.28 mm against 0.55 mm for bulk plus
slice-wise, on the same runs.

The rejection pattern followed repetition time rather than motion, so the
slowest-TR datasets failed most. Reported without this context it would read as a
site or biology effect.

### No cord study thresholds displacement

Kaptan et al. (2023) does not use framewise displacement at all. It censors on
dVARS and reference RMS at two standard deviations above each run's mean, and
carries the slice-wise translations as regressors. Ricchi et al. (2024) computes
displacement but applies it to subject exclusion rather than frame censoring. No
cord paper found publishes a frame-censoring displacement threshold. Displacement
also lacks a null distribution, whereas DVARS has one (Afyouni and Nichols, 2018).

## What changed

S4 no longer rejects a run for motion (`max_high_motion_fraction: null`). A run
fails on a technical failure of the correction: cord tSNR below 3, or an input
defect such as a mask that does not match the series geometry. A new warning
fires when correction reduces cord tSNR, which is the failure mode the step can
actually detect.

S8 censors on `DVARS > Q3 + 1.5·IQR` or `refRMS > Q3 + 1.5·IQR`, with
`fd_outlier_threshold_mm: null`. Displacement remains available as an operator
override. The change also resolves an inconsistency inside that file, which used
a within-run rule for DVARS and an inherited absolute for displacement.

Displacement is still computed, reported, plotted, and passed to S8 as a
regressor, where its scale does not matter.

Two defects in the displacement itself were fixed in the same pass. Stage 1
estimates with FLIRT on projections written with an identity affine, so it
reports in voxels, while Stage 2 reports the ANTs warp in millimetres. The two
were summed and thresholded in millimetres, which under-counted bulk motion by
the voxel size on every dataset that is not 1.0 mm in-plane. A synthetic test
confirms it: a 2-voxel shift on a 1.5 mm grid returns 2.000 rather than 3.0.
Separately, the signed slice-wise field was averaged across slices, so opposing
rostral and caudal shifts cancelled, removing the motion the slice-wise stage
exists to measure. SCT takes the per-slice magnitude before averaging for this
reason.

## Effect on the cohort

Recomputed from the persisted parameters. No motion re-run was required, because
the motion estimates never reach the image data.

```
before:  270 PASS / 140 WARN /  56 FAIL
after:   300 PASS / 165 WARN /   1 FAIL
```

The remaining failure is a defect the shape guard caught. `sub-21_task-pain` has
a moco mask of (28, 28, 40) against a BOLD series of (28, 28, 39), an off-by-one
in the S3 crop. Tracked separately.

## To verify before publication

- [ ] Figley and Stroman (2007) primary text, for the physiological cord
      displacement magnitude of roughly 0.6 mm. Paywalled and unread, so
      currently uncited.
- [ ] Whether Parkes et al. (2018) varied thresholds or only pipelines.
- [ ] The Power (2012) Corrigendum (NeuroImage 63(2):999), which amends the cited
      paper and is unread.
- [ ] A further sweep of Barry, Vahdat, Weber and Stroman before stating that no
      cord paper publishes a censoring threshold.
- [ ] The argument that cord displacement conflates physiological cord motion
      with subject motion is this project's reasoning, not a published claim. No
      source was found for it. It must be labelled as reasoning wherever it
      appears.
