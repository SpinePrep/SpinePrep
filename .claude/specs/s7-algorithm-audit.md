---
status: approved
---

# S7 algorithm audit — literature-backed, truthful, correct + reportlet QA

Companion to `.claude/specs/s7-template-normalization.md`. Audits both
the **algorithm** (PAM50 normalization via warp composition +
optional refinement + atlas-to-native warping) and the **reportlets**
against the field standard + visual standard.

## Sub-step summary

S7 takes one S6-registered BOLD run and produces:
- Composite `from-bold_to-PAM50_xfm.nii.gz` + inverse (SCT-native warps)
- Sidecar JSON with refinement params + policy SHA
- PAM50 atlas warped into native func space (cord, CSF, WM, GM,
  spinal_levels) via `sct_warp_template -a 1`
- Funcref-in-PAM50 (single 3D, QC-only)
- 3 reportlets (sagittal + axial overlay + vertebral alignment)

Engine: `sct_concat_transfo` composition of S2+S6 warps + optional
`sct_register_multimodal` EPI-level refinement + `sct_warp_template`.

## Per-choice verdict — algorithm

### Architecture

| Choice | Value | Literature | Verdict |
|---|---|---|---|
| Never resample 4D BOLD into PAM50 | atlas→native warping only | Eippert 2017; CoSpi `spi08_10_registration.sh`; SCT batch_processing.sh fMRI block | ✅ field-standard |
| Compose S2+S6 warps via `sct_concat_transfo` | single composite warp | SCT canonical | ✅ correct |
| Refinement DISABLED by default | `refinement.enable: false` | CoSpi reference does NOT refine; SCT batch_processing.sh DOES. Cohort: refinement dropped Dice from 0.82 → 0.68 on `cospine_pain` (empirical). | ⚠️ deviation from SCT canonical, but empirically validated. Documented. |
| Reference modality = `PAM50_t2s` | best contrast match for T2*-EPI | SCT batch_processing.sh; CoSpi | ✅ standard |
| Direction: `-i PAM50 -d funcref` for refinement | PAM50 is moving | SCT convention; `-owarp` is `PAM50_to_func` | ✅ standard |
| Output: SCT-native `.nii.gz` warps + BIDS sidecar | matches S2/S6 | ✅ chain-consistent |

### Refinement parameters (when enabled)

| Step | Algo | type | metric | smooth | iter | gradStep | Source |
|---|---|---|---|---|---|---|---|
| 1 | `slicereg` | seg | MeanSquares | 2 | — | — | SCT batch_processing.sh fMRI block verbatim |
| 2 | `bsplinesyn` | im | MeanSquares | — | 5 | 0.5 | SCT batch_processing.sh fMRI block verbatim |

✅ literature-backed verbatim.

### QC metrics

| Metric | Source / role | Verdict |
|---|---|---|
| `cord_dice_native_func` | PAM50_cord warped to native func vs S6 funccrop cord seg | ✅ Cohen-Adad 2014 standard, headline gate |
| `round_trip_func_med_mm` / `_max_mm` | forward∘inverse warp drift on funcref | ⚠️ intensity-weighted COM dominated by background noise — see Finding 5 |
| `label_offset_pam50_mean_mm` / `_max_mm` | subject vertebral labels warped to PAM50 vs PAM50 spinal_levels | ❌ meaningless under different label schemes — see Finding 7 |

### Cohort empirics (wf_reg_067)

11/11 runs land with valid metrics. Dice values:
- balgrist_motor: 0.92–0.93
- ds004386_rest: 0.94
- ds004616_handgrasp: 0.87–0.89
- ds005883_cospine_pain: 0.82
- ds005884_cospine_motor: 0.80 (borderline WARN), 0.81

Overall: **10 PASS + 1 WARN**. The WARN is real (cospine_motor sub-02 motorL Dice=0.797 vs 0.80 PASS gate — calibration working correctly).

All runs use `init=rootlet` from S2's preferred init method.
All runs run with `refinement_enabled=False` (policy default).

