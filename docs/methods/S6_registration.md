---
search:
  boost: 2
---

# S6: Registration

**Step Code:** `S6_func_to_anat_registration`
**Depends on:** S5 (Distortion Correction), S2 (Anatomical cord reference)
**Required by:** S7 (Normalization), S8 (Confounds)

---

## Purpose

S6 aligns the functional data to the subject's own anatomy. It registers the
distortion-corrected mean BOLD from S5 to the anatomical cord reference from S2,
and stores the transform in both directions:

- a **forward** warp (BOLD to anat), and
- an **inverse** warp (anat to BOLD).

S7 (PAM50 template normalization) and S8 (confound extraction) reuse these warps
rather than recomputing them. The registration is intentionally driven by the
cord segmentation, not by image intensity, because a cord-cropped EPI has an
intensity cost surface dominated by the air surrounding the cord — an
intensity-only registration diverges on this geometry.

---

## Algorithm

S6 is a single `sct_register_multimodal` call with a three-stage,
cord-segmentation-driven parameter string. This is the cord-fMRI field-standard
recipe (CoSpi 1FOV/2FOV; also used under Kaptan 2023 SCT conventions). The
functional image is the moving image and the anatomy is the destination
(`-i funcref -d anat`) — fewer slices on the destination is faster and avoids
resampling the BOLD onto the anat grid.

Before registration, the anatomy is cropped to a dilated cord region
(`sct_crop_image -m anat_seg -dilate 10x10x10`), which restricts the cost surface
to cord context.

| Step | Algorithm | Role |
|------|-----------|------|
| 1 | `centermassrot` | Bulk slicewise center-of-mass alignment plus rotation; needed for oblique cord acquisitions. |
| 2 | `columnwise` | Right-left scaling and A-P deformation along the cord axis; handles cross-section change along Z. |
| 3 | `bsplinesyn` (iter 20) | Slicewise nonlinear B-spline refinement. |

All three stages use `type=seg` (cord segmentation as the cost), the MeanSquares
metric, and `slicewise=1`. Resampling uses spline interpolation.

---

## Step Metric and QC

The step-local truth metric is **3D cord Dice** — the overlap between the EPI
cord (warped into anat space) and the anatomy cord segmentation. This is the
standard cord-registration validation measure (Cohen-Adad 2014). Three further
metrics support it:

- **HD95** (95th-percentile Hausdorff distance) — boundary disagreement. Dice can
  be high while a few cord voxels are far off; HD95 catches that. It is quantized
  to the EPI slice thickness (≈ 5 mm) and sensitive to single end-slice
  segmentation dropout, so it is treated as observability-only (it can soft-WARN
  but never FAILs).
- **ASD** (average symmetric surface distance) — mean boundary disagreement, less
  outlier-sensitive than HD95.
- **Centerline round-trip drift** — how far the cord centerline moves under
  forward-then-inverse warp. Because `bsplinesyn` optimizes forward and inverse
  separately, some drift is intrinsic even at Dice 0.95; this is
  observability-only, with permissive thresholds.
- **`mi_after`** — mutual information between BOLD and anat in registered space; a
  legacy sanity check, not a gate.

---

## Diagnostic Reportlets

- **`bold_on_anat`** — the BOLD shown against the anatomy with the cord contour
  overlaid, in axial and sagittal views. If the cord contour sits off the cord,
  Dice is low; if the cord rises or falls relative to the anatomy along Z, the
  columnwise stage failed.
- **`cord_dice_per_slice`** — a per-Z Dice bar chart, color-coded by
  PASS/WARN/FAIL. A few low-Dice slices point to an HD95 outlier; uniformly
  middling Dice points to a global mis-registration.

---

## Outputs

```
derivatives/spineprep/{dataset}/sub-{id}/func/
├── sub-{id}_..._from-bold_to-anat_xfm.nii.gz     # forward warp (+ .json sidecar)
├── sub-{id}_..._from-anat_to-bold_xfm.nii.gz     # inverse warp
├── sub-{id}_..._space-anat_desc-mean_bold.nii.gz # mean BOLD in anat geometry (QC)
└── sub-{id}_..._desc-tsnr_funcref.nii.gz         # tSNR reference (used by S7)

derivatives/spineprep/{dataset}/sub-{id}/figures/
├── sub-{id}_..._desc-S6_bold_on_anat.png
└── sub-{id}_..._desc-S6_cord_dice_per_slice.png
```

The forward-warp JSON sidecar carries the reproducibility receipt: policy SHA,
source path, registration method and parameters, and software versions.

---

## QC Status Logic

```
status = PASS if:
  - cord Dice >= pass_dice_min (0.85), OR
  - cord Dice >= pass_dice_min_syn_fallback (0.80) when S5 used the SyN fallback
    (a looser bar is realistic — a no-fieldmap BOLD is geometrically less faithful)

status = FAIL if:
  - cord Dice < fail_dice_below (0.65)

status = WARN otherwise (Dice in [0.65, pass gate))
```

HD95 and the centerline round-trip are reported but do not FAIL a run. On the
11-run validation cohort all runs PASS, with Dice 0.89-0.97 on most datasets and
a floor of 0.80 in the SyN-fallback regime.

---

## References

1.  **SCT registration:** De Leener et al. *NeuroImage* 145:24-43 (2017).
2.  **Cord registration validation (Dice):** Cohen-Adad et al. (2014).
3.  **Cord resting-state / SCT conventions:** Kaptan et al. *NeuroImage* (2023).
4.  **CoSpine database:** Wei et al. *Scientific Data* (2025).

---

*Last updated: July 2026*
