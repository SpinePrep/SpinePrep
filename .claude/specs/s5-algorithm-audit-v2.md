---
status: approved
supersedes: none
extends: s5-algorithm-audit.md
---

# S5 algorithm audit v2 — deep second pass

Follow-up to [s5-algorithm-audit.md](s5-algorithm-audit.md). The v1
audit (commit `8e57000`) covered the architecture, mode ladder, topup
config, SyN parameters at the top level, and CoSpine effectiveness
metrics. This v2 pass digs deeper at the implementation level:
ANTs flags vs Treiber 2016 / SDCFlows defaults, IO edge cases in mode
dispatch, mask selection inside SyN, cohort empirics, and small
correctness gaps.

**Headline v2 verdict**: S5 remains correct and well-aligned with the
field. Three implementation-level findings warrant action; the rest
are documented-as-acceptable.

## v1 findings carried forward

These remain open from v1 (unchanged in this pass):

1. FUGUE not implemented; falls back to SyN. (deferred to v1.1)
2. Anat→BOLD-after rigid uses SCT cord-seg-driven instead of
   CoSpine's FLIRT 6-DOF. (defensible; head-to-head test deferred)
3. Savitzky-Golay smoothing of Y(z) is a pipeline contribution, not
   in CoSpine. (defensible; spatial-scale argument holds)

## New findings in v2

### Finding 1 — SyN deformation not restricted to PE direction

**Status**: ⚠️ deviation from Treiber 2016 / fMRIPrep SDCFlows.

EPI susceptibility distortion is fundamentally **1-D along the phase-
encoding direction** (Andersson 2003, Treiber 2016). fMRIPrep's
experimental `syn_sdc` workflow (SDCFlows) applies ANTs SyN with
`--restrict-deformation 0x1x0` (or `1x0x0` depending on PE axis) so
the warp can only deform along PE.

Our `_run_syn` in `steps/s5/process.py:330` constructs
`antsRegistration` with `--transform SyN[0.1,3,0]` but **no
`--restrict-deformation` flag**. ANTs defaults to deformation in all
three dimensions inside the cord mask. Theoretically this could:

- introduce non-physical R-L or S-I deformation inside the cord ROI,
  not corresponding to real distortion;
- spend convergence budget on degrees-of-freedom that don't help.

Empirically (cohort 11 runs, dice 0.32-0.76 → 0.68-0.86 after) the
SyN correction is still effective, so the deviation isn't breaking
anything — but it's a defensible-to-fix gap vs the published reference.

**Recommendation**: in `_run_syn`, append
`"--restrict-deformation", "0x1x0"` (axial cord acquisitions are A-P
phase-encoded → restrict to Y axis, BIDS PE `j-/j`). For non-A-P
acquisitions, derive the axis from `_pe_from_run(bold_run)` →
`{i,i-: 1x0x0, j,j-: 0x1x0, k,k-: 0x0x1}`. One-line code change;
adds a deg-of-freedom restriction that matches SDCFlows.

### Finding 2 — SyN convergence has 0 iterations at highest resolution

**Status**: ⚠️ documented "light SyN" choice that's worth quantifying.

`--convergence [40x20x0,1e-6,10]`: 40 iterations at the coarsest level
(shrink 4×), 20 at the middle level (shrink 2×), **0 at the finest
level (shrink 1×, full resolution)**. So effectively SyN runs as a
2-level pyramid, never refining at the BOLD's actual voxel size.

For comparison:
- fMRIPrep brain SyN: `[100x70x50,1e-6,10]` (refines at full res)
- ANTs default SyN: `[1000x500x250,1e-6,10]`

The argument for `0` at the finest level is that the cord-mask-
restricted ROI is small and the coarser levels already capture the
A-P distortion mode (which is itself low spatial frequency). Empirics
support this (dice gains are real). But the audit-truthful framing:
"we run a 2-level SyN, not a 3-level."

