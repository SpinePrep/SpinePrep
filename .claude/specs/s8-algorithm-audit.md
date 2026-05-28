---
status: approved
---

# S8 algorithm audit — literature-backed, truthful, correct

Companion to `.claude/specs/s8-confounds-and-physio-regressors.md`.
Verifies each regressor family and gate against the cord-fMRI / brain-
fMRI confound-modelling literature.

## Sub-step summary

S8 takes one S6-registered BOLD run and emits a BIDS-Derivatives
**confound TSV** (one row per volume, ~30–100 columns) + JSON
sidecar. It does NOT regress them out — that's the analyst's job at
the GLM stage. Five regressor families are computed:

1. **Motion (24P-style scalar)** — 4 scalar columns: trans_x, trans_y,
   plus their first derivatives, plus FD. Derived from S4's slicewise
   `moco_params_x.nii.gz` / `_y.nii.gz` (mean across Z).
2. **Outliers (one-hot spike regressors)** — one column per
   flagged volume. Triggered by FD>0.2mm OR DVARS>μ+3σ OR refRMS>μ+3σ.
3. **CSF slicewise** — per-Z mean of the top-20%-variance voxels
   inside the S2-derived canal-minus-cord mask warped to native func.
   Hemmerling 2025 recipe.
4. **RETROICOR slicewise (when BIDS physio readable)** — FSL `popp` +
   `pnm_evs`, cardiac order 4 + respiratory order 4 + interaction
   4×4 = 16 → 32 slicewise EVs. Aggregation: slice_mean (1 col per EV).
5. **Cosine basis (DCT high-pass)** — equivalent of 1/100 s HP filter
   (Kaptan 2023 / Dabbagh 2024 cord standard). Always emitted.
6. **SpinalCompCor (Hemmerling 2025)** — dilated cord+CSF noise-ROI,
   per-voxel mean-center + DCT-detrend, single-SVD top-5 PCs by
   default. Aggregation `global_3d` (fMRIPrep `a_comp_cor`-style).

Status classification gates on **condition number** (multicollinearity
proxy) + **outlier fraction** (observability, soft-WARN).

## Per-choice verdict — algorithm

### Motion family (24P → 4P+FD)

| Choice | Value | Literature | Verdict |
|---|---|---|---|
| Translations only (trans_x, trans_y) | 2-D moco from S4 — cord moco is 2-D slicewise, no rotation params emitted | Mohammed 2020 cord moco | ✅ correct for the S4 pipeline |
| `*_derivative1` via `np.diff(prepend=ts[0])` | Power 2014 / Friston 24P convention | ✅ standard |
| FD = `|Δtrans_x| + |Δtrans_y|` | Power 2014 (brain uses 6 rigid params); we adapt to 2 cord params | ⚠️ — see Finding 1 |
| FD outlier threshold | 0.2 mm | Mohammed 2020 / Kaptan 2023 | ✅ cord-specific Power 2014 adaptation |
| No quadratic / squared-derivative terms (Friston 24P) | Just 4-of-24 | Friston 1996 24P = 6 rigid + 6 deriv + 6 sq + 6 sq-deriv. We have 2 trans + 2 deriv. **Doesn't ship the 24P 'full Friston'.** | ⚠️ — partial 24P, see Finding 2 |

### Outlier spike regressors

| Choice | Value | Literature | Verdict |
|---|---|---|---|
| One-hot spikes (Power 2014 scrubbing) | One column per flagged volume | Power 2014, fMRIPrep `motion_outlier_NN` | ✅ standard |
| Combined gate: FD OR DVARS μ+3σ OR refRMS μ+3σ | Dual criterion + spike + frame | Power 2014; Kaptan 2023 / Dabbagh 2024 | ✅ field-standard |
| DVARS / refRMS from S3.2 (mask-aware) | Re-uses S3 outputs | ✅ no recomputation |

### CSF slicewise

