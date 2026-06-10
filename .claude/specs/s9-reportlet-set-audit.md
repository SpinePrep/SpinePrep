---
status: approved
---

# S9 reportlet+metric-set audit — redundancy + field-standard composition

Examines whether S9's 4 reportlets and ~11 metrics are well-chosen,
non-redundant, and complete, against the cord-fMRI / brain-fMRI
preprocessed-output QC literature.

## Current S9 outputs

### Reportlets

| # | Reportlet | Content |
|---|---|---|
| 1 | `smoothed_vs_unsmoothed_axial` | 9-tile axial montage, mean BOLD pre vs post smoothing side-by-side with cord contour |
| 2 | `tsnr_map_axial` | 9-tile axial tSNR map (hot colormap) with cord-median in title |
| 3 | `tsnr_per_level` | Per-vertebral-level mean ± SD tSNR bar chart |
| 4 | `smoothness_summary` | Requested vs measured residual FWHM per axis (R-L / A-P / S-I) bar chart |

### Metrics (qc.json)

| Metric | Type | Gating? |
|---|---|---|
| `n_volumes` | int | ❌ informational |
| `tsnr_pre_median`, `tsnr_post_median` | float×2 | ❌ informational |
| `tsnr_ratio_median` | float | ✅ PASS / WARN / FAIL (1.5 / 1.2 / 1.0) |
| `fwhm_{x,y,z}_measured_mm` | float×3 | ❌ informational (tolerance gates declared in policy but not enforced) |
| `fwhm_{x,y,z}_requested_mm` | float×3 | ❌ informational (constant from policy) |
| `cord_dice_pre_post` | float | ✅ PASS / WARN / FAIL (0.95 / 0.85) |
| `n_levels_with_tsnr` | int | ❌ informational |
| `smoothing_runtime_s` | float | ❌ informational |

## Field-standard preprocessed-output QC visualisations

Reviewed 6 published tools / pipelines:

| Source | Reportlets | Metrics |
|---|---|---|
| **fMRIPrep brain output report** (Esteban 2019) | Carpet plot of preprocessed BOLD; tSNR axial map; smoothness summary; alignment overlay | tSNR, FD/DVARS, condition number |
| **MRIQC functional IQM** (Esteban 2017) | tSNR map; GCOR; AFNI smoothness FWHM; mean intensity map | ~30 IQMs |
| **SCT QC tool** (De Leener 2017) | Axial mosaic with overlay (smoothing not visualised) | — |
| **CoSpine 2025** (Wei et al., *Sci Data*) | Per-vertebra tSNR plot (Figure 6 — the cord-specific headline); group tSNR heatmap | Per-level tSNR median |
| **Kaptan 2023** (Eippert lab, *NeuroImage*) | Per-vertebra tSNR boxplots across subjects; group tSNR heatmap | Per-level tSNR mean |
| **Eippert 2017** (cord denoise review) | tSNR before/after denoising overlays; per-slice tSNR plot | tSNR median in cord |

**Field consensus pattern** for cord-fMRI primary derivatives QC:
1. **tSNR axial map** with cord-median annotation — universal (the headline)
2. **Per-vertebral-level tSNR** — cord-specific signature (Kaptan 2023, CoSpine 2025 — defining "what makes cord-fMRI work")
3. **Smoothing effectiveness** — before/after BOLD comparison, OR tSNR ratio metric
4. **Smoothness verification** — measured residual FWHM vs requested
5. **Carpet plot** — fMRIPrep brain convention; less common in cord (already covered by S8)

## Reportlet redundancy analysis

Each of the 4 current reportlets answers a different question:

