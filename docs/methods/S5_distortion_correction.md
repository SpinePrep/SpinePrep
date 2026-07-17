---
search:
  boost: 2
---

# S5: Distortion correction

S5 corrects susceptibility-induced geometric distortion in the motion-corrected
functional series and writes an undistorted BOLD series, a corrected reference,
and a per-slice geometric quality report.

## What it does

Echo-planar imaging of the cord is distorted along the phase-encode axis, which
for cervical acquisitions is anterior-posterior. Differences in magnetic
susceptibility between bone, cord, CSF and air displace the cord in the
functional image relative to the anatomy, which corrupts every downstream
registration. S5 estimates that displacement and unwarps the series.

Correcting distortion retrospectively is a deliberate departure from most cord
fMRI, which addresses the problem at acquisition instead: slice-specific
z-shimming (Eippert et al., 2017; Kaptan et al., 2023), cord-focused shim
volumes (Kinany et al., 2022), or distortion-resistant readouts (Powers et al.,
2018). Where retrospective correction is performed, reversed phase-encode
estimation is the best-evidenced option for the cord (Wei et al., 2025), and
gradient-echo fieldmap unwarping has a separate line of use (Vahdat et al.,
2015). S5 implements the first and falls back to an image-based method; the
gradient-echo path is specified but not implemented, for lack of data rather
than lack of standing.

## Correction modes

S5 selects one mode per run from the BIDS metadata, using `IntendedFor` and
`PhaseEncodingDirection`.

`topup`
: Used when the dataset ships a spin-echo EPI pair with opposite phase-encode
directions. FSL `topup` estimates the off-resonance field from the pair and
`applytopup` unwarps the series (Andersson et al., 2003).

`none`
: The default when no fieldmap or reversed-PE pair exists. The distortion is
measured and reported, and the series is passed through uncorrected. Performing no
retrospective correction is the cord field's own practice (Eippert et al., 2017;
Kaptan et al., 2023; Kinany et al., 2022), and it is the honest default here for a
reason established by a held-out validation (see Quality control): the image-based
alternative recovers only about a quarter of the true distortion and worsens a
quarter of runs, and there is no per-run way to tell which.

`syn`
: An opt-in alternative when no fieldmap exists. The mean functional image is
nonlinearly registered to the subject's anatomy with ANTs `antsRegistration`
(SyN; Avants et al., 2008), restricted to the cord region. It is off by default on
the evidence below; a site may enable it after validating it on its own data.

A gradient-echo phase-difference path (FSL `fugue`) is selected by no branch: it
is not implemented in v1 because no dataset in the validation cohort ships
gradient-echo fieldmaps, which is a data limitation rather than a judgement on the
method (gradient-echo unwarping has the longest track record in cord fMRI; Vahdat
et al., 2015). The run record carries both the mode that ran and the mode the data
implied.

## Algorithm and parameters

For `topup`, the field is estimated with the `b02b0_1.cnf` configuration, which
subsamples by 1 throughout. The default `b02b0.cnf` begins with a subsampling
factor of 2 and so requires even image dimensions, which cord-cropped BOLD
usually does not have. The correction is applied with `--method jac` (Jacobian
intensity modulation), FSL's standard apply method; `lsr` is not used because it
requires both phase-encode directions of the BOLD itself. Total readout time is
read from `TotalReadoutTime`, falling back to `EffectiveEchoSpacing ×
(ReconMatrixPE − 1)` and then to the BIDS sidecar.

For `syn`, the transform is `SyN[0.1,3,0]` with a mutual-information metric (32
bins, cross-modal BOLD to T2w), a `4x2x1` shrink schedule and `2x1x0vox`
smoothing, resampled with `LanczosWindowedSinc`.

`syn.transform`
: Symmetric normalization gradient and regularization. Default `SyN[0.1,3,0]`.

`syn.metric`
: Registration cost. Default `MI` (32 bins), appropriate for the cross-modal
BOLD-to-T2w alignment.

`qc_thresholds.pass_dice_min`
: Cord Dice at or above which a run passes. Default `0.50`.

`qc_thresholds.pass_displacement_max_mm`
: Post-correction mean A-P displacement at or below which a run passes. Default
`1.0`.

`qc_thresholds.cord_roi_max_level`
: Highest vertebral level scored (`8` = T1). Levels below this are excluded from
the metric.

