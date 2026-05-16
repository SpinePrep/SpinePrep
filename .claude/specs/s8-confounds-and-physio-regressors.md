---
status: approved
supersedes: private/SPEC/S8_confounds_and_physio_regressors.md
---

# Scope Spec: S8 Confounds + Physio Regressors (Cord-Standard, post round-3 audit)

## Objective
Emit a BIDS-Derivatives `*_desc-confounds_timeseries.tsv` + JSON sidecar per BOLD run, containing motion + CSF (slicewise) + RETROICOR (slicewise) + cosine HP basis + optional SpinalCompCor families. S8 does NOT regress confounds out of BOLD — analyst owns that at S9.

## Constraints
- **Native func space only.** S8 reads `*_desc-undistorted_bold.nii.gz` (S5), uses S7's `*_desc-PAM50csf_mask.nii.gz` (native func), and S3's funccrop_mask. No 4D BOLD resampling.
- **Slicewise where physiology demands it.** CSF (1 per slice) + RETROICOR (4×2 cardiac + 4×2 respiratory + 16 interactions = 32 per slice in PNM, then cord-mean averaged within each slice). Motion + cosine stay scalar.
- **Cord-calibrated thresholds.** FD outlier ≥ 0.2 mm (Kaptan 2023). DVARS OR refRMS ≥ 3 SD above run mean (Kaptan/Dabbagh).
- **FSL PNM** as RETROICOR tool (already in env, no MATLAB).
- **SpinalCompCor off by default for v1** (`policy.spinalcompcor.enabled: false`). When enabled: 18 mm dilation noise ROI, mean-center + DCT-detrend per-voxel pre-PCA, 50 IAAFT surrogates, parallel-analysis component selection.
- **TSV flat-columned**, BIDS-Derivatives convention. Column naming: `<family>_<param>[_slice{NN}]`.
- **No regression**. Emit columns only.
- Per-dataset isolation: `logs/S8_confounds_and_physio_regressors/<dataset_key>/qc.json`.

## Deliverables
**Per-run derivatives** (`derivatives/spinalfmriprep/<dataset_key>/sub-XX/[ses-YY]/func/`):
- `*_desc-confounds_timeseries.tsv` — flat-column TSV.
- `*_desc-confounds_timeseries.json` — per-column metadata.

**Per-run work** (`work/S8_confounds_and_physio_regressors/<dataset_key>/<run_id>/`):
- `pnm/` — FSL PNM intermediates.
- `csf_slicewise.npy`, `motion.npy` — per-family caches.
- `spinalcompcor/` (if enabled) — surrogate eigenvalue matrix, PC singular values.
- `qc_metrics.json`.

**Reportlets** (`figures/`):
- `*_desc-S8_confound_columns.png` — table of columns by family + presence flag.
- `*_desc-S8_fd_dvars_outliers.png` — FD + DVARS + refRMS time series with outlier highlights.
- `*_desc-S8_csf_variance.png` — slicewise CSF variance distribution.
- `*_desc-S8_pnm_peaks.png` — cardiac + respiratory traces with detected peaks (when physio present).
- `*_desc-S8_correlation_heatmap.png` — Pearson correlation across the full confound matrix.

**Code**: `src/spinalfmriprep/steps/s8/` mirroring s6/s7 layout (`__init__`, `process`, `orchestrate`, `reportlets`).

**Policy + schema**: `policy/S8_confounds.yaml`, `schemas/qc_S8_confounds.schema.json`.

## Inputs
- S5: `*_desc-undistorted_bold.nii.gz`, `*_desc-undistorted_funcref.nii.gz`.
- S4 work tree: `S4_func_motion_correction/<run_id>/moco_params_x.nii.gz`, `_y.nii.gz` (slicewise 4D).
- S5 derivatives: `*_moco_params.tsv` (per-frame combined RMS, single column).
- S3 runs: `S3_func_init_and_crop/<run_id>/metrics/frame_metrics.tsv` (DVARS + ref_rms + outlier flag).
- S7: `*_desc-PAM50csf_mask.nii.gz` in native func.
- S3: `funccrop_mask` or S3 `func_ref_fast_seg_crop.nii.gz` for cord-mean RETROICOR averaging.
- BIDS source: `<bids_root>/<sub>/[<ses>]/func/*_physio.tsv.gz` + JSON sidecar.
- BIDS source: `*_bold.json` for SliceTiming.

## Success Criteria
- **PASS**: motion + CSF-slicewise + cosine + (RETROICOR when physio present) emit non-NaN columns; matrix condition number ≤ 1000; outlier fraction ≤ 20%.
- **WARN**: physio expected but unreadable → RETROICOR skipped; OR any slice has < 5 CSF voxels (drop that slice's CSF column with note); OR condition number 1000–10000; OR outlier fraction 20–40%.
- **FAIL**: motion or cosine missing; condition number > 10000; outlier fraction > 40%; TSV empty.

## Acceptance criteria (v1)
- All 5 v1_validation datasets emit per-run TSV + JSON.
- For physio-bearing datasets (ds005883 pain, ds005884 motor): RETROICOR columns present with plausible cardiac peak rate (50–120 bpm) and respiratory peak rate (8–30 cycles/min).
- Dashboard reportlets render per run.

## Next Steps
1. Mark old spec superseded (done in this PR).
2. Write `policy/S8_confounds.yaml`.
3. Write `schemas/qc_S8_confounds.schema.json`.
4. Scaffold `src/spinalfmriprep/steps/s8/`.
5. Implement process: motion → CSF slicewise → RETROICOR (FSL PNM) → cosine → SpinalCompCor (opt-in).
6. Implement orchestrate (per-dataset, S6/S7-style).
7. Implement reportlets (5 PNGs).
8. CLI + dashboard registry + chain script wiring.
9. Smoke test on pain dataset; iterate.

## Decision Log
| # | Choice | Rationale |
|---|--------|-----------|
| Q1 | CSF = slicewise top-20%-variance mean | Hemmerling 2025 SOTA. Heterogeneity in field (Kaptan = 1, CoSpi = 5×slices) — pick most recent peer-reviewed dedicated paper. |
| Q2 | RETROICOR via FSL PNM | No MATLAB dep; SCT-recommended; slicewise NIfTI EVs native. |
| Q3 | RETROICOR interactions ON (4×4=16) | Dabbagh 2024 standard cord recipe; 32 total RETROICOR regressors. |
| Q4 | Outliers via S3-precomputed DVARS + refRMS at 3 SD | Already in S3 frame_metrics.tsv; avoids re-running fsl_motion_outliers. |
| Q5 | FD threshold 0.2 mm | Cord 3σ above group mean per Mohammed 2020 / Kaptan 2023. |
| Q6 | TSV flat-columned slicewise | BIDS convention; Nilearn load_confounds compatible. |
| Q7 | SpinalCompCor off by default v1 | Hemmerling says augments not replaces; needs validation; MATLAB-only ref impl forces Python port. |
| Q8 | Pre-PCA mean-center + DCT-detrend | fMRIPrep convention; guards against trivial drift PCs. |
| Q9 | CSF mask = S7 PAM50csf in native | Already produced; S2 canal-cord requires extra warp (v2). |
