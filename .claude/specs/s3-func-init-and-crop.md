---
status: implemented
---

# S3 func init and crop — audit against dev principles

Step-local audit of S3 against the SpinePrep development principles
(`CLAUDE.md`). Implementation spec for the *algorithms* lives in
`private/SPEC/S3_func_init_and_crop.md`.

## Objective

For each BOLD run, drop dummy volumes, localize the cord on a coarse
functional reference, gate frames by DVARS / DVARS-ref outliers, build
a robust functional reference (median of non-outlier volumes), and
crop the 4D volume around the cord. Outputs feed S4 motion correction.

Naming notes: "coarse functional reference" (a.k.a. internal symbol
`func_ref_fast` / on-disk `func_ref_fast.nii.gz`) is fMRIPrep's
"coarse/initial reference volume". "DVARS-ref" is the literature name
for what Kaptan 2023 / Dabbagh 2024 call **refRMS** — kept as
`ref_rms` on disk (frame_metrics.tsv) for the downstream S8 contract,
surfaced as DVARS-ref on reportlets. The "brain-contamination check (drift gate)" stays as the
internal symbol; reportlet and doc text use **brain contamination
check** so a field-reader recognises it.

## Sub-steps

| Stage | Purpose |
|---|---|
| S3.1 | Dummy drop + cord localization on coarse functional reference (`sct_deepseg seg_sc_contrast_agnostic`) with a brain-contamination check (a.k.a. internal "drift gate" — catches "cord seg leaked into brain") |
| S3.2 | Mask-aware DVARS + DVARS-ref (refRMS) frame metrics; outlier flagging via boxplot cutoff; robust functional reference (median of non-outlier volumes) |
| S3.3 | Cord-focused crop using the localization mask (60 mm cylinder); produces the cropped BOLD (`funccrop_bold.nii.gz`) + cord mask (`funccrop_mask.nii.gz`) downstream contract |

## Literature backing

| Choice | Source |
|---|---|
| Mask-aware DVARS | Power 2014, Smyser 2019 — restrict DVARS to a cord ROI to avoid noise being dominated by background |
| DVARS-ref (refRMS) metric | Standard fMRIPrep / `mriqc` frame metric; Kaptan 2023 / Dabbagh 2024 cord |
| Outlier boxplot cutoff (Q3 + 1.5·IQR) | Tukey 1977; field-standard non-parametric outlier definition |
| `sct_deepseg seg_sc_contrast_agnostic` for cord localization | SCT 7.0+ recommended |
| 60 mm cord cylinder crop | Cervical cord typical diameter; matches S2 cordref crop |

## Step-local truth metrics (principle §3)

`metrics` block in qc.json per run (this audit pulled them from the
already-computed `outlier_mask.json` and S3.1 / S3.3 sub-step returns):

- `n_frames_total` — volumes after dummy drop.
- `n_dummy_dropped` — first-N volumes dropped (steady-state).
- `n_outliers` — frames flagged outlier (DVARS OR DVARS-ref).
- `outlier_fraction` — **headline truth gauge.** Reference threshold in
  `qc_thresholds.outlier_fraction_pass_max` (0.20, Kaptan 2023).
  **Treated as observability / soft WARN, never FAIL** — high motion is
  the analyst's call at GLM time, so S3 surfaces the number (and a WARN
  above the threshold) but does not drop the run. Consistent with S8's
  motion handling.
- `dvars_threshold` / `dvars_ref_threshold` — the boxplot-derived cutoffs
  used for this run (recorded so the analyst can audit per-run gating).
- `n_cord_slices_localization` — cord coverage detected in S3.1.
- `funcref_in_cord_mean` / `funcref_in_cord_std` — quick funcref
  sanity within the cord ROI.

## Diagnostic reportlets (principle §4)

| Reportlet | What it shows | What failure looks like |
|---|---|---|
| `func_localization` | S3.1 cord localization on coarse functional reference | Cord drift into brain ⇒ S3.1 FAIL |
| `frame_metrics` | DVARS + DVARS-ref timeseries with outlier markers | High outlier_fraction visible |
| `crop_box_sagittal` | Crop ROI on funcref sagittal (S3.3) | Misaligned crop ⇒ wrong localization |
| `funcref_montage` | Axial montage of the robust funcref | Low signal / banding in cord = bad acquisition |

## Decision log

