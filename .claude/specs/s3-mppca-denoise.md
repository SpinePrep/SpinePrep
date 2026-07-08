---
status: implemented
---

# Spec: Optional MP-PCA thermal-noise denoising

> **Update 2026-06-20:** promoted from an S3 sub-stage to its own step,
> **S2B_func_denoise**, with QC reportlets. The placement/tool/method decisions
> below are unchanged; only the packaging moved. See "Separate step (S2B)".

## Separate step (S2B)
- New step **S2B_func_denoise** between S2 and S3 in `ALL_CHAIN_STEPS` (inserted
  without renumbering S3-S10, so all existing promotions stay valid).
- `steps/s2b/` (orchestrate + reportlets), top-level `S2B_func_denoise.py`, CLI
  `run/check` dispatch + choices, `policy/S2B_func_denoise.yaml`.
- Runs on the raw per-run 4D BOLD (after S1 inventory). Writes
  `denoise/<run_id>/desc-denoised_bold.nii.gz` + noise map per run; promoted to
  `done/<scope>/S2B`. **S3 consumes it** via `_find_denoised_bold` (same-wf, then
  promoted-S2B fallback by chain scope); falls back to raw when absent.
- OFF by default => clean passthrough (qc PASS, no outputs), chain advances.
- `link_chain` hardened to walk back past an absent S2B for the derivatives link.
- **QC reportlets (3)**: (1) noise σ map; (2) tSNR before vs after with median
  gain; (3) residual-structure check — temporal SD of removed = raw-denoised,
  which must be structureless (anatomy here = over-denoising). Plus an automatic
  gate: `residual_structure_corr` = corr(removed-SD, mean image); WARN >0.4, FAIL
  >0.6. Step-local metric = in-cord/tissue tSNR gain.

# Spec: Optional MP-PCA thermal-noise denoising (original S3 sub-stage)

## Objective
Add optional Marchenko-Pastur PCA (MP-PCA) thermal-noise denoising of the 4D
BOLD, off by default, literature-faithful and minimal.

## Decision: where, what, why

- **Placement — first S3 operation, on the raw per-run 4D BOLD, before
  localize/crop and before S4 motion correction.** MP-PCA requires non-
  interpolated data: any realignment/distortion/smoothing/resampling correlates
  the noise and breaks the Marchenko-Pastur i.i.d. assumption (MRtrix docs treat
  this as a failure condition). Matches the only cord-fMRI precedent — Kaptan/
  Eippert 2023 (NeuroImage): MP-PCA on the whole 4D cord series before moco,
  ~140% gray-matter tSNR gain without smoothing's spatial-smoothness inflation.
- **Tool — MRtrix3 `dwidenoise`** (Veraart 2016 + Cordero-Grande 2019), shelled
  out like SCT/FSL/ANTs. It is the reference implementation, auto-sizes the
  patch (7^3 for ~200-343 vols; the recommended voxels>=volumes regime), and
  emits a noise map. Captured in the per-run provenance for the S10 receipt.
- **Not NORDIC** — NORDIC needs complex/phase data or a noise scan; on this
  magnitude-only BOLD its advantages collapse (it falls back to MP-PCA
  internally), so plain MP-PCA is the simpler, equally-justified, better-tooled
  choice.
- **Not dipy** — same algorithm but I'd own the auto-patch logic and the noise-
  map; dwidenoise gives both for free and is the citable reference.

## Constraints / caveats (why opt-in)
- Magnitude data is Rician; dwidenoise does NOT correct the non-Gaussian floor
  (a tolerated high-SNR approximation).
- Low-rank denoising can cause activation "spreading" (also affects NORDIC).
- Cord/CSF/tissue patch mixing in the thin cord is unstudied for fMRI.
- Hence default OFF; falls back to the raw BOLD if dwidenoise is missing/errors
  (never silently corrupts the chain).

## Deliverables (implemented)
- `src/spineprep/lib/denoise.py` — `mppca_denoise()` shells dwidenoise
  (`-noise`, optional `-extent`, `-force`), returns (ok, noise_map, meta) with
  provenance (tool/version/extent), the step-local metric (tissue median tSNR
  pre/post + % gain), and noise median.
- `src/spineprep/steps/s3/session.py` — gated stage before S3.1; denoised
  series feeds the chain, raw BOLD untouched on disk (provenance).
- `policy/S3_func_init_and_crop.yaml` — `denoise: {enabled: false, extent: null}`
  with citations + caveats.
- `tests/test_S3_denoise.py` — 3 smoke tests (command, extent override,
  fallback). Real integration verified: noise estimate 14.94 vs true sigma 15.
- MRtrix3 3.0.4 installed (`dwidenoise`).

## How to use
Set `denoise.enabled: true` in the S3 policy and re-run from S3 (`--start S3`).
Off by default = zero change to existing runs. `denoise.nthreads` (default 6)
caps dwidenoise's internal thread pool -- it ignores OMP_NUM_THREADS, so without
this each call grabs all cores and oversubscribes when combined with run-level
batch-workers parallelism.

## Validated result (exp, June 2026)
Enabled on the balgrist `exp` scope, full chain re-run S3->S10. Real in-cord
tSNR gain (denoised vs raw, same cord masks, all 89 runs): median **5.72 ->
8.55, +50%** (per-run range +5%..+77%; motor runs ~+56%). Lower than Kaptan's
~140% because that is gray-matter-only while this is the whole cord seg
(WM+GM+partial volume). Provenance (tool/version/extent/in-cord tSNR pre-post)
recorded per run in the S3 qc.

## Follow-up (not done; deliberately out of this minimal change)
1. **Efficiency: denoise a cord-region crop, not the full 128x128 FOV.** The cord
   is ~30 vox; denoising the whole FOV (mostly air) is ~10x wasteful I/O+compute
   and made the HDD the bottleneck. Needs the localize-before-denoise reorder
   (S3.1 produces a coarse cord box first), which changes the step ordering --
   hence deferred from the minimal version. Would make denoise fast regardless of
   worker count.
2. Surface the in-cord tSNR gain on the S3 reportlet (currently QC-metric only).

## Decision Log
| Q | Choice | Rationale |
|---|--------|-----------|
| placement | first S3 op, pre-moco | MP-PCA needs raw/non-interpolated data; Kaptan 2023 precedent |
| tool | MRtrix3 dwidenoise (B) | reference impl, auto-patch, noise map, shell-out fit; install cost waived |
| method | MP-PCA not NORDIC | magnitude-only data; NORDIC needs complex/noise-scan |
| default | OFF | Rician/spreading/cord-patch caveats unsettled |
