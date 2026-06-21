---
status: approved
---

# Spec: FUGUE deferral + no slice-timing correction (S4/S5)

Two deliberate deviations from a "complete" SDC/temporal-preprocessing menu,
documented here per the project principle that deviations cite their reason.

## 1. FUGUE (GRE-fieldmap) distortion correction is deferred, not implemented

**State.** `steps/s5/process.py::_run_fugue()` is a stub that always returns
FAIL. The mode picker (`steps/s5/mode.py::select_mode`) still *selects* `fugue`
when a run has a GRE phasediff + magnitude pair, so the capability is detected;
the dispatcher then falls through to SyN.

**Why deferred.**
- No `intended_use: v1_validation` dataset ships a GRE phasediff fieldmap. The
  cohort spans reversed-PE EPI pairs (-> TopUp) and image-only runs (-> SyN).
- Shipping an unvalidatable code path violates the project's lock-and-ship rule
  (#6) and "visual QC is the validator" (#5): we cannot eyeball a FUGUE reportlet
  on data we do not have. Speculative SDC code that never runs is liability, not
  coverage.
- SyN is a defensible fallback for GRE-only data (cord-mask-restricted, the v1
  image-only default), so no run is left uncorrected.

**Truthfulness fix applied (this is the part that shipped).** The fugue->syn
fall-through is no longer silent:
- The dispatcher logs it loudly (parity with the existing topup->syn log).
- The run record carries both `mode` (what ran) and `requested_mode` (what the
  data implied), and appends a `failure_reasons` note
  "distortion mode fell back from fugue to syn (FUGUE not implemented in v1)".
- The S11 methods boilerplate states the FUGUE path is specified-but-not-
  implemented and that GRE-only data falls back to SyN.

**To finish FUGUE later.** Implement `_run_fugue` with the standard FSL recipe
(`fsl_prepare_fieldmap` from phasediff+magnitude -> `fugue --loadfmap` to unwarp
the BOLD using the EPI dwell time / `EffectiveEchoSpacing`), add a per-slice
displacement reportlet, and validate on a dataset that actually has GRE maps
before flipping it on. Cite Jenkinson 2003 (FUGUE) at that point.

## 2. No slice-timing correction (STC) is performed

**State.** The pipeline never slice-time corrects the BOLD. `SliceTiming` is
captured in the S1 inventory and consumed only by S8 to phase the RETROICOR
cardiac/respiratory regressors (FSL PNM `--slicetiming`).

**Why.** This matches the field's reference cord-fMRI pipelines (Eippert 2017;
Kaptan 2023), which do not STC cord data. The cervical cord slice stack is short
and TRs are long; the temporal interpolation STC requires would correlate the
thermal noise (the same i.i.d. concern that motivates running MP-PCA denoising
*before* any interpolation, see s3-mppca-denoise.md). The cost (interpolation
artifact) outweighs the benefit (sub-TR timing alignment) for cord task/rest
designs at this TR.

**Declared in.** The S11 auto methods boilerplate now states explicitly that no
STC is performed and why, so downstream users are not left guessing.
