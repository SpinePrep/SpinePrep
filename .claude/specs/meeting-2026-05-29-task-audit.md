---
status: approved
title: 2026-05-29 Gergely 1-on-1 — audited task ledger
source: vox transcript 2026-05-29_20260529_145244 (Gergely + Kiomars, toolbox review)
audited: 2026-06-05
method: 5 parallel codebase audits (S4, S5, S6/S7, S8, S9+) grounding each meeting item in spec+policy+src+schema with file:line evidence
---

# 2026-05-29 meeting — audited task ledger

Every item from the meeting was cross-checked against the actual codebase.
Status vocabulary: **DONE** (shipped) · **BUG** (real defect to fix) ·
**FEATURE** (genuine open build) · **DECISION** (knob exists, value/default
pending) · **DOC** (code right, docs stale) · **STRATEGY** (non-code) ·
**ADMIN** (lab/process) · **SEPARATE** (other project).

## Headline corrections to the meeting record
1. **"FLIRT 2D is the only step not done" — false.** The FLIRT 2-DOF (X/Y-only)
   bulk MoCo is already implemented, committed, fast, and working
   (`src/spinalfmriprep/lib/moco.py:79-89`, schedule `config/flirt_XY_only.sch`).
   The s4 specs/policy still *describe* the old `phase_cross_correlation` method
   — docs are stale, not the code.
2. **"S9+ not ready yet" — outdated.** S9 (smoothing, tSNR, per-level tSNR,
   smoothed+unsmoothed, FWHM) is DONE and locked; S10 (ROI/connectivity + pooled
   ICC) and S11 (release report) are implemented (late-May 2026 commits).
3. **"correction at S7" axis label — already gone.** That string exists nowhere
   in the code; current label is `"PAM50 spinal level (1..20)"`. The PI saw a
   stale cached PNG.
4. **There is no GLM / z-stat endpoint in this pipeline at all.** It is a
   *preprocessing* pipeline ending at S9 derivatives / S10 connectivity. Every
   "test it in the GLM / check the z-stats" item must be reframed to an S9/S10
   endpoint or flagged as downstream/out-of-scope.
5. **The PI's "really good find" (coreg with vs without SDC) cannot be run
   today** — no ablation toggle exists anywhere. It is the single most valuable
   genuine build on this list.
6. The audit surfaced **real bugs the meeting did not mention** (S4 FD trace,
   S8 PNM count, S7 level labels, S6 orientation markers, stale failing tests).

---

## Execution log
- **2026-06-07 — BUG-2 FIXED & verified.** `interaction_order` now = FSL multc/multr
  order (2 full, 0 short); removed `sqrt`+floor. Empirically reran `pnm_evs` on real
  physio: 32 EVs (full), 16 (short). No regressions (pre-existing failures only).
- **2026-06-07 — BUG-1 FIXED & verified.** S4 FD now reads SCT's signed
  `moco_params_x/_y.nii.gz` (mean-over-z) + Stage-1 bulk → FD = bulk+slicewise.
  Test mock now emits real SCT schema + a FD>0 regression guard; 9/9 S4 tests pass.
- **NEW finding → BUG-1b** (below): S8's analysis-grade FD is slicewise-ONLY (omits
  Stage-1 bulk). Documented, not yet fixed (changes confounds; needs decision/rerun).
- Pre-existing failures (NOT from W1): `test_S5_unit.py` ×5 = BUG-5 (stale tests);
  `test_qc_dashboard` + `test_S2_labeling` dashboard ×2 = separate, unrelated.
- **2026-06-09 — BUG-1c FIXED & verified** (found during a "verify moco code"
  pass). S4 Stage-1 bulk correction applied the FLIRT shift with the wrong sign;
  `moco.py` now uses `shift=[-tx, +ty]`. Empirically: a known (+dx,+dy) shift is
  recovered MSE 1328→9 only by `[-tx,+ty]`; old `[+tx,+ty]` AND the first
  workflow's proposed `[-tx,-ty]` both made MSE WORSE than no correction. Added
  an MSE-improvement assertion to `test_S4_unit.py` (the check it used to skip).
- **Reg cohort is STALE**: all 11 reg runs ran (10 PASS/1 WARN) but predate the
  BUG-1/1c/2 fixes (S8 still emits 80 EVs). A rerun from S4 is required:
  `python scripts/full_chain_reg.py --start S4`.
