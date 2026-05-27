---
status: approved
---

# Reportlet visual standard

Every PNG reportlet emitted by S2 onward shares one visual language.
This standard is the single source of truth — shared helpers in
`src/spinalfmriprep/reportlets_common.py` implement it; new renderers
import from there; existing renderers adopt at their next touch.

## Why one standard

- The operator scans 10+ reportlets per dashboard visit. Different
  fonts / colors / overlays per step is friction.
- A shared header / footer / status pill makes status legible at a
  glance across the chain.
- Shared helpers prevent the per-step drift we accumulated in S2
  (PIL + ImageMagick) vs S5 (matplotlib axes) vs S3 (matplotlib +
  PIL + ImageMagick mix).

## Field standards consulted

- **SCT QC tool** (`sct_qc`): sagittal mid-slice + 9-slice axial
  montage with thin contour overlays; reference for cord-only seg QC.
- **fMRIPrep / nipreps reports**: section-banner + SVG cuts in 3×3
  layouts; thin contour overlays for tissues; subject ID in header.
- **MRIQC**: IQM tables + mosaic plots with Z-cuts in mm; metric
  badges per panel.
- **CoSpine 2025** (Wei et al., Sci Data): sagittal label panel +
  axial cord montage with rainbow level coloring; per-slice Y
  displacement traces.
- **Cohen-Adad lab cord conventions**: cord-cropped axial, A-P axis
  vertical after rot90, R/L radiological convention.

## The standard

### Layout (every reportlet)

```
┌──────────────────────────────────────────────────────────────┐
│ TITLE 18pt bold     subtitle 12pt mono   metric   [STATUS]   │  header  ≤8% h
├──────────────────────────────────────────────────────────────┤
│                                                              │
│       SAGITTAL (40%)         │       AXIAL MONTAGE (55%)     │  body
│       cord-cropped X mid     │       6 cord-bearing Z slices │
│       overlays as contours   │       per-slice cord-centered │
│       S/I/A/P markers        │       Z idx + R/L markers     │
│                              │       grid 2×3 default        │
│                              │                               │
├──────────────────────────────────────────────────────────────┤
│ ⬛ legend item  ⬛ legend item              secondary metrics │  footer ≤6% h
└──────────────────────────────────────────────────────────────┘
```

Portrait-only reportlets (e.g. S2.1 full-FOV crop_box) use a single
sagittal panel sized to the image aspect, no axial montage.

### Figure dimensions

| Layout | Figure size |
|---|---|
| Sagittal + axial montage | 16 × 9 in |
| Sagittal-only, image aspect | width = body_h × (AP_mm / SI_mm), capped 8–14 in |
| Time-series / line plots | 11 × 6 in |

DPI: 130 (≥ 1200 px wide; sharp at gallery zoom + at 50% browser
zoom).

### Color palette

Status:
- PASS   fill `#14532d`  edge `#22c55e`  text `#22c55e`
- WARN   fill `#3a2f00`  edge `#f59e0b`  text `#f59e0b`
- FAIL   fill `#3a1010`  edge `#ef4444`  text `#ef4444`
- UNKNOWN fill `#1a1d23` edge `#666666`  text `#cccccc`

Page chrome:
- Background `#0f1115`
- Card / panel bg `#1a1d23`
- Border `#2a2e36`
- Body text `#e6e8ec`
- Muted `#9ca3af`
- Marker yellow `#facc15`  (orientation / slice indices)

Semantic data colors (use these or extend, do not re-pick):
- Cord (subject)            red    `#ef4444`
- Cord (template / PAM50)   blue   `#3b82f6`
- Discovery cord            cyan   `#22d3ee`
- Crop bbox                 amber  `#f59e0b`
- Canal                     purple `#a78bfa`
- Disc                      yellow `#facc15`
- Vertebrae                 green  `#22c55e`
- "Before"                  gray   `#888888`
- "After"                   blue   `#0086e6`

### Overlay style

