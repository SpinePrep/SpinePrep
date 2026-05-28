---
status: approved
---

# S6 reportlet-set audit — redundancy + field-standard composition

This audit examines whether S6's three reportlets are well-chosen,
non-redundant, and complete, by comparing against the cord-fMRI /
brain-fMRI registration-QC literature and adjacent fields.

## Current S6 reportlets

| # | Reportlet | Content |
|---|---|---|
| 1 | `bold_on_anat_axial` | **Composite view**: 2 tall-narrow sagittal strips (BOLD + Anat) on the left, 3×2 axial montage (BOLD top, Anat bottom) on the right. Yellow anat-cord contour + cyan EPI-cord contour on every panel. Header: Dice + HD95. |
| 2 | `bold_on_anat_sagittal` | **Sagittal-only view**: 2 paired mid-sagittal panels (BOLD + Anat), big (~38% width each). Same overlays as #1. |
| 3 | `cord_dice_per_slice` | **Quantitative**: per-Z 3D Dice bar chart, color-coded PASS/WARN/FAIL band. |

## Field-standard registration QC visualisations

I reviewed 7 published tools / pipelines for cord-fMRI and brain-fMRI
registration QC:

| Source | Reportlet composition |
|---|---|
| **fMRIPrep SDC report** (Esteban 2019, *Nat Methods*) | Sagittal triptych (Distorted EPI \| Corrected EPI \| Anat ref) + anat contour overlay. **Single composite figure**, no separate sagittal-only or axial-only. |
| **qsiprep** (Cieslak 2021) | Same composite as fMRIPrep, for diffusion. |
| **SCT QC tool** (De Leener 2014/2017) | Axial mosaic + mid-sagittal in **single multi-pane HTML**. No standalone sagittal. |
| **CoSpine 2025 Fig 4** (Wei et al., *Sci Data*) | Axial cord-cropped mosaic + per-slice displacement bar chart. **2 figures**, no separate sagittal. |
| **Kaptan 2023** (Eippert lab, *NeuroImage*) | 3D Dice + per-vertebra Dice + axial mosaic. **No separate sagittal**. |
| **MRIQC** (Esteban 2017) | Composite multi-view; quantitative summary table separately. |
| **Klein 2009 ANTs evaluation** | Checkerboard overlay + per-region Dice bar charts. Composite figures. |

**Consensus pattern**: **One composite-view figure + one quantitative
figure.** Two figures per registration step. None of the
7 tools keeps a standalone sagittal-only view alongside a composite
that already has sagittal.

## Redundancy analysis (S6 reportlets 1 vs 2)