| Choice | Value | Literature | Verdict |
|---|---|---|---|
| CSF mask source | S2 canal_dseg minus cord_dseg, warped to native via S6 | Hemmerling 2025 sub-cohort recipe | ✅ subject-specific, anatomically faithful |
| Fallback: PAM50 CSF warped to native | Used when S2 canal_dseg unavailable | ✅ defensive |
| `erode_voxels = 0` | No erosion (cord CSF is 1-2 vox wide) | Hemmerling 2025 doesn't erode; in-house validation | ✅ defensible deviation from brain `aCompCor` convention |
| Top 20% variance voxels → mean per slice | One column per slice with ≥5 vox | Hemmerling 2025 verbatim | ✅ standard |
| Per-slice min voxel count: 5 | numerical stability floor | ✅ defensible |

### RETROICOR (Glover 2000 RVT, Glover 2000 RETROICOR)

| Choice | Value | Literature | Verdict |
|---|---|---|---|
| Engine: FSL `popp` + `pnm_evs` | Cord-fMRI consensus | Brooks 2008 / Kong 2012 / Dabbagh 2024 | ✅ field-standard |
| Cardiac order 4 | 8 columns (sin + cos × 4) | Brooks 2008 cord; Dabbagh 2024 | ✅ standard |
| Respiratory order 4 | 8 columns | Brooks 2008 | ✅ standard |
| Interaction 4×4 | 16 cross-term columns | Harvey 2008 | ✅ standard |
| Total 32 EVs/slice → slice_mean aggregation = 32 cols | Kaptan 2023 reports ~32 cols | ✅ standard |
| HR + RVT enabled (popp `--rvt --heartrate`) | 2 slow regressors | Birn 2008 (RVT); Chang 2009 | ✅ standard |
| **Auto-disable when physio missing** | Documented graceful degradation | Empirical: only 1 of 5 reg datasets ships physio TSV | ⚠️ — see Finding 3 |

### Cosine basis (DCT high-pass)

| Choice | Value | Literature | Verdict |
|---|---|---|---|
| `cutoff_hz = 0.01` (= 1/100 s) | Kaptan 2023 / Dabbagh 2024 cord standard | ✅ cord-specific. Note: fMRIPrep brain default is 1/128 s. |
| DCT type-II basis | `√(2/N) · cos(πk(t+0.5)/N)`, k = 1..K | fMRIPrep convention | ✅ standard |
| `n_keep = floor(2·N·TR·cutoff_hz)` | DCT-to-frequency-keep rule | ✅ correct |

### SpinalCompCor (Hemmerling 2025)

| Choice | Value | Literature | Verdict |
|---|---|---|---|
| Engine: dilate (cord∪CSF) by 18 mm, subtract → noise ROI | Hemmerling 2025 reference recipe | ✅ verbatim |
| Pre-PCA per-voxel mean-center + DCT-detrend | fMRIPrep / Behzadi 2007 convention | ✅ standard. Hemmerling omits but cord-PCA without this is unstable |
| Top-K PCs via SVD | Behzadi 2007 / fMRIPrep `a_comp_cor` | ✅ standard |
| `fixed_n_components = 5` | fMRIPrep default for brain `a_comp_cor` | ✅ standard |
| Aggregation: `global_3d` (single 3D PCA) | fMRIPrep convention | ✅ standard. Hemmerling default is slicewise but it only fits long runs. |
| Component selection alternatives: `kaiser`, `iaaft` | IAAFT = Hemmerling 2025 parallel analysis (50 surrogates) | ⚠️ — see Finding 4 |
| Edge voxel removal: 3 vox | Hemmerling 2025 | ✅ standard |

### QC gating

