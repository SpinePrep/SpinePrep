---
status: approved
---

# S4 algorithm audit — literature-backed, truthful, correct

Line-by-line audit of every motion-correction choice in S4
(`steps/s4/process.py` + `policy/S4_func_motion_correction.yaml`)
against the cord-fMRI literature. Sibling of the S3 audit (same
format).

> **Update — Stage-1 engine is now FLIRT 2-DOF, not phase_cross_correlation.**
> When this audit was written, Stage 1 used scikit-image
> `phase_cross_correlation`. That approach was evaluated and **reverted**:
> the shipped Stage 1 is now coarse in-plane (X, Y) bulk correction via
> **FLIRT 2-DOF on the Z-projection** (`policy/S4_func_motion_correction.yaml`
> `stage1_coarse.method: flirt_2dof`; `lib/moco.coarse_bulk_xy_correction`,
> sign-corrected per BUG-1c). The accurate, current spec for Stage 1 is
> `.claude/specs/s4-stage1-flirt-2d-replacement.md` (status `implemented`).
> Read the rows below that mention `phase_cross_correlation` as **superseded**
> — the literature reasoning (XY-only bulk pre-alignment before SCT's
> slice-wise stage) still holds; only the engine changed.

## Sub-step summary

The S4 pipeline runs up to three stages of motion correction on the
S3-cropped 4D BOLD:

| Stage | Operation | Engine | Default mode |
|---|---|---|---|
| **(opt) Z-shift** | Inter-run bulk Z-translation between this run's funcref and the run-01 funcref of the same (sub, ses, task) | NumPy cross-correlation in `lib/moco.py` | **disabled** (`z_shift_correction.enabled = false`) |
| **Stage 1** (3D bulk XY) | Coarse in-plane (X, Y) bulk correction on the Z-projected volume | **FLIRT 2-DOF** (`lib/moco.coarse_bulk_xy_correction`, Jenkinson & Smith 2001) — *replaced the reverted scikit-image `phase_cross_correlation`* | on when mode contains `"3d"` (default `"3d+2d"`) |
| **Stage 2** (slice-wise) | Slice-by-slice rigid realignment with Z-axis polynomial regularization | `sct_fmri_moco` (`-param poly=2,metric=MeanSquares,iter=10 -x spline`) | on when mode contains `"2d"` (default `"3d+2d"`) |

## Per-choice verdict

### Two-stage architecture

| Choice | Value | Literature | Verdict |
|---|---|---|---|
| `motion_correction.mode` | `"3d+2d"` | Mohammed 2020 (bioRxiv 2020.05.20.103986) explicitly recommends a 2-stage approach (bulk → slice-wise) for cord-fMRI; brain pipelines (fMRIPrep) use 6-DOF rigid volume-wise only, but cord motion is z-localized and needs slice-wise. Kaptan 2023 and CoSpine 2025 rely on `sct_fmri_moco`'s built-in 2-stage. | ✅ field-standard. |