## Findings

### Finding 1 — Reportlets don't follow chain-wide visual standard

`reportlets.py` uses plain matplotlib without the
`reportlets_common.py` primitives:
- No `add_header` chrome (no title bar + status pill + Dice subtitle)
- No `add_footer` (no legend swatches + metric lines)
- No S/I/A/P + R/L orientation markers on sagittal / axial
- No per-tile Z labels
- Default `_crop_bbox` instead of `per_slice_centered_crop`
- Different palette (`#00d0ff` rather than the chain's MARKER_YELLOW
  + SEMANTIC.cord_epi)

S2/S3/S5/S6 have all been brought into compliance; S7 is the outlier.

**Recommendation**: rewrite both image reportlets on
`reportlets_common` primitives (mirror S6's composite pattern, but
with PAM50 cord contour instead of EPI cord seg). Visible chrome
matters for the user to immediately recognize the reportlet's step
and status. ~150-line rewrite.

### Finding 2 — Cyan cord contour is too thin

`linewidths=0.5` for axial and `0.8` for sagittal. The chain visual
standard uses `2.0–2.4` for cord contour on dark backgrounds. At
0.5 the contour can disappear at typical reportlet sizes (verified
visually on the cohort PNG — the cord contour is barely visible at
tile-corner resolution).

**Recommendation**: bump to `contour_lw=2.0` (matches S6 + S5).

### Finding 3 — `label_offset_*` metric is computed on incompatible label schemes

`process.py:248-280` computes a per-label centroid offset between:
- Subject's `vertebral_labels.nii.gz` from S2 — values 1..7 = C2..C8
  vertebral body labels
- PAM50's `spinal_levels.nii.gz` — values 1..20 = SEGMENTAL spinal
  cord levels (not vertebrae)

These are different anatomical concepts (vertebrae vs spinal segments
are spatially offset by 1-2 levels). Matching label values 1↔1, 2↔2
produces 17–32 mm offsets across the cohort that look catastrophic
but are anatomy mismatches, not registration failures.

The metric is **documented as observability-only** in the spec/audit
("not gating in v1") — but it remains in qc.json + sidecar and can
mislead anyone glancing at the numbers without reading the audit doc.

**Recommendation**: either
(A) drop the metric entirely (the cord Dice already validates the
    composite warp);
(B) compute label-offset only between matched-scheme labels
    (subject's vertebral labels vs PAM50's vertebral labels, not
    spinal_levels — PAM50 ships `PAM50_centerline.nii.gz` and
    `PAM50_label_disc.nii.gz` which use vertebral disc numbering); or
(C) rename to `label_offset_diagnostic_mismatched_schemes_mm` so its
    nonsense values are clearly flagged.

Recommend **A**: drop. It's noise in qc.json.

### Finding 4 — Round-trip metric is intensity-weighted COM over whole FOV

`_round_trip_displacement_mm` (process.py:283) computes:
```python
wa = a / max(a.sum(), 1.0)
ca = (coords * wa.ravel()).sum(axis=1) * zooms
```

This is the intensity-weighted center of mass of the **whole funcref
FOV** (cord + CSF + surrounding tissue + air). Background voxels
(huge in count, low individually but cumulatively large in sum) skew
the COM. The metric values 1.4–12.5 mm look concerning at first read,
but they're partly an artifact of the cord taking up ~5% of the FOV.

Documented as "observability-only" in the spec — but again, it
remains in qc.json + sidecar.

**Recommendation**: either
(A) restrict the COM to cord voxels only — push the FUNCCROP cord seg
    through the same forward∘inverse and measure cord-COM drift; or
(B) drop the metric (S6's `centerline_round_trip` already covers
    bsplinesyn drift at the func-anat tier).

Recommend **A**: cord-restricted COM is the meaningful S7 round-trip
signal.

### Finding 5 — PAM50_spinal_levels always loaded from $SCT_DIR

`process.py:441`:
```python
pam50_levels = _pam50_path(None, "template/PAM50_spinal_levels.nii.gz")
```