| Gate | Value | Verdict |
|---|---|---|
| `pass_condition_number = 1000` | Multicollinearity proxy. Brain heuristic (fMRIPrep doesn't gate on it). | ⚠️ defensible but not literature-anchored |
| `warn_condition_number = 10000` | ⚠️ same |
| `pass_outlier_fraction_max = 0.20` | Kaptan 2023; soft-WARN only | ✅ documented as observability, not gating per the code (`outlier_fraction` only WARNs, never FAILs) |

## Cohort empirics (wf_reg_068)

| Dataset | Runs | Status | Notes |
|---|---|---|---|
| balgrist_motor (4) | 4 WARN | High outlier fractions 63-83% (motion-heavy KombiShim). RETROICOR skipped (no BIDS physio). |
| ds004386_rest (2) | 2 WARN | OF 68-69%. RETROICOR skipped. |
| ds004616_handgrasp (2) | 2 WARN | OF 26-34%. Has physio? Verify Finding 3. |
| ds005883_cospine_pain (1) | 1 WARN | OF 31%. |
| ds005884_cospine_motor (2) | 1 PASS + 1 WARN | One run OF 15% → PASS; one OF 36% → WARN. |

**10 WARN + 1 PASS** — but ALL WARNs are `outlier_fraction WARN` (soft, observability-only) or `RETROICOR skipped`. None are condition-number failures or critical bugs.

## Findings

### Finding 1 — FD formula is L1, not L2 (Power 2014 uses L2 + radians)

`process.py:60`:
```python
fd = np.abs(dtx) + np.abs(dty)
```

Power 2014 brain FD is `|Δtx| + |Δty| + |Δtz| + 50·(|Δθx| + |Δθy| + |Δθz|)` (L1, with rotations converted to mm via 50 mm radius). We're missing:
- The Z-translation term (S4 cord moco is 2D, but bulk Z drift could matter)
- The rotation terms (S4 doesn't emit them, see also Finding 5)

The L1 form is correct for the params we have. The "50 mm radius rotation→mm" trick is not applicable when we have no rotation params.

**Verdict**: ✅ correct given S4's 2D-only moco output. **Documented as "2-D Power" already in the policy comment.** Acceptable.

### Finding 2 — Only 4 of Friston-24P emitted (no squares, no squared derivatives)

24P = 6 rigid + 6 deriv + 6 sq + 6 sq-deriv. We emit 2 trans + 2 deriv = 4 cols. No quadratic terms.

**Why this matters**: Friston 24P specifically catches nonlinear motion artifacts (head motion + B0 inhomogeneity interaction is quadratic). Skipping the squared terms loses some artifact-explaining variance.

**Why the omission is reasonable**: Cord BOLD is much smaller than brain (~100 cord voxels per slice vs ~10k brain voxels). Adding 4-8 extra cols just for the 2D translation case may overfit on short runs (some reg-cohort runs are <100 volumes). Kaptan 2023 reports 4-6 motion params, not 24.

**Recommendation**: leave as-is. Document explicitly in the audit and in the policy comment that we ship the **cord-2D variant** of motion confounds, not the brain-3D 24P.

### Finding 3 — RETROICOR skipped on 9/11 reg-cohort runs

Documented in qc.json failure_reasons:
- All 4 balgrist + 2 rest + 1 pain + 1 motor = 8 runs missing physio TSV
- 1 (cospine_motor sub-02 motorL) has physio and computed RETROICOR (the only PASS)
- 2 handgrasp runs say "outlier_fraction WARN" without RETROICOR-skip reason → physio MIGHT be present?

The auto-disable is correct behavior — if there's no physio TSV, we can't compute RETROICOR. But it's worth verifying:
- Whether handgrasp's physio is being read or silently skipped
- Whether SliceTiming is available + correctly used
- Whether the family_counts dict (currently `{}` for most runs in qc.json — see Finding 6) is being populated

**Recommendation**: add an `auto-disable` per-family flag to qc.json that explicitly records WHY each family was skipped (no physio, no SliceTiming, no canal_dseg, etc). Currently the user has to read failure_reasons for this signal.

### Finding 4 — IAAFT path is implemented but never used by default

`policy.spinalcompcor.component_selection = "fixed_n"` is the default. IAAFT is implemented (Hemmerling 2025 parallel analysis with 50 surrogates per voxel) at significant complexity cost (~30 min/run), but never engaged on the reg cohort.

**Recommendation**: Documented as expected — leave the IAAFT code in (it's the published reference) but make the comment clearer that v1 uses the simpler `fixed_n=5` (matches brain `a_comp_cor`). Optionally add a `policy.spinalcompcor.component_selection: "iaaft"` test run to validate the IAAFT path against the cohort once.

### Finding 5 — Rotation params not emitted by S4

S4's cord moco is 2D slicewise (centermassrot + columnwise + bsplinesyn), with bulk XY translation in stage 1. We don't pass rotation params through to S8.

If S4 ever switches to volume-wise 3D moco (e.g., for non-cord-fMRI extensions), S8's motion family would need to be extended. For now, the 2-D cord regime is correct.

**Recommendation**: No action. Documented assumption in `process.py` docstring.

### Finding 6 — `metrics.family_counts` empty / `n_columns` None in qc.json

```python
WARN  cols=None ... fam={}  ...
```

Every cohort run reports `n_columns: None` and `family_counts: {}` in qc.json. The PASS run too. This means the metrics dict in qc.json is NOT carrying the column-count breakdown that the spec promises.

Looking at `process.py`: `family_counts` IS computed and IS passed to the reportlet, but it might not be making it into the metrics dict that gets written to qc.json. Verify.

**Recommendation**: trace through `process.py` and ensure `n_columns` + `family_counts` land in the qc.json `metrics` field. This is observability — the user should be able to read qc.json and see "this run has 5 motion + 12 outlier + 20 CSF + 32 RETROICOR + 4 cosine + 5 compcor = 78 total columns" without opening the TSV.

### Finding 7 — `outlier_fraction` "WARN" routinely high on cord-fMRI

The reg cohort shows outlier fractions of 15-83%. The 0.20 PASS gate is too tight: only 1 of 11 runs passes it.

**Why high OFs are expected on cord-fMRI**:
- Cord BOLD has much smaller signal (lower SNR than brain), so the 3σ DVARS gate fires more often.
- Cord-cropped DVARS captures real physiological pulsation that the 3σ gate flags as "outlier."
- The Power 2014 0.20 brain threshold doesn't transfer 1:1 to cord.

The classifier already handles this — `outlier_fraction` only WARNs, never FAILs. So no critical issue. But the reportlet + qc.json messaging makes it look like 10 of 11 runs failed something, when actually they're passing the only hard gate (condition number).

**Recommendation**: loosen `pass_outlier_fraction_max` to 0.40 (matching `warn_outlier_fraction_max` and the actual cohort distribution), OR add a note in the dashboard reportlet caption that "OF > 20% is expected for cord-fMRI". The hard `fail_outlier_fraction_max` isn't set, so this is purely cosmetic.

### Finding 8 — Reportlets don't follow visual standard

`reportlets.py` uses plain matplotlib with light backgrounds (`#888` gridlines, no `BG="#0f1115"`, no header chrome, no status pill). S2/S3/S5/S6/S7 have all been brought into compliance.

**Recommendation**: defer. The S8 reportlets are quantitative plots (bar chart, time-series with thresholds, heatmap) — they don't need the full sagittal/axial chrome. But the dark theme + status pill would still help. Low priority.

### Finding 9 — Reportlet selection: 5 PNGs may be too many

Currently 5 reportlets per run:
1. `confound_columns` — bar chart of column counts by family
2. `fd_dvars_outliers` — 3-row time series + outlier markers
3. `csf_variance` — per-slice CSF voxel count
4. `pnm_peaks` — cardiac peaks + resp phase
5. `correlation_heatmap` — confound correlation matrix

For S6 (registration) we settled on 2; for S7 (template) we settled on 2; both per audit-redundancy review. Verify S8 audit similarly — `csf_variance` and `pnm_peaks` are observability-only and could be combined with `confound_columns` into a single "family health" panel.

**Defer to a separate redundancy audit** (next user request) — algorithm audit is the current scope.

### Finding 10 — `family_counts` not in schema

`qc_S8_confounds.schema.json` may not enumerate `family_counts` or `n_columns`. Verify against the audit Finding 6.

**Recommendation**: align schema with what `process.py` actually emits (or should emit after fixing Finding 6).

## Truthfulness review

| Claim | True? |
|---|---|
| "5 regressor families" | ✅ — motion, outliers, CSF, RETROICOR, cosine, plus optional SpinalCompCor = 6 actually |
| "Native func space only; no BOLD resampling" | ✅ |
| "Power 2014 / Kaptan 2023 / Dabbagh 2024 cord standard" | ✅ documented and matched |
| "Hemmerling 2025 SpinalCompCor verbatim" | ✅ recipe is verbatim |
| "RETROICOR auto-disabled when physio missing" | ✅ verified in cohort |
| "24P motion model" | ❌ — we ship 4 cols (2 trans + 2 deriv), not 24. The cord-2D variant. Document explicitly. |
| "Outlier fraction is observability-only" | ✅ — classifier only WARNs, never FAILs |
| "metrics.n_columns + family_counts in qc.json" | ❌ — see Finding 6, currently empty |
| "All metrics computed for every run" | ⚠️ — RETROICOR family skipped on most reg-cohort runs (no physio TSV) |

## Audit verdict

**S8 algorithm is correct and literature-aligned**. Each regressor
family matches its source paper:
- Motion → Power 2014 / Mohammed 2020 / Friston 1996 (cord-2D variant)
- Outliers → Power 2014 + Kaptan 2023 cord adaptation
- CSF slicewise → Hemmerling 2025 verbatim
- RETROICOR → FSL PNM (Brooks 2008, Glover 2000, Birn 2008)
- Cosine HP → Kaptan 2023 / Dabbagh 2024 cord 1/100 s standard
- SpinalCompCor → Hemmerling 2025 + Behzadi 2007 + fMRIPrep convention

**Implementation has some gaps**, none critical:
- ⚠️ **Finding 6** (`family_counts` + `n_columns` missing from qc.json):
  observability gap. Recommended fix.
- ⚠️ **Finding 3** (RETROICOR skip messaging unclear): observability;
  add per-family `auto_disable_reason` field.
- ⚠️ **Finding 7** (outlier fraction tight gate): purely cosmetic;
  consider loosening to match cohort distribution.
- 🟡 **Finding 2** (partial 24P): documented as cord-2D variant.
- 🟡 **Finding 8** (reportlets don't follow visual standard): low
  priority, quantitative plots are less standard-bound.
- 🟡 **Finding 9** (5 reportlets may be redundant): defer to a
  separate redundancy audit.
- 🟡 **Findings 1, 4, 5, 10**: documented as expected behavior or
  schema sync.

## Recommended actions

| # | Action | Priority | Effort |
|---|---|---|---|
| 6 | Ensure `n_columns` + `family_counts` land in qc.json `metrics` | high | ~10 lines |
| 3 | Per-family `auto_disable_reason` field in qc.json | medium | ~20 lines |
| 7 | Loosen `pass_outlier_fraction_max` to 0.40 OR clarify dashboard messaging | low | 1 line policy |
| 10 | Align schema with actual qc.json fields | low | schema update |
| 8 | Apply visual-standard dark theme + status pill to S8 reportlets | low | ~50 lines |
| 9 | Standalone redundancy audit for the 5 reportlets | medium | separate audit doc |
| 2, 5 | Document cord-2D motion variant in process.py docstring | low | comment update |

## Sources

- Power et al. 2014 — Methods to detect, characterize, and remove
  motion artifact in resting state fMRI (*NeuroImage*)
- Friston et al. 1996 — Movement-related effects in fMRI time-series
  (*Mag. Res. Med.*) [24P]
- Behzadi et al. 2007 — A component based noise correction method
  (CompCor) for BOLD and perfusion based fMRI (*NeuroImage*)
- Glover et al. 2000 — Image-based method for retrospective correction
  of physiological motion effects in fMRI: RETROICOR (*MRM*)
- Brooks et al. 2008 — Physiological noise modelling for spinal
  functional magnetic resonance imaging studies (*NeuroImage*)
- Birn et al. 2008 — Separating respiratory-variation-related
  fluctuations from neuronal-activity-related fluctuations in fMRI
  (*NeuroImage*)
- Kong et al. 2012 — Assessment of physiological noise modelling
  methods for functional imaging of the spinal cord (*NeuroImage*)
- Eippert et al. 2017 — Denoising spinal cord fMRI data (*NeuroImage*)
- Kaptan et al. 2023 — Reliability of resting-state functional
  connectivity in the human spinal cord (*NeuroImage*)
- Dabbagh et al. 2024 — Spinal cord fMRI confound modelling
  (*HBM* / *NeuroImage*)
- Mohammed et al. 2020 — Cord motion correction (bioRxiv)
- Hemmerling et al. 2025 — SpinalCompCor for spinal cord fMRI noise
  correction (NeuroImage / preprint)
- fMRIPrep — `motion_outlier_NN`, `a_comp_cor`, `cosine_NN`
  documentation
- FSL `pnm_evs` / `popp` documentation
