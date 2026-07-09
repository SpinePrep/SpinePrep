---
search:
  boost: 2
---

# S5: Distortion Correction

**Step Code:** `S5_func_distortion_correction`
**Depends on:** S4 (Motion Correction), S2 (Anatomical cord reference)
**Required by:** S6 (Registration)

---

## Purpose

S5 corrects the geometric distortion that echo-planar imaging (EPI) suffers near
the spinal cord. Differences in magnetic susceptibility between bone, cord, CSF
and air stretch and compress the image along the phase-encode direction — for
cervical cord acquisitions this is the anterior-posterior (A-P) axis. Left
uncorrected, the cord in the functional image does not sit where it does in the
anatomy, which corrupts every downstream registration.

S5 works on the motion-corrected mean functional image from S4 and produces an
undistorted mean image (and the matching 4D-eligible reference) for S6.

---

## Algorithm Overview

S5 picks one correction mode per run, automatically, from what the dataset
provides. The order below is the field-standard susceptibility-distortion ladder
(fMRIPrep SDCFlows; Andersson 2003):

| Mode | When it is used | Engine |
|------|-----------------|--------|
| **topup** | A reversed phase-encode EPI pair is available | FSL `topup` + `applytopup` |
| **syn** | No fieldmap — anatomy-driven fallback | ANTs `antsRegistration` (SyN) |

!!! note "No GRE fieldmap (FUGUE) path in v1"
    A third mode using a gradient-echo phase-difference fieldmap (FSL `fugue`)
    was removed in v1: no dataset in the validation cohort ships GRE fieldmaps,
    so GRE-only data falls through to the SyN fallback. This gap versus fMRIPrep
    is recorded honestly rather than stubbed.

---

## S5.A: topup mode

When the acquisition includes a spin-echo EPI pair with opposite phase-encode
directions (for example A-P and P-A), FSL `topup` estimates the off-resonance
field from the pair and `applytopup` unwarps the BOLD.

- **Config:** `b02b0_1.cnf`. This is FSL's tolerance configuration
  (`subsamp=1` throughout). The default `b02b0.cnf` uses a `subsamp=2` first
  iteration that requires even image dimensions; cord-cropped BOLD typically has
  odd in-plane and Z dimensions, so the default rejects it.
- **Apply method:** `jac` (Jacobian intensity modulation), matching the FSL and
  fMRIPrep default. `lsr` (least-squares) is not used because it needs both PE
  directions of the BOLD itself, which we do not have.
- **Total readout time** comes from the BIDS `TotalReadoutTime` field, with an
  `EffectiveEchoSpacing × (ReconMatrixPE − 1)` fallback.

The topup code path is exercised by unit tests. It is not integration-tested on
the validation cohort, because none of those datasets ship reversed-PE pairs.

---

## S5.B: SyN fallback mode

With no fieldmap, S5 falls back to an anatomy-driven nonlinear registration of
the mean BOLD to the subject's T2w anatomy, restricted to the cord region. This
follows the fMRIPrep SDCFlows experimental SyN convention (Avants 2008; Studholme
1999 for the mutual-information cost).

- **Transform:** `SyN[0.1,3,0]` (light symmetric normalization).
- **Metric:** mutual information, 32 bins (cross-modal BOLD to T2w).
- **Shrink / smoothing:** `4x2x1` / `2x1x0vox` (3-level pyramid).
- **Convergence:** `40x20x0` — effectively a 2-level run; A-P distortion is low
  spatial frequency and converges at the coarser levels. fMRIPrep's brain SyN
  uses `100x70x50` by comparison.
- **Resampling:** `LanczosWindowedSinc`, which preserves T2*-weighted contrast.
- The deformation is deliberately **not** restricted to the phase-encode axis; a
  cord-only, PE-restricted attempt was tried and reverted after it starved SyN of
  signal on the cohort.

Because a SyN correction has no fieldmap ground truth, it is treated as lower
confidence than topup regardless of how good its geometry score looks (see
Gates).

---

## Step Metric and QC

The step-local truth metric is the CoSpine geometric pair (Wei et al., Sci Data
2025), measured Before versus After correction:

