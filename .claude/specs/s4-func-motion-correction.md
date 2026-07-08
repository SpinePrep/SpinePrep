---
status: implemented
---

# S4 func motion correction — audit against dev principles

Step-local audit of S4 against the SpinePrep development principles
(`CLAUDE.md`). Implementation spec lives in `private/SPEC/S4_func_motion_correction.md`.
The earlier `.claude/specs/s4-moco-comparison-axial.md` is a *reportlet
redesign* scope, not this principles audit.

## Objective

Slice-wise rigid motion correction of cord-fMRI (cervical, axial EPI),
producing a per-frame motion parameter trace, an aligned 4D BOLD, and
quality gauges that downstream confound regression (S8) and
group-level analysis (S10) can consume.

## Engine

The S4 motion correction chain runs **three** rigid-realignment stages
(not two — see `.claude/specs/s4-algorithm-audit.md` for the
literature audit):

- **Stage 0 (target build)**: take the robust de-outliered funcref from
  S3.2 as the registration target.
- **Stage 1 (coarse bulk XY via FLIRT 2-DOF)**: per-volume coarse
  in-plane (X, Y) bulk correction with FLIRT 2-DOF on the Z-projected
  volume (`lib/moco.coarse_bulk_xy_correction`, sign-corrected per
  BUG-1c; Jenkinson & Smith 2001). This is the **shipped** Stage-1
  engine — the earlier `phase_cross_correlation` approach was evaluated
  and reverted (see `.claude/specs/s4-stage1-flirt-2d-replacement.md`,
  status `implemented`). CoSpi's MCFLIRT 3D 6-DOF was A/B-tested on the
  11-run dev cohort and lost (cord tSNR 15.26 ≈ no-correction vs
  FLIRT-2DOF 18.30 — MCFLIRT over-corrects on the cord-cropped FOV).
  Active when `motion_correction.mode` contains `"3d"` (default).
- **Stage 2 (SCT slice-wise)**: `sct_fmri_moco` with
  `-param poly=2,metric=MeanSquares,iter=10 -x spline` and the cord
  mask as registration ROI. **Note**: SCT's internal pipeline is itself
  2-stage (3D rigid + 2D SliceReg); since we don't pass `-r 0` (or
  equivalent), SCT's 3D rigid step runs in addition to its SliceReg.
  Active when `motion_correction.mode` contains `"2d"` (default).

The three-stage pipeline is functionally correct but documented in the
algorithm audit as a candidate for simplification at next S4 touch —
either drop our custom Stage 1 (rely on SCT's built-in 3D + 2D, matching
Kaptan 2023 / CoSpine 2025 exactly) or disable SCT's internal 3D step.
Deferred per principle §6 (lock and ship); not bug-fixable urgency.

## Literature backing

| Choice | Source |
|---|---|
| `sct_fmri_moco` slice-wise (not volume-wise) | SCT convention for cord fMRI; cord motion is dominated by physiological pulsation, which is z-localised — slice-wise rigid is the field standard (De Leener 2017, Eippert 2017) |
| Cord-mask-restricted registration ROI | Restricts cost function to cord pixels; avoids the cost being dominated by non-cord motion artefacts (Cohen-Adad 2014) |
| Framewise displacement (FD) as motion gauge | Power 2014; the standard cord-fMRI gauge |
| FD `0.5 mm` for high-motion classification (this step) | **Power 2014** lenient FD scrub. S8 per-frame outlier flagging now also uses **0.5 mm** (Power 2014). DOC-2: the earlier "0.2 mm (Mohammed/Kaptan)" was a misattribution — Kaptan uses dVARS/refRMS, not FD; 0.2 mm is Power's *stringent* variant. |
| tSNR before/after as moco-quality gauge | Mohammed 2020 cord-fMRI moco evaluation; tSNR improvement after slice-wise rigid is the field-standard sanity check |

## Step-local truth metrics (principle §3)

Already richly populated in qc.json per run:

- `max_fd_mm` — peak per-frame FD across the run. Headline FAIL gate.
- `mean_fd_mm` — average FD. Diagnostic context.
- `high_motion_frame_count` / `high_motion_fraction` — frames above
  `fd_threshold_mm` (0.5 mm). Headline WARN/FAIL gate.
