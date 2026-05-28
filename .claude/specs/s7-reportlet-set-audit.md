---
status: approved
---

# S7 reportlet+metric-set audit — redundancy + field-standard composition

This audit examines whether S7's three reportlets and three metric
families are well-chosen, non-redundant, and complete, by comparing
against the cord-fMRI / brain-fMRI template-normalization-QC
literature.

## Current S7 outputs

### Reportlets

| # | Reportlet | Content |
|---|---|---|
| 1 | `pam50_overlay_sagittal` | Mid-sagittal funcref with PAM50_cord contour (cyan, lw=0.8) |
| 2 | `pam50_overlay_axial` | 9-slice axial montage of funcref with PAM50_cord contour (cyan, lw=0.5) |
| 3 | `vertebral_alignment` | Mid-sagittal of warped PAM50_spinal_levels (color-coded 1..20). Optionally overlays subject vertebral labels as dashed white contour. |

### Metrics (qc.json)

| Metric | Role | Gated? |
|---|---|---|
| `cord_dice_native_func` | PAM50_cord-in-func vs S6 funccrop cord seg | ✅ headline gate |
| `label_offset_pam50_mean_mm` / `_max_mm` | per-label centroid offset | ❌ observability-only |
| `round_trip_func_med_mm` / `_max_mm` | forward∘inverse warp drift on funcref | ❌ observability-only |

## Field-standard QC for cord-fMRI template normalization

I reviewed 7 published tools / pipelines:

| Source | Reportlets | Metrics |
|---|---|---|
| **fMRIPrep brain normalization** (Esteban 2019) | Composite multi-pane: subject T1w warped to MNI + MNI reference + tissue-mask overlay. Animation/dynamic overlay in HTML. | Single Dice + alignment quality flag. |
| **qsiprep** (Cieslak 2021) | Same composite-view + per-region Dice. | Per-region Dice. |
| **SCT QC tool — sct_register_to_template** (De Leener 2014/2017) | Multi-slice axial mosaic with PAM50 cord + atlas contour overlay. | Whole-cord Dice. |
| **CoSpine 2025 Fig 5** (Wei et al., *Sci Data*) | Sagittal subject-in-PAM50 with template cord contour + per-vertebra alignment chart. | **3D Dice + per-vertebra Dice + label offset.** |
| **Kaptan 2023** (Eippert lab, *NeuroImage*) | Atlas-in-native overlay + per-vertebra Dice bar chart. | **3D Dice + per-vertebra Dice (C1–T1).** Per-level breakdown is THE highlighted signal. |
| **Valošek 2025 — Rootlets paper** (*NeuroImage*) | Per-subject per-level offset plot, rootlet vs disc init comparison. | Per-level vertebral offset (mm). |
| **MRIQC** | Composite multi-view + quantitative summary table. | Aggregate metrics. |

**Consensus pattern**:
- **Composite-view figure** (axial montage + sagittal or both) — universal
- **Per-vertebral-level quantitative breakdown** (Dice or offset) —
  highlighted by Kaptan 2023, Valošek 2025, CoSpine 2025
- **Two figures per step** is the dominant pattern (composite +
  quantitative)
- **No standalone single-view PNG** — composite is preferred

## Reportlet redundancy analysis

### Reportlets #1 (sagittal) and #2 (axial) — same data, different cuts

These are the same standard "sagittal + axial-montage" pair as S6.
Same single-modality background (funcref) and same single overlay
(PAM50_cord contour). The S6 cleanup audit established the convention
of **combining them into one composite figure** (sagittal strip on
left + axial grid on right). S7 hasn't been converted yet.

**Verdict**: ⚠️ standalone sagittal-only and axial-only are
redundant **as separate figures** — they should be one composite,
matching S6 + the literature consensus.

### Reportlet #3 (`vertebral_alignment`) — broken by design

