---
status: approved
---

# S6 algorithm audit — literature-backed, truthful, correct + reportlet QA

Companion to `.claude/specs/s6-func-to-anat-registration.md` (principles
audit). This document audits both the **algorithm** (the SCT recipe,
mode dispatch, metrics, gates) and the **reportlets** (visual quality,
standard adherence, correctness of what they show).

## Sub-step summary

S6 takes one PASS/WARN S5 BOLD run and produces:
- `from-bold_to-anat_xfm.nii.gz` (forward SCT warp)
- `from-anat_to-bold_xfm.nii.gz` (inverse SCT warp)
- Mean BOLD in anat geometry
- tSNR funcref
- 3 reportlets (axial overlay, sagittal overlay, per-slice Dice)

The engine is a single `sct_register_multimodal` call with a 3-stage
cord-seg-driven parameter string. No mode selection (vs S5).

## Per-choice verdict — algorithm

### Engine selection

| Choice | Value | Literature | Verdict |
|---|---|---|---|
| Single-engine: `sct_register_multimodal` | CoSpi `spi06_1fov_reg.sh`; SCT batch_processing cord recipe; Kaptan 2023; CoSpine 2025 | ✅ field-standard |
| Direction: `-i funcref -d anat` (func is moving, anat is destination) | Cohen-Adad 2014; CoSpi 1FOV/2FOV recipes | ✅ standard — fewer slices on dest = faster + no anat-grid resampling of BOLD |
| Param string: `step=1,seg,centermassrot:step=2,seg,columnwise:step=3,seg,bsplinesyn,iter=20` | CoSpi verbatim | ✅ field-standard cord recipe |

### Pre-flight

| Choice | Value | Verdict |
|---|---|---|
| Sync `sform=qform` on local copies of all inputs | ✅ defensive — silent SCT failure mode |
| Crop anat to dilated cord region (`sct_crop_image -m anat_dseg -dilate 10x10x10`) | ✅ CoSpi recipe — restricts cost surface to cord context |

### Step-by-step (3-stage)

| Step | Algo | type | metric | slicewise | smooth | iter | Rationale |
|---|---|---|---|---|---|---|---|
| 1 | `centermassrot` | seg | MeanSquares | 1 | 1 | — | Bulk slicewise COM + rotation alignment. Required for oblique cord BOLDs. |
| 2 | `columnwise` | seg | MeanSquares | 1 | 1 | — | R-L scaling + A-P columnwise deformation along Z. |
| 3 | `bsplinesyn` | seg | MeanSquares | 1 | — | 20 | Non-linear B-spline refinement, slicewise. |

All three are `type=seg` (cord seg as cost), MeanSquares. Standard
cord recipe. The cord-seg-driven cost is the right choice for
cord-cropped EPI where the intensity cost surface is dominated by
air around the cord.

### Output handling

| Choice | Verdict |
|---|---|
| Save `warp_func2anat` (forward) + `warp_anat2func` (inverse) as SCT-native `.nii.gz` displacement fields | ✅ matches S2 convention |
| BIDS-style names: `from-bold_to-anat_xfm.nii.gz` + sidecar JSON | ✅ BIDS-derivatives compliant |
| Sidecar JSON carries policy SHA256, source path, registration method, params, software, repro flags | ✅ reproducibility receipt — matches principle §9 |
| Mean BOLD in anat geometry (`*_space-anat_desc-mean_bold.nii.gz`) | ✅ QC artifact |
| tSNR funcref (`*_desc-tsnr_funcref.nii.gz`) | ✅ used by S7 ratio comparison |

### QC metrics

| Metric | Type | Verdict |
|---|---|---|
| `cord_dice` (3D, EPI-cord-warped ∩ anat-cord-dseg) | Headline gate | ✅ Cohen-Adad 2014 standard; 0.89–0.97 on reg cohort |
| `cord_hd95_mm` (Hausdorff-95) | Boundary outliers | ✅ catches "Dice high but a few pixels far off" |
| `cord_asd_mm` (avg surface distance) | Boundary mean | ✅ complementary to HD95 |
| `centerline_round_trip_med_vox` / `_max_vox` | Observability | ⚠️ both fields hold the same value — see Finding 5 below |
| `mi_after` | Legacy intensity sanity | ✅ non-gating |

## Per-choice verdict — reportlets

