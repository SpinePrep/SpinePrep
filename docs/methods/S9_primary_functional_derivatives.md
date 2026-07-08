---
search:
  boost: 2
---

# S9: Primary Functional Derivatives

**Step Code:** `S9_primary_functional_derivatives`
**Depends on:** S7 (PAM50 warps and spinal levels)
**Required by:** S10 (QC Aggregation & Release)

---

## Purpose

S9 produces the **final, analysis-ready functional outputs**: the preprocessed
BOLD series in both native and PAM50 template space, plus temporal-SNR maps and a
per-vertebral-level tSNR table. It performs the cord-aware spatial smoothing and
packages everything so an analyst can drop the data straight into a general
linear model (GLM).

S9 does **not** high-pass filter the BOLD (the cosine basis from S8 handles
drift) and does **not** regress out confounds (that is the analyst's GLM, using
the S8 table).

---

## Algorithm

### 1. Cord-aware smoothing

Brain-style isotropic smoothing would blur signal out of the thin cord. Instead,
S9 smooths **along the straightened cord axis** using SCT's
`sct_smooth_spinalcord` (CoSpine lineage), which straightens the cord per volume
before applying the kernel.

- **Kernel:** σ = 1, 1, 5 mm in the right-left, anterior-posterior and
  superior-inferior directions (FWHM ≈ 2.35 × 2.35 × 11.8 mm). The heavy
  superior-inferior smoothing exploits signal repetition along the cord while the
  light in-plane smoothing preserves the cord cross-section.
- An alternative in-plane Gaussian method is available; it applies no
  through-slice blur.

Both a **smoothed** and an **unsmoothed** series are kept, so analysts who prefer
to smooth at modelling time can use the unsmoothed data.

### 2. PAM50 template-space outputs

The BOLD is warped into the PAM50 spinal-cord template. Warping the full 0.5 mm
template grid would cost ~17 GB per run; instead S9 crops the template to each
run's cord field of view (with padding) and warps directly into that cropped
grid, yielding ~1–2 GB per run at the same 0.5 mm resolution. The template-space
BOLD ships co-gridded with its cord mask, so it is GLM-ready out of the box. Both
smoothed and unsmoothed PAM50 series are emitted, alongside a PAM50 functional
reference (temporal mean) and a PAM50 tSNR map.

### 3. Per-level tSNR

Using S7's PAM50 spinal-level labels, S9 writes a table of mean and standard-
deviation tSNR per vertebral level — the cohort-comparison metric S10 plots as a
heatmap.

---

## Step Metric and QC

The step-local truth metric is the **in-cord tSNR ratio** (post-smoothing /
pre-smoothing). Cord-aware smoothing should raise tSNR by roughly 1.5–2.5×.

| Metric | PASS | WARN | FAIL |
|--------|------|------|------|
| tSNR ratio (post/pre) | ≥ 1.5 | ≥ 1.2 | < 1.0 (smoothing hurt → upstream issue) |
| median in-cord tSNR | ≥ 5.0 | ≥ 3.0 | — |
| cord-mask Dice (pre vs. post) | ≥ 0.95 | ≥ 0.85 | — |

S9 also verifies the achieved smoothness by estimating per-axis FWHM in the cord
mask and checking it against the requested kernel within tolerance.

---

## Outputs

```
derivatives/spineprep/{dataset}/sub-{id}/func/
├── sub-{id}_..._space-PAM50_desc-smoothed_bold.nii.gz     # GLM-ready, template space
├── sub-{id}_..._space-PAM50_desc-unsmoothed_bold.nii.gz
├── sub-{id}_..._space-PAM50_desc-funcref.nii.gz           # temporal mean
├── sub-{id}_..._space-PAM50_desc-tsnr.nii.gz              # tSNR map
├── sub-{id}_..._space-PAM50_desc-cordmask.nii.gz          # co-gridded cord mask
└── sub-{id}_..._desc-tsnr_per_level.tsv                   # per-vertebral-level tSNR

derivatives/spineprep/{dataset}/sub-{id}/figures/
└── sub-{id}_..._desc-S9_tsnr_map_axial.png
```

---

## References

1. **Cord-aware smoothing:** Spinal Cord Toolbox `sct_smooth_spinalcord`;
   De Leener et al. *NeuroImage* 145:24–43 (2017). [DOI](https://doi.org/10.1016/j.neuroimage.2016.10.009)
2. **PAM50 template:** De Leener et al. *NeuroImage* 165:170–179 (2018). [DOI](https://doi.org/10.1016/j.neuroimage.2017.10.041)

---

*Last updated: June 2026*
