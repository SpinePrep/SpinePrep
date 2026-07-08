---
status: implemented
---

# S2 anat cordref — audit against dev principles

Step-local audit of S2 against the SpinePrep development principles
(`CLAUDE.md`). Implementation spec for the *algorithms* lives in
`private/SPEC/S2_anat_cordref.md`; this document records the
**principles-alignment** audit and the changes that came out of it.

## Objective

For each anat candidate per (subject, session), produce a native-space
cord reference (`cordref`) that anchors every downstream cord-fMRI
step. Outputs: cordref intensity + cord_dseg + canal_dseg + vertebral
labels + disc labels + (optional) rootlets + PAM50 warps.

## Literature backing

| Choice | Source |
|---|---|
| Cord seg via `sct_deepseg spinalcord` (contrast-agnostic) | SCT 7.0+ recommended default; replaces `sct_deepseg_sc -c …`. |
| Vertebral labeling via TotalSpineSeg | `sct_deepseg -task totalspineseg`; the only method that produces cord + canal + vertebrae + discs in one pass. |
| PAM50 template registration | De Leener 2018, NeuroImage — the cord-fMRI community standard template. |
| MEGRE synthesis (RMS over echoes, mean over runs) | CoSpi `spi03_anat_preproc.sh` recipe (cited in `policy/S2_anat_cordref.yaml:22-28`). |
| RPI orientation standardization | SCT convention; all PAM50 tools assume RPI input. |
| 60 mm cord cylinder crop | Cervical cord typical diameter + dilation margin. |

## Step-local truth metric (principle §3)

`metrics` block in qc.json per run carries:

- Descriptive (already present): `cord_length_mm`, `cord_volume_mm3`, `csa_mean_mm2` / `csa_min_mm2` / `csa_max_mm2`, `voxels`, `voxel_volume_mm3`.
- **Truth-relative (added this audit):**
  - `pam50_cord_dice` — 3D Dice between PAM50_cord warped into native
    space (via the run's `warp_template2anat`) and the native
    `cord_dseg`. A high Dice means PAM50 registration landed the cord
    where the native segmentation places it; a low Dice flags a
    geometrically-off registration even when the visual overlay "looks
    plausible". Gate in `qc_thresholds.pam50_cord_dice_pass_min`.
  - `n_vertebral_levels` — count of distinct vertebra labels detected
    by TotalSpineSeg (sanity that labeling didn't silently collapse).
  - `n_disc_levels` — same for disc labels.
  - `n_rootlet_labels` — number of distinct rootlet labels (when
    rootlets enabled). Should be ~16 (C1–T8 left + right).

## Diagnostic reportlets (principle §4)

Five PNGs, each diagnostic for a specific failure mode:

| Reportlet | What it shows | What failure looks like |
|---|---|---|
| `crop_box_sagittal` | Raw FOV sagittal with red box marking the 60 mm cord crop. | Crop box misaligned with cord ⇒ discovery seg failed. |
| `cordmask_montage` | Axial montage of cord seg overlaid on anat. | Missing/extra cord voxels ⇒ deepseg failed. |
| `totalspineseg_montage` | Sagittal view with vertebra + disc + canal labels colored. | Skipped vertebrae or wrong labels ⇒ labeling failed. |
| `rootlets_montage` | Axial montage with rootlet labels. | Few/no rootlets ⇒ rootlets failed (skipped if not eligible). |
| `pam50_reg_overlay` | PAM50 cord contour over native anat. | Contour off-cord ⇒ low `pam50_cord_dice`. |

## Decision log

| # | Choice | Rationale |
|---|---|---|
| 1 | Keep five reportlets — don't consolidate | Each diagnoses a distinct failure mode; consolidation would mix signals (principle §4) |
| 2 | Add `pam50_cord_dice` as the headline truth metric | Complements the visual overlay with a number; matches CoSpine/SCT convention for registration QC |
| 3 | Gate PAM50 Dice at 0.80 (PASS) / 0.60 (WARN) | Initial CoSpine-style band; retune on reg cohort before v1 lock |
| 4 | No change to algorithm defaults | All choices already cite literature; no churn warranted |
| 5 | `private/SPEC/S2_anat_cordref.md` stays as the implementation spec | This file is the *principles* audit; the implementation spec stays where it lives |

## Audit verdict per principle

| # | Principle | Verdict |
|---|---|---|
| 1 | Small dev cohort | ✅ 11-run reg set; 6 unique anat |
| 2 | Literature defaults | ✅ SCT 7.0+, TSS, PAM50, CoSpi MEGRE |
| 3 | Step-local truth metric | ✅ after this audit — `pam50_cord_dice` + label counts added |
| 4 | Diagnostic reportlet | ✅ 5 PNGs, each diagnostic |
| 5 | Visual QC validator | ✅ reportlets are designed for eyeballing |
| 6 | Lock and ship | ✅ versioned policy YAML + spec docs |
| 7 | No chain backtracking | ✅ only reads from S1 |
| 8 | Full cohort = deliverable | ✅ scales; ~5 min per anat |
| 9 | Reproducible | ✅ schema + policy + spec all versioned |
| 10 | Heterogeneity is the test | ✅ runs on 5 datasets, T1w/T2w/T2star modalities, with explicit MEGRE handling |

## Remaining gaps (acceptable / deferred)

- Per-vertebral-level Dice (not just one cord 3D Dice) would let you
  see where in the cord the registration breaks. Defer until needed —
  the global Dice + per-slice visual overlay covers the typical
  diagnostic need.
- TotalSpineSeg confidence map could be propagated as a per-vertebra
  quality score. TSS doesn't expose this cleanly; defer.
