---
search:
  boost: 2
---

# S7: Template normalization

S7 links each functional run to the PAM50 spinal cord template by composing
transforms, and brings the template's masks and level atlas into the run's own
space without resampling the data.

## What it does

S7 concatenates the anat-to-PAM50 warp computed in S2 with the BOLD-to-anat warp
computed in S6, producing a single composite BOLD-to-PAM50 transform and its
inverse (De Leener et al., 2018, for the template). It uses the inverse to pull
the PAM50 cord, tissue masks and spinal-level atlas into native functional space,
so template ROIs are available in the run's own geometry.

The 4D BOLD is never resampled into template space. The per-subject analysis stays
in native functional space, and the analyst pushes their own
first-level contrast and statistic maps to PAM50 for group inference, using the
warps S7 stores. S9 does not resample the 4D BOLD into template space either. Keeping the timeseries native avoids a resampling that
would blur it for no per-subject benefit, and it matches the cord-fMRI practice of
analyzing in native space and warping the atlas inward: Kaptan et al. (2023) state
their analyses were "carried out in native space" and use `sct_warp_template` to
bring template masks in, a practice traced to Barry et al. (2014). S7 does not redo the anat-to-PAM50 registration; it trusts
S2's warp, including S2's choice of a rootlet- or disc-driven registration.

## Algorithm and parameters

The composition is a single `sct_concat_transfo` call. The atlas is then brought
into native space with `sct_warp_template -a 1`, which resamples the full PAM50
pack: cord, CSF, white-matter and gray-matter masks plus the spinal-level atlas.
The masks are resampled with nearest-neighbour and the funcref preview with
spline.

An optional second pass refines the functional reference directly against
`PAM50_t2s` (`sct_register_multimodal`, initialised from the composed warp), but it
is off by default. SCT's fMRI tutorial and Kaptan et al. (2023) both run this refinement, seeded by
the composed anat warp but with reduced iterations because the step is sensitive
to EPI artifacts. S7 is more conservative still: it omits the pass entirely,
because it added no information over S6's already-thorough cord-driven registration
and, on the pain dataset, dropped cord Dice from 0.82 to 0.68.
Enabling it runs `slicereg` (segmentation, MeanSquares, smooth 2) then `bsplinesyn`
(image, MeanSquares, 5 iterations, gradient step 0.5).

`refinement.enable`
: Whether to run the second-pass EPI-level refinement. Default `false`.

`template.reference_modality`
: PAM50 contrast used for refinement and the QC preview. Default `T2s`, the
closest match to T2\*-weighted BOLD.

`qc_thresholds.per_level_pass_min`
: Median per-level cord Dice at or above which a run passes. Default `0.90`.

`qc_thresholds.pass_dice_min`
: Whole-volume cord Dice pass level, used only as a fallback when per-level Dice
is unavailable. Default `0.80`.

## Inputs and outputs

```
derivatives/spineprep/sub-<id>/[ses-<id>/]func/
├── sub-<id>_..._from-bold_to-PAM50_xfm.nii.gz    # composite warp (+ .json sidecar)
├── sub-<id>_..._from-PAM50_to-bold_xfm.nii.gz    # composite inverse
├── sub-<id>_..._space-PAM50_desc-funcref.nii.gz  # funcref in PAM50 (QC overlay only)
├── sub-<id>_..._desc-PAM50cord_mask.nii.gz       # PAM50 cord in native func
├── sub-<id>_..._desc-PAM50csf_mask.nii.gz        # + wm / gm masks
└── sub-<id>_..._desc-PAM50spinallevels.nii.gz    # spinal-level atlas in native func
```

The warps are SCT-native displacement fields, matching the S2 and S6 convention,
with a JSON sidecar carrying the reproducibility receipt.

## Quality control

The reported metric is cord Dice in native functional space, the overlap between
the PAM50 cord warped through the composite transform and the S6 cord
segmentation. It reads partly as a convergence check: the BOLD-to-anat hop was
segmentation-driven on the functional cord, so that end of the composite warp was
optimized toward this overlap. It is less circular than the S6 metric, because the
anat-to-PAM50 hop was driven by the anatomical cord and vertebral disc labels,
which never saw the functional cord, so a low Dice here still localizes a real
composition failure. The visual overlay remains the primary check.

The primary gate is the median per-level cord Dice, computed level by level along
the cord. This is deliberately coverage-independent: a brain-plus-cord acquisition
images only a few cervical levels, which caps whole-volume overlap near 0.84 even
for a perfect registration, so a per-level median measures registration quality
where the cord is present. Per-level reporting is normal in this literature
(Kaptan et al., 2023; Dabbagh et al., 2024); using median per-level cord Dice as
the registration gate is SpinePrep's own refinement, not a cited standard. Whole-volume cord Dice is kept as a fallback and an
observability value. A cord-restricted forward-then-inverse round-trip drift is
also reported, as observability only, since `bsplinesyn` optimizes the forward and
inverse separately and some drift is intrinsic even at high Dice.

The reviewer inspects two reportlets: `pam50_on_func` (the functional reference
with the warped PAM50 cord contour overlaid, sagittal and axial) and
`cord_dice_per_level` (per-level Dice bars, where a single low level flags a broken
edge slice and uniformly low bars flag a global composition problem).

A run fails when whole-volume cord Dice falls below 0.65 or the registration exits
non-zero, warns when the median per-level Dice sits below the pass gate or any
single level falls below 0.50, and passes otherwise.

## Limitations

The composite warp is only as good as the two registrations it concatenates: an
error in S2's anat-to-PAM50 warp or S6's BOLD-to-anat warp propagates here, and
the cord-Dice metric cannot fully separate the two sources. The pipeline is
cervical: the PAM50 spinal-level atlas spans the whole column, but only the
cervical levels are used and validated. Refinement is off by default on
one-dataset evidence, so a cohort with different geometry might benefit from a
lighter refinement than the SCT default.

## References

- Cohen-Adad, J., et al. (2014). Cord registration validation.
- De Leener, B., et al. (2017). SCT: Spinal Cord Toolbox. NeuroImage 145, 24–43.
- De Leener, B., et al. (2018). PAM50: unbiased multimodal template of the
  brainstem and spinal cord. NeuroImage 165, 170–179.
- Barry, R. L., et al. (2014). Resting-state functional connectivity in the human
  spinal cord. eLife 3, e02812.
- Dabbagh, A., Horn, U., Kaptan, M., & Eippert, F. (2024). Reliability of task-based
  fMRI in the dorsal horn of the human spinal cord. Imaging Neuroscience.
  doi:10.1162/imag_a_00273
- Kaptan, M., et al. (2023). Reliability of resting-state functional connectivity in
  the human spinal cord. NeuroImage 275, 120152.

Running S7: see the [CLI reference](../reference/cli.md).

---
*Parameters reflect `policy/S7_template_normalization.yaml`, shipped with
SpinePrep; verified against the implementation on 2026-07-18. Audit:
`.claude/specs/s7-algorithm-audit.md`.*
