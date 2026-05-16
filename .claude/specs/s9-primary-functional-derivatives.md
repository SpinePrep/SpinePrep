---
status: approved
supersedes: private/SPEC/S9_primary_functional_derivatives.md
---

# Scope Spec: S9 Primary Functional Derivatives v2

## Objective
Emit the final preprocessed 4D BOLD outputs (native + PAM50, smoothed; un-smoothed preserved) plus tSNR references and per-vertebral-level tSNR — the last preproc deliverable before analyst-side GLM.

## Constraints
- **Cord-aware smoothing is primary.** Use `sct_smooth_spinalcord` with σ in mm (R-L, A-P, S-I). Straightens cord, applies anisotropic Gaussian, de-straightens. Cord-restricted via S6's cord seg in BOLD geometry.
- **No 4D BOLD ever resampled into PAM50 by S7.** S9 *produces* the PAM50 4D BOLD itself by applying S7's composite `from-bold_to-PAM50` warp to the native smoothed BOLD. (The original spec's input ref to a `_space-PAM50_desc-preproc_bold.nii.gz` from S7 was stale; S7 never emits one.)
- **Smooth in native first, then warp to PAM50.** `sct_smooth_spinalcord` requires native geometry (cord-straightening is meaningless in PAM50). Two resamplings, but each in well-conditioned space.
- **No high-pass on the BOLD itself.** Cosine basis from S8 lets the analyst's GLM do high-pass.
- **Preserve the un-smoothed BOLD** in both native and PAM50 spaces — analyst chooses which to feed the GLM.
- **Per-vertebral-level tSNR** as a cord-specific deliverable: aggregate tSNR within each level mask from S7's PAM50 spinal_levels in native func.
- **No regression of confounds** at S9 — S8 emitted them, S9 emits the matrix-ready BOLD.
- Per-dataset isolation: `logs/S9_primary_functional_derivatives/<dataset_key>/qc.json`.

## Deliverables

**Per-run derivatives** (`derivatives/spinalfmriprep/<dataset_key>/sub-XX/[ses-YY]/func/`):
- `*_desc-preproc_bold.nii.gz` — native, smoothed (FINAL native BOLD for GLM).
- `*_desc-unsmoothed_bold.nii.gz` — native, unsmoothed (S5 undistorted, repacked under canonical name).
- `*_desc-preproc_funcref.nii.gz` — temporal mean of native smoothed.
- `*_desc-tsnr_native.nii.gz` — tSNR map of native smoothed BOLD.
- `*_space-PAM50_desc-preproc_bold.nii.gz` — PAM50, smoothed (FINAL PAM50 BOLD).
- `*_space-PAM50_desc-unsmoothed_bold.nii.gz` — PAM50, unsmoothed (warped from native unsmoothed).
- `*_space-PAM50_desc-preproc_funcref.nii.gz` — PAM50 temporal mean.
- `*_space-PAM50_desc-tsnr.nii.gz` — tSNR map in PAM50 space.
- `*_desc-tsnr_per_level.tsv` — per-vertebral-level tSNR (level, mean, std, n_voxels).

**Per-run work** (`work/S9_primary_functional_derivatives/<dataset_key>/<run_id>/`):
- `straightened/` — sct_smooth intermediates.
- `qc_metrics.json` — provenance + tSNR + FWHM verification.

**Reportlets** (`figures/`):
- `*_desc-S9_smoothed_vs_unsmoothed_axial.png` — 9-slice montage, before/after.
- `*_desc-S9_tsnr_map_axial.png` — 9-slice tSNR montage (native).
- `*_desc-S9_tsnr_per_level.png` — bar chart of tSNR per PAM50 vertebral level.
- `*_desc-S9_smoothness_summary.png` — measured vs requested FWHM bars.

**Code**: `src/spinalfmriprep/steps/s9/` mirroring s7/s8 layout (`__init__`, `process`, `orchestrate`, `reportlets`).

**Policy + schema**: `policy/S9_primary_functional_derivatives.yaml`, `schemas/qc_S9_primary_functional_derivatives.schema.json`.

**Spec housekeeping**: mark `private/SPEC/S9_primary_functional_derivatives.md` status → `superseded`.

## Inputs
- **S5**: `*_desc-undistorted_bold.nii.gz` (native, moco-corrected, distortion-corrected 4D).
- **S3**: `runs/S3_func_init_and_crop/<run_id>/init/localize/func_ref_fast_seg_crop.nii.gz` — cord seg in BOLD geometry (for `sct_smooth_spinalcord -s`).
- **S7**: `*_from-bold_to-PAM50_xfm.nii.gz` (composite warp), `*_desc-PAM50spinallevels.nii.gz` (per-level mask in native func).
- **PAM50**: `$SCT_DIR/data/PAM50/template/PAM50_t2s.nii.gz` (PAM50 output grid reference).
- **Policy**: `policy/S9_primary_functional_derivatives.yaml`.