| Reportlet | What it shows | Verdict |
|---|---|---|
| `bold_on_anat_axial` | 9-tile axial montage, BOLD intensity + cord-seg contour | ⚠️ "anat contour" is intensity-percentile, not cord seg — see Finding 8 |
| `bold_on_anat_sagittal` | Mid-sagittal slice, BOLD + anat-intensity-percentile contour + cord seg | Same issue as axial |
| `cord_dice_per_slice` | Bar chart of per-Z Dice, color-coded PASS/WARN/FAIL | ✅ purpose-fit, simple, readable |

None of the three reportlets follow the chain-wide visual standard
(`.claude/specs/reportlet-visual-standard.md`): no header chrome,
no footer, no status pill, no S/I/A/P + R/L orientation markers,
no per-tile Z labels, no consistent palette with S2 / S3 / S5.
See Finding 9.

## Findings

### Finding 1 — `_world_align_anat_z` is dead code

`process.py:48` — a 47-line helper that performs a header-only Z
translation pre-flight so anat cord COM aligns with BOLD cord COM in
world coordinates. **Never called.** Pre-flight is now the CoSpi
`sct_crop_image -m anat_dseg -dilate` approach (`_maybe_crop_anat`).
The dead helper hangs around as confusion bait.

**Recommendation**: delete `_world_align_anat_z` and its docstring
references. Or wire it back in if the cspine-pain ASD=0.56mm runs
benefit from it (untested).

### Finding 2 — `_maybe_z_crop_anat` is dead code

`process.py:98` — 60 lines implementing extent-ratio-based anat Z
cropping for partial-coverage BOLDs. **Never called.** Superseded by
`_maybe_crop_anat` (the CoSpi dilated-cord crop).

**Recommendation**: delete.

### Finding 3 — `_make_cylindric_mask` is dead code

`process.py:160` — 60 lines building a cylindric cord mask via
`sct_get_centerline` + `sct_create_mask`, with a 3-level fallback
cascade. **Never called.** The cord seg is now provided via
`-iseg funccrop_mask` directly (S3's localized cord seg).

**Recommendation**: delete.

### Finding 4 — Stale module docstring

`process.py:1-15` says:
```
Algorithm (Kaptan 2023 verbatim, intensity-agnostic):
  step1: type=seg,algo=centermass
  step2: type=seg,algo=bsplinesyn,metric=MeanSquares,smooth=1,slicewise=1,iter=3
```

But the actual `_build_param_string` defines **three** steps
(`centermassrot` → `columnwise` → `bsplinesyn,iter=20`). Docstring
predates the CoSpi 3-stage rework. Misleading for any future
contributor reading top-of-file.

**Recommendation**: rewrite the module docstring to match the actual
CoSpi 3-stage recipe.

### Finding 5 — `_centerline_round_trip` med/max are the same value

`process.py:394` computes a COM-only drift between forward∘inverse
warps and returns `(drift, drift)`. The two qc.json fields
`centerline_round_trip_med_vox` and `centerline_round_trip_max_vox`
therefore always carry identical values. The field names imply
distinct stats (median + max of a per-slice drift array), but the
implementation only computes a single scalar (norm of COM offset).

**Recommendation**: either (a) compute true per-slice drift array
and report `np.median` + `np.max`, or (b) drop one of the two
fields and rename to a single `centerline_round_trip_com_vox`.

### Finding 6 — Threshold defaults in `_classify` don't match policy YAML

`_classify` at `process.py:438` uses these `dict.get(..., default)`
values that diverge from the policy YAML:

| Threshold | Code default | Policy YAML | Diff |
|---|---|---|---|
| `pass_hd95_mm_max` | 2.0 | 4.0 | **stricter than policy** |
| `warn_hd95_mm_max` | 4.0 | 8.0 | **stricter** |
| `pass_centerline_med_vox_max` | 0.5 | 3.0 | **stricter** |
| `warn_centerline_med_vox_max` | 1.0 | 6.0 | **stricter** |

If the policy file fails to load (any YAML parse error → empty
dict), `_classify` falls back to dramatically tighter gates than
the documented policy. The cohort would partially fail under that
silent fallback.

**Recommendation**: align code defaults with policy YAML values
(set defaults to 4.0 / 8.0 / 3.0 / 6.0). Or refactor so the
policy file is treated as required.

### Finding 7 — T2star modality detection missing

`process.py:532`:
```python
anat_modality = "T1w" if "_T1w" in anat_path.name else "T2w" if "_T2w" in anat_path.name else None
```

Doesn't check `_T2star`. balgrist_motor S2 outputs `*_desc-cordref_T2star.nii.gz`;
S6 orchestrator prefers T2star → picks that file → `anat_modality`
becomes `None`. The 4 balgrist runs in the reg cohort qc.json have
`anat_modality: null`. Sidecar JSON gets `AnatModality: null`.
Cohort empirics: `anat_modality: {?: 4, T2w: 4, T1w: 3}` instead of
`{T2star: 4, T2w: 4, T1w: 3}`.

**Recommendation**: extend the modality check to `T2star` (and
`PD`, `T1map` for completeness):
```python
for mod in ("T2star", "T2w", "T1w", "PD", "T1map"):
    if f"_{mod}" in anat_path.name:
        anat_modality = mod
        break
```

### Finding 8 — Reportlet "anat contour" is intensity-percentile, not cord seg

`reportlets.py:77-79` and `:121-123` draw the "anat contour" as a
contour at the **median anat intensity** (`np.percentile(grid_anat[
grid_anat > 1e-5], 50)`). On a T2w/T1w anat in BOLD geometry, this
contour traces the median-intensity surface — which includes cord +
CSF + vertebrae + other tissues, not just the cord boundary. The
rendered axial reportlet (visible in sub-02_task-motorR) shows
chaotic orange contour lines all over the background and through
non-cord structures, not localized to the cord.

The reportlet caller has `anat_dseg_in_bold` (the warped anat cord
SEGMENTATION) available — that's the file the contour SHOULD use.
Passing the seg gives a clean cord-boundary contour, matching the
intent stated in the title ("anat contour").

**Recommendation**: thread `anat_dseg_in_bold` into both renderers
and contour at `levels=[0.5]` on the binary mask. Drop the intensity-
percentile contour. This is a correctness fix, not cosmetic — the
current contour is misleading about what "anat" means.

### Finding 9 — Reportlets don't follow the visual standard

`.claude/specs/reportlet-visual-standard.md` defines a chain-wide
visual contract: dark theme #0f1115, header (title + subtitle +
status pill), footer (legend swatches + metrics), S/I/A/P + R/L
orientation markers, per-slice cord-centered crop, voxel-faithful
rendering (`interpolation="nearest"`), pixel-aspect-aware sagittal.