Two parameter choices are worth stating plainly because they depart from
brain-derived practice. The SyN convergence is `40x20x0`, which runs zero
iterations at full resolution and so is a two-level rather than three-level fit
(fMRIPrep's brain SyN uses `100x70x50`). The deformation is **not** restricted to
the phase-encode axis, and the cost is restricted to the crop cylinder rather than
the cord segmentation. fMRIPrep's fieldmap-less SyN does restrict deformation to
the phase-encode axis; both restrictions were implemented here and reverted after
they measurably reduced cord Dice, because a cord-only region with a single-axis
warp leaves the cost function too little signal to converge. The looser
configuration is retained on that evidence, not by convention.

## Inputs and outputs

S5 reads the motion-corrected series from S4 and the cord reference from S2.

```
derivatives/spineprep/sub-<id>/[ses-<id>/]func/
├── sub-<id>_..._desc-undistorted_bold.nii.gz      # corrected series
└── sub-<id>_..._desc-undistorted_funcref.nii.gz   # corrected reference
```

## Quality control

The step-local metric is the geometric pair introduced by Wei et al. (2025),
measured before and after correction. The headline measure is per-slice A-P
cord-centerline displacement: the distance in millimetres between the EPI cord
centroid and the anatomy cord centroid along the phase-encode axis. Wei et al.
report approximately 2.73 mm uncorrected and 0.13 mm after reversed-PE
correction. The per-slice trace is Savitzky-Golay smoothed (window 5, polynomial
order 2) to suppress finite-voxel centroid jitter of roughly 0.3 mm. The
supporting measure is cord Dice, the overlap between the cord segmented from the
mean BOLD with `sct_deepseg sc_epi` (EPISeg; Banerjee et al., 2025) and the
anatomy cord resampled into the BOLD grid. Slices with fewer than five cord
voxels are dropped as sampling-dominated.

The anatomy is brought into the BOLD grid with an `sct_register_multimodal`
cord-segmentation-driven rigid step rather than the intensity-driven FLIRT used
by Wei et al., which diverges on cord-cropped inputs whose intensity cost is
dominated by surrounding air. This deviation is documented rather than claimed as
equivalent.

Only cervical levels are scored. Static B0 offset rises steeply toward the
cervicothoracic junction, from about 20 Hz at C1 to about 154 Hz at T1 at 7 T
(Beghini et al., 2026), and published field profiles stop at T1, so the metric is
restricted to the levels where the field has been characterized rather than
extrapolated below them.

A run fails when cord Dice after correction falls below 0.30, when A-P
displacement exceeds 2.0 mm in `topup` mode, or when mutual information drops by
more than 10 percent while the geometric measures do not improve. It warns when
Dice or displacement sit between the pass and fail bands. A `syn` run that
exceeds the displacement ceiling while its Dice still clears the floor is flagged
distortion-limited and kept, because the limitation is acquisition-side: the
displacement bands were calibrated on reversed-PE data, and an image-based method
has no independent field measurement to match them.

Three reportlets carry the evidence: `slice_displacement` (per-slice A-P
displacement, before and after), `cord_dice_per_slice` (per-slice overlap with
the pooled 3D Dice in the title), and `distortion_effectiveness` (before and
after mean BOLD with the anatomy cord contour overlaid).

## Limitations

The `syn` mode was validated against the measured field and found wanting, which
is why it is off by default. On the 80 CoSpine runs that carry a reversed-PE pair,
each run was corrected both by `topup` (the measured field) and by `syn`
(withholding the fieldmap), and the two were compared per slice against the
field, not against cord Dice. SyN recovered about a quarter of the distortion the
fieldmap measured (a residual of roughly 2.0 mm out of 2.75 mm), and on a quarter
of runs it moved the cord further from the field than doing nothing. The measured
2.75 mm of uncorrected distortion matches the value CoSpine reports (Wei et al.,
2025), which confirms the comparison is sound.

The `syn` fallback has no independent measurement of the field. It infers
displacement from anatomy alone, so it can only be as right as that registration,
and its Dice score is partly circular: the metric rewards the alignment the
method optimizes. A published cord-specific objection exists and is not settled
here. Vahdat and colleagues, developing FASB, considered nonlinear warping of
cord EPI and rejected it, reporting that cord EPI "is often spatially distorted
at the disk level, and performing a nonlinear transformation generates
non-optimal twisted warping fields"; they aligned slice-wise centerlines instead.
SpinePrep's per-slice displacement trace is reported precisely so that such a
warp would be visible, but the objection stands until tested against a held-out
reversed-PE reference.

The `topup` path is exercised by unit tests and by the reversed-PE datasets in
the cohort, but the gradient-echo fieldmap path is absent, which omits the method
with the longest cord track record (Vahdat et al., 2015). Distortion correction
cannot recover signal that dropout has already destroyed, and no correction is
scored below T1.

## References

- Andersson, J. L. R., Skare, S., & Ashburner, J. (2003). How to correct
  susceptibility distortions in spin-echo echo-planar images. NeuroImage 20(2),
  870–888.
- Avants, B. B., et al. (2008). Symmetric diffeomorphic image registration with
  cross-correlation. Medical Image Analysis 12(1), 26–41.
- Banerjee, S., et al. (2025). EPISeg: Automated segmentation of the spinal cord
  on echo planar images. doi:10.1101/2025.01.07.631402
- Beghini, M., et al. (2026). Static and dynamic B0 field characterization of the
  cervical spinal cord. MAGMA. doi:10.1007/s10334-026-01349-4
- Eippert, F., et al. (2017). Denoising spinal cord fMRI data. NeuroImage.
- Kaptan, M., et al. (2023). Reliability of resting-state functional connectivity
  in the human spinal cord. NeuroImage.
- Kinany, N., et al. (2022). Towards reliable spinal cord fMRI. NeuroImage 250,
  118964.
- Powers, J. M., et al. (2018). Ten key insights into the use of spinal cord fMRI.
  Brain Sciences.
- Savitzky, A., & Golay, M. J. E. (1964). Smoothing and differentiation of data by
  simplified least squares procedures. Analytical Chemistry 36(8), 1627–1639.
- Vahdat, S., et al. (2015). Simultaneous brain-cervical cord fMRI reveals
  intrinsic spinal cord plasticity during motor sequence learning. PLoS Biology.
  doi:10.1371/journal.pbio.1002186
- Verma, T., & Cohen-Adad, J. (2014). Effect of respiration on the B0 field in the
  human spinal cord at 3T. Magnetic Resonance in Medicine. doi:10.1002/mrm.25075
- Wei, Z., et al. (2025). CoSpine: a simultaneous brain and spinal cord fMRI
  dataset. Scientific Data.

Running S5: see the [CLI reference](../reference/cli.md).

---
*Parameters reflect `policy/S5_func_distortion_correction.yaml`, shipped with
SpinePrep; verified against the implementation on 2026-07-16. Audit:
`.claude/specs/s5-algorithm-audit-v3.md`.*