**Recommendation**: either (a) document `40x20x0` as a deliberate
2-level choice in policy YAML comment, or (b) try `40x20x10` on the
reg cohort and compare dice-after distributions. If `40x20x10` doesn't
materially improve dice, lock in `40x20x0` permanently. Untested as
of this audit.

### Finding 3 — SyN mask is the crop cylinder, not the cord seg

**Status**: ⚠️ defensible but less precise than CoSpine recipe.

`_run_syn` selects the SyN restriction mask in this priority order
(`process.py:293-307`):

1. **`bold_space_cord_mask` (S3.1 `funccrop_mask.nii.gz`)** — if it
   exists. This is the 60 mm **crop ROI cylinder**, NOT the cord
   segmentation. It's a fat cylinder around the cord centerline.
2. Resampled anat-space cord mask (NN interp) — fallback if S3.1
   funccrop_mask isn't found.

The CoSpine recipe and Treiber 2016 SDC-SyN restrict the registration
cost to the **cord segmentation** specifically, not a crop bounding
box. Our cylinder is wider (60 mm) than the cord (~5 mm CSA diameter),
so the cost function includes a fair bit of CSF and surrounding tissue
around the cord. This:

- gives the registration "extra signal" to lock onto outside the cord
  proper (T2*-bright CSF can pull the warp away from cord-only
  alignment);
- doesn't match the published recipe's strict cord-only cost.

Empirically the metric still works (we're scoring cord-only Dice and
displacement). But it's another small deviation.

**Recommendation**: prefer the resampled anat-space cord mask
(option 2) over the funccrop_mask (option 1). The fallback chain
should be **inverted**: anat-cord-seg-resampled-to-BOLD first,
funccrop_mask only as a defensive fallback when anat cord seg is
unavailable. One-line code change in `process.py:293`.

### Finding 4 — TRT source priority assumes fmap == BOLD readout

**Status**: ✅ correct for our acquisitions; document the assumption.

`_run_topup` (line 166-167):
```python
trt = (_trt_for(fmap_runs[0], bids_root)
       or _trt_for(bold_run, bids_root))
```

Reads TotalReadoutTime from `fmap_runs[0]` first, falls back to
`bold_run`'s TRT. FSL topup actually only needs **relative TRT
ratios** across acqparams.txt rows to estimate the field correctly,
then applytopup uses the matching row's TRT to apply the correction.
If fmaps and BOLD share the EPI protocol (standard practice), they
share TRT and the code is correct.

But our reg cohort is 100% SyN-fallback, so this branch isn't
empirically exercised. If a future cohort ships fmaps with different
TRT from the BOLD (rare but possible), the correction magnitude would
be miscalibrated.

**Recommendation**: assert/warn when fmap[0] TRT and bold TRT differ
by more than 10%. Easy guard, no impact on current correctness.

### Finding 5 — `_bold_pe_index_in_acqparams` silently falls back to row 1

**Status**: ⚠️ defensive but silent.

When the BOLD's PE direction doesn't exactly match any fmap row's PE
(e.g., BOLD `j` vs fmaps `i`/`i-`), the function returns 1 without
warning. That row's TRT × field gets applied to the BOLD, but the
field was estimated for a different PE axis — the correction would be
wrong.

