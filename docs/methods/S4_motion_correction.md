---
search:
  boost: 2
---

# S4: Motion correction

S4 aligns every functional volume to a common frame and writes the
motion-corrected 4D series, the per-frame motion parameters, and a motion and
temporal-SNR quality report.

## What it does

S4 corrects subject motion in the cord-cropped 4D EPI produced by S3. Cord fMRI
is sensitive to small movements because the cord cross-section is a few
millimetres across, and its dominant motion is in-plane and can differ slice to
slice with the cardiac cycle. Correction runs in two stages: a coarse in-plane
bulk alignment of each volume, then a slice-wise realignment regularized along
the cord axis. No slice-timing correction is applied; the series is never
temporally resampled, following the cord-fMRI field standard (Eippert et al.,
2017; Kaptan et al., 2023). Slice-timing metadata is used only later, by
RETROICOR in S8.

## Algorithm and parameters

Stage 1 estimates a bulk in-plane translation for each volume with FSL `flirt`
v6.0 (2-DOF; Jenkinson & Smith, 2001), registering the volume's axial mean
projection to the mean projection of the robust reference from S3, and applies
that translation identically to every slice. Stage 2 performs slice-wise
in-plane realignment with `sct_fmri_moco` (SliceReg; De Leener et al., 2017),
regularizing the per-slice translations with a polynomial along the
inferior–superior axis so that a noisy single slice cannot diverge from its
neighbours. The registration metric is restricted to the cord by a cord mask.
`sct_fmri_moco` in the integrated SCT 7.1 builds its own registration target by
iterative averaging and takes no external reference, so the robust reference
governs Stage 1 and the tSNR comparison rather than the slice-wise stage.

`mode`
: Which stages run. Default `3d+2d` (both). Allowed: `3d+2d`, `3d`, `2d`.

`stage1_coarse.interpolation_order`
: Spline order for applying the Stage-1 shift. Default `1` (linear).

`stage2_slicereg.poly_order`
: Degree of the along-Z polynomial regularizing the slice-wise translations.
Default `2` (the `sct_fmri_moco` default).

`stage2_slicereg.metric`
: Registration cost function. Default `MeanSquares`, appropriate for the
same-contrast BOLD-to-BOLD alignment here. Allowed: `MeanSquares`, `MI`.

`stage2_slicereg.iterations`
: Maximum optimizer iterations per slice. Default `10`.

`z_shift_correction.enabled`
: Detect and correct a bulk inferior–superior shift between runs of the same
subject and task. Default `false`; detection is reported when a run-01 reference
of matching shape is available.

## Inputs and outputs

S4 reads the cropped BOLD, the robust reference, and the cord segmentation from
the S3 run directory. It writes, per run:

```
derivatives/spineprep/sub-<id>/[ses-<id>/]func/
├── sub-<id>_..._desc-mocoref_bold.nii.gz   # motion-corrected 4D series
└── sub-<id>_..._moco_params.tsv            # per-frame motion magnitude
```

The signed slice-wise translation fields (`moco_params_x.nii.gz`,
`moco_params_y.nii.gz`) are retained in the working directory and read by S8 to
build the motion confound regressors.

## Quality control

The step-local metric is temporal SNR (voxel temporal mean divided by temporal
standard deviation) measured inside the cord segmentation, reported before and
after correction; effective correction raises cord tSNR (Kaptan et al., 2023).
Framewise displacement is reported but does not determine the run's status.
It is the sum of the absolute derivatives of the in-plane translations,
`|Δtx| + |Δty|`, a cord adaptation of Power et al. (2012) that drops the
through-plane and rotational terms because the slice-wise stage estimates
in-plane translation only. The two stages are composed per slice in millimetres,
and the absolute temporal difference is taken per slice before averaging across
slices, so opposing shifts at different levels cannot cancel.

Motion does not fail a run. Frames are censored downstream in S8 on the
intensity metrics (DVARS and reference-RMS, each against a within-run box-plot
fence), which is the cord field's practice: Kaptan et al. (2023) censor on those
metrics at two standard deviations and carry the slice-wise translations as
regressors rather than thresholding displacement. An absolute displacement
threshold is not used, for three measured reasons. Power's 0.5 mm was chosen for
brain data as a value "well above the norm found in still subjects", and it sits
at the median of cord framewise displacement, so it inverts the criterion that
produced it. Frames below 0.5 mm show no more residual signal change after
correction than frames below 0.25 mm, so censoring there removes usable data.
And displacement is not comparable across acquisitions: it scales with
repetition time (Jones et al., 2022) and with the definition used, both of which
vary across datasets. Framewise displacement is instead supplied to S8 as a
nuisance regressor, where its scale does not matter. A run fails only on a technical
failure of the correction itself: cord tSNR below 3, or an input defect such as a
mask that does not match the series geometry. It is warned when correction lowers
cord tSNR, or when a single-frame displacement peak exceeds `warn_fd_mm`, both of
which point the reviewer at a specific run without rejecting it. The reviewer inspects three reportlets:
a motion-trace panel (in-plane translation, FD, and DVARS on a shared time
axis), a slice-by-time heatmap of the signed slice-wise shift, and a
before/after tSNR comparison with a per-slice cord profile.

## Limitations

Motion is often sub-voxel in cooperative cohorts, where correction changes the
series little and the value is mainly in the QC record. The slice-wise stage
estimates in-plane translations only; through-plane and rotational motion are
not modelled, consistent with the cord field but a genuine limit on heavily
moving runs. Correction quality depends on the S3 cord segmentation, since the
registration metric is restricted to it. Framewise displacement built from
in-plane translations does not capture out-of-plane motion, so a low FD does not
by itself certify a still run.

## References

- De Leener, B., et al. (2017). SCT: Spinal Cord Toolbox, an open-source
  software for processing spinal cord MRI data. NeuroImage 145, 24–43.
- Eippert, F., et al. (2017). Denoising spinal cord fMRI data: Approaches to
  acquisition and analysis. NeuroImage.
- Jenkinson, M., & Smith, S. (2001). A global optimisation method for robust
  affine registration of brain images. Medical Image Analysis 5(2), 143–156.
- Jones, S., et al. (2022). A multi-dataset evaluation of frame censoring for
  motion correction in task-based fMRI. Aperture Neuro.
  doi:10.52294/ApertureNeuro.2022.2.NXOR2026
- Kaptan, M., et al. (2023). Reliability of resting-state functional
  connectivity in the human spinal cord. NeuroImage.
- Power, J. D., et al. (2012). Spurious but systematic correlations in functional
  connectivity MRI networks arise from subject motion. NeuroImage 59(3),
  2142–2154.

Running S4: see the [CLI reference](../reference/cli.md).

---
*Parameters reflect `policy/S4_func_motion_correction.yaml`, shipped with
SpinePrep; verified against the implementation and SCT 7.1 on 2026-07-16. Audit:
`.claude/specs/s4-algorithm-audit.md`.*