S6's three reportlets predate the standard and:
- Use plain `plt.subplots`, no `add_header` / `add_footer` chrome
- No status pill
- No orientation markers
- Default `_crop_bbox` (not `per_slice_centered_crop`)
- Two-column "Mean BOLD" + "BOLD + anat" panel split in the axial —
  redundant with the visual standard's overlay-on-single-panel pattern
- Different palette (orange/blue) from S2/S3/S5 (yellow/cyan)

S2, S3, S5 have all been brought into compliance; S6 is the outlier.

**Recommendation**: rewrite `render_s6_axial` and `render_s6_sagittal`
on top of `reportlets_common.render_sagittal_plus_montage` (or the
lower-level primitives), following the S5
`distortion_effectiveness` reportlet's pattern. Keep
`render_s6_dice_per_slice` as-is (purpose-fit non-image plot, OK
without chrome).

### Finding 10 — Stale S6 cohort empirics (mode_inherited=syn for all 11)

The locked S6 at `wf_reg_066` runs against the OLD S5 state when all
11 runs were SyN-fallback. The S5 fixes (commits `2c9e5d9`,
`1f0d4c2`, `3f5f423`, `2a31eb2`) gave 3 runs (cospine_pain, 2 ×
cospine_motor) a real topup correction. Those runs should now be
classified against the STRICTER `pass_dice_min=0.85` instead of
the SyN-fallback `0.80`.

Empirically all 3 topup-eligible runs already meet 0.90+ Dice, so
they'll stay PASS — but `syn_fallback_inherited: true` is now wrong
on those 3 runs, and the sidecar JSON / qc.json `mode_inherited`
field is stale.

**Recommendation**: rerun S6 on a fresh wf, mark_done after, refresh
the stitched view. Should take ~5 min × 11 runs.

## Truthfulness review

| Claim | True? |
|---|---|
| "Kaptan 2023 verbatim, intensity-agnostic, seg-driven" | ✅ |
| "Direction: `-i funcref -d anat`" | ✅ |
| "3-stage CoSpi recipe centermassrot → columnwise → bsplinesyn iter=20" | ✅ in code, ❌ in module docstring (says 2-stage iter=3) — see Finding 4 |
| "Dice as headline metric (Cohen-Adad 2014)" | ✅ |
| "HD95 / ASD as boundary complements" | ✅ |
| "anat contour overlay on axial / sagittal reportlets" | ❌ — contour is intensity-percentile, not cord seg — see Finding 8 |
| "centerline round-trip med/max" | ❌ — both fields are the same scalar — see Finding 5 |
| "11/11 PASS on reg cohort" | ✅ |
| "Threshold defaults follow policy YAML" | ❌ — code defaults are 50-80% stricter — see Finding 6 |