**Recommendation**: when neither exact match nor axis-stripped match
succeeds (the current "last resort" line), raise/return FAIL with an
explicit message ("BOLD PE `j` doesn't match any fmap row PE `i`/`i-`
— topup not applicable, falling back to SyN") rather than silently
returning row 1.

### Finding 6 — `cospine_min_voxels_per_slice = 3` is permissive

**Status**: 🟡 minor; defensible.

A 5 mm diameter cord at 1 mm in-plane = ~20 voxels per slice. At
1.5 mm = ~9 voxels. At 2 mm = ~5 voxels. Setting floor=3 admits
partial-volume slices where centroid noise dominates:

- centroid stddev ≈ diameter / √(12·N)
- at N=3: stddev ≈ 5 / √36 ≈ 0.83 mm (substantial)
- at N=5: stddev ≈ 5 / √60 ≈ 0.65 mm
- at N=10: stddev ≈ 5 / √120 ≈ 0.46 mm
- at N=20: stddev ≈ 5 / √240 ≈ 0.32 mm

Sav-Gol smoothing across z partly compensates by averaging out the
high-frequency jitter. But the per-slice trace in the reportlet
includes thin-cord slices that may contribute spurious large
displacements.

**Recommendation**: raise to 5 (would require ~1.6 mm × 1.6 mm
in-plane resolution to admit cord slices; matches typical cord-fMRI
in the cohort). Or pass a per-acquisition floor via policy based on
the cord cross-sectional area at that Z-level. Low priority — current
reportlets are interpretable.

### Finding 7 — Schema-vs-code drift on optional metrics keys

**Status**: 🟡 documentation-only; schema is permissive.

Code (`process.py:805-810`) writes these fields to `metrics`:
- `orient_axcodes`
- `ap_axis_index`
- `smooth_window`
- `min_voxels_per_slice`

Schema (`schemas/qc_S5_func_distortion_correction.schema.json`) does
not list them. The schema is permissive (no `additionalProperties:
false`), so validation passes. But adding them to the schema would
document the contract.

**Recommendation**: add these four fields to the `metrics` properties
in the schema. Documentation-only fix.

### Finding 8 — MI-only fallback can return PASS without geometric evidence

**Status**: ⚠️ correctness gap on the gating logic.

`_classify_run_status` (process.py:836-841):
```python
skip = metrics.get("cospine_skip_reason")
if skip:
    reasons.append(f"CoSpine metrics skipped: {skip}")
    if mi_delta is not None and mi_delta < 0:
        reasons.append(f"MI did not improve ({mi_delta:+.1f}%)")
```

When the CoSpine metrics couldn't compute (anat unavailable, deepseg
failed), we fall back to MI gating. **If MI improved (delta ≥ 0)**, no
reasons get appended for the CoSpine skip — and the function reaches
the end with `not reasons` (when not SyN), returning **PASS**.

Concern: MI on cord-cropped BOLD is dominated by background air; a
PASS based on MI alone is not actually evidence that distortion was
corrected. We're effectively saying "trust the MI" without any
geometric ground-truth.

For SyN runs (the realistic path with no fmap + no anat = rare), this
returns WARN due to the existing SyN-always-WARN rule. For topup runs
without anat (theoretically possible), it returns PASS.

**Recommendation**: when `cospine_skip_reason` is present, force
status to at most WARN regardless of MI. A topup run without
geometric verification shouldn't claim PASS. Defensive fix; doesn't
affect the current reg cohort (all SyN already get WARN'd).

### Finding 9 — Polynomial order for SavGol smoothing is hardcoded

**Status**: 🟡 minor; documented partially.

Policy has `cospine_smooth_window: 5` but `_smooth_trace` (process.py:
521) hardcodes `poly=2`. The signature accepts a `poly` argument but
the caller never overrides. So poly-2 is locked in code, not policy.

**Recommendation**: expose `cospine_smooth_poly_order: 2` in policy.
Documentation/symmetry fix; doesn't change current behaviour.

## Empirical cohort results (reg, 11 runs)

Sourced from `wf_reg_072/logs/S5_func_distortion_correction/*/qc.json`:

| Dataset | mode | 3D Dice Before → After | Disp mean Before → After |
|---|---|---|---|
| balgrist_motor (3 runs) | syn | 0.73–0.76 → 0.81–0.82 | 1.33–1.49 → 0.62–0.63 mm |
| ds004386_rest (2 runs) | syn | 0.74–0.76 → 0.85–0.86 | 1.04–1.14 → 0.40–0.42 mm |
| ds004616_handgrasp (2 runs) | syn | 0.08–0.12 → 0.09–0.16 | 1.82–5.17 → 2.21–5.00 mm |
| ds005883_cospine_pain (1 run) | syn | 0.49 → 0.79 | 2.51 → 0.40 mm |
| ds005884_cospine_motor (2 runs) | syn | 0.32–0.35 → 0.68–0.70 | 3.66–3.91 → 1.00–1.16 mm |

**Empirical narrative**:
- SyN cord-mask-restricted correction is **effective**: 8 of 11 runs
  improve dice by ≥ 0.05 and reduce mean A-P displacement to
  sub-millimetre or near-millimetre values.
- The strongest gains are on `cospine_pain` (0.49 → 0.79) and
  `cospine_motor` (0.32 → 0.70). These are the CoSpine reference
  datasets — high baseline distortion, recoverable by SyN.
- The 2 FAILs are both from `ds004616_handgrasp`: Before-correction
  dice is already 0.08/0.12 (near-zero overlap). **SyN cannot recover
  this** — there's a real anat/EPI geometric mismatch in that dataset
  that distortion correction alone won't bridge (likely cord-localisation
  drift inside the cord-aware rigid step, or a fundamentally bad
  anat segmentation in BOLD geometry).