Two known issues:
- **Conceptual mismatch** (audit Finding 3 in
  `s7-algorithm-audit.md`): subject `vertebral_labels.nii.gz` uses
  vertebral-body numbering (1..7 → C2..C8) while PAM50
  `spinal_levels.nii.gz` uses segmental-level numbering (1..20 →
  spinal segments). The two arrays cannot agree on a per-label
  centroid basis — they're different anatomical concepts.
- **No comparison signal** when subject labels aren't passed
  (verified: balgrist runs render only the PAM50 levels, no overlay
  comparison — see `wf_reg_067` empirical PNGs).

When the user looks at the rendered output:
- With subject labels overlaid: false "disagreement" because schemes
  don't match.
- Without subject labels (the typical case on the reg cohort): just
  shows the warped PAM50 levels, which doesn't QC anything —
  registration could be totally wrong and the levels would still
  appear as colored blocks.

**Verdict**: ❌ **the reportlet conveys no diagnostic signal as
currently designed**. Drop or replace.

## Metric redundancy + correctness analysis

| Metric | Verdict | Reason |
|---|---|---|
| `cord_dice_native_func` | ✅ keep | Cohen-Adad 2014 cord-registration standard; headline gate; works across cohort. |
| `label_offset_*` | ❌ drop | Different label schemes (see audit Finding 3); 17-32 mm values in qc.json mislead. |
| `round_trip_func_*` | ⚠️ replace | Intensity-weighted COM over whole FOV dominated by background voxels (see audit Finding 4). Replace with **cord-restricted COM** for meaningful drift signal. |

The literature consensus highlights **per-vertebral-level Dice** as
the most diagnostic S7 metric (Kaptan 2023, CoSpine 2025, Valošek
2025). We don't have this; we should add it.

## Optimal reportlet+metric set (proposal)

Mirror the S6 cleanup pattern: **composite-view + quantitative**.

### Reportlets (2)

```
1. pam50_on_func          — composite registration QC:
                            sagittal pair (funcref + funcref/anat
                            context optionally) + 3 cord-bearing axial
                            tiles, all with the warped PAM50_cord
                            contour (yellow, lw=2.0) AND the
                            PAM50_spinal_levels color-coded sagittal
                            overlay so the user sees BOTH the cord
                            boundary alignment AND which vertebral
                            levels are present in the FOV. Header
                            pill from Dice + Dice value + status.

2. cord_dice_per_level    — per-vertebral-level 3D Dice bar chart
                            (Kaptan 2023 standard). Each bar is one
                            PAM50_spinal_levels segment present in
                            the BOLD FOV, height = Dice between
                            PAM50_cord-restricted-to-that-level and
                            the native cord seg restricted to the
                            same Z slices. Color bands PASS / WARN /
                            FAIL. Catches "global Dice high but
                            C7-T1 alignment poor" — the actual
                            failure mode for cervical-cord scans.
```

### Metrics

```
KEEP:
  cord_dice_native_func                — overall 3D Dice in native (gating)

ADD:
  cord_dice_per_level                  — dict {level_id: dice} for
                                          PAM50_spinal_levels values
                                          present in the BOLD FOV
  vertebral_level_coverage             — list of int level IDs in FOV
                                          (e.g. [3, 4, 5, 6] for a
                                          C3–C6 cervical scan)
  cord_round_trip_med_mm               — cord-MASK-restricted COM
                                          drift on forward∘inverse
                                          (replaces FOV-wide
                                          round_trip_func_med_mm)
  cord_round_trip_max_mm

DROP:
  label_offset_pam50_mean_mm           — meaningless under mismatched schemes
  label_offset_pam50_max_mm
  round_trip_func_med_mm               — FOV-dominated, not cord-restricted
  round_trip_func_max_mm
```

### What's gone