- **2026-06-09 — reg rerun #1 (S4→S11) exposed BUG-1d.** S4–S7 regenerated fine
  (S4 FD correctly larger), but S8 emitted 80 EVs again → condition_number FAIL
  on pain/handgrasp. Cause: the chain symlinks every step's `work/` to S1's
  shared tree, so S8's `_run_pnm` reused the stale May-28 `ev_evlist.txt` (80
  entries) — `pnm_evs` rewrote evev001–032 but 48 stale EVs + the stale evlist
  shadowed the count. **Fixed (BUG-1d):** `_run_pnm` now deletes stale
  `ev*.nii.gz`/`ev*evlist*.txt` before regenerating → deterministic reruns.
  Re-running S8→S11 to validate (expect 32/16/0 EVs, condition_number recovered).

## TIER A — Real bugs (audit-surfaced; highest value)

### BUG-1 — S4's own FD/QC silently drops Stage-2 motion (scope: S4 only)
`steps/s4/process.py:337-340` adds Stage-2 motion only `if 'X'/'Y' in
p2.columns`, but SCT's `moco_params.tsv` has a single column
`mean(sqrt(X^2+Y^2))` — so the guards are ALWAYS false (a membership guard, NOT
a try/except) and S4's FD is built from Stage-1 bulk `tx_coarse/ty_coarse` only
(nonzero-but-bulk-only — verified; the old "all 0.0" note was a different,
stale, file-specific artifact). **Scope (verified by workflow):** this corrupts
ONLY S4's step-local FD/QC gate (`max_fd_mm`) and the S4 motion reportlet. It
does NOT reach the confounds matrix — S8 computes motion independently from
`moco_params_x/_y.nii.gz` (mean-over-z, `s8/process.py:39-75`). `tests/
test_S4_integration.py:90` mocks a fake `X\tY` (all-zero) header that hides it.
**Fix:** read SCT's real output (the `_x/_y` NIfTI fields or the magnitude
column) in S4; fix the test mock. **Open sub-q:** confirm whether S8's own FD
captures both bulk(Stage-1)+slicewise(Stage-2) or only Stage-2.
*(Meeting "how many regressors": 2 motion AXES — tx,ty, no Z/rotations — and
FD=|Δtx|+|Δty|; BUT S8 emits 5 scalar motion columns: trans_x, trans_y,
+derivative1 each, +FD — so Gergely's "five" was correct.)*

### BUG-2 — S8 RETROICOR emits 80 regressors, not the intended 32 (empirically confirmed)
`steps/s8/process.py:446` `mult = int(sqrt(interaction_order))` = int(sqrt(16))
= 4 → `pnm_evs --multc=4 --multr=4` → interaction EVs = 4·multc·multr = 64 →
8c+8r+64 = **80** on long runs. Verified by RUNNING pnm_evs across parameter
sweeps; FSL `pnm_evs.cc:358` nreg = 2·oc+2·or+4·multc·multr. Intended **32** =
8c+8r+16int — confirmed verbatim in Kaptan 2023 ("…32 regressors") & Dabbagh
2024 ("32 noise regressors…+ an additional CSF regressor" → 33 total;
interaction method = Harvey 2008). **Fix (verified):** `mult = 2`
(= `sqrt(interaction_order/4)`) → 16 interaction → 32. **Short-run is NOT a
clean value:** n_vol<200 sets interaction_order=0 but the `max(1,…)` floor
forces mult=1 → 4 interaction → **20** (8+8+4), not 16 — so decide the intended
short-run count when fixing. 0 on no-physio is genuinely correct. Sync
policy/spec comments (`s8-algorithm-audit.md:75-76`, policy `interaction_order`).

### BUG-1b — S8's analysis-grade FD/motion was slicewise-ONLY (omitted Stage-1 bulk) [FIXED 2026-06-09]
**Fixed:** `_extract_motion` now reads the co-located `moco_params_coarse.tsv`
and adds `tx_coarse/ty_coarse` to the slicewise mean → S8 motion/FD = bulk +
slicewise, consistent with S4. Verified on a real run (handgrasp): trans_x std
0.39→0.63 once bulk included. (Original finding below.)

Discovered while fixing BUG-1. S8's `_extract_motion` (`s8/process.py:39-75`)
builds `trans_x/trans_y`/FD purely from `moco_params_x/_y.nii.gz` (SCT Stage-2
slicewise), so the confounds matrix's motion regressors + FD **never include the
Stage-1 coarse bulk XY** (`tx_coarse/ty_coarse`). After the BUG-1 fix, S4's FD
(bulk+slice) and S8's FD (slice only) will DIFFER. Bulk is sub-mm so the effect
is small, but it's a real inconsistency. **Decision needed** (changes the shipped
confounds + needs S8 rerun): either (a) add Stage-1 bulk into S8's motion (read
`moco_params_coarse.tsv` and add), or (b) accept slice-only and document why.
**Do not fix silently.**

