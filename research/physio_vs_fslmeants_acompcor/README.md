# CSF aCompCor: FSL `fslmeants --eig` vs SPM PhysIO (CoSpi)

Validates that S8's CSF regressors (FSL `fslmeants --eig --order 5` on per-voxel
constant+linear-detrended BOLD) reproduce CoSpi's `spi12_acompcor.m`
(SPM PhysIO noise-ROI, `n_components = 5`, threshold 0.9) — same dataset/slice,
so the engine swap agreed with Gergely + Jan in Slack is safe.

## Setup
- One CSF slice (slice01, 34 voxels), 199 volumes, same detrended BOLD fed to both.
- PhysIO output `physio_slice01.txt` = **6 columns**: col1 = ROI **mean** (|r|=1.00
  with the computed ROI mean), cols 2–6 = **pc1–5**. `spi12` keeps cols 2–6, i.e.
  CoSpi's 5 regressors = the 5 PCs, **mean dropped**.
- FSL output `fsl_pcs_slice01_detrended.txt` = **5 columns** = our 5 eigenvariates.

## Result
Per-component absolute correlation (FSL pc_k vs its PhysIO match): **0.86–0.99**.

Subspace agreement (what actually matters for a GLM — the span, not the columns):

| Comparison | Canonical correlations |
|---|---|
| OUR-5 vs CoSpi-5 (PhysIO pc1–5) | **1.00, 1.00, 1.00, 0.996, 0.912** |
| OUR-5 vs PhysIO all-6 (mean+pc1–5) | 1.00, 1.00, 1.00, 1.00, 0.992 |

CSF ROI variance removed: **OUR-5 = 92.9%**, CoSpi-5 = 90.1%.

## Conclusion
The two 5-regressor sets span essentially the **same subspace** and remove the
**same CSF variance** → denoising-equivalent. The only nuance: PhysIO separates
the ROI mean into its own (dropped) column, whereas FSL's eigenvariate keeps the
mean inside `pc1` (CSF mean and pc1 are ~collinear). Net: our `pc1` ≈ the mean
CoSpi drops, so we sit one PC "shallower," costing only the 5th-axis 0.912 — and
including the mean is the canonical aCompCor behaviour (Behzadi 2007 / fMRIPrep).
No change needed. Exact PhysIO parity (spatial mean-center before the eig) is a
one-line option if ever wanted, but not worth it.

Reproduce: `detrend_lstsq.py` (the per-voxel const+linear detrend) → the `.txt`
PC files here. The slice-wise design uses **5 CSF regressors per slice**.
