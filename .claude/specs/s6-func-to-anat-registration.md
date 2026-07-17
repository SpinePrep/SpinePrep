---
status: implemented
---

# S6 func→anat registration — audit against dev principles

Step-local audit of S6 against the SpinePrep development principles
(`CLAUDE.md`). Implementation spec lives in `private/SPEC/S6_func_to_anat_registration.md`.

## Objective

For each BOLD run, register the distortion-corrected mean BOLD (S5
output) to the subject's anat cordref (S2 output), producing a forward
warp (BOLD→anat) and an inverse warp (anat→BOLD) usable by S7 (PAM50
normalization) and S8 (confound regression).

## Engine — CoSpi 3-stage cord recipe

```
sct_register_multimodal
  step=0 (initialisation)
  step=1: type=seg, algo=centermassrot   # bulk roll alignment
  step=2: type=seg, algo=columnwise      # per-slice scaling along Z
  step=3: type=seg, algo=bsplinesyn,iter=20,slicewise=1,metric=MeanSquares
```

This is SpinePrep's own seg-driven chain (CoSpi `spi06_1fov_reg.sh`), built
from SCT's standard registration primitives. It is NOT Kaptan 2023 verbatim:
their chain is 2 steps (centermass -> bsplinesyn, iter=3) registering
template->func directly; SCT's default is also 2 steps. columnwise and iter=20
are SpinePrep tuning. See s6-algorithm-audit-v2.md F1.
**centermassrot** does bulk axial roll alignment from cord center-of-
mass; **columnwise** handles cord cross-section variation along Z;
**bsplinesyn** with slicewise=1, MeanSquares, iter=20 does the final
nonlinear cord-localized warp.

## Literature backing

| Choice | Source |
|---|---|
| 3-stage centermassrot → columnwise → bsplinesyn | SpinePrep chain (CoSpi `spi06_1fov_reg.sh`); SCT primitives, not a published recipe verbatim |
| `type=seg` cord-seg cost (not intensity) | Cord cropped EPI has air-dominated intensity cost surface; seg-driven cost converges on cord |
| `slicewise=1` for bsplinesyn | Cord motion + distortion is z-localized (Eippert 2017) |
| MeanSquares cost on segs | Seg-to-seg matching; standard for binary masks |
| Cord pre-flight crop with `sct_crop_image -m anat_dseg -dilate` | CoSpi 1FOV recipe; restricts cost to cord region (no world-Z prealign needed) |
| Dice as headline metric | Cohen-Adad 2014 cord registration validation standard |
| HD95 / ASD as surface-distance complements to Dice | Mid-2010s segmentation-metric consensus; Dice can be high while boundary disagreement is large |
| Lower SyN-fallback Dice gate | When S5 used SyN (no fieldmap), the BOLD is geometrically less faithful → looser registration bar is realistic |

## Step-local truth metrics (principle §3)

| Metric | What it measures |
|---|---|
| `cord_dice` | 3D Dice between EPI cord (warped to anat) and anat cord_dseg. **Headline gate.** Mostly 0.85+ on cord-shimmed reg runs. |
| `cord_hd95_mm` | 95th-percentile Hausdorff distance — boundary-disagreement gauge. Dice can be 0.9+ while a few cord pixels are far off; HD95 catches this. |
| `cord_asd_mm` | Average symmetric surface distance — mean boundary disagreement (less outlier-sensitive than HD95). |
| `centerline_round_trip_med_vox` / `_max_vox` | Median / max round-trip drift of the cord centerline under forward∘inverse warp. Observability-only — bsplinesyn's forward and inverse are separately optimized so non-zero drift is intrinsic. |
| `mi_after` | Mutual information BOLD↔anat in registered space; legacy sanity. |

The HD95 / ASD pair is what makes S6 robust: a registration that
"looks fine" on Dice but has a 5 mm tail in HD95 is a problem.

## Diagnostic reportlets (principle §4)

| Reportlet | What it shows | What failure looks like |
|---|---|---|
| `bold_on_anat_axial` | Axial montage: BOLD intensity with anat cord contour overlay | Cord contour off-cord ⇒ low Dice |
| `bold_on_anat_sagittal` | Mid-sagittal slice: BOLD over anat with cord seg overlay | Cord rises/falls vs anat in Z ⇒ columnwise step failed |
| `cord_dice_per_slice` | Per-slice Dice bar chart | A few low-Dice slices ⇒ HD95 outlier; uniform mid-Dice ⇒ global mis-registration |

## Threshold rationale (`policy/S6_func_to_anat_registration.yaml`)

| Gate | Value | Source |
|---|---|---|
| PASS `pass_dice_min` | 0.85 | CoSpi-validated cord registration band |
| PASS `pass_dice_min_syn_fallback` | 0.80 | Looser bar when S5 used SyN fallback |
| WARN `warn_dice_min` | 0.65 | Below this on After ⇒ FAIL |
| FAIL `fail_dice_below` | 0.65 | Hard floor |
| PASS `pass_hd95_mm_max` | 4.0 | Realistic on cord-cropped EPI (~1mm in-plane, 3–4mm Z); EPISeg baseline 1.28±0.73 mm is seg-vs-truth on same image, not via warp |
| WARN `warn_hd95_mm_max` | 8.0 | Above ⇒ FAIL |
| Centerline round-trip thresholds | Permissive | Observability-only; bsplinesyn intrinsic non-zero drift even at Dice 0.95 |

## Audit verdict per principle

| # | Principle | Verdict |
|---|---|---|
| 1 | Small dev cohort | ✅ |
| 2 | Literature defaults | ✅ CoSpi 3-stage + Cohen-Adad 2014 metrics |
| 3 | Step-local truth metric | ✅ Dice + HD95 + ASD + centerline round-trip + MI |
| 4 | Diagnostic reportlet | ✅ axial overlay + sagittal overlay + per-slice Dice |
| 5 | Visual QC validator | ✅ |
| 6 | Lock and ship | ✅ policy w/ explicitly-documented thresholds (incl. SyN-fallback split) |
| 7 | No chain backtracking | ✅ consumes S2 + S5; S6 metrics are self-contained |
| 8 | Full cohort = deliverable | ✅ |
| 9 | Reproducible | ✅ schema + policy + spec |
| 10 | Heterogeneity is the test | ✅ — all 11 reg runs PASS even though they span 5 datasets + multiple anat modalities (T1w / T2w / T2star secondary cordref). |

## Decision: no code change

S6 already satisfies all 10 principles. The 11/11 PASS rate (Dice
0.85+ on most runs, lowest at 0.80 in the SyN-fallback regime) shows
the algorithm + thresholds work across the heterogeneity of the reg
cohort. No churn warranted (principle §6).

This audit doc captures:

- The CoSpi 3-stage rationale (often misremembered; documenting it
  here means future contributors don't change steps "for cleanness"
  without knowing what each step does).
- Why HD95 / ASD complement Dice — Dice alone misses boundary
  outliers.
- The SyN-fallback Dice gate split — looser bar when S5 already
  degraded.
- Centerline round-trip as observability, not gating.

## Remaining gaps (acceptable / deferred)

- Could compute per-vertebral-level Dice once vertebral labels are
  available in BOLD geometry (S7 emits PAM50 vertebral labels; would
  need to backproject through S6 inverse warp). Defer until a
  per-segment quality breakdown is shown to drive decisions.
- The `mi_after` metric is informative but not gating. Could be
  promoted to a soft-gate if a regression emerges where Dice passes
  but MI says the intensities don't agree. Not a current issue.