The composite axial reportlet (#1) already contains a sagittal pair —
tall-narrow strips at ~8.5% figure width each, properly aspect-matched
to the cord's 1:3.4 W:H, showing BOLD and Anat with full overlays + S/I/A/P
markers + status pill. The standalone sagittal (#2) shows the **same
mid-sagittal slice at midcord X**, the **same two backgrounds (BOLD +
Anat)**, the **same two overlays (anat + EPI cord)**. Only difference:
**panel size** (38% width vs 8.5% width).

| Aspect | Composite axial (#1) | Standalone sagittal (#2) | Different? |
|---|---|---|---|
| Sagittal cut plane | midcord X | midcord X | ❌ same |
| Background image(s) | BOLD + Anat | BOLD + Anat | ❌ same |
| Overlay contours | anat-cord + EPI-cord | anat-cord + EPI-cord | ❌ same |
| Z slices covered | full Z range | full Z range | ❌ same |
| Panel area | 8.5% × 2 = 17% | 38% × 2 = 76% | ✅ bigger |

The only thing the standalone sagittal adds is **magnification**. No new
view, no new signal, no new slice, no new modality.

**Verdict**: ⚠️ **redundant**. The 8.5%-width sagittal strips in the
composite reportlet are already sized to the cord data aspect (1:3.4) so
no information is being lost at the small size — the cord fills the
strip vertically. The bigger standalone version just renders the same
voxels larger.

## Reportlet #3 (cord_dice_per_slice) — not redundant

The per-slice Dice bar chart is qualitatively different:
- **Different question**: not "where is the cord" (image overlay) but
  "how good is the alignment at each Z" (quantitative gauge)
- **Different signal**: numeric metric, color-coded by gate
- **Different use case**: spot Z slices where registration is locally
  poor (a low bar in the middle of a high-Dice run)

Matches Kaptan 2023's per-vertebra Dice + CoSpine 2025's per-slice
displacement bar — field-standard quantitative complement to the visual
overlay.

**Verdict**: ✅ **keep**, not redundant.

## Truthfulness review

| Claim | True? |
|---|---|
| Composite reportlet is "the registration QC view" (axial + sagittal in one figure) | ✅ — matches fMRIPrep/qsiprep/SCT/CoSpine consensus |
| Standalone sagittal adds new information | ❌ — same data, just zoomed |
| 3 reportlets per registration step is standard | ❌ — field uses 2 (composite-view + quantitative) |
| Per-slice Dice is a field-standard complement to overlay | ✅ — Kaptan 2023, CoSpine 2025 use per-slice quantitative bars |

## Optimal reportlet set (proposal)

```
1. bold_on_anat                  — composite: axial montage + sagittal
                                   pair, both with anat-cord + EPI-cord
                                   contours, BOLD vs Anat dual modality.
                                   Renamed from bold_on_anat_axial; the
                                   "axial" suffix understated what this
                                   composite actually shows.

2. cord_dice_per_slice           — quantitative per-Z Dice bar chart,
                                   color-coded PASS/WARN/FAIL.
```

**Drop**: `bold_on_anat_sagittal` (redundant magnification of data
already in `bold_on_anat`).

## Optional enrichment (deferred)

The dice-per-slice plot is sparse — just one bar per Z. Could be
enriched with:

- **HD95 per slice** as a secondary trace (line plot overlaid on the
  Dice bars). Catches "Dice high, one outlier voxel far off" cases that
  the headline HD95=4.27 alone doesn't localize. Kaptan 2023 plots per-
  vertebra HD complementarily.

- **Per-slice cord centroid offset (mm)** as a secondary trace. Matches
  CoSpine 2025's per-slice displacement reportlet aesthetic and would
  ground-truth where the warp deviates from anat-cord centroid.

Defer to a v2 of the dice reportlet if a regression actually surfaces
where Dice alone misses the failure mode. v1 cohort empirics
(cospine_motorR HD95=4.27 → WARN) say the headline HD95 catches what
needs catching.

## Recommended actions

| # | Action | Effort | Priority |
|---|---|---|---|
| 1 | Drop `render_s6_sagittal` from `reportlets.py` and remove its call site in `process.py` | 30 lines | high (clean up redundancy) |
| 2 | Remove `bold_on_anat_sagittal` from the reportlets dict, the schema, and the dashboard label registry | 10 lines | high |
| 3 | Rename `render_s6_axial` → `render_s6_composite` (and the reportlet key from `bold_on_anat_axial` → `bold_on_anat`) to reflect what it actually contains | 15 lines | medium (clarity) |
| 4 | Regen cohort to drop the obsolete PNG (or leave it — it stops being referenced when its key drops out of the schema) | 0 lines | — |
| 5 | (deferred) Add HD95-per-slice trace to dice reportlet | ~30 lines | low |

## Final reportlet contract — what S6 emits

After this cleanup, S6's QC report consists of:

1. **`bold_on_anat`** — the visual answer to "did the registration
   land the EPI cord on the anat cord?" Axial montage + sagittal pair,
   dual modality, full chrome (header / status pill / footer / S-I-A-P /
   R-L markers). One figure, no zoom-of-zoom.

2. **`cord_dice_per_slice`** — the quantitative answer to "is the
   registration uniform across Z, or does it fail locally?" Per-Z 3D
   Dice with PASS/FAIL bands. Field-standard complement.

Two reportlets matches the literature consensus and removes the
duplicate-magnification redundancy.

## Sources

- Esteban et al. 2019 — fMRIPrep, *Nat Methods*
- Cieslak et al. 2021 — qsiprep, *Nat Methods*
- De Leener et al. 2014/2017 — SCT, *NeuroImage*
- Wei et al. 2025 — CoSpine database, *Sci Data*
- Kaptan et al. 2023 — Reliability of cord rs-fMRI, *NeuroImage*
- Esteban et al. 2017 — MRIQC, *PLoS One*
- Klein et al. 2009 — ANTs evaluation, *NeuroImage*
- Avants et al. 2008 — SyN, *Med. Image Anal.*
- Internal: `.claude/specs/reportlet-visual-standard.md`
