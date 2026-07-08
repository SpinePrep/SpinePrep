---
search:
  boost: 2
---

# S2B: Functional Denoise (optional)

**Step Code:** `S2B_func_denoise`
**Depends on:** S1 (Input Verify)
**Required by:** S3 (Func Init & Crop) — consumes the denoised series when present
**Default state:** OFF (opt-in)

---

## Purpose

S2B optionally removes **thermal noise** — the random, structureless electronic
noise the scanner adds to every voxel — from the raw functional time series
before any other functional processing. Thermal noise is a large share of the
moment-to-moment fluctuation in the tiny spinal cord, so suppressing it can
meaningfully raise the temporal signal-to-noise ratio (tSNR), the basic measure
of how stable a voxel's signal is over time.

The step is **disabled by default**. When off, it is a clean passthrough: it
emits a PASS with no outputs and S3 simply reads the raw BOLD. It is opt-in
because, on thin cord data, aggressive denoising can also remove real signal
(see Caveats), so it ships behind QC that the human must eyeball.

---

## Algorithm

S2B runs **MP-PCA** (Marchenko–Pastur Principal Component Analysis) via MRtrix3's
`dwidenoise`. The method slides a small 3D patch through the image, decomposes
each patch's voxel-by-time matrix into principal components, and discards the
components whose strength is consistent with pure noise (predicted by random-
matrix theory). What remains is the signal estimate; the difference is the
removed noise.

- **Tool:** `dwidenoise` (MRtrix3), the reference MP-PCA implementation.
- **Why first:** MP-PCA assumes independent, identically-distributed noise across
  voxels. That assumption holds only on the **rawest, non-interpolated** data, so
  S2B runs at the very head of the functional chain — before S3 cropping and S4
  motion correction, both of which resample and correlate neighbouring voxels.
- **Patch size (`extent`):** unset by default, so `dwidenoise` auto-sizes the
  smallest isotropic patch that exceeds the volume count (e.g. 7×7×7 for ≤343
  volumes), keeping voxels ≥ volumes as the method requires.
- **Failure handling:** any `dwidenoise` error falls back to the raw series; the
  chain never breaks on an optional step.

### Literature basis

- **MP-PCA:** Veraart et al., *NeuroImage* 142:394–406 (2016).
- **Spinal-cord precedent:** Kaptan, Eippert et al., *NeuroImage* (2023) report
  a whole-cord tSNR gain; on the in-house balgrist cohort we measured roughly
  +50% in-cord tSNR.

---

## Caveats (why it is opt-in)

- Magnitude MRI data has a **Rician** (non-Gaussian) noise floor; MP-PCA does not
  correct for it.
- Low-rank denoising can cause activation **"spreading"** (blurring of true
  signal into neighbours).
- Patch mixing of cord, CSF and surrounding tissue in the very thin cord is
  unstudied for fMRI — which is exactly why the residual-structure QC below
  exists.

---

## QC Reportlets

S2B emits three reportlets per run. One look should tell you whether denoising
helped or quietly removed signal.

1. **Noise sigma map** (`desc-S2B_noise_sigma.png`) — where, and how much,
   thermal noise was estimated across the image. A healthy map is flat and
   anatomy-free.
2. **tSNR before vs. after** (`desc-S2B_tsnr_before_after.png`) — temporal SNR
   on matched slices and colorbar, annotated with the median tSNR gain. tSNR
   should visibly rise.
3. **Residual-structure check** (`desc-S2B_residual_structure.png`) — the
   temporal standard deviation of the **removed** signal (raw minus denoised).
   This must look like structureless noise. If cord or CSF anatomy is visible
   here, real signal was removed (over-denoising).

---

## Step Metric

The step-local truth metric is the **in-cord median tSNR gain (%)** from before
to after denoising. The step also reports a **residual-structure correlation** —
the correlation between the removed-noise map and the mean image — which gates
over-denoising directly.

| Metric | PASS | WARN | FAIL |
|--------|------|------|------|
| tSNR gain (%) | improves | below 0% gain | — |
| residual-structure correlation | ≤ 0.4 | 0.4–0.6 | > 0.6 (anatomy leaked → over-denoising) |

A negative tSNR gain warns (denoising did little or hurt); a residual that
correlates strongly with anatomy fails the run.

---

## Outputs

```
<workfolder>/denoise/<run_id>/
├── desc-denoised_bold.nii.gz    # denoised 4D series (S3 reads this when present)
└── denoise_noise_map.nii.gz     # estimated noise (sigma) map

derivatives/spineprep/{dataset}/sub-{id}/figures/
├── sub-{id}_..._desc-S2B_noise_sigma.png
├── sub-{id}_..._desc-S2B_tsnr_before_after.png
└── sub-{id}_..._desc-S2B_residual_structure.png
```

When denoising is disabled, no outputs are written and S3 falls back to the raw
BOLD.

---

## Policy

Key knobs in `policy/S2B_func_denoise.yaml`:

- `enabled: false` — opt-in master switch.
- `nthreads: 1` — `dwidenoise`'s own thread pool (it ignores `OMP_NUM_THREADS`).
- `extent: null` — auto-size the patch.
- `qc_thresholds.warn_residual_corr: 0.4`, `fail_residual_corr: 0.6`,
  `warn_min_tsnr_gain_pct: 0.0`.

---

## References

1. **MP-PCA:** Veraart et al. *NeuroImage* 142:394–406 (2016). [DOI](https://doi.org/10.1016/j.neuroimage.2016.08.016)
2. **Cord tSNR gain:** Kaptan, Eippert et al. *NeuroImage* (2023).

---

*Last updated: June 2026*
