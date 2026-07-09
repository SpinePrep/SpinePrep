---
search:
  boost: 2
---

# S7: Normalization

**Step Code:** `S7_template_normalization`
**Depends on:** S2 (anat-to-PAM50 warps), S6 (BOLD-to-anat warps), S5 (functional reference)
**Required by:** S8 (Confounds), S9 (Functional Derivatives), S10 (QC & Release)

---

## Purpose

S7 links each functional run to the PAM50 spinal cord template (De Leener 2018),
so that template masks and atlases can be brought into the run's own space and so
that group analysis has a common coordinate system. It does this by **composing
warps**, not by resampling the data:

- It fuses S2's anat-to-PAM50 warp with S6's BOLD-to-anat warp into a single
  composite BOLD-to-PAM50 transform (and its inverse).
- It uses the inverse to pull the PAM50 cord, tissue masks and level atlas into
  native functional space.

!!! note "The 4D BOLD is never resampled into PAM50"
    The per-subject GLM stays in native functional space, matching SCT
    `batch_processing.sh`, the CoSpi lineage, and Eippert 2017. Resampling 4D BOLD
    into template space would cost signal-to-noise and disk for no per-subject
    benefit. Only S9 pushes contrast/statistic maps to PAM50 for group inference.

S7 trusts S2's anat-to-PAM50 warp as the single source of truth for the
rootlet-versus-disc registration decision; it does not redo that step.

---

## Algorithm

1. **Compose warps.** The S2 (anat↔PAM50) and S6 (BOLD↔anat) warps are
   concatenated (`sct_concat_transfo`) into the composite BOLD↔PAM50 transform.
2. **Optional EPI-level refinement (disabled by default).** A second
   `sct_register_multimodal` pass against the functional reference, initialised
   from the composed warp, is supported but off by default (see below). Its
   reference is `PAM50_t2s`, the best contrast match for T2*-weighted BOLD.
3. **Warp the atlas to native space.** `sct_warp_template -a 1` brings the full
   PAM50 pack into native functional space: cord, CSF, WM and GM masks plus the
   spinal-level atlas.

!!! note "Refinement is off by default"
    The SCT `batch_processing.sh` fMRI block includes a refinement pass; S7
    disables it because it added no information over S6's already-thorough
    cord-driven registration and, on the pain dataset, dropped cord Dice from 0.82
    (compose-only) to 0.68. When enabled, the pass runs `slicereg` (seg,
    MeanSquares, smooth 2) then `bsplinesyn` (image, MeanSquares, iter 5, gradStep
    0.5) — the SCT recipe verbatim. Set `refinement.enable: true` to opt in.

This is a cervical pipeline: PAM50 coverage is used for levels C1-T1. The shipped
spinal-level atlas spans the whole column, but only the cervical levels are used
in practice.

---

## Step Metric and QC

The step-local truth metric is **cord Dice in native functional space** — the
overlap between the PAM50 cord (warped through the composite transform into native
space) and the S6 cord segmentation. It tests whether the composite
S2∘S6-and-refine warp actually lands the template cord on the functional cord
(Cohen-Adad 2014).

The primary gate is the **median per-level cord Dice**, computed level by level
along the cord. This is deliberately coverage-independent: a brain-plus-cord
acquisition images only a few cervical levels, which caps whole-volume overlap
near 0.84 even for a perfect registration, so a per-level median is the fair
measure of registration quality where the cord is actually present. The
whole-volume cord Dice is kept as a legacy fallback and observability value for
when per-level Dice is unavailable.

A cord-restricted forward-then-inverse round-trip drift is also reported, as
observability only — `bsplinesyn` optimizes forward and inverse separately, so
some drift is intrinsic even at high Dice.

---

## Diagnostic Reportlets

- **`pam50_on_func`** — the functional reference with the warped PAM50 cord
  contour overlaid, in sagittal and axial views. This is the direct visual check
  that the template cord lands on the functional cord.
- **`cord_dice_per_level`** — a per-vertebral-level cord Dice bar chart, colored
  by the PASS/WARN bands. A single low level flags a broken edge slice; uniformly
  low bars flag a global composition problem.

---

## Outputs

```
derivatives/spineprep/{dataset}/sub-{id}/func/
├── sub-{id}_..._from-bold_to-PAM50_xfm.nii.gz    # composite warp (+ .json sidecar)
├── sub-{id}_..._from-PAM50_to-bold_xfm.nii.gz    # composite inverse
├── sub-{id}_..._space-PAM50_desc-funcref.nii.gz  # funcref in PAM50 (QC overlay only)
├── sub-{id}_..._desc-PAM50cord_mask.nii.gz       # PAM50 cord in native func
├── sub-{id}_..._desc-PAM50csf_mask.nii.gz        # + wm / gm masks
└── sub-{id}_..._desc-PAM50spinallevels.nii.gz    # spinal-level atlas in native func

derivatives/spineprep/{dataset}/sub-{id}/figures/
├── sub-{id}_..._desc-S7_pam50_on_func.png
└── sub-{id}_..._desc-S7_cord_dice_per_level.png
```

The warps are stored as SCT-native displacement fields (`.nii.gz`), matching the
S2 and S6 convention, with a JSON sidecar carrying the reproducibility receipt.

---

## QC Status Logic

```
status = PASS if:
  - median per-level cord Dice >= per_level_pass_min (0.90)
    (fallback when per-level Dice is unavailable: whole-volume Dice >= 0.80)

status = WARN if:
  - median per-level cord Dice below the PASS gate but not failing, OR
  - any single level Dice < per_level_broken_below (0.50) — that level is excluded

status = FAIL if:
  - whole-volume cord Dice < fail_dice_below (0.65), OR
  - sct_register_multimodal exits non-zero
```

On the 11-run validation cohort, S7 lands 10 PASS and 1 WARN; the single WARN is a
genuinely borderline run (Dice 0.797 against the 0.80 whole-volume gate) rather
than a failure — the metric is calibrated correctly. All runs ran with refinement
disabled.

---

## References

1.  **PAM50 template:** De Leener et al. *NeuroImage* 165:170-179 (2018).
2.  **Native-GLM convention:** Eippert et al. (2017).
3.  **Cord registration validation (Dice):** Cohen-Adad et al. (2014).
4.  **Rootlets-based PAM50 registration:** Valošek et al. (2025).
5.  **SCT `batch_processing.sh` fMRI block** — canonical refinement recipe.

---

*Last updated: July 2026*