| Overlay type | Style | When |
|---|---|---|
| Binary mask vs an image | **thin contour** (`linewidth 1.4–1.8`, `alpha 0.95`) | Cord seg, cord_dseg, PAM50 cord, discovery cord |
| Labeled region (vertebrae, discs) | **filled** (`alpha 0.30–0.45`) | TSS labels |
| Per-slice metric | line plot with marker (`linewidth 1.4–1.6`) | Displacement, Dice traces |

Solid filled overlays on a binary cord seg are NOT allowed (they hide
the boundary). Contours always.

### Intensity windowing

Robust 2-98 percentile within the displayed slice. Computed
**per-panel** — sagittal vmin/vmax independent from axial mid-slice
vmin/vmax. Improves contrast in both panels for datasets with very
different brightness profiles between mid-cord and edge slices.

### Sagittal panel

- Slice = `data[x_mid, :, :]` where `x_mid` = X-axis median of the
  cord seg voxels.
- For features off-cord-midline (rootlets are dorsal ~7 vox from
  centerline), use max-projection across `x_mid ± slab_halfwidth_x`
  voxels. Param `sag_slab_halfwidth_x` per reportlet.
- Display: `np.rot90` of the sagittal slice so S is at top, I at
  bottom, A on left, P on right (post-rot90).
- Orientation markers in the 4 corners: yellow text on a 55% dark
  rounded backdrop.
- Optional: vertebral level labels along the right margin (C1, C2,
  …, T1) at the median Z of each label, 10pt bold.

### Axial montage

- 6 cord-bearing Z slices, uniformly spaced, with an **8% edge skip**
  from each end of the cord-Z range (avoids partial-cord slices at
  the FOV entry/exit).
- **Per-slice cord-centered crop**: 22 × 22 voxel window centered on
  that slice's cord centroid. Cord (5–7 mm) fills ~30 % of tile;
  ~8 mm margin in every direction even when the cord curves
  laterally.
- Grid 2 × 3 (top → bottom = superior → inferior, left → right
  within a row).
- Z-index label bottom-left of each tile, yellow text on dark
  backdrop.
- R/L orientation markers (radiological convention) on first tile
  only.

### Header / footer

Header (~ 0.08 fig height):
- Left, vertically stacked:
  - Title 18 pt bold (`S2.2 — Cord segmentation`)
  - Subtitle 12 pt monospace (`sub-02 • <dataset_key>  (algorithm)`)
- Right:
  - Optional metric 14 pt bold (`CSA 68 mm² • vol 10.4 cm³`)
  - **Status pill** — plain `Rectangle` with status palette fill +
    edge. NOT `FancyBboxPatch` (rounding artifacts in narrow strips).

Footer (~ 0.06 fig height):
- Left: legend swatches (rectangle 0.016 × 0.36 axes coords) + label
  (12 pt). Spacing uses **renderer-measured text bbox**, not a
  per-character estimate (which under-counted proportional font
  width and merged adjacent labels).
- Right: secondary metric strings in monospace (12 pt), e.g.
  `length 153 mm  pam50_cord_dice 0.74`.

### Status pill

```
+--------+
|  PASS  |   plain Rectangle, fill=pal["fill"], edge=pal["edge"], lw=1.2
+--------+
```

NEVER `FancyBboxPatch(boxstyle="round,…")` with `rounding_size >
min(w, h)/2` — that produces visible corner-arc artifacts that read
as extra horizontal lines.

### Per-slice plot (line-trace reportlets)

For step-local truth metrics that vary per-Z (S5 displacement, S5
Dice, S6 cord_dice_per_slice, S9 tsnr_per_level):

- 2-panel: left = per-slice trace (Z on Y-axis, metric on X-axis),
  right = mean ± SD summary bar.
- Before line: `#888` 1.4 lw. After line: `#0086e6` 1.6 lw.
- Reference line at 0 (displacement) / 1.0 (Dice) / etc, `#444`
  dashed 0.8 lw.
- Title: `<measure> — mode=<mode>, Δ=<value>`.

## Per-step adoption status