| Dropped | Why |
|---|---|
| `pam50_overlay_sagittal` (standalone) | redundant with composite |
| `pam50_overlay_axial` (standalone) | redundant with composite |
| `vertebral_alignment` (broken) | conceptual mismatch (Finding 3 / 9) |
| `label_offset_*` metrics | mismatched-scheme noise |
| `round_trip_func_*` (FOV-wide) | replaced by cord-restricted version |

## Truthfulness review

| Claim | True? |
|---|---|
| "3 reportlets is the right number for S7" | ❌ — field uses 2 (composite + quantitative); the third was broken by design |
| "label_offset is observability-only and that's OK" | ⚠️ — true that it's not gated, but 17-32mm values in qc.json mislead. Drop. |
| "round_trip catches bsplinesyn drift" | ⚠️ — intensity-weighted FOV-wide COM is dominated by background. Cord-restricted COM is the meaningful version. |
| "Vertebral alignment reportlet shows vertebral alignment" | ❌ — without comparison signal (and with conceptual mismatch when present), it shows only the warped levels block-by-block |
| "Composite + per-level Dice matches Kaptan 2023 / CoSpine 2025 / Valošek 2025" | ✅ — three independent sources highlight per-level Dice as the diagnostic |

## Optimal reportlet contract — what S7 should emit

After cleanup:

1. **`pam50_on_func`** — the visual answer to "did the composite
   S2∘S6∘S7 warp land PAM50 on the BOLD?" Sagittal + axial composite
   with cord boundary contour and spinal-level color blocks.

2. **`cord_dice_per_level`** — the quantitative answer to "is the
   alignment uniform across the cord, or does it fail at specific
   vertebral levels?" Per-PAM50-level Dice bars. Field-standard per
   Kaptan 2023 + CoSpine 2025 + Valošek 2025.

Two reportlets, field-standard composition.

## Implementation map

| Step | Action | Effort |
|---|---|---|
| 1 | Delete `render_s7_pam50_overlay_sagittal` (standalone). | ~30 lines |
| 2 | Delete `render_s7_vertebral_alignment` (broken). | ~70 lines |
| 3 | Rename + rewrite `render_s7_pam50_overlay_axial` → `render_s7_pam50_on_func`. Use `reportlets_common` primitives (sagittal strip + axial grid; cord contour at lw=2.0; header chrome with Dice pill; footer legend). Add spinal-level color blocks behind the cord on the sagittal anchor for vertebral coverage context. | ~200 lines new |
| 4 | New `render_s7_cord_dice_per_level` — bar chart, one bar per `PAM50_spinal_levels` value present in BOLD FOV, height = per-level Dice, color-coded PASS / WARN / FAIL. | ~80 lines new |
| 5 | In `process.py` compute `cord_dice_per_level` dict + `vertebral_level_coverage` list; restrict round_trip to cord voxels. | ~50 lines |
| 6 | Drop `label_offset_*` metrics + their helper. | ~50 lines deletion |
| 7 | Update schema (drop dropped metrics + reportlets, add new) | ~30 lines |
| 8 | Update `qc_dashboard_html.py` REPORTLET_ORDER + REPORTLET_LABELS | ~10 lines |
| 9 | Rerun cohort on a fresh wf, mark_done + view refresh | ~30 min |

## Sources

- Esteban et al. 2019 — fMRIPrep, *Nat Methods*
- Cieslak et al. 2021 — qsiprep, *Nat Methods*
- De Leener et al. 2014/2017 — SCT, *NeuroImage*
- Wei et al. 2025 — CoSpine database, *Sci Data*
- Kaptan et al. 2023 — Reliability of cord rs-fMRI, *NeuroImage*
- Valošek et al. 2025 — Rootlets-based PAM50 registration, *NeuroImage*
- Esteban et al. 2017 — MRIQC, *PLoS One*
- Internal: `.claude/specs/reportlet-visual-standard.md`,
  `.claude/specs/s7-algorithm-audit.md`,
  `.claude/specs/s6-reportlet-set-audit.md` (S6 went through the
  same cleanup; S7 follows the same pattern).
