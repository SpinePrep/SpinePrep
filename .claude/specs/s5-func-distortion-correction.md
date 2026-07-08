---
status: implemented
---

# S5 func distortion correction — audit against dev principles

Step-local audit of S5 against the SpinePrep development principles
(`CLAUDE.md`). Implementation spec lives in `private/SPEC/S5_func_distortion_correction.md`.

S5 received the deepest audit-and-rework in the May 2026 cycle —
v1 reportlets (`crop_box_sagittal` + `mi_summary`) were replaced with
CoSpine-style geometric metrics (Wei et al., Sci Data 2025), then a v2
re-rework added proper FLIRT/SCT cost-driven registration and
per-slice smoothing.

## Objective

For each cord-fMRI BOLD run, correct EPI susceptibility distortion in
the A–P direction. Per-run mode selection:

1. **topup** — when reversed-phase EPI fieldmap pair is available (FSL).
2. **fugue** — when GRE phasediff + magnitude fieldmap is available (v1: falls back to SyN).
3. **syn** — anat-driven nonlinear fallback (ANTs SyN with MI cost, restricted to cord region) when no fieldmap exists.

## Literature backing

| Choice | Source |
|---|---|
| topup ranked first | Andersson 2003; Wei 2025 CoSpine (topup gave 2.73 → 0.13 mm A–P displacement on cord) |
| SyN as anat-driven fallback | fMRIPrep brain convention; ANTs SyN MI for multi-modal |
| sct_register_multimodal rigid (anat→BOLD-after) for reference alignment | CoSpine §Registration calls for cost-driven FLIRT 6-DOF; intensity-only FLIRT diverges on cord-cropped inputs (cost dominated by air around the cord), so we use SCT's cord-seg-driven rigid — same end goal, more robust for our geometry. Same registration recipe S6 uses for func→anat. |
| Per-slice A–P cord-centerline displacement | CoSpine §Slice-by-slice Y-axis displacement. Headline truth metric |
| 3D cord Dice (`sct_dice_coefficient`-equivalent) | CoSpine §Spinal cord DSC |
| Savitzky-Golay smoothing of per-slice Y(z) | Suppresses ~0.3 mm finite-voxel sampling jitter on thin cord (cord disc ≈ 12–20 voxels @ 1 mm in-plane → centroid stddev ≈ d/√(12·N)). Preserves the 5–10-slice spatial scale of real distortion variation. |

## Step-local truth metrics (principle §3) — CoSpine v2

| Metric | What it measures |
|---|---|
| `dice_3d_after` | 3D cord-Dice between EPI cord seg (sct_deepseg_sc on mean-BOLD-after) and PAM50-anat cord ground truth in BOLD voxel grid. **Headline gate.** |
| `dice_mean_after` | Mean per-slice 2D Dice |
| `dice_delta` | `dice_mean_after − dice_mean_before` (positive = correction helped) |
| `displacement_mean_after_mm` | Mean per-slice |Δy| (EPI cord centroid vs anat centroid in mm). **Second headline gate.** |
| `displacement_max_after_mm` | Worst per-slice displacement |
| `displacement_delta_mm` | `mean_after − mean_before` (negative = improvement) |
| `dice_per_slice_*` / `displacement_*_mm` (arrays) | Per-Z traces for the two reportlets |
| `n_slices_evaluated` | Number of cord-bearing Z slices that passed the min-voxel floor |
| `orient_axcodes` / `ap_axis_index` | Affine-derived A–P axis (defensive for non-RPI data) |
| `mi_before` / `mi_after` / `mi_delta_pct` | Legacy MI — kept as secondary sanity (catastrophic drop fails outright) |
| `cospine_skip_reason` | Present iff CoSpine metrics could not be computed (anat unavailable, deepseg failure) — fallback to MI gating |

## Diagnostic reportlets (principle §4)

| Reportlet | What it shows |
|---|---|
| `slice_displacement` | Per-Z A–P displacement trace (Before grey, After blue) + mean ± SD bar. Title encodes mode + Δmean. |
| `cord_dice_per_slice` | Per-Z 2D Dice trace + mean Dice bar + 3D pooled Dice in the title. |

Both PNGs use a black background with the per-slice trace on the left
and a summary bar on the right. A human can tell from one image whether
distortion correction worked, by how much, and where in the cord it
worked best.

## Threshold rationale (`policy/S5_func_distortion_correction.yaml`)

| Gate | Value | Source |
|---|---|---|
| PASS `pass_dice_min` | 0.50 | CoSpine bands: post-correction Dice well above 0.50 expected for fieldmap modes; SyN-fallback typically 0.5–0.8 |
| WARN `warn_dice_min` | 0.30 | Below this on After ⇒ FAIL outright |
| PASS `pass_displacement_max_mm` | 1.0 | CoSpine TOPUP achieved 0.13 mm; 1.0 is a defensible "well-corrected" floor |
| WARN `warn_displacement_max_mm` | 2.0 | Above this on After ⇒ FAIL |
| `epsilon_dice` | 0.02 | Tolerance for "did not degrade" — Dice may drop slightly on small effects |
| `epsilon_displacement_mm` | 0.2 | Tolerance for "did not worsen" |
| `cospine_smooth_window` | 5 | Savitzky-Golay window (odd) for Y(z) smoothing |
| `cospine_min_voxels_per_slice` | 3 | Drop slices with thin cord — centroid sampling-dominated below this |
| `fail_mi_max_drop_pct` | 10.0 | Legacy catastrophic-drop sanity check |

