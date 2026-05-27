---
status: implemented
---

# S4 func motion correction — audit against dev principles

Step-local audit of S4 against the SpinalfMRIprep development principles
(`CLAUDE.md`). Implementation spec lives in `private/SPEC/S4_func_motion_correction.md`.
The earlier `.claude/specs/s4-moco-comparison-axial.md` is a *reportlet
redesign* scope, not this principles audit.

## Objective

Slice-wise rigid motion correction of cord-fMRI (cervical, axial EPI),
producing a per-frame motion parameter trace, an aligned 4D BOLD, and
quality gauges that downstream confound regression (S8) and
group-level analysis (S10) can consume.

## Engine

- **Stage 1**: build a robust registration target from the de-outliered
  funcref (S3.2 output).
- **Stage 2**: `sct_fmri_moco` slice-wise rigid alignment with the cord
  mask as the registration ROI.

## Literature backing

| Choice | Source |
|---|---|
| `sct_fmri_moco` slice-wise (not volume-wise) | SCT convention for cord fMRI; cord motion is dominated by physiological pulsation, which is z-localised — slice-wise rigid is the field standard (De Leener 2017, Eippert 2017) |
| Cord-mask-restricted registration ROI | Restricts cost function to cord pixels; avoids the cost being dominated by non-cord motion artefacts (Cohen-Adad 2014) |
| Framewise displacement (FD) as motion gauge | Power 2014; the standard cord-fMRI gauge |
| FD `0.5 mm` for high-motion classification (this step) | Coarse usability gate, looser than the 0.2 mm scrubbing threshold S8 uses for per-frame outlier flagging. Two thresholds are intentional: 0.5 mm asks "is the run usable at all", 0.2 mm asks "which frames to regress" (S8 uses Mohammed 2020 / Kaptan 2023 0.2 mm for the latter). |
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
| `S4_motion_traces` | Per-frame X/Y translation, X/Y rotation, FD vs time | Step jumps ⇒ uncorrected sudden movement; oscillation ⇒ respiratory coupling |
| `S4_dvars_plot` | Post-moco DVARS timeseries | High DVARS spikes despite low FD ⇒ residual physiological pulsation (S8 will mitigate via RETROICOR) |
| `S4_tsnr_comparison` | Side-by-side axial tSNR maps Before/After + headline tSNR improvement | Brighter cord after ⇒ moco helped; darker ⇒ moco introduced blurring |

The earlier-spec `S4_moco_comparison` axial PNG (per-slice Before/After
mean BOLD) is not currently registered in the dashboard or emitted in
production; the three above cover the diagnostic surface.

## Threshold rationale (`policy/S4_func_motion_correction.yaml`)

| Gate | Value | Source |
|---|---|---|
| FAIL `max_fd_mm` | 3.0 | "Run unusable" hard ceiling (Power 2014 + cord-acquisition voxel size scaling) |
| WARN `warn_fd_mm` | 2.0 | "Run questionable" |
| FAIL `min_tsnr` | 3.0 | Cord tSNR floor (Mohammed 2020) |
| WARN `warn_tsnr` | 5.0 | "Cord signal questionable" |
| FAIL `max_high_motion_fraction` | 0.50 | More than half the volumes high-motion ⇒ unusable |
| WARN `warn_high_motion_fraction` | 0.30 | More than 30% high-motion ⇒ questionable |
| `fd_threshold_mm` | 0.5 | Per-frame high-motion definition (S4 coarse gate); S8 uses 0.2 mm for finer scrubbing |

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
- Surface a cord-fMRI-specific 0.2 mm FD outlier count alongside the
  0.5 mm coarse gauge (Kaptan 2023 standard). Tracked as a low-priority
  follow-up — S8 already does this for the per-frame regression layer.
- Add the previously-scoped `S4_moco_comparison` axial PNG if a fourth
  diagnostic dimension proves useful in practice.

## Decision: no changes this audit

The pattern is "audit → fix gaps → ship". S4 has no gaps that would
meaningfully change a future user's confidence in S4's output. Adding
metrics or thresholds without a problem to solve violates principle §6
(lock and ship). Move on to S5.
