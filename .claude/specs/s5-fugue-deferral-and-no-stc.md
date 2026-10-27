---
status: superseded
status_note: superseded   # FUGUE removed in v1 (v1-claims-ledger.md); STC section still valid
slug: s5-fugue-deferral-and-no-stc
kind: decision
needs_review: true        # the FUGUE deferral rests on a premise falsified 2026-08-12
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
- ~~No `intended_use: v1_validation` dataset ships a GRE phasediff fieldmap.~~
  **FALSIFIED 2026-08-12, and the correction unblocks the strongest available
  validation.** ds005883 ships GRE fieldmap data for **all 39 subjects** — 234 files,
  `acq-GRE_magnitude1` (TE 4.92 ms), `magnitude2` (TE 7.38 ms) and `phase1`. The phase
  image is scaled **−4096 to +4094**, which is Siemens phase-*difference* scaling, not
  absolute phase, so ΔTE = **2.46 ms** and `fsl_prepare_fieldmap` has every input it
  needs. The file is named `phase1` rather than the BIDS `phasediff`, which is the only
  reason `select_mode` never detects it.

  **This is better than a bug report.** ds005883 carries a reversed-PE pair *and* a GRE
  map for the same 39 subjects, which is precisely the dataset this spec says does not
  exist: **two independent measured fields on the same run**. That makes it the natural
  validation set for FUGUE, and it also gives F1 a second physical referee — the finding
  currently rests on one measured field, and this would test it against another obtained
  by a different physical mechanism. Before implementing, check that the phase map
  unwraps in the neck; cord GRE maps often do not, and a documented unwrap failure is
  itself the measured reason the cord field prefers reversed-PE.
- The rest of the cohort spans reversed-PE EPI pairs (-> TopUp) and image-only runs
  (-> SyN).
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
- The S10 methods boilerplate states the FUGUE path is specified-but-not-
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

**Verdict (literature-checked 2026-06).** Skipping STC is correct and matches
field-standard practice for cord-only fMRI — but the original justification in
this spec was wrong and has been replaced. A three-angle literature review
(cord pipelines, general STC methodology, cord-specific acquisition) settled it.

**Every cord-only reference pipeline omits STC** — verified, not assumed:
- Eippert 2017 (cervical RS-FC, TR 1890 ms, 16 slices): slice-wise motion
  correction -> PNM/RETROICOR -> registration. No STC.
- Barry 2014 (eLife, cervical RS-FC): 14-step pipeline, slice-wise motion
  correction (AFNI 3dWarpDrive) + RETROICOR + bandpass. No STC.
- Kaptan / Dabbagh 2023-24 (Imaging Neuroscience; read directly from full text):
  MP-PCA -> slice-wise motion correction -> segmentation/normalization ->
  RETROICOR slice-wise PNM -> SUSAN smoothing. A whole-document search for
  "slice timing / interpolation / interleaved" returns nothing.
- Spinal Cord Toolbox fMRI tutorial + `sct_fmri_moco`: no slice-timing step.
- Hemmerling/Bright SpinalCompCor 2025; Cohen-Adad "Ten Key Insights" review:
  STC not used / not even discussed.
- The ONE clear STC user is *simultaneous brain+spinal-cord* acquisition
  (Harita/Stroman/Barry, PLOS Biology), where STC aligns the cord slices with
  the *brain* slices — a brain-driven rationale that does not apply to a
  cord-only pipeline.

**Why skipping is defensible (the corrected reasons).**
- Resting-state and block-design signal is low-frequency (< 0.1 Hz), the band
  where STC has little effect (Parker & Razlighi 2019).
- Event-related task sensitivity is instead recovered with a hemodynamic
  temporal-derivative regressor in the GLM — the standard substitute (Kong;
  general fMRI practice).
- STC's temporal interpolation interacts poorly with motion correction, and the
  cord is motion/physiology-dominated; applying them sequentially each violates
  the other's assumption. This is why the HCP minimal pipeline also omits STC
  (Glasser 2013; Kasper 2016; Parker & Razlighi 2019).
- SliceTiming is better spent assigning each slice its cardiac/respiratory phase
  for the RETROICOR physiological regressors (Brooks 2008) than on interpolating
  the BOLD.

**Honest caveat (this is a trade-off, not a law).** At TR 1.5-3 s with a 2D
sequential slice stack, STC is *not* negligible — Kasper 2016 measured ~16%
benefit at TR 2 s with conventional tools, largest for event-related designs.
The earlier claim here ("short stack / long TR makes it marginal; interpolation
would correlate the thermal noise") was not supported and was removed. One group
(Kong, on the spinalcordmri.org forum) reports STC recently improved their tSNR,
activation, and connectivity and may recommend it in future. So the decision is
"omit STC to match field practice and avoid the STC x motion interaction, and
recover task timing via GLM temporal derivatives, accepting a small, known
sensitivity cost" — not "STC provides no benefit here."

**Future option.** If event-related cord-task sensitivity becomes a priority, STC
could be added as an *optional* pre-moco step (mirroring how MP-PCA denoise ships
opt-in), applied after motion/distortion correction per the HCP ordering, and
validated on a task dataset. Not implemented now — the marginal, contested
benefit does not justify the STC x motion-correction risk by default.

**Declared in.** The S10 auto methods boilerplate states that no STC is performed
and gives the corrected rationale, so downstream users are not left guessing.

**Key sources.** Eippert 2017 (PMC5315056); Barry 2014 (PMC4120419 / eLife
02812); Kaptan/Dabbagh 2023-24 (Imaging Neuroscience); SCT fMRI tutorial;
Hemmerling/Bright 2025 (PMC11785179); Cohen-Adad "Ten Key Insights" (PMC6162663);
Harita/Stroman/Barry brain+cord (PMC7363111); Sladky 2011 (PMID 21757015);
Kasper 2016 (PMC5274797); Parker & Razlighi 2019 (PMC6736626); Glasser 2013 HCP;
spinalcordmri.org "Slice timing in spinal cord fMRI" forum thread.

## Unverified / Assumptions

Added 2026-08-12 alongside the correction to the FUGUE deferral premise.

**Verified in this session, on disk:**
- ds005883 ships 234 GRE files, `acq-GRE_magnitude1` / `magnitude2` / `phase1`, for all
  39 subjects. Checked by directory listing.
- Echo times 4.92 ms and 7.38 ms, read from the JSON sidecars, so ΔTE = 2.46 ms.
- The `phase1` image spans −4096 to +4094 in float64, read from the array itself.

**Assumed, not verified:**
- That the ±4096 range means a Siemens *phase-difference* map rather than a rescaled
  absolute phase. This is the standard `gre_field_mapping` export and the two-magnitude,
  one-phase layout is that sequence's signature, but the sidecars carry no `EchoTime1` /
  `EchoTime2` pair and no `Units`, so the interpretation rests on convention. **Check
  before implementing:** a phase-difference map has near-zero mean inside tissue and
  wraps smoothly; an absolute phase map does not.
- That the map unwraps usably in the cervical neck. Cord GRE fieldmaps frequently do not,
  and this has not been attempted here.
- That `IntendedFor` links these fmaps to the BOLD runs. Not checked; the sidecar read in
  this session returned `IntendedFor: None` for sub-01, so the S5 matcher would fall
  through to its permissive default.

**Unaffected by the correction:** no run was silently degraded. ds005883 also has a
reversed-PE pair, so every one of its runs already ran `topup`. What was wrong is the
stated *reason* for deferring FUGUE, not the outcome of any run.

**Section 2 (no slice-timing correction) is untouched by this correction** and its
sources stand as written.
