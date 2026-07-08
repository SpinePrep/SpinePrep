---
status: deferred
supersedes: private/SPEC/S10_roi_timeseries_and_reliability.md
---

> **DEFERRED 2026-06-11 — removed from the active pipeline.** This step was
> the **former S10 (ROI/connectivity)**; its step number has since been reused
> for the QC aggregation & release step (the new S10). ROI timeseries,
> connectivity, and ICC reliability are downstream **analysis**, not
> preprocessing. SpinePrep's contract is preprocess → confounds → release
> (S1–S10, with S10 = QC aggregation & release); the analyst owns the
> GLM/connectivity on their own design (the same boundary S8 states: "S8 emits
> the matrix; the analyst regresses"). The former S10 (ROI/connectivity) was
> also the pipeline's only persistent FAIL source (hemicord-ROI "no
> ROIs survived" on cospine_motor). Removed from the chain runner, the dashboard
> registry, and the release step's consumption (cohort FC summary,
> `max_condition_number`, the ROI methods paragraph). The step **code is
> retained** (not deleted) so it can return as an analyst-side module / v2.
> Reason it was kept around historically below.

# Scope Spec: Former S10 (ROI/connectivity) — ROI Timeseries + Connectivity + Reliability v2

## Objective
Emit per-run BIDS-Derivatives ROI timeseries TSVs + ROI×ROI connectivity matrices (Pearson + partial, raw + Fisher-z) for three PAM50-derived ROI catalogs, plus per-subject reliability summary (ICC(3,1) + spatial Dice) when multi-session, and a `_summary.json` enabling group-level aggregation at S10 (QC aggregation & release) without re-touching 4D BOLD.

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
- **No statistical modelling** beyond ICC + correlation. Group-level outputs are S10's (QC aggregation & release) job.
- **No regression of confounds out of BOLD itself** — only the TSV timeseries are confound-cleaned. Analyst still gets raw BOLD from S5/S9.
- Per-dataset isolation: `logs/S10_roi_timeseries_and_connectivity/<dataset_key>/qc.json`.

## Deliverables

### Per-run derivatives (`derivatives/spineprep/<ds>/sub-XX/[ses-YY]/func/`)

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

### Per-subject derivatives (`derivatives/spineprep/<ds>/sub-XX/`)

- `sub-XX_summary.json` — per-ROI mean tSNR, per-connection mean Fisher-z, list of run_ids contributing. Always emitted; aggregable by S10 (QC aggregation & release).
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
- `src/spineprep/steps/s10/__init__.py`
- `src/spineprep/steps/s10/process.py` — masker setup, extraction, connectivity, ICC, Dice, summary JSON.
- `src/spineprep/steps/s10/orchestrate.py` — per-dataset, per-run + per-subject (multi-session) aggregation.
- `src/spineprep/steps/s10/reportlets.py` — 5 PNGs.
- `src/spineprep/S10_roi_timeseries_and_connectivity.py` — CLI re-export.

### Policy + schema
- `policy/S10_roi_timeseries_and_connectivity.yaml`
- `schemas/qc_S10_roi_timeseries_and_connectivity.schema.json`

### Spec housekeeping
- Mark `private/SPEC/S10_roi_timeseries_and_reliability.md` status → `superseded` (private/ is gitignored but the mark is documentation).

## Inputs

- **BOLD source**: S5 `*_desc-undistorted_bold.nii.gz` (native; default) or S9 `*_desc-preproc_bold.nii.gz` (smoothed; analyst choice via policy `bold_source`).
- **PAM50 levels (segmental) in native**: S7 `*_desc-PAM50spinallevels.nii.gz` (already in derivatives).
- **PAM50 vertebral levels + horn atlases**: warp at former-S10 (ROI/connectivity) time using S7's `from-PAM50_to-bold_xfm.nii.gz` (saved) — source files: `$SCT_DIR/data/PAM50/template/PAM50_levels.nii.gz` and `$SCT_DIR/data/PAM50/atlas/PAM50_atlas_{30,31,34,35}.nii.gz`.
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
1. All 5 v1_validation datasets emit per-run former-S10 (ROI/connectivity) outputs (3 catalogs × 2 modes = 6 TSVs + 9 connectivity TSVs + JSON sidecars).
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
4. Scaffold `src/spineprep/steps/s10/` (`__init__`, `process`, `orchestrate`, `reportlets`).
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
10. Run full chain S2→former-S10 (ROI/connectivity) on 5 reg datasets; verify all PASS/WARN.

