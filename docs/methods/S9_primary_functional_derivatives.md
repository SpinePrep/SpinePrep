---
search:
  boost: 2
---

# S9: Primary functional derivatives

S9 finalizes the per-run functional outputs: the preprocessed BOLD in native
space, temporal-SNR maps, and a per-vertebral-level tSNR table, packaged so an
analyst can run a general linear model directly.

## What it does

S9 writes the motion- and distortion-corrected functional series as the primary
derivative, `desc-preproc_bold`, in native functional space. It does not high-pass
filter the series (the cosine basis from S8 provides that), does not regress out
confounds (that is the analyst's model, using the S8 table), and does not smooth
by default. It computes temporal-SNR maps and a per-vertebral-level tSNR table,
and it warps small 3D quality-control references into the PAM50 template for the
group dashboard.

The design is deliberately analysis-agnostic, matching fMRIPrep, which states it
"does not perform any denoising (e.g., spatial smoothing) itself" so as to remain
neutral to any downstream analysis.

## Smoothing is optional and off by default

Cord-aware smoothing along the straightened cord axis (`sct_smooth_spinalcord`) is
available but off by default. When enabled, it emits an additional
`desc-smoothed_bold` series with a σ = 1, 1, 5 mm kernel (right-left,
anterior-posterior, superior-inferior; FWHM ≈ 2.35 × 2.35 × 11.8 mm): light
in-plane smoothing preserves the cord cross-section while heavier
superior-inferior smoothing exploits the cord's columnar organization.

Smoothing is off by default because it is an analysis choice, not neutral
preprocessing, and an unusually consequential one in the cord. fMRIPrep does not
smooth. The Eippert lab does not smooth the cord in its primary pipeline and warns
that even a 2 mm kernel "should only be employed with great caution in the spinal
cord," because the dorsal and ventral horns lie millimetres apart, so smoothing
mixes exactly the signals an analyst wants to separate (Kaptan et al., 2023). The
field is split (CoSpine, Wei et al. 2025, smooths at 3 mm), which is why S9
exposes it as a knob rather than baking it in.

`smoothing.enabled`
: Emit an additional cord-aware smoothed series. Default `false`.

`smoothing.sigma_mm`
: Kernel standard deviations in mm (R-L, A-P, S-I) when enabled. Default
`[1.0, 1.0, 5.0]`.

## Template space

S9 does not resample the 4D BOLD into PAM50 by default. The cord field analyzes in
native space and warps the atlas back to native (Kaptan et al., 2023); a
template-resampled 4D cord series is an extra interpolation over
interpolation-fragile data that no one is meant to analyze, and it costs several
gigabytes per run. The useful template deliverables are the bidirectional warps
(from S7) and the PAM50 atlas already resampled into native space (from S7), which
let an analyst push their own first-level results to PAM50 for group inference.
Small 3D PAM50 references (temporal mean, tSNR) are still emitted for the group QC
dashboard.

`pam50_4d_output.enabled`
: Emit a convenience 4D BOLD resampled into PAM50 (not for primary analysis).
Default `false`.

## Inputs and outputs

```
derivatives/spineprep/sub-<id>/[ses-<id>/]func/
├── sub-<id>_..._desc-preproc_bold.nii.gz         # primary series, native, unsmoothed
├── sub-<id>_..._desc-smoothed_bold.nii.gz        # only when smoothing is enabled
├── sub-<id>_..._desc-preproc_funcref.nii.gz      # temporal mean
├── sub-<id>_..._desc-tsnr_native.nii.gz          # tSNR map
├── sub-<id>_..._space-PAM50_desc-tsnr.nii.gz     # 3D tSNR in PAM50 (group QC)
└── sub-<id>_..._desc-tsnr_per_level.tsv          # per-vertebral-level tSNR
```

## Quality control

The primary, always-on gate is the median in-cord temporal SNR, the signal-quality
floor that applies whether or not smoothing ran. When smoothing is enabled, two
further gates apply: the tSNR ratio before versus after smoothing (smoothing
should raise cord tSNR, not lower it) and the cord-mask Dice before versus after
(smoothing must not distort the cord segmentation), with a residual-FWHM check that
the achieved smoothness matches the requested kernel. With smoothing off, those
three do not apply, since there is no smoothing to assess.

The reviewer inspects the tSNR map and the per-vertebral-level tSNR reportlet.

## Limitations

The per-vertebral-level tSNR depends on S7's spinal-level atlas in native space; a
level with too few cord voxels is reported as empty rather than estimated.
Temporal SNR is a coarse signal-quality summary and does not by itself certify the
data for a given analysis.

## References

- De Leener, B., et al. (2017). SCT: Spinal Cord Toolbox. NeuroImage 145, 24–43.
- De Leener, B., et al. (2018). PAM50: unbiased multimodal template. NeuroImage
  165, 170–179.
- Esteban, O., et al. (2019). fMRIPrep: a robust preprocessing pipeline for
  functional MRI. Nature Methods 16, 111–116.
- Kaptan, M., et al. (2023). Reliability of resting-state functional connectivity
  in the human spinal cord. NeuroImage 275, 120152.
- Wei, Z., et al. (2025). CoSpine: a simultaneous brain and spinal cord fMRI
  dataset. Scientific Data.

Running S9: see the [CLI reference](../reference/cli.md).

---
*Parameters reflect `policy/S9_primary_functional_derivatives.yaml`, shipped with
SpinePrep; verified against the implementation on 2026-07-18.*