## Empirical cohort results (wf_reg_066)

11/11 PASS. Strong metrics:

| Dataset | Dice | HD95 (mm) | ASD (mm) |
|---|---|---|---|
| balgrist_motor (4 runs) | 0.96–0.97 | 1.00 | 0.09–0.13 |
| ds004386_rest (2 runs) | 0.95 | 1.00 | 0.14–0.16 |
| ds004616_handgrasp (2 runs) | 0.89–0.91 | 1.41 | 0.37–0.44 |
| ds005883_cospine_pain (1 run) | 0.90 | 4.00 | 0.56 |
| ds005884_cospine_motor (2 runs) | 0.89–0.90 | 1.50–3.00 | 0.50–0.65 |

**Caveats**:
- All 11 runs report `syn_fallback_inherited=true`. Stale (Finding 10).
- HD95 = 1.00 mm on most balgrist runs is right at the floor (1 voxel)
  — the cord-seg-driven bsplinesyn iter=20 can produce extremely tight
  registrations on cord-shimmed data. Verified plausible, not a bug.
- The 4.00 mm HD95 on cospine_pain is right at the pass ceiling — that
  run is borderline. After S5 was switched to topup mode (now PASS,
  Dice=0.81), the S6 input changed. Rerun needed (Finding 10).

## Audit verdict

**S6 is algorithmically correct and literature-aligned.** Empirics
say 11/11 PASS at strong Dice/HD95 values. The published recipe is
followed verbatim.

**However**, the implementation has accumulated dross:
- ⚠️ **Finding 8 (anat contour bug)** — real correctness issue in the
  reportlet; misleading visualization. **Recommended fix**.
- ⚠️ **Finding 6 (threshold defaults vs policy)** — silent regression
  risk if policy YAML ever fails to load. **Recommended fix**.
- ⚠️ **Finding 7 (T2star modality)** — affects 4 of 11 runs' metadata.
  **Recommended fix**.
- ⚠️ **Finding 9 (reportlets don't follow visual standard)** — chain-
  wide consistency. **Recommended rewrite using reportlets_common**.
- 🟡 **Finding 10 (stale S5 inheritance)** — rerun + relock S6.
- 🟡 **Findings 1-3 (dead code)** — delete three unused helpers (~170
  lines).
- 🟡 **Findings 4, 5** — docstring + metric-naming cleanups.

No critical bugs in the actual registration pipeline; the warps and
gates work. The findings are all in the surrounding code: dead
helpers, stale docstrings, miscoded reportlet contour, mismatched
defaults, missing T2star case.

## Recommended actions

| # | Action | Priority | Effort |
|---|---|---|---|
| 8 | Fix `anat contour` in axial + sagittal reportlets — use cord seg, not intensity percentile | high | ~10 lines |
| 6 | Align `_classify` defaults with policy YAML values | high | 4 lines |
| 7 | Add `T2star`/`PD`/`T1map` to modality detection in process.py | high | 5 lines |
| 9 | Rewrite axial + sagittal reportlets on `reportlets_common` primitives | medium | ~200 lines |
| 4 | Rewrite module docstring | low | 10 lines |
| 1-3 | Delete dead helpers (`_world_align_anat_z`, `_maybe_z_crop_anat`, `_make_cylindric_mask`) | low | -170 lines |
| 5 | Fix `_centerline_round_trip` to compute true per-slice med/max, OR rename field | low | 15 lines |
| 10 | Rerun S6 on a fresh wf after S5 was rebuilt; relock | medium | ~30 min cohort time |

## Sources (consulted)

- CoSpi `spi06_1fov_reg.sh` — the 3-stage recipe origin
- Kaptan et al. 2023 — Reliability of resting-state functional connectivity
  in the human spinal cord (NeuroImage)
- Wei et al. 2025 — CoSpine database (Sci Data)
- Cohen-Adad et al. 2014 — Spinal cord registration toolbox validation
- Eippert et al. 2017 — Cord fMRI denoising
- SCT — `sct_register_multimodal` docs; `sct_apply_transfo` docs
- BIDS Derivatives spec — `*_from-X_to-Y_xfm.nii.gz` + JSON sidecar
- Internal: `.claude/specs/reportlet-visual-standard.md`,
  `.claude/specs/s6-func-to-anat-registration.md`