### BUG-1c — S4 Stage-1 bulk correction had the WRONG shift sign [FIXED 2026-06-09]
`lib/moco.py` registered each Z-projected volume with FLIRT then applied
`scipy.ndimage.shift(vol, [+tx, +ty])`. Because the FLIRT temp images are
written with `np.eye(4)` (positive-det → FSL neurological, internal x-flip),
FLIRT's tx matches the axis-0 displacement sign and ty is opposite on axis-1, so
the correct pull-back is `[-tx, +ty]`. The old `[+tx,+ty]` pushed the moving
frame FURTHER from the reference — Stage-1 actively *worsened* bulk alignment
(verified: known shift recovered MSE 1328→9 only by `[-tx,+ty]`; `[+tx,+ty]`→1715,
`[-tx,-ty]`→1929). Real-world impact was masked because real bulk motion is
sub-mm and Stage-2 SCT cleans up the residual — but post-BUG-1 the wrong-signed
bulk now feeds FD. **Fixed:** `shift=[-tx, ty]`; added an MSE-improvement
regression assertion to `test_S4_unit.py`. Note: the first verification
workflow's auto-proposed fix (`[-tx,-ty]`) was itself wrong — caught by
re-testing before applying.

### BUG-3 — S7 per-level bars mislabeled "L6/L7" on cervical data
`steps/s7/reportlets.py:311` does `f"L{lvl}"` over raw PAM50 *segmental*
integers (1..20), so a cervical scan containing segments 6/7 renders "L6/L7"
(looks lumbar). **Fix:** drop the "L" prefix; label as `seg N` or map segment
int→cord-segment name (6→C6…) via an explicit table; fix the inconsistent axis
label/title (`reportlets.py:313,316`). ~10 lines.

### BUG-4 — S6/S7 sagittal S/I/A/P markers are hardcoded (orientation-unsafe)
`reportlets_common.py:361-368` writes S/I/A/P unconditionally assuming RAS; S6/S7
reportlets load with raw `nib.load` (not `load_canonical()`), so markers are
wrong for non-RAS files. **Fix:** switch S6/S7 reportlet loads to
`load_canonical()` (smallest, fixes all at once) or derive markers from the
affine via `nib.orientations.aff2axcodes` (pattern already in
`steps/s3/localize.py:68-102`).

### BUG-5 — Stale S5 unit tests will fail
`tests/test_S5_unit.py:167-219` imports removed reportlets
(`render_s5_before_after`, `render_s5_mi_summary`) and asserts the deleted
"SyN-always-WARN" rule. **Fix:** update/delete the three obsolete tests; keep
the mode-selection/TRT tests.

### BUG-6 — S10 per-connection "icc" column is a mislabeled Pearson proxy
`steps/s10/process.py:380-398` — single-connection ICC is ill-defined, so the
column is actually cross-session Pearson; only the pooled value is true
ICC(3,1). **Fix:** rename column to `cross_session_pearson` (or compute true
pooled ICC). *(Related: SpinalCompCor carpet DVARS threshold line draws μ+3σ
instead of the actual Tukey gate — `s8 reportlets.py:537-539`, cosmetic.)*

---

## TIER B — Genuine open features (meeting-driven)

### FEAT-1 — SDC necessity ablation harness  ⭐ the PI's "really good find"
No coreg-with-vs-without-SDC path exists; S6 unconditionally consumes S5's
`desc-undistorted` BOLD. **Build:** (a) `distortion_correction.enabled` flag in
`policy/S5_...yaml` → when false, identity-copy mocoref→undistorted, `mode:none`,
still compute CoSpine metrics; (b) add `"none"` to the schema mode enum;
(c) harness (`scripts/s5_sdc_ablation.py` or `--ablate-sdc`) that runs two chains
from S5 (enabled true/false) through S6 and tabulates ΔDice / Δdisplacement /
ΔHD95 across the 11-run reg cohort. That table *is* the necessity answer.
(Covers meeting items: SDC-necessary?, coreg±SDC test.)