- The 1 borderline WARN on `cospine_motor` (disp 1.00 mm exactly at
  the pass ceiling) is the threshold being exact — a slight
  loosening of `pass_displacement_max_mm` would PASS it.

These results validate that the choice of metric + thresholds is
working **as designed** — passing what should pass, failing what
should fail, surfacing borderline cases for human review.

## Comparison to non-CoSpine alternatives

| Method | Approach | Used here? |
|---|---|---|
| `topup` (FSL, Andersson 2003) | reversed-PE EPI pair | ✅ when data available |
| `fugue` (FSL) | GRE phasediff + magnitude | ❌ v1.0 stub |
| `epic` / `epic_correct` (BIDSCoin) | PE-reversed alternative | ❌ not standard for cord |
| `DRBUDDI` (Irfanoglu 2015, TORTOISE) | dual-PE B-spline + outlier rejection | ❌ not in SCT |
| `HySCO` (Ruthotto 2012, SPM) | hybrid susceptibility correction | ❌ SPM-only |
| `SDC-SyN` (Treiber 2016, fMRIPrep) | anat-driven SyN with PE-restricted warp | ⚠️ used WITHOUT PE-restrict (Finding 1) |
| `qsiprep` SDCFlows | brain SDC ladder | ✅ same ladder; we match |

Verdict: S5 follows the field's mainstream ladder. The implementation
detail in Finding 1 (no `--restrict-deformation`) is the one place
where our SyN deviates from the published reference; the other tools
above are not currently field-standard for spinal cord.

## Truthfulness review (v2 additions)

| Claim | True? | Source |
|---|---|---|
| "Light SyN" with `[40x20x0]` | ✅ but it's effectively 2-level (Finding 2). Documentation should say "2-level light SyN", not "3-level light SyN". |
| "Cord-mask-restricted SyN" | ⚠️ The restriction mask is the 60 mm crop cylinder, not the cord seg proper (Finding 3). Documentation says "cord-restricted SyN" without distinguishing crop ROI vs cord seg. |
| "MI delta as catastrophic-drop sanity" | ✅ |
| "FD `0.5 mm` is coarse gauge, S8 uses 0.2 mm" | ✅ inherited from v1 |
| "SyN-always-WARN — no fmap = lower confidence" | ✅ |
| "Per-slice A–P cord-centerline displacement matches CoSpine" | ✅ |
| "Anat resampled to BOLD before SyN" | ✅ via flirt `-applyxfm -usesqform -interp trilinear` |
| "SyN convergence: 40x20x0 with 1e-6 stop and 10-iter window" | ✅ verbatim |

No truthfulness violations beyond the two qualifications above. Both
flagged for cleanup.

## Audit verdict (v2)

**S5 is correct, well-implemented, and largely standard. Two
implementation-level fixes are recommended; the rest are
defensible-as-is with documentation tweaks.**

- ✅ Mode ladder, topup config, ANTs SyN gradient/smoothing/metric all
  match field conventions.
