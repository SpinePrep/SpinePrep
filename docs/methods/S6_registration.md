---
search:
  boost: 2
---

# S6: Functional-to-anatomical registration

S6 registers the functional data to the subject's own anatomy and stores the
transform in both directions, so later steps can move data between functional and
anatomical space without recomputing the alignment.

## What it does

S6 aligns the distortion-corrected mean functional image from S5 to the
anatomical cord reference from S2, and writes a forward warp (functional to
anatomy) and its inverse. S7 (template normalization) and S8 (confound
extraction) reuse these warps rather than recomputing them, so the functional
series stays in its native space and is never resampled onto the anatomical grid.
The registration is driven by the cord segmentation rather than image intensity,
because a cord-cropped EPI has an intensity cost surface dominated by the air
around the cord, on which an intensity-only registration diverges. Because the
cost sees only the cord outline, the same recipe works whether the anatomy is
T1w, T2w or T2star.

## Algorithm and parameters

S6 is a single `sct_register_multimodal` call (De Leener et al., 2017) with a
three-stage, cord-segmentation-driven parameter string, run with the functional
image as the moving image and the anatomy as the destination, `-i funcref -d
anat`. Before registration the anatomy is cropped to a dilated cord region
(`sct_crop_image -m anat_seg -dilate 10x10x10`), which restricts the cost surface
to cord context.

The three stages are built from SCT's standard registration primitives:
`centermassrot` (slicewise center-of-mass and rotation alignment, for oblique
acquisitions), `columnwise` (right-left scaling and anterior-posterior
deformation along the cord axis), and `bsplinesyn` (slicewise nonlinear B-spline
refinement, 20 iterations). All three use the cord segmentation as the cost
(`type=seg`) with the MeanSquares metric.

This composition is SpinePrep's own, not a published recipe copied verbatim.
SCT's default template chain is two stages (`centermassrot` then `bsplinesyn`);
the inserted `columnwise` stage and the higher iteration count are deliberate
tuning for cord-cropped EPI. Registering the functional image to the subject's
own anatomy, rather than to the template directly, is a two-hop design
(functional to anatomy here, anatomy to PAM50 in S7) shared with CoSpine (Wei et
al., 2025) and Eippert et al. (2017); some pipelines instead register the
template to the functional mean directly.

`step{1,2,3}.algo`
: The three stage algorithms above. Defaults `centermassrot`, `columnwise`,
`bsplinesyn`.

`step3.iter`
: B-spline refinement iterations. Default `20`.

`anat_crop.dilate`
: Dilation of the cord region the anatomy is cropped to. Default `10x10x10`.

`interpolation`
: Resampling kernel. Default `spline`.

## Inputs and outputs

```
derivatives/spineprep/sub-<id>/[ses-<id>/]func/
├── sub-<id>_..._from-bold_to-anat_xfm.nii.gz     # forward warp (+ .json sidecar)
├── sub-<id>_..._from-anat_to-bold_xfm.nii.gz     # inverse warp
├── sub-<id>_..._space-anat_desc-mean_bold.nii.gz # mean BOLD in anat geometry (QC)
└── sub-<id>_..._desc-tsnr_funcref.nii.gz         # tSNR reference (used by S7)
```

The forward-warp JSON sidecar carries the reproducibility receipt: the policy
hash, source path, registration method and parameters, and software versions.

## Quality control

The reported metric is 3D cord Dice, the overlap between the EPI cord warped into
anatomical space and the anatomy cord segmentation. This is a **convergence
check, not an independent validator**: the registration is driven to maximize
that same overlap, so a high Dice mainly confirms the optimizer reached its
objective. It is structurally blind to two things a reviewer should check on the
reportlet directly. One is a cord aligned in cross-section but shifted along its
axis (Dice on a smooth cord is nearly invariant to axial shifts); the other is
intensity mismatch inside the cord. The `0.85` pass level is SpinePrep's operating point on
cord-cropped EPI, not a threshold reported in the literature.

Three metrics support it, all observability-only (they never fail a run): HD95
(95th-percentile Hausdorff distance) catches a few cord voxels sitting far off
even when Dice is high, though it is quantized to the EPI slice thickness and
sensitive to single end-slice dropout; ASD (average symmetric surface distance)
gives the mean boundary disagreement; and a centerline round-trip drift reports
how far the cord centerline moves under forward-then-inverse warp, which is
non-zero even for a good registration because `bsplinesyn` optimizes the two
directions separately.

The reviewer inspects two reportlets: `bold_on_anat` (BOLD against anatomy with
the cord contour overlaid, axial and sagittal; if the contour sits off the cord,
or the cord rises or falls along Z relative to anatomy, the registration is
wrong) and `cord_dice_per_slice` (per-Z Dice, where a few low slices point to an
HD95 outlier and uniformly middling Dice points to a global mis-registration).

## Limitations

Cord Dice cannot by itself certify the registration, for the reasons above; the
visual overlay is the real check, and an independent level- or intensity-based
metric is a planned addition. The nonlinear refinement is applied to the cord
segmentation rather than the EPI intensities, which insulates it from the
susceptibility-driven "twisted warp" failure that motivates avoiding nonlinear
warps of cord EPI (Vahdat et al.); but because each slice is optimized
independently, an under-segmented or near-circular cord can still admit
non-physical slice-to-slice deformation. Registration quality depends on the S3
and S2 cord segmentations it consumes.

## References

- De Leener, B., et al. (2017). SCT: Spinal Cord Toolbox, an open-source software
  for processing spinal cord MRI data. NeuroImage 145, 24–43.
- Eippert, F., et al. (2017). Investigating resting-state functional connectivity
  in the cervical spinal cord at 3T. NeuroImage.
- Kaptan, M., et al. (2023). Reliability of resting-state functional connectivity
  in the human spinal cord. NeuroImage 275, 120152.
- Wei, Z., et al. (2025). CoSpine: a simultaneous brain and spinal cord fMRI
  dataset. Scientific Data.

Running S6: see the [CLI reference](../reference/cli.md).

---
*Parameters reflect `policy/S6_func_to_anat_registration.yaml`, shipped with
SpinePrep; verified against the implementation and Kaptan et al. (2023)'s
published code on 2026-07-16. Audit: `.claude/specs/s6-algorithm-audit-v2.md`.*