| # | Choice | Rationale |
|---|---|---|
| 1 | Don't rewrite outlier_mask.json structure | Existing format is already correct; just surface into `metrics` |
| 2 | Use the boxplot cutoff per-run, not a fixed threshold | Adaptive to per-run signal level; Tukey-IQR is robust and parameter-free |
| 3 | Set outlier_fraction PASS gate at 0.20 | Kaptan 2023 cord-fMRI quality threshold |
| 4 | No new reportlets — existing 4 cover the failure modes | Adding more would dilute eyeball signal (principle §4) |

## Audit verdict per principle

| # | Principle | Before | After | Notes |
|---|---|---|---|---|
| 1 | Small dev cohort | ✅ | ✅ | 15 runs across 5 datasets |
| 2 | Literature defaults | ✅ | ✅ | Power 2014, Tukey 1977, Kaptan 2023, SCT 7.0+ |
| 3 | Step-local truth metric | ❌ (empty) | ✅ | added 7 metrics from already-computed substep outputs |
| 4 | Diagnostic reportlet | ✅ | ✅ | 4 reportlets, each diagnoses one failure mode |
| 5 | Visual QC validator | ✅ | ✅ | reportlets eyeball-able |
| 6 | Lock and ship | ⚠️ | ✅ | policy YAML + new `qc_thresholds` block + audit doc |
| 7 | No chain backtracking | ✅ | ✅ | only reads S2 (cordref + cord_dseg) |
| 8 | Full cohort = deliverable | ✅ | ✅ | ~1 min per run; scales freely |
| 9 | Reproducible | ✅ | ✅ | versioned policy + schema + spec |
| 10 | Heterogeneity is the test | ✅ | ✅ | 4 FAILs on `_acq-KombiShimZBrain` (brain-shim acquisitions in balgrist) — the brain-contamination check (drift gate) correctly catches cord-seg leakage into brain. **The heterogeneity surfaced the bug.** |

## Brain-contamination check (internal: drift gate) — pipeline-specific QC guard (not literature-backed)

The S3.1 brain-contamination check (internal symbol: `drift_gate` —
implemented as `_check_drift_gate` in `localize.py`) is a
**SpinePrep contribution**, not a published cord-fMRI
convention.

**Why it exists**: `sct_deepseg seg_sc_contrast_agnostic` can drift
into the brain on cospine-style acquisitions where the top of FOV
clips through the brain stem. The "cord" segmentation then bleeds
upward and the downstream pipeline computes cord-fMRI metrics on
brain tissue. Documented by SCT issue threads and indirectly
acknowledged in CoSpine 2025's "per-acquisition QC" caveat, but
not codified as a published guard.

**How it works**: two cheap checks on the most-superior 5 cord-
bearing slices:

| Check | Threshold | Rationale |
|---|---|---|
| `absolute_area_cap_mm2` | 200 mm² | Cervical cord CSA ≤ 80 mm² normally; 200 mm² floor leaves margin for swelling / pathology while rejecting brain-stem leaks (CSA 500+ mm²) |
| `area_spike_threshold` | 4× | Top-slice / immediate-inferior-slice ratio. Brain stem is 6-10× cord CSA; 4× is sensitivity-favoring (catches early drift) |

**Effect on the reg cohort**: the 4 `KombiShimZBrain` runs in
`reg_internal_balgrist_motor_11_subset` correctly FAIL with
`S3.1 brain-contamination check (drift gate): empty segmentation` — these are brain-shim
acquisitions never intended for cord analysis. The brain-contamination check (drift gate) is
the QC layer that prevents them from polluting downstream.

**Status**: novel but principled. Cited in
`.claude/specs/s3-algorithm-audit.md` as the one S3 component
without published precedent. Algorithm audit verdict: defensible.

## Remaining gaps (acceptable / deferred)

- Per-Z slice tSNR estimate (currently we report only mean/std of the
  funcref in cord). Defer to S9 which does this rigorously.
- No "cord coverage in EPI" metric (number of Z slices with ≥3 cord
  voxels in S3.1 localization). The S3.1 `n_cord_slices` partly
  covers this; could be sharpened later.

## Notable finding from the heterogeneity test (principle §10)

The 4 FAIL runs in `reg_internal_balgrist_motor_11_subset` are all
`_acq-KombiShimZBrain` — brain-shim acquisitions that the cord
localization correctly rejects ("S3.1 brain-contamination check (drift gate): empty segmentation").
This is **not a bug**; it's the brain-contamination check (drift gate) working as designed,
preventing a brain-shimmed BOLD from polluting downstream cord-only
analysis. The cord-shimmed runs (`_acq-KombiShimZSpine`) all PASS.