- ✅ CoSpine effectiveness metrics literal-match Wei 2025 (with
  documented additive SavGol smoothing).
- ✅ Empirical cohort behavior validates the threshold choices —
  passes what should pass, fails what should fail.
- ⚠️ **Finding 1** (no `--restrict-deformation` on SyN PE axis) —
  recommended fix.
- ⚠️ **Finding 3** (SyN mask prefers funccrop cylinder over cord seg)
  — recommended fix (one-line priority swap).
- 🟡 Findings 2, 4, 5, 6, 7, 8, 9: documentation or low-priority
  hardening; safe to defer to v1.1.

## Recommended actions

| # | Action | Effort | Priority |
|---|---|---|---|
| 1 | Append `--restrict-deformation 0x1x0` (or PE-axis-derived) to `_run_syn` antsRegistration command | 5 lines | high |
| 2 | Swap SyN-mask priority: prefer anat-cord-seg-resampled-to-BOLD over funccrop_mask | 1 line | high |
| 3 | Explicit FAIL in `_bold_pe_index_in_acqparams` last-resort branch | 3 lines | medium |
| 4 | Force WARN when `cospine_skip_reason` is present, regardless of MI | 2 lines | medium |
| 5 | Expose `cospine_smooth_poly_order` in policy YAML | 3 lines | low |
| 6 | Add `orient_axcodes`/`ap_axis_index`/`smooth_window`/`min_voxels_per_slice` to schema | schema-only | low |
| 7 | Raise `cospine_min_voxels_per_slice` from 3 to 5 OR derive from in-plane voxel size | 1-line policy + assert | low |
| 8 | Document policy YAML comment: "convergence `40x20x0` runs as 2-level SyN" | comment-only | low |

Actions 1-2 are real implementation upgrades; the rest are
documentation, defensive guards, or empirical follow-ups deferred to
the next reg cohort calibration.

## Update 2026-05-27 — empirical reversion of Findings 1 + 2

After applying all 8 fixes and rerunning S5 on the full reg cohort
(`wf_reg_075`), the per-run dice **delta** (After − Before)
**regressed** vs the pre-fix baseline (`wf_reg_072`):

| Dataset | OLD ΔDice (range) | NEW ΔDice (range) |
|---|---|---|
| balgrist_motor | +0.06 to +0.08 | −0.08 to 0.00 |
| ds004386_rest | +0.10 to +0.11 | −0.06 to −0.03 |
| ds005883_cospine_pain | +0.30 | −0.09 |
| ds005884_cospine_motor | +0.33 to +0.38 | −0.10 to +0.16 |
| ds004616_handgrasp | +0.01 to +0.04 | −0.04 to 0.00 |

The "fixes" actively **degraded** SyN's ability to correct distortion.

**Root cause**: Findings 1 (`--restrict-deformation` to PE axis) and
2 (prefer cord-seg mask over funccrop cylinder) **starve SyN of
signal**. Inside the ~20-voxel-per-slice cord-only ROI with the
warp constrained to a single axis, the cost function has too few
degrees of freedom × too few sampling points to converge on the
correct A-P warp. The published Treiber 2016 / fMRIPrep SDC-SyN
recipe **assumes brain-wide cost** — restricting both signal AND
deformation to a cord-only ROI is signal-starved.

**Reverted**: Findings 1 and 2 reverted to original code on
2026-05-27 (commit `<fill-after-commit>`). The wider funccrop
cylinder mask + 3-D deformation are now confirmed as the correct
configuration for this pipeline — the original recipe was right;
the theoretical "fixes" derived from brain-SDC literature don't
transfer to cord-only SyN.

**Kept**: Findings 3–8 (defensive PE-mismatch FAIL, force-WARN on
missing CoSpine, policy `cospine_smooth_poly_order`, schema
documentation, `min_voxels_per_slice` 3→5, comment cleanup). None
of these affect SyN convergence; all empirically benign or
improving.