### FEAT-2 — End-to-end SDC on/off endpoint  (reframe required)
Extends FEAT-1 through S10; compare ROI-timeseries/connectivity (S10) under SDC
on vs off as the "endpoint" — because **no GLM/z-stat stage exists**. First
confirm with PI: endpoint = S10 connectivity (in scope) vs downstream activation
GLM (out of scope). Do not fabricate a z-stat stage.

### FEAT-3 — S6 rostral/caudal orientation annotation on per-slice figures
`render_s6_dice_per_slice` (`reportlets.py:307`) has only `"Slice (Z)"`. Add
caudal/rostral end-labels derived from the affine (NOT hardcoded; keep slice
numbers, do NOT relabel to C1/C2). Same optional cue for S7 per-level. Shares the
affine-orientation fix with BUG-4.

### FEAT-4 — S6 low-Dice slice flag → exclusion mask → endpoint A/B  (research)
Entirely unimplemented; per-slice Dice is render-only (not even in qc.json).
**Build:** persist `cord_dice_per_slice` to qc.json + schema; emit a
slice-exclusion mask (Dice < `warn_dice_min` 0.65); wire as optional censor at
S9/S10; A/B on the reg cohort. **Write a `.claude/specs/` spec first** (cite cord
slice-censoring precedent). Endpoint = S9/S10, not GLM (see FEAT-2).

### FEAT-5 — Finish S10 spatial-Dice test-retest reliability
`_seed_to_voxel_map`/`_spatial_dice` are imported+defined but never called;
`mean_spatial_dice` hardcoded `None` (`steps/s10/orchestrate.py:423`,
`process.py:428,469`). **Fix:** wire them into the multi-session block; populate
`mean_spatial_dice`/`dice_per_seed`; add a 2-session regression subset (ds004386
sub with `sessions:[01,02]`) so reliability is smoke-tested. (Completes meeting
ICC ask — pooled ICC already works in S10.)

### FEAT-6 — Real BIDS-App entrypoint for external-dataset pilots
README advertises `spinalfmriprep /bids /out participant` but the CLI is
dataset-key-driven (`cli.py:38-93`) — the documented command fails. **Fix:** add
a positional BIDS-App entrypoint wrapping the chain (or document the
manifest+`--bids-root` path and fix README:76-103); flesh out the stub
`Dockerfile.spinalfmriprep`. Needed for the PI's "send us one dataset" outreach.

---

## TIER C — Decisions (knob exists; pick a value)

- **DEC-1 — Smoothing kernel default.** Current default is anisotropic σ=1,1,5 mm
  (FWHM ≈ 2.35×2.35×11.8, CoSpine/Eippert), **not** Gergely's isotropic 5×5×5 mm
  (σ≈2.12). One-line policy edit (`policy/S9_...yaml:16`) + update FWHM tolerance
  bands; literature default is defensible (CLAUDE.md principle 2). Could A/B on
  reg cohort.
- **DEC-2 — CSF default = 5 PCs?** "29/27" is the *per-slice CSF* family
  (variance-mean, Hemmerling 2025); the *5-PC* family is SpinalCompCor and
  already emits exactly 5. No bug. If you want per-slice CSF replaced by 5-PC
  PCA, add `csf_slicewise.method: {variance_mean|pca5}`.
- **DEC-3 — "Spinal-cord regressor" optional.** No separate flag; SpinalCompCor
  is ON by default. Clarify terminology (is it SpinalCompCor?), then set its
  default to opt-in if desired.
- **DEC-4 — Cosine/DCT regressors.** Always emitted (count volume-driven 5–11),
  no toggle. If you may remove it, add `cosine.enabled` flag.
- **DEC-5 — Cross-correlation MoCo fallback.** `phase_cross_correlation` already
  exists (prior Stage-1, still in `detect_z_shift`). Only a `stage1.method`
  policy switch + default decision is open — not a build.

---

## TIER D — Already done / resolved (close out; some doc-sync)

- **DONE-1** FLIRT 2-DOF bulk MoCo (BUG: docs say `phase_cross_correlation`).
  → **DOC:** sync `policy/S4_...yaml:19-23`, `s4-func-motion-correction.md`,
  `s4-algorithm-audit.md`, set `s4-stage1-flirt-2d-replacement.md`→implemented;
  delete root scratch (`*.sch`, `test_flirt_*.py`, `test_mcflirt.*`).
- **DONE-2** TOPUP (reverse-PE) + SyN (default) selection ladder — exactly the
  meeting decision.