## Success Criteria
- **PASS**: tSNR ratio (post/pre) ≥ 1.5 (cord mask median); residual FWHM in-plane within ±0.5 mm of requested; cord-mask Dice between pre- and post-smoothed cord_dseg ≥ 0.95; per-level tSNR computed for ≥ 80% of cord-bearing levels.
- **WARN**: tSNR ratio 1.2–1.5; residual FWHM within ±1.0 mm; cord Dice 0.85–0.95.
- **FAIL**: tSNR ratio < 1.0 (smoothing harmed tSNR — upstream error); cord Dice < 0.85; sct_smooth_spinalcord non-zero exit.

## Acceptance criteria (v1)
- All 5 v1_validation datasets emit per-run S9 qc.json with status.
- Median in-cord tSNR (post-smoothing) ≥ 5 (CoSpine 2025 published baseline).
- tSNR ratio ≥ 1.5 in ≥ 80% of runs.
- Residual FWHM in-plane is requested ± 0.5 mm; through-slice residual FWHM is the requested S-I FWHM ± 1.0 mm.
- Dashboard renders all 4 reportlets per run.

## Next Steps
1. Mark `private/SPEC/S9_primary_functional_derivatives.md` superseded (done in this PR).
2. Write `policy/S9_primary_functional_derivatives.yaml` (sigma defaults, qc thresholds, method toggle).
3. Write `schemas/qc_S9_primary_functional_derivatives.schema.json`.
4. Scaffold `src/spinalfmriprep/steps/s9/` (`__init__`, `process`, `orchestrate`, `reportlets`).
5. Implement:
   - `_run_sct_smooth` — invoke `sct_smooth_spinalcord -i undistorted_bold -s cord_seg -smooth σ -o desc-preproc_bold`.
   - `_warp_to_pam50_4d` — `sct_apply_transfo -i {smoothed,unsmoothed}_bold -d PAM50_t2s -w from-bold_to-PAM50_xfm -x spline`.
   - `_compute_tsnr` — mean / std along time, per-voxel; mask by cord; save NIfTI.
   - `_per_level_tsnr` — aggregate tSNR within each `PAM50_spinal_levels` value; emit TSV.
   - `_estimate_residual_fwhm` — autocorrelation-based FWHM estimate in cord mask (one number per axis).
   - QC + reportlets.
6. CLI + dashboard registry + chain script wiring (S9 step).
7. Smoke test on pain dataset; iterate.
8. Run full chain S2→S9 on 5 reg datasets; verify all PASS/WARN.

## Decision Log
| Q# | Choice | Rationale |
|----|--------|-----------|
| Q1 | A — `sct_smooth_spinalcord` (cord-aware) | Balgrist/CoSpi validated; Eippert 2017 anisotropic principle; SCT-blessed. |
| Q2 | A — σ = 1, 1, 5 mm | CoSpi `spi14_2_smooth.sh` exact value; FWHM ≈ 2.35 × 2.35 × 11.8 mm; heavy S-I exploits cord-axis signal repetition. |
| Q3 | A — Native-smooth, then warp to PAM50 | Cord-straightening requires native geometry. Two resamplings each well-conditioned. Matches CoSpi convention. |

## Out of scope (deferred)
- Anatomically-constrained graph-pruned smoothing (Lien 2026 cord-port — not validated for cord yet).
- One-shot composite resampling (moco+distortion+S6+S7 into single ITK transform) — incompatible with cord-aware smoothing.
- Temporal smoothing.
- Confound regression (analyst's job at S10/GLM).
- Subject-specific kernel adaptation (e.g., per-vertebral-level σ).

## References
- CoSpi reference: `/mnt/hdd2/P1_CoSpi/scripts_pilot_motor/spi14_2_smooth.sh` (σ = 1, 1, 5 via sct_smooth_spinalcord, cord-restricted).
- SCT — `sct_smooth_spinalcord` documentation: σ in mm, R-L/A-P/S-I order, straighten-smooth-destraighten pipeline.
- Eippert et al. 2017 — anisotropic smoothing principle (small in-plane, larger S-I).
- Brooks et al. 2008 — physiological noise modelling foundational; anisotropic FWHM 1.5×1.5×6 mm originator.
- CoSpine 2025 (Nature Sci Data, paywalled) — modern cord fMRI database; representative alternative recipe.
- Kaptan et al. 2023 / Dabbagh et al. 2024 — cord fMRI confound + smoothing conventions.
- fMRIPrep — one-shot resampling pattern (does not apply here because cord-aware smoothing is not a separable convolution).