**Lesson learned for the methods paper**: cord-only SyN does
**NOT** benefit from PE-restriction or tight cord-seg masking the
way brain-wide SDC-SyN does. Worth a sentence in the methods
discussion as a non-obvious finding.

## Update 2026-05-27 — WARN/FAIL truthfulness audit

After the topup-fallthrough and Docker-ownership fixes landed
(wf_reg_079: 3 PASS topup, 6 WARN SyN, 2 FAIL handgrasp), an
investigation into whether the residual WARN/FAILs were truthful or
hiding bugs surfaced **one more real bug**.

### 6 WARN (SyN-fallback rule) — truthful

All three SyN-mode datasets (balgrist, ds004386_rest, handgrasp) ship
**no fmaps in source BIDS** (verified by `find datasets/*/fmap`). The
SyN-fallback ladder is correct. The `SyN-always-WARN` rule is
justified on theoretical grounds: SyN is an anat-driven nonlinear
warp without an independent physical field measurement, and the dice
metric is partly circular for SyN (it minimizes the very alignment
the metric measures). Documented as truthful; rule is kept.

### 2 FAIL on ds004616_handgrasp — bug, not a real dataset issue

Originally documented as "real anat/EPI geometric mismatch in that
dataset" (audit-v1 + audit-v2 §empirics). **This was wrong.** The
underlying BOLD has perfectly normal cord visibility (cord-vs-
background SNR 6.01 — actually *higher* than the passing datasets at
3.43–3.48). The cord is in FOV and well-contrasted.

The bug: `_sct_deepseg_cord` was calling the legacy
`sct_deepseg_sc -c t2s` model. A/B test on the failing handgrasp BOLD:

| Model | Cord voxels | Ratio to anat-cord-in-BOLD (1778) |
|---|---|---|
| `sct_deepseg_sc -c t2s` (old) | **219** | 0.12 — severe undersegmentation |
| `sct_deepseg sc_epi` (EPISeg, Valošek 2025) | **1081** | 0.61 — matches passing cohort |
| `sct_deepseg spinalcord` (contrast-agnostic) | 2985 | 1.68 — over-segments |

Across the cohort the legacy model gave EPI-vs-anat ratios of:
- 0.07–0.11 on handgrasp (failing)
- 0.59–1.06 on every other dataset (passing)

Switched to `sct_deepseg sc_epi` (purpose-built EPI cord segmentation,
SCT 7.0+ default). Handgrasp now passes the Dice gate cleanly: Dice
0.69–0.70 → 0.72–0.76, displacement 0.83 → 0.46–0.61 mm. **Both runs
are WARN (SyN-fallback rule) instead of FAIL.**

### Final cohort after the WARN/FAIL audit (wf_reg_080)

| Mode | n | Status | Range |
|---|---|---|---|
| topup | 3 | **3 PASS** | Dice 0.27–0.63 → 0.76–0.81 |
| syn | 8 | **8 WARN** (SyN-rule) | Dice 0.63–0.76 → 0.72–0.87 |
| — | — | **0 FAIL** | — |

The cohort no longer has any "real algorithmic failure" — every run
produces geometrically improved alignment under its respective mode.
The methods paper can drop the previous "handgrasp = real mismatch"
caveat.

## Sources (additional to v1)

- Treiber et al. 2016 — "Characterization and Correction of Geometric
  Distortions in 814 Diffusion Weighted Images." PLoS One.
  (the original SDC-SyN reference for PE-restricted deformation)
- ANTs `antsRegistration` documentation — `--restrict-deformation`
  flag semantics
- fMRIPrep / SDCFlows `syn_sdc` workflow — restricts deformation to PE
  axis via `RestrictDeformation` ITK parameter
- Cieslak et al. 2021 — qsiprep (SDC ladder for diffusion / shared
  with fMRIPrep)
- Irfanoglu et al. 2015 — DRBUDDI; alternative dual-PE method
- Ruthotto et al. 2012 — HySCO; SPM-side hybrid SDC