| Step | Renderer file | Standard adopted | Action |
|---|---|---|---|
| S1 | `steps/s1/reportlets.py` | N/A — HTML tables | none |
| S2 | `steps/s2/reportlets_unified.py` | ✅ reference impl | none |
| S3 | `steps/s3/reportlets.py` | ⚠️ mix mpl + PIL + IM | adopt on next touch |
| S4 | `steps/s4/.../reportlets.py` | ⚠️ no shared style | adopt on next touch |
| S5 | `steps/s5/reportlets.py` | ⚠️ partial (palette ✓, header ✗) | adopt on next touch |
| S6 | `steps/s6/reportlets.py` | ⚠️ partial | adopt on next touch |
| S7 | `steps/s7/reportlets.py` | ⚠️ partial | adopt on next touch |
| S8 | `steps/s8/reportlets.py` | ⚠️ partial | adopt on next touch |
| S9 | `steps/s9/reportlets.py` | ⚠️ partial | adopt on next touch |
| S10 | `steps/s10/reportlets.py` | ⚠️ partial | adopt on next touch |
| S11 | (HTML release report) | N/A | none |

We do not refactor working renderers solely to adopt the standard
(principle §6: lock and ship). The next time any step's renderer
gets touched for a real reason — bug fix, new metric, new reportlet
— the change includes adopting the shared `reportlets_common`
helpers.

## Shared module API

`src/spinalfmriprep/reportlets_common.py` exports:

| Helper | Purpose |
|---|---|
| `BG`, `PANEL`, `TEXT`, `MUTED`, `BORDER`, `MARKER_YELLOW`, `STATUS`, `SEMANTIC` | palette constants |
| `load_canonical(path)` | NIfTI → (data, affine, zooms) in canonical orientation |
| `intensity_window(arr, lo=2, hi=98)` | robust percentile vmin/vmax |
| `cord_bbox_xy(mask, margin)` | in-plane bbox of 3D cord mask |
| `cord_zrange(mask)` | (z0, z1) cord-bearing Z extent |
| `uniform_z_picks(z0, z1, n, edge_skip_frac)` | N uniform Z indices with edge margin |
| `per_slice_centered_crop(mask, z, window_vox)` | (x0,x1,y0,y1) cropped to cord centroid |
| `midcord_sagittal_slice(mask)` | median X of cord seg |
| `draw_pill(ax, x, y, w, h, label, status, fontsize)` | plain-Rectangle status pill |
| `draw_stat_card(ax, x, y, w, h, label, value, accent)` | card with big number + label |
| `add_header(fig, title, subtitle, status, metric)` | top header strip |
| `add_footer(fig, legend_items, metric_lines)` | bottom legend + metric strip |
| `render_axial_tile(ax, slice_xy, overlays, vmin, vmax, z_idx, first, crop)` | one axial tile |
| `render_sagittal(ax, sag_yz, overlays, vmin, vmax, z_label_levels)` | sagittal panel |
| `render_sagittal_plus_montage(...)` | full layout dispatcher used by S2 |

## Anti-patterns (do not do)

- ❌ Solid fill on a binary cord seg (hides boundary).
- ❌ `FancyBboxPatch` for status pills (corner-arc artifacts).
- ❌ Per-character text-width estimate for legend spacing (under-counts
  proportional fonts; labels merge).
- ❌ Single global cord bbox for axial tiles (cord curves laterally;
  some tiles end up off-center).
- ❌ Slice picks including `z0` and `z1` (partial-cord edge slices).
- ❌ Fixed figure dimensions for portrait-only data (massive empty
  black margins).
- ❌ Per-step ad-hoc color palettes (visual chaos across the chain).
- ❌ ImageMagick shell-out (slower than matplotlib, harder to debug,
  inconsistent fonts).

## Open questions (deferred)

- SVG output (vector, accessible, smaller files) vs PNG (rasterized,
  smoother gradients). Currently PNG; SVG could land alongside if a
  consumer asks.
- A11y: contrast ratios for the status palette are WCAG AA on dark
  bg but not verified per text size. Defer until an external review
  asks.