## Decision Log

| # | Choice | Rationale |
|---|--------|-----------|
| D1 | Nilearn `NiftiMapsMasker`/`NiftiLabelsMasker` + `ConnectivityMeasure` | SCT's `sct_extract_metric` is 3D-scalar only (verified). Nilearn is brain-fMRI standard, handles 4D + confounds + bandpass in one call. |
| D2 | Three ROI catalogs (vertlvl + spinalseg + hemicord×seg) | Vertlvl gives coverage reporting; spinalseg matches Kaptan/Hemmerling rsFC convention; hemicord×seg gives the rigorous 16-seed analysis. Cheap to extract all three. |
| D3 | Emit BOTH raw + S8-regressed timeseries (`none` + `s8_default`) | Analysts vary on whether to regress before connectivity. Nilearn convention says yes; some cord papers regress in FEAT residuals after. Emit both, let user choose. |
| D4 | Pearson + partial correlation matrices | Pearson is universal; partial (Marrelec 2006, Ledoit-Wolf shrinkage) is more interpretable for network analysis. Both are 1-liner Nilearn. |
| D5 | ICC(3,1) (NOT ICC(2,1)) | Kaptan 2023 cord-convention. Two-way mixed effects, consistency, single rater. Spec's original ICC(2,1) was wrong. |
| D6 | Spatial Dice on seed-to-voxel maps as supplementary reliability | Kaptan 2023 explicit recommendation: voxel ICC is poor (cord), spatial localization (Dice) is good (~0.88). |
| D7 | Warp PAM50 horn atlases at former-S10 (ROI/connectivity) time (not extend S7) | Self-contained step; ~30s overhead; S7's emit list stays minimal. |
| D8 | Bandpass 0.01–0.1 Hz default (configurable) | Resting-state cord convention since Eippert 2014. For task data, analyst can disable. |
| D9 | min_voxels_per_roi = 10 default | Cord cross-section is small; some hemicord-segment combinations have only 5–15 voxels. Below 10 the mean is too noisy. |
| D10 | Per-subject `summary.json` for S10 (QC aggregation & release) | Decouples per-run vs group-level; S10 can build group reports without touching 4D BOLD. |

## Out of scope (deferred to v2 / analyst-side)

- Dynamic functional connectivity (sliding-window, Vahdat 2020).
- ICA / dual regression (analyst-side, `nilearn.decomposition`).
- Coherence-based FC in 0.01–0.1 Hz.
- WM tract timeseries (PAM50_atlas labels 0–29) — feasible but not in the round-2 design; can be added by extending policy's ROI catalog.
- Per-task GLM (events-based contrasts).
- Group-level statistics (S10, QC aggregation & release, owns).
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

---

# Principles audit (May 2026)

Post-implementation audit of the former S10 (ROI/connectivity) against the `CLAUDE.md` dev principles.
The scope spec above is the *redesign rationale* (Nilearn NiftiMapsMasker
on PAM50 horn atlases, hemicord + spinalseg + vertlvl extraction);
this section is the principles-alignment check.

## Audit verdict per principle

