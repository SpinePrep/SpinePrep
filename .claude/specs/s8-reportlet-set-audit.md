---
status: approved
---

# S8 reportlet+metric-set audit — redundancy + field-standard composition

Examines whether S8's 4 reportlets + ~15 metric families are well-chosen,
non-redundant, and complete, against the cord-fMRI / brain-fMRI
confound-modelling QC literature.

## Current S8 outputs

### Reportlets

| # | Reportlet | Content |
|---|---|---|
| 1 | `confound_columns` | Bar chart of regressor counts per family (6 bars) with status pill + n_columns_total + condition_number in subtitle |
| 2 | `fd_dvars_outliers` | 3-row time series (FD + DVARS + refRMS) with outlier-frame vertical markers + threshold lines |
| 3 | `pnm_peaks` | Cardiac peak ticks + respiratory phase trace (or "physio absent" placeholder) |
| 4 | `correlation_heatmap` | Pearson r matrix across all confound columns (multicollinearity proxy) |

### Metrics (qc.json)

| Metric | Type | Gating? |
|---|---|---|
| `n_volumes` | int | ❌ informational |
| `n_slices_with_csf` | int | ❌ informational |
| `n_columns_total`, `_motion`, `_outliers`, `_csf`, `_retroicor`, `_cosine`, `_spinalcompcor` | int×7 | ❌ informational |
| `outlier_fraction` | float | ✅ soft WARN |
| `condition_number` | float | ✅ PASS / WARN / FAIL |
| `fd_mean_mm`, `fd_max_mm` | float×2 | ❌ informational |
| `dvars_mean` | float | ❌ informational |
| `cardiac_bpm_estimate` | float / None | ❌ documented but **never populated** (see Finding 1) |
| `respiratory_cpm_estimate` | float / None | ❌ same |
| `spinalcompcor_median_pcs` | float / None | ❌ documented but **always NaN in global_3d mode** (see Finding 2) |

## Field-standard confound-matrix QC visualisations

Reviewed 7 published tools / pipelines:

| Source | Reportlets | Metrics |
|---|---|---|
| **fMRIPrep confound report** (Esteban 2019) | FD/DVARS time series; **carpet plot of BOLD with confound traces below** (the headline diagnostic); regressor count table; correlation heatmap | FD mean/max, DVARS mean, scrub fraction, condition number |
| **MRIQC** (Esteban 2017) | FD/DVARS panels; IQM table; carpet plot | IQM (image quality metrics) |
| **Power 2017 carpet plot** (*NeuroImage*) | Voxel × time intensity image, voxels grouped by tissue, confound traces (FD/DVARS) plotted underneath | — |
| **Power 2014** (*NeuroImage*) | FD time series; before/after scrubbing comparison | FD stats |
| **Kaptan 2023** (Eippert lab, *NeuroImage*) | Carpet plot of cord BOLD before/after confound regression; FD/DVARS | n_columns per family; cond. number |
| **CoSpine 2025** (Wei et al., *Sci Data*) | FD/DVARS scatter; regressor family table | FD/DVARS, outlier_fraction |
| **Glover 2000 RETROICOR** | Cardiac peak detection diagnostic + power spectrum of cardiac/resp signals | bpm, breathing rate |

**Field consensus pattern**:
1. **FD/DVARS time series** — universal (every tool)
2. **Carpet plot** — fMRIPrep / Power 2017 / MRIQC / Kaptan 2023; the gold-standard "where is the residual noise" diagnostic
3. **Confound count summary** — fMRIPrep, CoSpine 2025
4. **Correlation heatmap** — fMRIPrep multicollinearity proxy
5. **Physio peak QC** — Glover 2000 / FSL PNM when physio is present
6. **bpm + breathing rate** as numeric metrics — Glover 2000 standard

## Reportlet redundancy analysis

Each of the 4 current reportlets answers a different question:

| Reportlet | Question answered | Overlap with others |
|---|---|---|
| `confound_columns` | "What regressors got built?" (family counts) | ❌ unique |
| `fd_dvars_outliers` | "Where in time is the motion / noise?" | ❌ unique |
| `pnm_peaks` | "Is the physio signal clean?" | ❌ unique (only fires when physio present) |
| `correlation_heatmap` | "Is the design matrix degenerate?" | ❌ unique |

**Verdict**: ✅ no pairwise redundancy. Each reportlet stands alone.

But the literature consensus highlights **one missing diagnostic**:

### Missing: carpet plot (Power 2017 / fMRIPrep standard)

The carpet plot is the dominant "did I model the noise right" view in
brain fMRI. fMRIPrep ships it as the headline confound reportlet. For
cord, it has been adopted by Kaptan 2023 (showing cord-restricted
carpet pre/post confound regression).

What it adds beyond current 4:
- **Spatial localization**: WHERE in the cord does residual noise
  live? FD/DVARS time series shows WHEN; carpet shows WHERE +
  WHEN simultaneously
- **Spatial coherence check**: striped patterns indicate a confound
  the model isn't capturing; speckled = noise; gradient = bias field
- **Diagnostic when condition_number is OK but the BOLD still looks
  noisy**

What's the cost: one additional PNG per run. Cord-restricted carpet
is small (~100 voxels per slice × N volumes); render time ~1 s.

**Verdict**: ⚠️ add `carpet_plot` as a fifth reportlet. Matches
Power 2017 / fMRIPrep / Kaptan 2023 standard. Moves S8 from
"4 quantitative reportlets" to "1 spatial + 4 quantitative" —
matching the field consensus.

## Metric redundancy + correctness analysis