The first argument is hardcoded `None`, so this ignores any custom
`template.data_dir` in the policy and always reads from `$SCT_DIR`.
Inconsistent with `pam50_t2s` and `pam50_cord` which honor the
policy.

**Recommendation**: pass `template_data_dir` instead of `None` for
consistency.

### Finding 6 — Funcref-in-PAM50 interpolation policy value isn't valid SCT

Policy YAML: `interpolation.bold: "LanczosWindowedSinc"`. But
`sct_apply_transfo -x` accepts only `nn | linear | spline` — not
ANTs's `LanczosWindowedSinc`. The current code passes the policy
value verbatim:

```python
"-x", policy.get("interpolation", {}).get("bold", "spline"),
```

If the policy is loaded, SCT receives `LanczosWindowedSinc` which it
rejects → funcref-in-PAM50 fails silently (no `failure_reasons`
appended because `_run_command` swallows the error in this call site).

Verified empirically: `funcref_in_PAM50` files DO exist in the
cohort, so either SCT accepts the unknown value and substitutes
default, or it actually fails silently. Either way the policy value
is misleading documentation.

**Recommendation**: change policy YAML to `bold: "spline"` (matches
SCT's spline cubic interpolation, equivalent quality for 3D
resampling), or to `"linear"` if speed matters. Drop the
`LanczosWindowedSinc` reference (that's ANTs's interpolation name,
not SCT's).

### Finding 7 — S7 figures dir is `<dataset_key>/sub-XX/figures` (S6 uses `sub-XX/figures`)

S7 puts reportlet PNGs under
`derivatives/spineprep/<dataset_key>/sub-XX/figures/`.
S2, S5, S6 use `derivatives/spineprep/sub-XX/figures/` (no
dataset_key prefix in the path).

The S2 anat outputs already use the dataset_key prefix, so S7 inherits
that convention. S6 doesn't.

Result: per-step figures live in different subtrees:
- S2: `<dataset_key>/sub-XX/anat/...`
- S5/S6: `sub-XX/func/...` + `sub-XX/figures/...`
- S7: `<dataset_key>/sub-XX/func/...` + `<dataset_key>/sub-XX/figures/...`

Cosmetic. The dashboard server resolves each reportlet via its
qc.json path so this doesn't break the UI, but it's not BIDS-clean.

**Recommendation**: normalize to one convention. Since BIDS-Derivatives
spec allows the dataset_key prefix as the dataset name, the
S2/S7-style is actually MORE BIDS-correct. Backport S5/S6 to use the
dataset_key prefix — or accept the inconsistency and document.

Defer for now — not a blocking issue.

### Finding 8 — Axial reportlet tiles don't show vertebral-level annotation

The axial montage shows 9 cord-bearing tiles with cyan PAM50_cord
contour, but no annotation of which vertebral level (C1, C2, …, T1)
each tile corresponds to. For S7 specifically — whose job IS to align
to PAM50's vertebral coordinates — the level annotation is the
natural QC signal.

The PAM50 atlas in native func contains `PAM50_spinal_levels.nii.gz`
which maps each voxel to a 1..20 integer. For each Z slice in the
montage, we could compute the modal value of the PAM50 levels mask
at that Z and label the tile with it.

**Recommendation**: annotate each axial tile with the PAM50 level
present at that Z (e.g. "C3", "C4-5", "C5") in the corner where
other reportlets show "z=N".

### Finding 9 — Three reportlets but the third (vertebral_alignment) is largely useless

The `vertebral_alignment` reportlet shows the sagittal PAM50
spinal_levels (color-coded by level) optionally with subject
vertebral labels overlaid as white dashed contours. Because of
Finding 3 (different label schemes), the subject labels and PAM50
levels DON'T agree — they're different anatomical concepts.

So the reportlet shows two unrelated label arrays superimposed,
suggesting they should agree when they fundamentally can't.

**Recommendation**: either
(A) drop the reportlet — Finding 9 redundancy + Finding 3 conceptual
    mismatch make it less informative than the composite cord-overlay
    view; or
(B) replace with a per-level Dice bar chart (PAM50_cord cropped to
    each spinal_level, Dice within that level against the native cord
    seg). This would be the analog of S6's `cord_dice_per_slice` but
    grouped by vertebral level — much more diagnostically useful.

Recommend **B** for the next S7 touch; for now **A** (drop) is
acceptable.

### Finding 10 — Refinement disabled by default deviates from SCT canonical

The SCT `batch_processing.sh` fMRI block includes the refinement step
unconditionally. S7 disables it by default with the rationale that
on the `cospine_pain` dataset, refinement degraded Dice 0.82 → 0.68.

The "pain dataset degradation" is real — but it's one dataset; the
SCT canonical recipe assumes a different default. This deviation
needs to live in the spec (it does) AND be visible in the policy
file (it is, under the long comment in the YAML).

**Recommendation**: keep as-is, document explicitly in the audit. A
future touch could try `iter=2` or `iter=3` instead of `iter=5` to
see if a lighter refinement helps without breaking pain.

## Truthfulness review

| Claim | True? |
|---|---|
| "Never resample 4D BOLD into PAM50" | ✅ — atlas→native + funcref-only 3D push for QC |
| "Compose S2+S6 warps via sct_concat_transfo" | ✅ |
| "Refinement DISABLED by default per empirical validation" | ✅ — `cospine_pain` Dice degradation documented |
| "Cord Dice in native func is headline gate" | ✅ |
| "`label_offset_pam50_*` is observability-only" | ⚠️ technically true (not in classifier) but misleadingly large numbers in qc.json |
| "`round_trip_func_*` is observability-only" | ⚠️ same — large values look concerning despite being expected |
| "11/11 PASS on reg cohort" | ⚠️ 10 PASS + 1 WARN, not 11/11 |
| "Reportlets follow chain visual standard" | ❌ — S7 reportlets predate the standard (Finding 1) |

## Audit verdict

**S7 algorithm is correct and literature-aligned.** The composite-
warp approach (S2 ∘ S6) preserves native GLM per Eippert 2017 /
CoSpi / SCT batch_processing. The decision to disable refinement is
empirically validated (cospine_pain regression).

**Implementation has accumulated dross**:
- ⚠️ **Finding 1 + 2** (reportlets don't follow visual standard +
  thin contours) — chain-wide consistency. **Rewrite recommended.**
- ⚠️ **Finding 3** (`label_offset_*` is meaningless under different
  label schemes) — misleading qc.json values. **Drop or fix.**
- ⚠️ **Finding 4** (round-trip COM dominated by background) —
  intensity-weighted-FOV instead of cord-restricted. **Fix to cord-
  COM.**
- 🟡 **Finding 5** (`pam50_levels` always from $SCT_DIR) — small
  consistency bug.
- 🟡 **Finding 6** (`LanczosWindowedSinc` in policy isn't valid SCT
  interp) — silent failure / documentation lie.
- 🟡 **Finding 7** (figures dir convention diverges from S5/S6) —
  cosmetic.
- 🟡 **Finding 8** (axial tiles lack vertebral-level annotation) —
  enhancement, not a bug.
- 🟡 **Finding 9** (vertebral_alignment reportlet has limited value
  given Finding 3) — drop or replace with per-level Dice.
- ✅ **Finding 10** (refinement disabled is a deviation from SCT
  canonical) — documented and empirically validated, no action.

## Recommended actions

| # | Action | Priority | Effort |
|---|---|---|---|
| 1 | Rewrite `render_s7_pam50_overlay_sagittal` + `render_s7_pam50_overlay_axial` on `reportlets_common` primitives. Cord contour `lw=2.0`. Header chrome with Dice + status pill. | high | ~150 lines |
| 3 | Drop `label_offset_*` metrics from `_compute_qc` / qc.json / sidecar | high | 30 lines deletion |
| 4 | Restrict `_round_trip_displacement_mm` to cord voxels only (cord-seg-masked COM) | high | 15 lines |
| 6 | Change policy YAML `interpolation.bold` from `LanczosWindowedSinc` → `spline` | low | 1 line |
| 5 | Pass `template_data_dir` to `pam50_levels` lookup for policy consistency | low | 1 line |
| 9 | Replace `vertebral_alignment` reportlet with per-level Dice bars, OR drop entirely | medium | ~80 lines |
| 8 | Annotate axial tiles with vertebral level from `PAM50_spinal_levels` | low | ~30 lines |
| 7 | Decide figures-dir convention — backport S5/S6 to dataset_key prefix, or strip prefix from S2/S7 | low | 20 lines |

## Sources (consulted)

- Eippert et al. 2017 — Spinal cord fMRI denoising / native-GLM convention (NeuroImage)
- De Leener et al. 2018 — PAM50 template (NeuroImage)
- Cohen-Adad et al. 2014 — SCT registration validation (NeuroImage)
- Rootlets-based PAM50 registration (the anat->PAM50 init) is S2's step, not
  S7's; its attribution (Bédard/Valošek 2025) and DOI are UNVERIFIED and belong
  in the S2 audit. S7 only composes S2's warp and does not cite it.
- SCT `batch_processing.sh` — canonical fMRI block recipe
- CoSpi reference: `spi08_10_registration.sh`, `spi17_stat_standard.sh`
- Wei et al. 2025 — CoSpine database (Sci Data)
- Internal: `.claude/specs/reportlet-visual-standard.md`,
  `.claude/specs/s7-template-normalization.md`

## v2 verification (2026-07-18) — literature pass

Verified the architecture against primary sources. All confirmed sound; three
citation/framing corrections applied.

- **Keep-BOLD-native + warp-atlas-in = VERIFIED Eippert-lab practice.** Kaptan
  2023 (NeuroImage 275:120152) verbatim: "all analyses were carried out in native
  space", registering to PAM50 only "to obtain the warping fields that allowed to
  bring region-specific probabilistic masks from PAM50 template space to each
  individual's native space (sct_warp_template)". Dabbagh 2024 (imag_a_00273) same.
  Precedent is Barry 2014 (eLife e02812), which Kaptan cites. FIX: the doc/policy
  cited "Eippert 2017" for this; that specific attribution is unverified, corrected
  to Kaptan 2023 + Barry 2014.
- **Compose via anat->template seeding = VERIFIED standard** (SCT fMRI tutorial
  `-initwarp`; Kaptan 2023). NUANCE: SCT and Kaptan both still run a FRESH func
  refinement pass (reduced iterations, "sensitive to the artifacts in fMRI data").
  S7's pure-compose (no fresh func pass) is MORE conservative than both — a real
  deviation, now stated explicitly in the doc.
- **disc-label sct_register_to_template + PAM50_t2s = VERIFIED standard** (SCT
  docs; Kaptan: "C2-C7 vertebral levels ... used for the vertebral alignment").
- **Dice circularity: VERIFIED less circular than S6** (anat->PAM50 hop driven by
  anat cord + disc labels, independent of the func cord the Dice scores). The
  field's independent validator is spinal-level/landmark alignment, not cord
  outline. Open: add a level-alignment metric (the PAM50 levels came from
  independent disc labels) as the non-circular check.
- **Per-level Dice: coverage confound real, per-level reporting field-normal
  (Kaptan, Dabbagh), but "median per-level cord Dice as the gate" is UNVERIFIED as
  a published metric — it is SpinePrep's own.** Doc now says so.
- **Refinement-off: defensible.** SCT itself dials fMRI-refinement iterations DOWN
  (artifact-sensitive); skipping is within that spirit. The 0.82->0.68 drop is our
  own cohort evidence, not literature.
- **Citation hazard corrected:** PMC10769329/PMC12290578 = Dabbagh/Horn/Kaptan/
  Eippert 2024 (imag_a_00273, 3 SD), NOT "Kaptan 2023". The real Kaptan 2023 is
  NeuroImage 275:120152 (2 SD).