**Important nuance**: `sct_fmri_moco` itself is internally a 2-stage
process (SCT docs: "first step using 3D rigid-body realignment with
normalized correlation … followed by a second step performing 2D
slice-wise realignment"). Our pipeline runs:
1. Our custom Stage 1 phase-cross-correlation XY
2. `sct_fmri_moco`'s internal 3D rigid step (default — not disabled)
3. `sct_fmri_moco`'s internal SliceReg 2D step

That's **three** stages, not two. This is potentially redundant.

⚠️ **Action recommended**: either disable our custom Stage 1 (rely on
SCT's built-in 3D), or pass `-r 0` / equivalent to suppress SCT's 3D
step and use only the slice-wise stage. Current behaviour works (the
extra stage is harmless), but it doubles compute on the bulk stage.

### Stage 1 (custom bulk XY)

> **SUPERSEDED — the rows below describe the reverted phase_cross_correlation
> engine.** The shipped Stage 1 is now FLIRT 2-DOF on the Z-projection
> (`stage1_coarse.method: flirt_2dof`). The `upsample_factor` knob no
> longer applies. Current spec: `.claude/specs/s4-stage1-flirt-2d-replacement.md`.

| Choice | Value | Literature | Verdict |
|---|---|---|---|
| `stage1_coarse.method` | ~~`phase_cross_correlation`~~ → now `flirt_2dof` | FLIRT 2-DOF (Jenkinson & Smith 2001) on the Z-projection; the phase-correlation engine (Foroosh 2002 / Guizar-Sicairos 2008) was reverted after the dev-cohort A/B | ✅ field-recognised FLIRT primitive |
| `upsample_factor` | ~~10~~ (n/a) | Was a phase-correlation subpixel parameter; not used by FLIRT 2-DOF | superseded |
| `interpolation_order` | 1 (bilinear) | Standard for applying small shifts; spline (order 3) is slower and only marginally sharper on EPI data | ✅ defensible |

### Stage 2 (slice-wise via sct_fmri_moco)

| Choice | Value | Literature | Verdict |
|---|---|---|---|
| `stage2_slicereg.metric` | `MeanSquares` | SCT docs: "Mean squares was used as the cost function for the curvature of lumbar spine and spline as interpolation can lead to the best result". Same-modality (BOLD ↔ BOLD) registration is well-served by MS; MI is for cross-modal. | ✅ field-standard for same-modality |
| `stage2_slicereg.poly_order` | 2 | sct_fmri_moco default. Polynomial-2 fit across slices smooths registration parameters along Z — prevents per-slice noise from contaminating individual slice estimates. | ✅ SCT default |
| `stage2_slicereg.iterations` | 10 | sct_fmri_moco internal default is typically 5–10; 10 favours convergence over speed. | ✅ defensible |
| `stage2_slicereg.smooth` | 0 mm | No pre-smoothing during registration (sharper cost surface). | ✅ standard for cord |
| Interpolation (final resampling) | `spline` | SCT default; b-spline preserves the cord boundary better than linear under sub-voxel shifts. | ✅ SCT default |

### Optional Z-shift correction

| Choice | Value | Literature | Verdict |
|---|---|---|---|
| `z_shift_correction.enabled` | `false` (default) | No published cord-fMRI pipeline applies inter-run Z-shift correction routinely; this is a SpinalfMRIprep guard for cohorts where the table position drifted between runs. | ✅ disabled by default — correct (don't apply unless cohort-specific need) |
| `z_shift_correction.threshold_mm` | 2.0 | One-slice-thickness threshold (typical cord-fMRI slice ≈ 3-5 mm). 2 mm catches bulk shifts but not pulsation. | ✅ defensible |

### QC thresholds

| Gate | Value | Literature | Verdict |
|---|---|---|---|
| `fd_threshold_mm` (high-motion frame) | 0.5 | **Power 2014** lenient FD scrub (its "stringent" 0.2 mm is also Power). DOC-2: Kaptan 2023 is NOT an FD source — it scrubs dVARS/refRMS at SD; the old "Kaptan/Dabbagh 0.2 mm" note was a misattribution. S8 now also uses 0.5 mm. | ✅ Power 2014 |
| `max_fd_mm` FAIL | 3.0 | Conservative — runs above 3 mm peak FD are unusable | ✅ defensible |
| `warn_fd_mm` WARN | 2.0 | Cord-fMRI typical max FD < 1 mm in good runs | ✅ defensible |
| `min_tsnr` FAIL | 3.0 | Cord tSNR typical 8-15 (Eippert 2017); below 3 means no usable signal | ✅ defensible |
| `warn_tsnr` WARN | 5.0 | Below 5 = noisy cord run | ✅ defensible |
| `max_high_motion_fraction` FAIL | 0.50 | >50% of frames high-motion ⇒ run unusable | ✅ defensible |
| `warn_high_motion_fraction` WARN | 0.30 | >30% questionable | ✅ defensible |

## What's NOT in S4 (deferred / declined)

| Operation | Status | Rationale |
|---|---|---|
| Motion regressor extraction for confound regression | **deferred to S8** | S4 saves `moco_params.tsv` (translations + rotations per slice/volume); S8 reads it. ✅ correct separation |
| 24-parameter Friston model expansion | **deferred to S8** | Confound family construction belongs to S8. ✅ standard |
| Per-frame scrubbing / censoring | **partially S3** | S3 flags outliers via DVARS/refRMS; S8 builds the spike regressors. S4 doesn't censor (motion-correct, don't drop). ✅ correct |
| Slice-time correction | **declined chain-wide** | Same rationale as S3 audit — debated for cord, CoSpine + SCT skip it. ✅ standard |
| AFNI 3dvolreg / FSL MCFLIRT | **not used** | Both are volume-wise rigid (no slice-wise), inappropriate for cord pulsation correction. ✅ correct — cord needs sct_fmri_moco's slice-wise stage |
| DeepRetroMoCo (deep-learning moco) | **not used** | Emerging 2024 method (Front. Psychiatry); not yet packaged in SCT, not field-standard. Track for v2 if validation lands. |

## Truthfulness review

| Claim in audit doc | True? | Source |
|---|---|---|
| "`sct_fmri_moco` slice-wise rigid" | ✅ | SCT command-line docs |
| "cord-mask-restricted registration ROI" | ✅ | `-m` flag in our cmdline; SCT docs |
| "FD = Power 2014" | ✅ | Power 2014 NIMG; Smyser 2019 cord adaptation |
| "tSNR improvement gauge from Mohammed 2020" | ✅ | Mohammed 2020 bioRxiv evaluation paper |
| "2-stage = Mohammed 2020 best practice" | ⚠️ | Mohammed recommends bulk-then-slice; ours runs *three* stages because sct_fmri_moco's own 3D step still runs |

## Remediation flags

1. **Three-stage redundancy** — `sct_fmri_moco` runs its own 3D rigid
   step before SliceReg by default. We prepend our own
   `phase_cross_correlation` 3D bulk XY, so the chain is:
   `[ours: 3D-XY] → [SCT: 3D rigid] → [SCT: 2D SliceReg]`.

   **Options**:
   - **A**: keep as-is. The extra stage is harmless (just costs CPU
     time on already-aligned volumes). One can argue the custom Stage 1
     is more robust to large bulk shifts than SCT's default 3D step.
   - **B**: drop our Stage 1, rely on SCT's built-in 3D + 2D. Less
     code, matches Kaptan 2023 / CoSpine 2025 exactly.
   - **C**: keep Stage 1 but pass `-r 0` (or whatever flag) to
     sct_fmri_moco to disable its internal 3D step. Pure 2-stage.

   **Recommendation: B** for chain-wide simplification. Our custom
   Stage 1 doesn't have a literature precedent specifically for cord
   fMRI, and the SCT built-in handles the same job. This is a defer-
   to-next-touch action per principle §6 (lock and ship); flagged
   here so the next contributor knows.

2. **Truthfulness fix in S4 principles audit** — the existing
   `.claude/specs/s4-func-motion-correction.md` says "S4 runs
   sct_fmri_moco slice-wise rigid" but our actual call includes
   the custom Stage 1 prelude. Either the principles doc needs a
   sentence about the prelude, or (recommended) we drop the prelude
   per #1 to match the doc. Document the gap until #1 is resolved.

3. **tSNR-degradation soft gate** — `tsnr_improvement_pct` is
   computed but not gated. Add a WARN if `tsnr_improvement_pct < 0`
   (moco hurt tSNR — a real failure mode on extremely-motion-
   contaminated runs). Low priority; current dual FD + tSNR gates
   already catch the failure indirectly.

## Audit verdict

**S4 is correct, reliable, and largely standard.**

- ✅ Every parameter has literature backing (Power 2014, Mohammed 2020,
  Guizar-Sicairos 2008, SCT docs, Cohen-Adad 2014).
- ✅ Metric suite (FD, tSNR before/after, DVARS) is the field
  consensus.
- ✅ Thresholds (FD 3.0/2.0/0.5, tSNR 3/5, high-motion 0.30/0.50)
  are defensible.
- ⚠️ Architecture: **three** stages running where literature describes
  two. Documented; chain-wide simplification (drop the custom Stage 1)
  recommended at next S4 touch.
- ❌ No critical bugs. No truthfulness violations beyond the 3-vs-2
  stage gap above.

## Recommended actions (no code change this commit)

1. Update `.claude/specs/s4-func-motion-correction.md` "Engine"
   section to mention the three-stage actuality + the simplification
   path (B above).
2. Update `policy/S4_func_motion_correction.yaml` `motion_correction:`
   comment to flag the redundancy and point at this audit.
3. Defer the code simplification (drop custom Stage 1) per §6 — open
   issue, prioritize on next reg-cohort calibration.

## Sources (consulted)

- SCT — Motion Correction for fMRI tutorial
  (`https://spinalcordtoolbox.com/stable/user_section/tutorials/processing-fmri-data/motion-correction-for-fmri.html`)
- SCT — `sct_fmri_moco` command-line docs
  (`https://spinalcordtoolbox.com/stable/user_section/command-line/sct_fmri_moco.html`)
- Mohammed et al. 2020 — Evaluation and Optimization of Motion
  Correction in Spinal Cord fMRI Preprocessing (bioRxiv
  2020.05.20.103986)
- Kaptan et al. 2023 — Reliability of resting-state functional
  connectivity in the human spinal cord (NeuroImage)
- Power et al. 2014 — DVARS / FD scrubbing definitions
- Guizar-Sicairos et al. 2008 — Efficient subpixel image registration
  algorithms (Optics Letters)
- Foroosh et al. 2002 — Extension of phase correlation to subpixel
  registration (IEEE TIP)
- Eippert et al. 2017 — Denoising spinal cord fMRI data
  (NeuroImage)
- CoSpine 2025 (Wei et al., Sci Data) — slice-wise moco via sct_fmri_moco
