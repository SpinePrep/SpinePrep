---
search:
  boost: 2
---

# S8: Confounds & Physio Regressors

**Step Code:** `S8_confounds_and_physio_regressors`
**Depends on:** S3 (frame metrics), S4 (motion), S6 (warps), S7 (PAM50 levels)
**Required by:** S10 (QC Aggregation & Release)

---

## Purpose

S8 builds the **nuisance regressors** — the time-courses an analyst later removes
from the BOLD signal so that physiological pulsation, motion and scanner drift do
not masquerade as neural activity. It does not regress anything itself and does
not resample the BOLD: it computes the regressors in native functional space and
writes them to a table for the downstream general linear model (GLM).

The output is one BIDS-Derivatives `*_desc-confounds_timeseries.tsv` per run,
with a JSON sidecar describing each column.

> **No slice-timing correction.** The pipeline never temporally resamples the
> BOLD. The slice-timing metadata in the BIDS sidecar is used here only to phase
> the RETROICOR cardiac/respiratory regressors — following the cord-fMRI field
> standard (Eippert 2017; Kaptan 2023).

---

## Regressor families

S8 emits five families, a mix of single columns and per-slice columns. CSF and
RETROICOR are computed **per slice** because cord GLMs are often fit slice by
slice.

### 1. Motion and outlier flags (always present)

- **Translations** `trans_x`, `trans_y`: slice-mean translation per volume from
  S4's motion parameters, plus first derivatives.
- **Framewise displacement (FD)**: `|Δtrans_x| + |Δtrans_y|` — the 2D cord
  adaptation of Power's FD.
- **DVARS / RefRMS**: already computed at S3; repacked here with outlier flags.
- **Outlier flags**: a volume is flagged if FD > **0.5 mm** (Power 2014 lenient
  scrubbing cutoff) **or** if DVARS/RefRMS exceeds a box-plot fence of
  Q3 + 1.5·IQR, the documented default of FSL `fsl_motion_outliers` (Tukey 1977),
  chosen because the cord's DVARS distribution is heavy-tailed. This differs from
  the cord literature, which thresholds on the run's own mean plus a multiple of
  its standard deviation (Kaptan et al., 2023 use 2 SD; Dabbagh et al., 2024 use
  3 SD), and from fMRIPrep, which thresholds standardised DVARS at 1.5 and FD at
  0.5 mm.

### 2. CSF aCompCor, per slice (when a CSF mask exists)

The top **5 principal components** of the cerebrospinal-fluid (CSF) signal in
each slice (`csf_slice{z}_pc{k}`). aCompCor (Behzadi 2007) captures shared
physiological fluctuation. Computed with FSL `fslmeants --eig` after per-voxel
constant+linear detrending, on a subject-specific CSF mask (S2 canal minus cord,
warped to native func via S6; falls back to the PAM50 CSF mask). No erosion (the
cord-CSF rim is too thin); slices with fewer than 5 voxels are skipped.

### 3. RETROICOR, per slice (when readable physiology is present)

Cardiac and respiratory phase regressors via FSL PNM, auto-disabled when physio
recordings are absent. With cardiac order 4, respiratory order 4 and interaction
order 2, that is 8 + 8 + 16 = **32 regressors** per slice (Kaptan 2023 / Dabbagh
2024 cord recipe), aggregated to one column per regressor by averaging across
cord-bearing slices. Optional heart-rate and respiration-volume-per-time (RVT)
slow regressors are added.

### 4. Cosine drift basis (default ON)

A discrete-cosine high-pass basis — the regressor-based equivalent of high-pass
filtering — with a **0.01 Hz** (1/100 s) cutoff (Kaptan 2023 / Dabbagh 2024 cord
standard). Disable when the analyst's GLM owns high-pass filtering.

### 5. SpinalCompCor (default ON)

A cord-specific anatomical-noise component method (Hemmerling 2025). It dilates
the cord-plus-CSF mask by 18 mm, subtracts the original to define a surrounding
"noise" region, and extracts the top 5 principal components of that region's
signal. By default these are taken globally with a fixed component count; an
optional, slower per-slice parallel-analysis selection (IAAFT surrogates) is
available for research use.

---

## Step Metric and QC

The step-local check is the **design-matrix condition number** — a number that
flags when regressors are so correlated that the GLM becomes numerically
unstable. Because the per-slice CSF regressors are applied slice-locally
downstream, S8 scores each slice's real design (global regressors plus that
slice's own columns) and gates on the **worst slice**.

| Metric | PASS | WARN |
|--------|------|------|
| condition number (worst slice) | ≤ 1000 | ≤ 10000 |
| outlier fraction (FD or DVARS/RefRMS) | ≤ 0.20 | ≤ 0.40 |

High motion only soft-warns and never fails: whether to drop a high-motion run is
the analyst's call at GLM time.

---

## Outputs

```
derivatives/spineprep/{dataset}/sub-{id}/func/
├── sub-{id}_task-{task}_desc-confounds_timeseries.tsv   # all regressor columns
└── sub-{id}_task-{task}_desc-confounds_timeseries.json  # column descriptions

derivatives/spineprep/{dataset}/sub-{id}/figures/
└── sub-{id}_..._desc-S8_confound_columns.png            # regressor overview
```

---

## References

1. **aCompCor:** Behzadi et al. *NeuroImage* 37(1):90–101 (2007). [DOI](https://doi.org/10.1016/j.neuroimage.2007.04.042)
2. **FD / scrubbing:** Power et al. *NeuroImage* 84:320–341 (2014). [DOI](https://doi.org/10.1016/j.neuroimage.2013.08.048)
3. **Cord RETROICOR recipe:** Kaptan et al. *NeuroImage* (2023); Dabbagh et al. (2024).
4. **SpinalCompCor:** Hemmerling et al. (2025).

---

*Last updated: June 2026*
