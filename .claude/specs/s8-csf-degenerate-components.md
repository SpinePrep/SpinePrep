---
status: implemented
---

# S8: fabricated CSF components from dead slices, and design-matrix rank

Written 2026-07-18, from the full 9-dataset / 456-run cohort run.

## What was found

Four runs in `ds005883_cospine_pain` failed S8's condition-number gate at ~1e16 —
a numerically singular confound design. The mechanism turned out to be neither
collinearity nor an artifact-dominated PCA.

`_csf_acompcor_slicewise` guards each slice with a count-only floor:
`nv < min_voxels_per_slice`. It never asks whether those voxels contain anything.
The CSF mask is warped in from anatomical space (S2 canal minus cord, through S6)
and is **not clipped to the acquired slab**, so on a run whose bottom slice was
never acquired the mask still claims voxels there. Verified on `sub-33_task-pain`:
slice 0 holds 51 CSF mask voxels, **0 of them carrying any signal**, slice mean
exactly 0.00, while slices 1-27 are fully live.

`fslmeants --eig` is then handed an all-zero 51x226 matrix. For a zero matrix every
singular value is zero and the singular vectors are mathematically arbitrary;
LAPACK returns identity basis vectors, which fslmeants variance-normalises to
sqrt(226) = 15.0333 — exactly the value in the TSV. The result is **five unit delta
functions per dead slice**. They are not degenerate components; they are not
components at all.

Exact singularity follows only where such a delta lands on a frame that a one-hot
outlier regressor already flags. That is why only 4 runs failed.

## Prevalence (measured, 456 runs)

| | |
|---|---|
| runs with >=1 dead CSF slice | **36 (7.9%)** |
| fabricated regressors shipped | **180** (5 per dead slice) |
| dead slice location | **35 of 36 at z=0** (slab edge) |
| CSF mask voxels empty cohort-wide | 1838 / 659244 (**0.3%**) |
| designs numerically singular | 39 (9.5%) |

So the 4 failures were the visible tip: ~32 further runs PASSed while carrying
fabricated regressors that happened not to collide with an outlier column.

## What this did and did NOT do

It did **not** corrupt anyone's residuals. With a pseudo-inverse the residuals of a
rank-deficient design are unique and correct; only the individual coefficients
become unidentifiable (Poline, Kherif & Penny, SPM book ch. 8; Mumford, Poline &
Poldrack 2015, PLoS ONE 10:e0126255 — "the overall model fit is not impacted by the
collinearity in the model"). Confound regression uses only residuals and never
interprets a nuisance beta. Do not claim otherwise in the paper.

What it DID do:
1. shipped meaningless regressors to analysts in 36 runs;
2. turned the condition-number gate into an alarm with no remedy;
3. **broke the degrees-of-freedom count** — the standard practice of charging one
   DOF per column holds only for linearly independent columns.

## Fix (implemented)

1. **Live-voxel floor** in `_csf_acompcor_slicewise`, beside the existing mask-voxel
   floor: a slice must have `min_voxels_per_slice` voxels that actually carry
   temporal signal. Skipped slices are recorded with `skipped_reason`. Verified on
   `sub-33`: slice 0 now skipped as `no_signal_in_mask`, no `csf_slice00` columns,
   135 CSF columns instead of 140, zero delta-like columns anywhere.
2. **Drop zero-variance regressors** before writing the TSV, reporting the count —
   the rule AFNI `3dTproject` applies ("discarded as all zero, after censoring").
   Guards every regressor family, not just CSF.
3. **Report rank** — `design_rank`, `design_rank_deficit`, `regressor_frame_ratio`
   in `qc.json`, so an analyst can use `n - rank(X)` for DOF instead of the column
   count. No tool found does all of: warn, use rank-based DOF, and surface it.
   AFNI warns but uses column-count DOF; nilearn truncates by pivoted QR but never
   warns; CONN warns only at full saturation.
4. **Citation honesty** — per-slice CSF PCA has a genuine cord precedent in Barry
   et al. 2014 (eLife 3:e02812), which used an adaptive 2-6 per slice. The **fixed
   5 is SpinePrep's own choice**, from the in-house CoSpi `spi12_acompcor.m`, and
   must not be attributed to a publication. The cord majority (Eippert 2017, Kaptan
   2023, Dabbagh 2024, EPFL) uses a mean high-variance CSF time course, not PCA;
   the two have never been compared head-to-head in the cord.

## Second finding: design width

The design is built for a SLICEWISE GLM. Measured flat across the cohort:
median **139 regressors against 227 frames**; 86% of designs spend over half the
available DOF; **8.7% have more regressors than frames** — rank-deficient by
construction, independent of the bug above.

`reference_analysis.py` was itself doing the flat regression it warns against. It
now residualizes slice by slice, each slice cleaned with the global regressors plus
its own per-slice columns, and records `regressors_per_slice` in its provenance.

## Deferred

Projecting the motion and spike regressors out of the per-slice CSF time-series
*before* `fslmeants --eig` would remove artifact-dominated components rather than
merely keeping the matrix invertible (CONN precedent; Morfini et al. 2023,
10.3389/fnins.2023.1092125). It does not address the dead-slice case at all —
projecting anything out of an all-zero series leaves zero — and it changes the
components on every run, so it needs its own validation. Filed as a candidate issue.

Intersecting the CSF mask with a BOLD coverage mask at construction time is the
principled fix for the root cause, but it changes mask geometry for every run and
would need revalidation across all 8 datasets. The live-voxel floor gets the same
protection with no effect on healthy data.