- **A-P cord-centerline displacement** (headline): the per-slice distance, in mm,
  between the EPI cord centroid and the anatomy cord centroid along the A-P axis.
  Good correction drives this toward zero (CoSpine reports post-topup ≈ 0.13 mm
  versus ≈ 2.73 mm uncorrected). The per-slice Y(z) trace is Savitzky-Golay
  smoothed (window 5, polynomial order 2) to suppress ≈ 0.3 mm finite-voxel
  centroid jitter without flattening real distortion variation.
- **Cord Dice** — 3D pooled and per-slice overlap between the EPI cord
  segmentation (`sct_deepseg_sc` on the mean BOLD) and the anatomy cord in the
  BOLD grid.

The anatomy is brought into the BOLD grid for this comparison with an
`sct_register_multimodal` cord-segmentation-driven rigid step. This deviates from
CoSpine's intensity-driven FLIRT 6-DOF, which diverges on cord-cropped inputs
whose intensity cost is dominated by surrounding air; the same seg-driven recipe
S6 uses is more robust here. This deviation is documented, not claimed as
CoSpine-standard.

Only cervical cord slices count toward the metric: slices with vertebral level
above T1 (`cord_roi_max_level: 8`) are excluded, because the lung-adjacent
thoracic cord is uncorrectable without a fieldmap and would unfairly drag the run
score. Slices with fewer than 5 cord voxels are dropped as sampling-dominated.

---

## Diagnostic Reportlets

S5 emits three PNGs. The first two are the quantitative per-slice truth metrics
on a black background (trace on the left, summary bar on the right).

- **`slice_displacement`** — per-Z A-P displacement, Before (grey) and After
  (blue), with a mean ± SD bar. Title encodes the mode and the change in mean.
- **`cord_dice_per_slice`** — per-Z 2D cord Dice, with a mean-Dice bar and the 3D
  pooled Dice in the title.
- **`distortion_effectiveness`** — Before versus After mean BOLD with the anat
  cord contour overlaid, so a human can see the cord move into place.

One image should answer whether correction worked, by how much, and where in the
cord it worked best.

---

## Outputs

```
derivatives/spineprep/{dataset}/sub-{id}/func/
├── sub-{id}_..._desc-undistorted_bold.nii.gz       # distortion-corrected BOLD
└── sub-{id}_..._desc-undistorted_funcref.nii.gz    # corrected mean reference

derivatives/spineprep/{dataset}/sub-{id}/figures/
├── sub-{id}_..._desc-S5_slice_displacement.png
├── sub-{id}_..._desc-S5_cord_dice_per_slice.png
└── sub-{id}_..._desc-S5_distortion_effectiveness.png
```

---

## QC Status Logic

```
status = FAIL if:
  - cord Dice (After) < warn_dice_min (0.30), OR
  - A-P displacement (After) > warn_displacement_max_mm (2.0 mm)   [topup mode]
  - legacy MI drops by more than fail_mi_max_drop_pct (10%)

status = WARN if:
  - cord Dice (After) below pass_dice_min (0.50) but above the warn floor, OR
  - displacement above pass_displacement_max_mm (1.0 mm), OR
  - a SyN-fallback run exceeds the displacement ceiling while its cord Dice still
    passes the warn floor — flagged "distortion-limited" and kept, because the
    limitation is acquisition-side (request a reverse-PE pair), not a pipeline
    failure (syn_displacement_distortion_limited: true)

status = PASS otherwise
```

On the 11-run validation cohort, which ships no fieldmaps, all runs use the SyN
fallback: most land WARN with good geometry (Dice 0.55-0.86, displacement
0.40-1.17 mm), and two handgrasp runs FAIL on genuine A-P mismatch (Dice
0.07-0.18, displacement 3.6-5.0 mm) — a real geometric problem the metric
correctly surfaces.

---

## References

1.  **Susceptibility distortion (topup):** Andersson, Skare, Ashburner.
    *NeuroImage* 20(2):870-888 (2003).
2.  **SyN registration:** Avants et al. *Medical Image Analysis* 12(1):26-41 (2008).
3.  **Mutual information cost:** Studholme et al. *Pattern Recognition* 32(1):71-86 (1999).
4.  **CoSpine geometric metrics:** Wei et al. *Scientific Data* (2025) — slice-by-slice
    A-P displacement; spinal cord DSC.
5.  **Savitzky-Golay smoothing:** Savitzky & Golay. *Analytical Chemistry* 36(8):1627-1639 (1964).

---

*Last updated: July 2026*