- `tsnr_before_mean` / `tsnr_after_mean` — cord tSNR before vs after
  moco. The moco-quality signal.
- `tsnr_improvement_pct` — relative tSNR gain (negative = moco hurt).
- `dvars_mean` / `dvars_max` — post-moco DVARS as a residual-motion
  sanity (cord moco should leave low DVARS; high DVARS = uncorrected
  motion or topup-needed distortion).
- `z_shift_detected_mm` / `z_shift_corrected` — Z-axis drift detection
  (S4 internally corrects bulk Z shift before slice-wise moco).

## Diagnostic reportlets (principle §4)

| Reportlet | What it shows | What failure looks like |
|---|---|---|
| `S4_motion_traces` | Per-frame X/Y translation, X/Y rotation, FD vs time (DVARS now folded into this panel) | Step jumps ⇒ uncorrected sudden movement; oscillation ⇒ respiratory coupling; high DVARS despite low FD ⇒ residual physiological pulsation |
| `S4_slicewise_heatmap` | Per-slice/per-frame moco map | Slice-localised residual motion (one slice misbehaving) |
| `S4_tsnr_comparison` | Side-by-side axial tSNR maps Before/After + headline tSNR improvement | Brighter cord after ⇒ moco helped; darker ⇒ moco introduced blurring |

The three reportlets above are the ones actually emitted. The
standalone `S4_dvars_plot` was dropped — DVARS is now folded into the
`S4_motion_traces` panel. The earlier-spec `S4_moco_comparison` axial
PNG (per-slice Before/After mean BOLD) is also not registered in the
dashboard or emitted in production.

## Threshold rationale (`policy/S4_func_motion_correction.yaml`)

| Gate | Value | Source |
|---|---|---|
| FAIL `max_fd_mm` | 3.0 | "Run unusable" hard ceiling (Power 2014 + cord-acquisition voxel size scaling) |
| WARN `warn_fd_mm` | 2.0 | "Run questionable" |
| FAIL `min_tsnr` | 3.0 | Cord tSNR floor (Mohammed 2020) |
| WARN `warn_tsnr` | 5.0 | "Cord signal questionable" |
| FAIL `max_high_motion_fraction` | 0.50 | More than half the volumes high-motion ⇒ unusable |
| WARN `warn_high_motion_fraction` | 0.30 | More than 30% high-motion ⇒ questionable |
| `fd_threshold_mm` | 0.5 | Per-frame high-motion definition (Power 2014); S8 scrubbing now also uses 0.5 mm |

## Audit verdict per principle

| # | Principle | Verdict |
|---|---|---|
| 1 | Small dev cohort | ✅ 11 runs across 5 datasets |
| 2 | Literature defaults | ✅ SCT `sct_fmri_moco`, Power 2014 FD, Mohammed 2020 tSNR gauge |
| 3 | Step-local truth metric | ✅ already richly populated (FD, tSNR, DVARS) |
| 4 | Diagnostic reportlet | ✅ 3 PNGs, each maps to a distinct failure mode |
| 5 | Visual QC validator | ✅ reportlets eyeball-able |
| 6 | Lock and ship | ✅ versioned policy w/ explicit threshold rationale |
| 7 | No chain backtracking | ✅ only consumes S3 (funcref + cord mask) |
| 8 | Full cohort = deliverable | ✅ scales |
| 9 | Reproducible | ✅ schema + policy + spec |
| 10 | Heterogeneity is the test | ✅ 1 WARN in balgrist (real-data heterogeneity) |

## No-code change

S4 already satisfies all 10 principles. This audit doc records that.
Future tightening could:
- Optionally surface Power 2014's "stringent" 0.2 mm FD outlier count
  alongside the 0.5 mm lenient gauge. Low-priority follow-up. (Kaptan 2023
  is not an FD source — it scrubs dVARS/refRMS.)
- Add the previously-scoped `S4_moco_comparison` axial PNG if a fourth
  diagnostic dimension proves useful in practice.

## Decision: no changes this audit

The pattern is "audit → fix gaps → ship". S4 has no gaps that would
meaningfully change a future user's confidence in S4's output. Adding
metrics or thresholds without a problem to solve violates principle §6
(lock and ship). Move on to S5.