| # | Principle | Verdict |
|---|---|---|
| 1 | Small dev cohort | ✅ 11-run reg set |
| 2 | Literature defaults | ✅ Kaptan 2023 hemicord ROIs, Eippert 2017 rsFC bandpass, Marrelec 2006 partial correlation, Shrout & Fleiss 1979 ICC(3,1), Cicchetti 1994 reliability bands, Frostell 2016 vertebral→segmental mapping |
| 3 | Step-local truth metric | ✅ `n_rois_hemicord` / `n_rois_spinalseg` / `n_rois_vertlvl` (coverage), `n_rois_dropped_low_voxels` (the headline gauge), `condition_number_pearson_hemicord` (matrix conditioning), `n_volumes` |
| 4 | Diagnostic reportlet | ✅ 3 PNGs emitted per single-session run (`hemicord_timeseries`, `hemicord_connectivity`, `vertlvl_tsnr`) + 2 multi-session reportlets (`reliability_icc`, `reliability_dice`) that fire only when a subject has ≥2 same-task sessions |
| 5 | Visual QC validator | ✅ |
| 6 | Lock and ship | ✅ scope spec + policy w/ thresholds |
| 7 | No chain backtracking | ✅ consumes S8 confound TSVs + S9 smoothed BOLD + S7 PAM50-in-native atlases; former-S10 (ROI/connectivity) metrics are self-contained |
| 8 | Full cohort = deliverable | ✅ |
| 9 | Reproducible | ✅ schema + policy + spec all versioned |
| 10 | Heterogeneity is the test | ✅ **11/11 WARN — all due to `dropped_rois > 0`**. The dropped-ROI counts vary by dataset (rest: 4; balgrist_motor: 14; cospine_motor: 48–50), encoding the actual cord coverage variability across the 5 datasets. **This is the principle §10 signal**: heterogeneity surfacing as quantitative coverage differences. |

## Step-local truth metric rationale

| Metric | What it answers |
|---|---|
| `n_rois_dropped_low_voxels` | **Headline gauge.** Number of PAM50 ROIs that fell below the minimum-voxel floor in this run's cord coverage. Encodes "how much of the cord did this EPI cover?" — a coverage-faithfulness measure that the cohort-level S10 (QC aggregation & release) coverage matrix builds on. |
| `n_rois_hemicord` / `_spinalseg` / `_vertlvl` | Per-atlas usable ROI count. Drops below the atlas's nominal label count (8/30/20 respectively) signal coverage limits. |
| `condition_number_pearson_hemicord` | Connectivity matrix conditioning. High κ ⇒ some hemicord ROIs are near-collinear (small ROI with shared variance). Brain-heuristic gate; cord recalibration deferred. |
| `n_volumes` | Pass-through context: short runs (n < 80) have unreliable connectivity. |

## Threshold rationale (`policy/S10_roi_timeseries_and_connectivity.yaml`)

| Gate | Value | Source |
|---|---|---|
| `warn_dropped_rois_max` | 0 | Any drop ⇒ WARN. Intentionally strict — tells the analyst "this run doesn't span the full cord; check coverage before aggregating to segmental analyses." |
| PASS `pass_max_condition_number` | 1000.0 | fMRIPrep brain heuristic |
| WARN `warn_max_condition_number` | 10000.0 | Above ⇒ FAIL |

## Why 11/11 WARN is acceptable

The reg cohort spans 5 heterogeneous datasets with cord-FOV variability
ranging from a few segments (cospine cord-only acquisitions) to most
of the cervical cord (rest test-retest). With 30 spinal_levels +
20 vertebral_levels + 8 hemicord ROIs available in PAM50 and a
strict-zero PASS gate, any run that doesn't span the full cord WARNs
on `dropped_rois`. **This is the metric working as designed** — flagging
coverage gaps so cohort-level aggregation (S10, QC aggregation & release) can stratify by
coverage rather than blindly average. The dropped-ROI count is itself
the heterogeneity signal of principle §10.

## Decision: no code change

The former S10 (ROI/connectivity) already satisfies all 10 principles. The 11/11 WARN bias carries
information (per-dataset coverage variability), not noise. Loosening
the gate to "PASS any coverage > 50%" would hide the heterogeneity
that the cohort needs to be aware of. Lock and ship (principle §6).

## Remaining gaps (acceptable / deferred)

- Cord-specific `condition_number` thresholds (same as S8 — brain
  heuristic, cord recalibration deferred).
- Per-vertebral-level connectivity matrix (currently only hemicord
  connectivity is plotted). Tracked in scope spec; not blocking.
- The 50-ROI drop on cospine_motor reflects a known coverage gap in
  that dataset; the S10 (QC aggregation & release) cohort coverage matrix surfaces this to the
  analyst directly.

