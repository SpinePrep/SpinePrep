---
status: approved
supersedes: private/SPEC/S10_roi_timeseries_and_reliability.md
---

# Scope Spec: S10 ROI Timeseries + Connectivity + Reliability v2

## Objective
Emit per-run BIDS-Derivatives ROI timeseries TSVs + ROI×ROI connectivity matrices (Pearson + partial, raw + Fisher-z) for three PAM50-derived ROI catalogs, plus per-subject reliability summary (ICC(3,1) + spatial Dice) when multi-session, and a `_summary.json` enabling group-level aggregation at S11 without re-touching 4D BOLD.

## Constraints
- **Native func space extraction** using S7's `*_desc-PAM50spinallevels.nii.gz` already in native + PAM50 horn atlases warped on demand via S7's saved `from-PAM50_to-bold_xfm.nii.gz`. No 4D BOLD in PAM50 (S9 deliberately doesn't emit it).
- **Tool**: Nilearn `NiftiMapsMasker` for probabilistic horn atlases; `NiftiLabelsMasker` for discrete level atlases; `ConnectivityMeasure` for Pearson + partial; hand-rolled ICC(3,1) (no `pingouin` dep) + Dice.
- **PAM50 fact-check (round-3 verified, label values from local SCT 7.x)**:
  - `PAM50_levels.nii.gz` = VERTEBRAL, discrete labels **1–20** (C1=1 … C7=7, T1=8 … T12=19, L1=20).
  - `PAM50_spinal_levels.nii.gz` = SPINAL SEGMENTAL, discrete labels **1–30** (C1=1 … C8=8, T1=9 … T12=20, L1=21 … L5=25, S1=26 … S5=30).
  - GM horns are PROBABILISTIC files in `atlas/`: 30 = left ventral, 31 = right ventral, 32/33 = intermediate zones, 34 = left dorsal, 35 = right dorsal.
  - Kaptan-2023's "C5–C8" = labels 5–8 in `PAM50_spinal_levels` (NOT vertebral).
- **Reliability metric is ICC(3,1)** (two-way mixed effects, single rater, consistency) per Kaptan 2023 cord convention. NOT ICC(2,1).
- **Confound regression order**: regress confounds BEFORE correlation (Kaptan 2023 / Nilearn standard). Done inside `NiftiMapsMasker`/`NiftiLabelsMasker` via `confounds=` arg.
- **Three confound modes**: `none` (raw timeseries), `s8_default` (motion + CSF-slicewise + cosine + outliers + RETROICOR when present + SpinalCompCor). Default: emit BOTH.
- **Bandpass 0.01–0.1 Hz** applied via masker's `high_pass`/`low_pass` (resting-state convention; configurable for task data).
- **Connectivity types**: Pearson (correlation) + partial correlation (Ledoit-Wolf shrinkage when nv < nROI). Both emitted.
- **Min-voxel guards**: ROI skipped if total voxels < `min_voxels_per_roi` (default 10). Per-slice analysis (if enabled) skips slices with < 3 voxels.
- **Per-dataset ROI catalog** depends on cord coverage (Balgrist 11-slice covers ~3 spinal segments; OpenNeuro 35-slice covers ~8). Emit ROIs only when present in the BOLD FOV.
- **No statistical modelling** beyond ICC + correlation. Group-level outputs are S11's job.
- **No regression of confounds out of BOLD itself** — only the TSV timeseries are confound-cleaned. Analyst still gets raw BOLD from S5/S9.
- Per-dataset isolation: `logs/S10_roi_timeseries_and_connectivity/<dataset_key>/qc.json`.

## Deliverables

### Per-run derivatives (`derivatives/spinalfmriprep/<ds>/sub-XX/[ses-YY]/func/`)

**ROI timeseries TSVs** (one per catalog × confound mode = up to 6):
- `*_desc-vertlvl_rawts_timeseries.tsv` — vertebral-level (PAM50_levels) raw, columns C1..L1 (coverage-filtered).
- `*_desc-vertlvl_s8reg_timeseries.tsv` — vertebral-level, S8-default-regressed.
- `*_desc-spinalseg_rawts_timeseries.tsv` — spinal segmental (PAM50_spinal_levels) raw.
- `*_desc-spinalseg_s8reg_timeseries.tsv` — spinal segmental, regressed.
- `*_desc-hemicord_rawts_timeseries.tsv` — 4 horns × segmental levels (VL_C5, VR_C5, DL_C5, DR_C5, … per coverage), raw.
- `*_desc-hemicord_s8reg_timeseries.tsv` — hemicord × seg, regressed.

**Connectivity matrices** (Pearson + partial × regressed only — raw matrices are dominated by confounds and rarely useful):
- `*_desc-hemicord_pearson_connectivity.tsv` — symmetric ROI×ROI Pearson r.
- `*_desc-hemicord_fisherz_connectivity.tsv` — Fisher-z transformed.
- `*_desc-hemicord_partial_connectivity.tsv` — Ledoit-Wolf shrunk partial correlation.
- `*_desc-vertlvl_pearson_connectivity.tsv` + `_fisherz` + `_partial`.
- `*_desc-spinalseg_pearson_connectivity.tsv` + `_fisherz` + `_partial`.

**JSON sidecars** alongside each TSV: ROI labels, n_voxels per ROI, confound strategy, bandpass, computation method.

### Per-subject derivatives (`derivatives/spinalfmriprep/<ds>/sub-XX/`)

- `sub-XX_summary.json` — per-ROI mean tSNR, per-connection mean Fisher-z, list of run_ids contributing. Always emitted; aggregable by S11.
- `sub-XX_reliability.json` — multi-session only:
  - `icc31_per_connection` — ICC(3,1) for each connection across sessions.
  - `dice_per_seed` — spatial Dice on thresholded seed-to-voxel maps per seed.
  - `bland_altman_per_connection` — mean diff + 95% LoA on Fisher-z.
  - `icc_thresholds_cicchetti` — count of connections per Cicchetti band (poor/fair/good/excellent).

### Per-run work artifacts (`work/S10_roi_timeseries_and_connectivity/<ds>/<run_id>/`)
- `horns_native/PAM50_atlas_{30,31,34,35}_in_func.nii.gz` — 4 horn probability maps warped to native via S7 xfm.
- `vertlvl_native/PAM50_levels_in_func.nii.gz` — vertebral labels in native.
- `parcellations/` — composed multi-label NIfTIs used by Nilearn maskers.
- `confounds_used/` — copy of the confound DataFrame slice actually fed to each masker.
- `qc_metrics.json` — provenance + per-ROI voxel counts + bandpass + masker settings.

### Reportlets (`figures/`)
- `*_desc-S10_hemicord_timeseries.png` — line plot, one curve per hemicord×seg ROI, shared y, regressed mode.
- `*_desc-S10_hemicord_connectivity.png` — heatmap of Fisher-z matrix, ROI-clustered to show within-segment block structure.
- `*_desc-S10_vertlvl_tsnr.png` — bar per vertebral level (mean tSNR + n_voxels).
- `*_desc-S10_reliability_icc.png` (subject-level, multi-session) — bar of ICC per connection + Cicchetti threshold lines.
- `*_desc-S10_reliability_dice.png` (subject-level, multi-session) — bar of spatial Dice per seed.

### Code (new package, mirrors S6–S9 layout)
- `src/spinalfmriprep/steps/s10/__init__.py`
- `src/spinalfmriprep/steps/s10/process.py` — masker setup, extraction, connectivity, ICC, Dice, summary JSON.
- `src/spinalfmriprep/steps/s10/orchestrate.py` — per-dataset, per-run + per-subject (multi-session) aggregation.
- `src/spinalfmriprep/steps/s10/reportlets.py` — 5 PNGs.
- `src/spinalfmriprep/S10_roi_timeseries_and_connectivity.py` — CLI re-export.

### Policy + schema
- `policy/S10_roi_timeseries_and_connectivity.yaml`
- `schemas/qc_S10_roi_timeseries_and_connectivity.schema.json`

### Spec housekeeping
- Mark `private/SPEC/S10_roi_timeseries_and_reliability.md` status → `superseded` (private/ is gitignored but the mark is documentation).

## Inputs

- **BOLD source**: S5 `*_desc-undistorted_bold.nii.gz` (native; default) or S9 `*_desc-preproc_bold.nii.gz` (smoothed; analyst choice via policy `bold_source`).
- **PAM50 levels (segmental) in native**: S7 `*_desc-PAM50spinallevels.nii.gz` (already in derivatives).
- **PAM50 vertebral levels + horn atlases**: warp at S10 time using S7's `from-PAM50_to-bold_xfm.nii.gz` (saved) — source files: `$SCT_DIR/data/PAM50/template/PAM50_levels.nii.gz` and `$SCT_DIR/data/PAM50/atlas/PAM50_atlas_{30,31,34,35}.nii.gz`.
- **Cord mask**: S3 `func_ref_fast_seg_crop.nii.gz` (BOLD geometry).
- **Confound TSV**: S8 `*_desc-confounds_timeseries.tsv`.
- **Policy**: `policy/S10_roi_timeseries_and_connectivity.yaml`.

## Success Criteria

### Per-run gating
- **PASS**: all expected ROIs (coverage-filtered) have ≥ `min_voxels_per_roi` voxels, no NaN/inf in any emitted timeseries, condition number of Pearson connectivity matrix < 1e6.
- **WARN**: 1–2 ROIs dropped for low voxel count; OR matrix condition 1e6–1e10; OR confound regression rank-deficient (Nilearn warns).
- **FAIL**: > 2 ROIs dropped; OR > 10% timeseries cells NaN; OR masker raises exception.

### Per-subject reliability gating (multi-session only)
- **PASS**: ICC(3,1) computed for all connections; ≥ 50% in Cicchetti good-or-excellent bands (informational; doesn't gate run status).
- **WARN**: < 50% good-or-excellent; OR mean spatial Dice < 0.7.
- **FAIL**: ICC undefined (insufficient variance) for > 50% of connections.

### Dataset-level acceptance (v1 release)
1. All 5 v1_validation datasets emit per-run S10 outputs (3 catalogs × 2 modes = 6 TSVs + 9 connectivity TSVs + JSON sidecars).
2. Hemicord × spinal-segmental ROIs present for all cord-bearing segments per dataset coverage (Balgrist ~C5–C7, OpenNeuro full ~C2–C8).
3. For multi-session subjects (ds004386 rest 2 sessions, ds004616 handgrasp 2 sessions): reliability JSON emitted, ICC + Dice computed.
4. Dashboard renders all 5 reportlet types.
5. Subject-level `summary.json` exists and is valid JSON for every subject.

### Runtime budget
- ~30 s per run for the full extraction + connectivity + reportlets pipeline (Nilearn is vectorized; sct_apply_transfo of 4 horn atlases ~10s; SVD/correlation < 1s).
- Total chain on 11 reg runs: ~6 min.

## Next Steps

1. Mark `private/SPEC/S10_roi_timeseries_and_reliability.md` superseded.
2. Write `policy/S10_roi_timeseries_and_connectivity.yaml` (ROI catalogs, confound modes, bandpass, ICC thresholds, min-voxel guards).
3. Write `schemas/qc_S10_roi_timeseries_and_connectivity.schema.json`.
4. Scaffold `src/spinalfmriprep/steps/s10/` (`__init__`, `process`, `orchestrate`, `reportlets`).
5. Implement core helpers in `process.py`:
   - `_warp_pam50_atlas_to_native()` — sct_apply_transfo of PAM50_levels + PAM50_atlas_{30,31,34,35} via S7 xfm.
   - `_build_hemicord_parcellation()` — threshold horn probs > 0.5, intersect with segmental levels, combine to multi-label NIfTI.
   - `_extract_timeseries()` — Nilearn `NiftiMapsMasker` / `NiftiLabelsMasker` with confounds + bandpass.
   - `_compute_connectivity()` — Pearson + partial via `ConnectivityMeasure`; Fisher-z transform.
   - `_icc_3_1()` — Shrout & Fleiss (1979) two-way mixed effects, consistency, single rater.
   - `_spatial_dice_seed_to_voxel()` — Kaptan 2023 spatial reliability metric.
   - `_summary_json()` — per-subject aggregable summary.
6. Implement `orchestrate.py`: per-run + per-subject aggregation; reliability skipped when single-session.
7. Implement `reportlets.py`: 5 PNGs.
8. CLI + dashboard registry + chain script wiring.
9. Smoke test on pain dataset (1 run, no reliability); then handgrasp dataset (2 sessions → reliability test).
10. Run full chain S2→S10 on 5 reg datasets; verify all PASS/WARN.

## Decision Log

| # | Choice | Rationale |
|---|--------|-----------|
| D1 | Nilearn `NiftiMapsMasker`/`NiftiLabelsMasker` + `ConnectivityMeasure` | SCT's `sct_extract_metric` is 3D-scalar only (verified). Nilearn is brain-fMRI standard, handles 4D + confounds + bandpass in one call. |
| D2 | Three ROI catalogs (vertlvl + spinalseg + hemicord×seg) | Vertlvl gives coverage reporting; spinalseg matches Kaptan/Hemmerling rsFC convention; hemicord×seg gives the rigorous 16-seed analysis. Cheap to extract all three. |
| D3 | Emit BOTH raw + S8-regressed timeseries (`none` + `s8_default`) | Analysts vary on whether to regress before connectivity. Nilearn convention says yes; some cord papers regress in FEAT residuals after. Emit both, let user choose. |
| D4 | Pearson + partial correlation matrices | Pearson is universal; partial (Marrelec 2006, Ledoit-Wolf shrinkage) is more interpretable for network analysis. Both are 1-liner Nilearn. |
| D5 | ICC(3,1) (NOT ICC(2,1)) | Kaptan 2023 cord-convention. Two-way mixed effects, consistency, single rater. Spec's original ICC(2,1) was wrong. |
| D6 | Spatial Dice on seed-to-voxel maps as supplementary reliability | Kaptan 2023 explicit recommendation: voxel ICC is poor (cord), spatial localization (Dice) is good (~0.88). |
| D7 | Warp PAM50 horn atlases at S10 time (not extend S7) | Self-contained S10; ~30s overhead; S7's emit list stays minimal. |
| D8 | Bandpass 0.01–0.1 Hz default (configurable) | Resting-state cord convention since Eippert 2014. For task data, analyst can disable. |
| D9 | min_voxels_per_roi = 10 default | Cord cross-section is small; some hemicord-segment combinations have only 5–15 voxels. Below 10 the mean is too noisy. |
| D10 | Per-subject `summary.json` for S11 aggregation | Decouples per-run vs group-level; S11 can build group reports without touching 4D BOLD. |

## Out of scope (deferred to v2 / analyst-side)

- Dynamic functional connectivity (sliding-window, Vahdat 2020).
- ICA / dual regression (analyst-side, `nilearn.decomposition`).
- Coherence-based FC in 0.01–0.1 Hz.
- WM tract timeseries (PAM50_atlas labels 0–29) — feasible but not in the round-2 design; can be added by extending policy's ROI catalog.
- Per-task GLM (events-based contrasts).
- Group-level statistics (S11 owns).
- Brain-cord joint FC.

## References (verified in round-2/3 audit)

- Kaptan et al. 2023 — Spinal fMRI segmental functional networks: test-retest reliability ([PMC10831202](https://pmc.ncbi.nlm.nih.gov/articles/PMC10831202/)). Origin of 16-seed (4 horns × 4 segmental C5–C8) + ICC(3,1) + spatial Dice methodology.
- Hemmerling et al. 2023 — Reliability of rsFC across denoising strategies ([PMC10262064](https://pmc.ncbi.nlm.nih.gov/articles/PMC10262064/)). Quantitative thresholds + "maximal denoising hurts intensity reliability" warning.
- Vahdat et al. 2020 — Dynamic FC of resting-state spinal cord fMRI (Neuron). Slice-wise-then-average correlation convention.
- Marrelec et al. 2006 — Partial correlation for fMRI FC.
- Shrout & Fleiss 1979 — ICC types.
- Cicchetti 1994 — ICC reliability thresholds (< 0.4 poor / 0.4–0.59 fair / 0.6–0.74 good / > 0.75 excellent).
- PAM50 — local label index `info_label.txt` (template + atlas folders); 20 vertebral × 30 segmental labels verified by direct NIfTI read.
- Nilearn `NiftiMapsMasker`, `NiftiLabelsMasker`, `ConnectivityMeasure` — implementation backbone.
- Frostell et al. 2016 Table 3 — anatomical vertebral-to-spinal-segment correspondence reference.