| Reportlet | Question answered | Overlap with others |
|---|---|---|
| `smoothed_vs_unsmoothed_axial` | "Did smoothing actually blur the BOLD?" | ❌ unique |
| `tsnr_map_axial` | "Where in the cord is tSNR highest?" | ❌ unique (different signal from #1) |
| `tsnr_per_level` | "How does tSNR vary by vertebral level?" | ❌ unique (different aggregation) |
| `smoothness_summary` | "Did smoothing achieve the requested FWHM?" | ❌ unique (different metric family) |

**Verdict**: ✅ no pairwise redundancy. All 4 stand alone.

But two questions worth probing:

### Q1: Is `smoothed_vs_unsmoothed_axial` (visual) redundant with `tsnr_ratio_median` (numeric)?

The visual shows the BLUR change; the metric quantifies the SNR
improvement. These measure adjacent but distinct things:
- Heavy smoothing with bad cord seg ⇒ visual shows wide blur, ratio
  stays low (signal smeared away from cord)
- Light smoothing on clean data ⇒ visual barely changes, ratio still
  goes up (matched cord-axis smoothing)

So they're complementary. **Keep both.**

### Q2: Is `smoothness_summary` (per-axis FWHM bars) the right diagnostic?

Looking at the cospine_pain reportlet (rendered): requested
Z-FWHM = 11.8 mm, measured = 9.1 mm. That's a 23% underestimate
of the measured smoothness — well within reason (autocorrelation-
based FWHM estimates routinely under-report by 10-30%).

But the user sees "you asked for 11.8, got 9.1" with no
interpretation. The right diagnostic for cord-fMRI smoothness is
**did smoothing land in the policy tolerance band**, not the
abstract requested-vs-measured comparison. The policy declares
tolerances (`tolerance_mm_xy: 0.5`, `tolerance_mm_z: 1.0`) but
they're never enforced in the classifier.

**Verdict**: ⚠️ `smoothness_summary` is right shape but should
color-code PASS/WARN/FAIL bands per the policy tolerances + show
the tolerance window as horizontal bands. Currently it's just two
side-by-side bars with no acceptance signal.

## Metric redundancy + correctness analysis

| Metric | Verdict | Reason |
|---|---|---|
| `n_volumes` | ✅ keep | downstream needs it |
| `tsnr_pre_median` / `tsnr_post_median` | ✅ keep | the ratio's components are informative on their own (e.g. a high ratio with low post-median is suspect) |
| `tsnr_ratio_median` | ✅ keep | headline gate |
| `fwhm_{x,y,z}_measured_mm` | ✅ keep | observability of actual smoothness |
| `fwhm_{x,y,z}_requested_mm` | 🟡 derivable from policy | matches the policy 1:1, but useful for auditability when policy changes between locks. Marginal but cheap. Keep. |
| `cord_dice_pre_post` | ✅ keep | second gate (smoothing didn't destroy the cord seg) |
| `n_levels_with_tsnr` | ✅ keep | observability — sparse-coverage runs surface here |
| `smoothing_runtime_s` | ✅ keep | useful for cost-controls |

**No metric is redundant.**

But three issues:

### Issue 1 — FWHM tolerance gates declared but not enforced

`policy.fwhm_estimate.tolerance_mm_xy: 0.5` and `_z: 1.0` exist but
`_classify` doesn't read them. The 11 PASS+1 WARN cohort doesn't
gate on FWHM at all. Either enforce the gate (tighten the
classifier) or drop the policy keys (avoid declared-but-unused
configuration).

### Issue 2 — `cord_dice_pre_post` is uninformative on cord-aware smoothing

By design, `sct_smooth_spinalcord` smooths IN STRAIGHTENED COORD
SPACE, so the cord mask voxels are preserved exactly through the
operation. Pre/post Dice is always ~0.95-1.00 across the cohort
(verified: range 0.95-1.00 with median 0.99).

The metric is technically correct (it does report cord preservation)
but it's never the failing signal — it always passes. It's a "sanity
check that the file got written correctly" rather than a "did
smoothing work" metric. Status-color it as observability-only?

### Issue 3 — tSNR ratio bar is high (1.5×)

Cohort: ratios 2.01-2.92. The 1.5 PASS bar is satisfied by all 11
runs. Either the bar should be higher (calibrate from cohort
empirics — pass at the 25th percentile), OR document that 1.5 is
the floor below which "smoothing didn't help meaningfully" rather
than "ratio is good".

## Proposed optimal set

### Reportlets (4 — current set is correct, one redesign)

```
1. tsnr_map_axial           — KEEP. Headline cord-fMRI tSNR view.
                              Already shows cord-median in title.

2. tsnr_per_level           — KEEP. Cord-specific signature
                              (Kaptan 2023 / CoSpine 2025 figure).

3. smoothed_vs_unsmoothed_axial — [DROPPED 2026-06-11, see note below]
                                  Originally KEEP for visual
                                  confirmation of the smoothing
                                  operation.

4. smoothness_summary       — KEEP but REDESIGN: color-code PASS/
                              WARN/FAIL bars per the policy
                              tolerance bands; show the tolerance
                              window as a horizontal shaded band
                              behind the measured bar. Today the
                              reportlet just shows numbers; the
                              redesign shows whether smoothing
                              landed in spec.
```

### Metrics

```
KEEP unchanged: all 11 current metrics.

FIX:
  - Enforce the FWHM tolerance gates in _classify (or drop them
    from policy). Currently declared-but-unused.
  - Either calibrate tsnr_ratio_min from cohort empirics (e.g.
    pass at 2.0), OR document 1.5 as the "minimum useful gain"
    floor rather than a quality bar.
  - cord_dice_pre_post: keep but document that it's always near
    1.0 with sct_cord smoothing (the metric is a sanity check, not
    a regression signal).
```

## Truthfulness review

| Claim | True? |
|---|---|
| "4 reportlets cover the field-standard cord-fMRI primary-derivative QC" | ✅ matches Eippert/Kaptan/CoSpine convention; tSNR map + per-level + smoothing-effectiveness + smoothness-verification |
| "tsnr_ratio_median is the headline gate" | ✅ |
| "FWHM tolerance gates enforced" | ❌ — declared in policy but `_classify` doesn't read them |
| "cord_dice_pre_post is a quality gate" | ⚠️ technically true (in the classifier) but always near 1.0 with sct_cord smoothing (the smoothing IS in cord-straightened space → mask preserved by design) |
| "tSNR ratio 1.5 = PASS bar" | ⚠️ all 11 cohort runs exceed it; calibrate or document as floor |

## Implementation map

| # | Action | Priority | Effort |
|---|---|---|---|
| 1 | Redesign `smoothness_summary` reportlet — add PASS/WARN/FAIL color bands per axis using policy tolerances, show tolerance window as shaded background, dark-theme chrome | high | ~80 lines |
| 2 | Apply dark-theme + status-pill chrome to all 4 reportlets (currently white background, no chrome) | medium | ~100 lines |
| 3 | Enforce FWHM tolerance gates in `_classify` (or drop the unused policy keys + document) | medium | ~20 lines |
| 4 | Document cord_dice_pre_post + tsnr_ratio interpretation in policy YAML comments | low | comments only |

## Update 2026-05-28 — FWHM gate is WARN-only, not PASS/WARN/FAIL

The first implementation attempt enforced PASS/WARN/FAIL on per-axis
|requested - measured| FWHM with policy tolerances (0.5/1.0 mm XY,
1.0/2.0 mm Z). Empirically on the 11-run reg cohort this would FAIL
**every single run**: requested 2.4/2.4/11.8 mm against measured
~0.5–1.8 / 0.6–1.8 / 3.2–11.4 mm, giving |Δ| of 1.3–2.1 / 0.5–1.8 /
0.4–8.6 mm.

Root cause: autocorrelation-based residual-FWHM estimators
systematically **under-report** the applied kernel width when
restricted to small ROIs (well-known limitation in fMRIPrep / AFNI
3dFWHMx documentation; whole-brain ROIs are needed for accurate
recovery). Our cord-only ROI (~1000 voxels) loses 50-70% of the
applied kernel through the per-axis autocorrelation calculation.

Decision: the FWHM metric **cannot legitimately FAIL OR WARN** a run
because it can't truthfully measure cord-restricted smoothness. The
WARN-only first pass still flagged 11/11 cohort runs as WARN — same
false-alarm problem at a different threshold. Final decision: FWHM
is **observability-only** — the metric is recorded in qc.json and
visualised in the smoothness_summary reportlet (with tolerance
bands for analyst review), but does NOT enter the PASS/WARN/FAIL
classifier at all.

The smoothness_summary reportlet keeps its tolerance bands; those
visualize the same policy values but for the analyst to read rather
than a hard accept/reject.

## Update 2026-06-11 — `smoothed_vs_unsmoothed_axial` dropped

The `smoothed_vs_unsmoothed_axial` reportlet has been **removed**. S9
now ships **three** reportlets: `tsnr_map_axial`, `tsnr_per_level`,
`smoothness_summary`.

Reason: the side-by-side mean-BOLD panel added no diagnostic that the
tSNR map didn't already carry. The tSNR map is itself the smoothing
signal — smoothing's whole purpose is to raise tSNR, and that shows up
directly (and quantitatively, via `tsnr_ratio_median`) in the tSNR map
and per-level plot. The "did smoothing blur the BOLD" question the
side-by-side panel answered is redundant with "did tSNR go up", and the
extra panel diluted the eyeball signal (principle §4). The earlier
"keep both — complementary" call (Q1 above) was re-examined and
reversed: in practice a wide-blur / low-ratio mismatch shows up just as
clearly on the tSNR map (signal smeared away from the cord → low cord
tSNR) without needing the second panel.

- Esteban et al. 2019 — fMRIPrep (*Nat Methods*)
- Esteban et al. 2017 — MRIQC (*PLoS One*)
- De Leener et al. 2017 — SCT (*NeuroImage*)
- Wei et al. 2025 — CoSpine database (*Sci Data*) — per-vertebra tSNR Fig 6
- Kaptan et al. 2023 — cord rs-fMRI reliability (*NeuroImage*) — per-vertebra tSNR
- Eippert et al. 2017 — Spinal cord fMRI denoising (*NeuroImage*) — tSNR before/after
- Internal: `.claude/specs/reportlet-visual-standard.md`,
  `.claude/specs/s9-primary-functional-derivatives.md`