- **DONE-3** STC declined chain-wide w/ rationale (`s4-algorithm-audit.md:90`);
  coreg does NOT require STC; SliceTiming used only by S8 RETROICOR. → just
  answer the PI.
- **DONE-4** Smoothing is its own ordered step (S9), native-then-warp.
- **DONE-5** S9 derivatives all exist: tSNR map, per-level tSNR,
  smoothed+unsmoothed axial, FWHM (observability-only by design).
- **DONE-6** aCompCor/SpinalCompCor is MATLAB-free (numpy DCT-detrend + SVD; 5
  PCs).
- **DONE-7** Outliers combined (one source of truth across FD/DVARS/refRMS) —
  matches the meeting lean.
- **DONE-8** S8 outlier-rate root cause fixed & committed (FD 0.5 + Tukey IQR,
  `9144f60`). → **DOC:** `s8-confounds-and-physio-regressors.md` still says 0.2.
- **DONE-9** CoSpine pilot data already wired in: ds005883 (pain) + ds005884
  (motor), with reg subsets + local roots; chain has run on them.
- **DONE-10** S9/S11 implemented & locked; S10 implemented (minus FEAT-5 Dice).
- **DOC-1** S6 Dice threshold: metric cited (Cohen-Adad 2014) but the 0.85/0.65
  *cutoffs* are internal ("CoSpi-validated"). Add a citable band (Cohen-Adad
  2014 / De Leener 2017 report cord-reg Dice ~0.85-0.95) to the policy comment.
- **DOC-2** FD-threshold citation is a MISATTRIBUTION (verified vs primary
  sources). `policy/S8_confounds.yaml:28` credits FD>0.5 mm to "Power 2014 /
  Kaptan 2023 / Dabbagh 2024", but Kaptan 2023 uses NO FD threshold — it scrubs
  dVARS/refRMS at 2 SD (FSL fsl_motion_outliers). FD>0.5 mm AND 0.2 mm are both
  Power 2014. Repo also self-contradicts: s8-outlier-rate-root-cause.md:73 says
  Kaptan=0.5, s4-algorithm-audit.md:75 & s4-func-motion-correction.md:51 say
  Kaptan=0.2, s3-algorithm-audit.md:63 correctly says Kaptan=3σ-on-dVARS. Fix
  all FD citations to Power 2014; keep dVARS/refRMS SD-cutoff as Kaptan 2023.

---

## TIER E — Strategy / dissemination (non-code)

- **STRAT-1** Publish a paper showing QC metrics + endpoint effect to drive
  adoption. QC-metrics half is supported (S11 release report); endpoint/
  detectability half needs a downstream GLM harness (out of current scope).
- **STRAT-2** Outreach: ask other groups for one dataset each, run the toolbox,
  show reliability/detectability gains. Gated on FEAT-6 (clean ingestion) +
  FEAT-5 (reliability deliverable).
- **STRAT-3** Concrete pilot: run S1→S11 on the CoSpine pain set, hand the group
  the S11 `release_report.html` + per-level tSNR + reliability tables. Data is
  already present (DONE-9); only the deliverable run is pending.

---

## TIER F — Admin / lab / separate projects

- **ADMIN-1** Master-student interviews — next Tuesday (4 candidates, batched,
  Skype, with Jan).
- **ADMIN-2** (Gergely) propose to Patrick: lab/CoSpine meeting every 2 weeks.
- **ADMIN-3** (Gergely) propose CoSpi recruitment → Dario + Elia, not Kiomars;
  Kiomars helps with design/analysis only.
- **ADMIN-4** Kiomars: focus on writing paper 1 then paper 2 (4–5 topics ready);
  small literature search on CoSpi design/analysis.
- **SEPARATE-1** Shape analysis / SpineNorm (different project): present results
  next week (~80% neuro-level, ~95% within ±1, unsupervised); meet the incoming
  SpineNorm master student to verify approach; get Gergely's input on method.

---

## Suggested execution order
1. Quick wins / truth-restoring: **BUG-3, BUG-5, BUG-4, DOC-1, DONE-1 doc-sync.**
2. High-value correctness: **BUG-1, BUG-2, BUG-6.**
3. The PI's headline question: **FEAT-1** (→ FEAT-2 reframe with PI).
4. Reportlet/feature: **FEAT-3**, then **FEAT-5**.
5. Decisions to close with Gergely: **DEC-1..DEC-5.**
6. Research: **FEAT-4.**
7. Dissemination enablers: **FEAT-6 → STRAT-3.**