SyN mode is **always** WARN: no fieldmap ⇒ lower confidence regardless
of Dice. Documented in `_classify_run_status`.

## Decision log (v1 → v2)

| # | Decision | Rationale |
|---|---|---|
| 1 | Drop `crop_box_sagittal` + `mi_summary` (v1) | Qualitative montage didn't quantify; MI is monotone with Dice but less interpretable |
| 2 | Add `slice_displacement` + `cord_dice_per_slice` (CoSpine v1) | Literal CoSpine metrics; quantitative, geometric, interpretable |
| 3 | Replace `-applyxfm -usesqform` with `sct_register_multimodal` rigid (v2) | sform-only header alignment leaves 1–3 mm common-mode offset that pollutes per-slice traces |
| 4 | Add Savitzky-Golay smoothing of Y(z) (v2) | Suppresses ~0.3 mm finite-voxel centroid jitter |
| 5 | Affine-derive AP axis via `nib.aff2axcodes` (v2) | Defensive for non-RPI data (S2 enforces RPI for anat but BOLD chain may differ) |
| 6 | Min-voxel-per-slice floor of 3 (v2) | Drop edge slices where centroid is sampling-dominated |
| 7 | Keep SyN-always-WARN rule | No-fmap mode is inherently lower-confidence; geometric metric alone shouldn't override the absence of ground truth |
| 8 | Track `cospine_skip_reason` + fall back to MI when CoSpine unavailable | Defensive: missing anat shouldn't break gating |

## Audit verdict per principle

| # | Principle | Verdict |
|---|---|---|
| 1 | Small dev cohort | ✅ 11 runs / 5 datasets |
| 2 | Literature defaults | ✅ topup→fugue→SyN ladder + CoSpine recipe |
| 3 | Step-local truth metric | ✅ CoSpine Dice + displacement (replaced MI) |
| 4 | Diagnostic reportlet | ✅ 2 PNGs, quantitative + per-slice |
| 5 | Visual QC validator | ✅ |
| 6 | Lock and ship | ✅ policy with v2 thresholds + audit doc |
| 7 | No chain backtracking | ✅ |
| 8 | Full cohort = deliverable | ✅ |
| 9 | Reproducible | ✅ schema + policy + spec |
| 10 | Heterogeneity is the test | ✅ — the 2 handgrasp FAILs are *real* geometric mismatches surfaced by the new metric (dice 0.07–0.18, disp 3.6–5.0 mm), not v1 artefacts. Documented in commit `972e9fe`. |

## Run-set status

After the v2 rework on the 11-run reg set:

- 9 WARN — all SyN-fallback (no fieldmap available in the reg cohort); the geometric metrics themselves are good (dice_after 0.55–0.86, disp_after 0.40–1.17 mm)
- 2 FAIL — handgrasp `ds004616` sessions with dice_after 0.07–0.18 and disp_after 3.6–5.0 mm. Real anat/EPI geometric mismatch in that dataset; the new metric correctly surfaces it.

## Remaining gaps (acceptable / deferred)

- Per-vertebral-level breakdown of displacement/Dice (CoSpine's "C1–T1 segments" framing). Defer until a vertebral-level mapping is available in BOLD geometry (S7 emits this for PAM50 space; would need to backproject).
- No "topup-on-the-only-reg-dataset-that-has-fmaps" test — all 5 reg datasets are SyN-fallback because none ship reversed-PE pairs. The topup code path is therefore exercised only by unit tests, not by the reg-set. Acceptable for now; the unit tests assert command-line construction and warp-file existence.

## v1.1 work items (from `.claude/specs/s5-algorithm-audit.md`)

The audit-and-rework cycle surfaced three deferrable items, none of
which affect v1.0 correctness:

1. **Implement FUGUE mode.** The `_run_fugue()` stub returns FAIL,
   forcing fall-through to SyN. fMRIPrep SDCFlows ships GRE-based
   unwarping; we don't, but no reg-cohort run has a GRE phasediff +
   magnitude pair so the gap is currently untested. When a cohort
   ships GRE data, implement using `fugue` + the GRE-derived field map
   in rad/s. See FSL `fugue` user guide.

2. **Head-to-head SCT-vs-FLIRT-6DOF reg comparison.** Our anat→BOLD-
   after rigid uses `sct_register_multimodal -param type=seg,algo=rigid`
   instead of CoSpine's `FLIRT -dof 6 -cost normmi`. The deviation is
   defensible (FLIRT intensity-only cost on cord-cropped inputs is
   air-dominated and diverges), but it would be cleaner to record an
   empirical comparison rather than only a theoretical justification.

3. **Integration test on fmap-equipped public dataset.** Find a public
   cord-fMRI dataset with reversed-PE fmaps (CoSpine itself ships some;
   `ds-fmripreptests` has brain analogues but not cord). Run S5 topup
   path end-to-end on at least one subject so the topup branch is
   exercised by something more than unit tests.