| Metric | Verdict | Reason |
|---|---|---|
| `n_volumes` | ✅ keep | unique, downstream tools need it |
| `n_slices_with_csf` | 🟡 derivable | technically equals `n_columns_csf` since each kept slice → one CSF column. Marginal value. |
| `n_columns_total` | ✅ keep | sum of `n_columns_*`, but convenience. fMRIPrep uses this. |
| `n_columns_*` per-family | ✅ keep | each unique, headline diagnostic |
| `outlier_fraction` | ✅ keep | gating metric |
| `condition_number` | ✅ keep | gating metric |
| `fd_mean_mm` / `fd_max_mm` | ✅ keep | Power 2014 + CoSpine 2025 standard |
| `dvars_mean` | ✅ keep | Power 2014 standard |
| **`cardiac_bpm_estimate`** | ❌ **bug** — declared but never populated. Always None in qc.json. The renderer computes bpm; should be saved as a metric too. |
| **`respiratory_cpm_estimate`** | ❌ **bug** — same |
| `spinalcompcor_median_pcs` | ❌ **bug** — always NaN. The metric is computed as `np.median(sc_meta.get("pcs_per_slice", [0]))`, but with `aggregation: global_3d` (the default), `pcs_per_slice` is `[]` (no per-slice PC count). `np.median([])` returns NaN. Either rename to a global metric or compute per-slice when applicable. |

## Proposed optimal set

### Reportlets (5)

```
1. carpet_plot              — NEW: Power 2017 / fMRIPrep standard.
                              Voxel × time BOLD intensity image,
                              cord-restricted, with FD/DVARS traces
                              below. The gold-standard "where + when
                              is the noise" view.

2. confound_columns         — KEEP: per-family regressor count bar
                              chart with status pill.

3. fd_dvars_outliers        — KEEP: 3-row time series. The Power
                              2014 universal diagnostic.

4. pnm_peaks                — KEEP: cardiac + respiratory QC when
                              physio is present.

5. correlation_heatmap      — KEEP: design-matrix multicollinearity
                              proxy.
```

### Metrics

```
KEEP unchanged:
  n_volumes, n_columns_total, n_columns_motion/outliers/csf/
  retroicor/cosine/spinalcompcor, outlier_fraction, condition_number,
  fd_mean_mm, fd_max_mm, dvars_mean

FIX (populate when PNM ran):
  cardiac_bpm_estimate
  respiratory_cpm_estimate

REPLACE (always-NaN field):
  spinalcompcor_median_pcs  →  spinalcompcor_n_components
                                (or NULL when SpinalCompCor disabled
                                / global_3d mode emits a single
                                fixed K)

DROP (derivable / marginal):
  n_slices_with_csf  →  equals n_columns_csf; redundant.
```

## Truthfulness review

| Claim | True? |
|---|---|
| "4 reportlets is the complete S8 QC set" | ⚠️ matches CoSpine 2025 but misses carpet plot (fMRIPrep / Power 2017 / Kaptan 2023 standard) |
| "cardiac_bpm_estimate populated when PNM ran" | ❌ — code comment says so, qc.json shows None even on the 5 PNM-ran runs |
| "spinalcompcor_median_pcs is the median PC count" | ❌ — always NaN in `global_3d` mode (the default) |
| "n_columns_* per family non-redundant" | ✅ |
| "fd_dvars_outliers + correlation_heatmap + confound_columns are non-redundant" | ✅ |

## Implementation map

| # | Action | Priority | Effort |
|---|---|---|---|
| 1 | NEW carpet plot reportlet — Power 2017 / fMRIPrep standard. Cord-restricted (S6 funccrop mask), voxels sorted by mean intensity, FD/DVARS traces below. | high | ~150 lines new renderer |
| 2 | FIX `cardiac_bpm_estimate` / `respiratory_cpm_estimate` — compute from `popp_card.txt` / `popp_resp.txt` same way the reportlet does, save in `metrics` dict | high | ~25 lines |
| 3 | RENAME `spinalcompcor_median_pcs` → `spinalcompcor_n_components`, compute correctly for global_3d mode (= fixed_n_components when fired; None when disabled or skipped) | medium | ~10 lines |
| 4 | DROP `n_slices_with_csf` from metrics (it equals `n_columns_csf`) | low | 1 line |
| 5 | Update schema for: new `carpet_plot` reportlet; remove `n_slices_with_csf`; rename spinalcompcor field; add cardiac/respiratory bpm fields | low | schema update |
| 6 | Dashboard registry: add `carpet_plot` label | low | 2 lines |

## Sources

- Power et al. 2017 — A simple but useful way to assess fMRI scan
  qualities (*NeuroImage*) — carpet plot
- Power et al. 2014 — Methods to detect, characterize, and remove
  motion artifact in resting state fMRI (*NeuroImage*)
- Esteban et al. 2019 — fMRIPrep (*Nat Methods*) — confound report
  layout
- Esteban et al. 2017 — MRIQC (*PLoS One*) — IQM + carpet
- Glover et al. 2000 — RETROICOR (*MRM*)
- Kaptan et al. 2023 — Reliability of resting-state functional
  connectivity in the human spinal cord (*NeuroImage*) — cord
  carpet pre/post confound regression
- Wei et al. 2025 — CoSpine database (*Sci Data*)
- Behzadi et al. 2007 — CompCor (*NeuroImage*)
- FSL PNM `popp` / `pnm_evs` documentation
- Internal: `.claude/specs/reportlet-visual-standard.md`,
  `.claude/specs/s8-algorithm-audit.md`
