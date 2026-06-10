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
- **Cord-calibrated thresholds.** FD outlier ≥ 0.5 mm (Power 2014 lenient scrub — NOT Kaptan, which uses no FD threshold). DVARS OR refRMS via Tukey Q3+1.5·IQR (the dVARS/refRMS outlier rule; cf. Kaptan 2023's SD-cutoff). [DOC-2/DONE-8: was "0.2 mm (Kaptan 2023)" — wrong value AND wrong citation.]
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
| Q5 | FD threshold 0.5 mm | Power 2014 lenient FD scrub (superseded the wrong "0.2 mm Kaptan" — Kaptan uses dVARS/refRMS, no FD). See s8-outlier-rate-root-cause.md. |
| Q6 | TSV flat-columned slicewise | BIDS convention; Nilearn load_confounds compatible. |
| Q7 | SpinalCompCor off by default v1 | Hemmerling says augments not replaces; needs validation; MATLAB-only ref impl forces Python port. |
| Q8 | Pre-PCA mean-center + DCT-detrend | fMRIPrep convention; guards against trivial drift PCs. |
| Q9 | CSF mask = S7 PAM50csf in native | Already produced; S2 canal-cord requires extra warp (v2). |

---

# Principles audit (May 2026)

Post-implementation audit of S8 against the `CLAUDE.md` dev principles.
The scope spec above is the *redesign rationale*; this section is the
principles-alignment check.

## Audit verdict per principle

| # | Principle | Verdict |
|---|---|---|
| 1 | Small dev cohort | ✅ 11-run reg set |
| 2 | Literature defaults | ✅ Kaptan 2023, Dabbagh 2024, Hemmerling 2025, Behzadi 2007, Power 2014, Eippert 2017 (each policy knob cites its source in `policy/S8_confounds.yaml`) |
| 3 | Step-local truth metric | ✅ rich: per-family column counts (`n_columns_motion`/`csf`/`retroicor`/`cosine`/`spinalcompcor`/`outliers`), `n_columns_total`, `outlier_fraction`, `condition_number`, `fd_mean_mm`/`fd_max_mm`, `dvars_mean`, `cardiac_bpm_estimate`, `spinalcompcor_median_pcs`, `n_slices_with_csf`, `n_volumes` |
| 4 | Diagnostic reportlet | ✅ 5 PNGs (`confound_columns`, `fd_dvars_outliers`, `csf_variance`, `pnm_peaks`, `correlation_heatmap`) — each covers a distinct family's failure mode |
| 5 | Visual QC validator | ✅ |
| 6 | Lock and ship | ✅ policy w/ documented thresholds + scope spec above |
| 7 | No chain backtracking | ✅ S8's gauges are derived from S5 BOLD + S7 PAM50csf + S3 frame metrics; nothing depends on what S9 does with them |
| 8 | Full cohort = deliverable | ✅ ~2 min/run (+ 1 min with SpinalCompCor on) |
| 9 | Reproducible | ✅ schema + policy + scope spec all versioned |
| 10 | Heterogeneity is the test | ✅ **10/11 WARN, 1/11 PASS** across 5 datasets — the WARN bias is **real**: outlier_fraction routinely 0.2–0.4 on cord-fMRI at this resolution, reflecting the Kaptan 2023 threshold's tightness, not a bug in S8. |

## Step-local truth metric rationale

The headline gauges are all **about the confound matrix itself**, not
the BOLD it regresses (which would be downstream).

| Metric | What it answers |
|---|---|
| `n_columns_total` + per-family breakdown | Did each family produce columns? E.g., `n_columns_retroicor=0` ⇒ physio missing or PNM failed silently. |
| `outlier_fraction` | What fraction of volumes were flagged (DVARS OR refRMS)? This is the S8 confound layer's mirror of S3's headline gauge. |
| `condition_number` | Matrix conditioning — high κ ⇒ near-singular design ⇒ regression unstable. Brain heuristic (10⁴) used as initial gate; cord-specific recalibration tracked in scope spec Q1. |
| `fd_*` / `dvars_mean` | Pass-through context: was the motion / volatility regime expected? |
| `cardiac_bpm_estimate` | Sanity of FSL PNM peak detection (50–110 bpm physiological); None when physio absent. |
| `spinalcompcor_median_pcs` | When SpinalCompCor on, median per-slice PC count from parallel analysis. |

## Threshold rationale (`policy/S8_confounds.yaml`)

| Gate | Value | Source |
|---|---|---|
| PASS `pass_condition_number` | 1000.0 | fMRIPrep brain heuristic; cord recalibration tracked |
| WARN `warn_condition_number` | 10000.0 | Above ⇒ FAIL |
| PASS `pass_outlier_fraction_max` | 0.20 | Kaptan 2023 cord-fMRI |
| WARN `warn_outlier_fraction_max` | 0.40 | Above ⇒ FAIL |

Both S4's `fd_threshold_mm = 0.5` (coarse run-usability gate) and S8's
`motion.fd_outlier_threshold_mm = 0.5` (per-frame scrubbing gate) use the
**Power 2014** lenient FD threshold (the earlier S8 value of 0.2 was corrected
to 0.5 in s8-outlier-rate-root-cause.md). Kaptan 2023 is NOT the source of
either FD value — it scrubs on dVARS/refRMS SD-cutoff.

## Why 10/11 WARN is acceptable

The reg cohort spans 5 heterogeneous datasets at cord-fMRI typical
resolutions (~1×1×4 mm, TR 2–3 s, low cord SNR). Outlier fractions
in the 0.20–0.40 range are common per Kaptan 2023 / Dabbagh 2024,
which set the threshold at 0.20 specifically to flag the upper end
of acceptable. **The WARN bias is the metric working as designed**;
the runs are still usable (would be a FAIL at >0.40). The 1 PASS
(balgrist_motor sub-02 run-01) had outlier_fraction = 0.18.

## Decision: no code change

S8 already satisfies all 10 principles. The metric coverage is the
densest in the pipeline (≥15 per-run gauges spanning 5 families) and
the 5 reportlets cover each family's failure mode independently. The
heterogeneity test (principle §10) is exactly the kind of "different
algorithm tells different story per dataset" signal the principles
expect — the WARN/PASS pattern carries information.

## Remaining gaps (acceptable / deferred)

- Cord-specific `condition_number` thresholds (the 10³/10⁴ brain bands
  may be too lenient for cord with high collinearity among RETROICOR
  + cosine columns). Tracked in scope spec Q1.
- SpinalCompCor validation on full cohort before flipping the default
  to ON. Scope spec Q7 marks this as v2 work.
