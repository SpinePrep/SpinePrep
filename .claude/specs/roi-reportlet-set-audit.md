---
status: implemented
implemented_in: wf_reg_089
implemented_at: 2026-05-28
---

# Former S10 (ROI/connectivity) reportlet+metric-set audit — redundancy + field-standard composition

> This audit concerns the **former S10 (ROI/connectivity)** step, which was
> removed from the active pipeline on 2026-06-11. Its step number has since been
> reused for QC aggregation & release (the new S10). All bare "former S10"
> references below mean the removed ROI/connectivity step, not the release step.

Examines whether the former S10's (ROI/connectivity) 3 emitted reportlets and
5 metrics are well-chosen, non-redundant, and complete, against the cord-fMRI /
brain-fMRI functional-connectivity QC literature.

## Current former-S10 (ROI/connectivity) outputs

### Reportlets (emitted to qc.json `reportlets` dict)

| # | Reportlet | Content |
|---|---|---|
| 1 | `hemicord_timeseries` | Per-ROI line plot, 4-column grid, one panel per hemicord×segment ROI (~13-24 panels) |
| 2 | `hemicord_connectivity` | Fisher-z ROI×ROI heatmap (RdBu_r, ±1.0), no clustering |
| 3 | `vertlvl_tsnr` | Per-vertebral-level median tSNR bar chart |

### Reportlets DEFINED but NOT WIRED

`render_s10_reliability_icc` and `render_s10_reliability_dice` exist
in `reportlets.py` but are never called from `process.py`.
**Multi-session reliability reportlets are dead code.**

### Metrics (qc.json)

| Metric | Type | Gating? |
|---|---|---|
| `n_volumes` | int | ❌ informational |
| `n_rois_vertlvl` | int | ❌ informational |
| `n_rois_spinalseg` | int | ❌ informational |
| `n_rois_hemicord` | int | ❌ informational |
| `n_rois_dropped_low_voxels` | int | ✅ WARN (>0) / FAIL (>2) |
| `condition_number_pearson_hemicord` | float | ✅ PASS / WARN / FAIL |

## Field-standard FC QC visualisations

Reviewed 7 published tools / pipelines:

| Source | Reportlets | Metrics |
|---|---|---|
| **fMRIPrep / Nilearn** | Connectivity heatmap (clustered); timeseries strip; carpet plot | n_rois, FD, condition number |
| **MRIQC** | tSNR map; IQM table; no FC | tSNR, GCOR, ~30 IQMs |
| **CONN toolbox** (Whitfield-Gabrieli 2012) | Connectivity matrix (clustered); seed-to-voxel maps; histograms of r distribution | FC strength stats |
| **C-PAC** (Craddock 2013) | FC matrix; timeseries; seed-to-voxel | — |
| **Kaptan 2023** (cord rs-fMRI reliability) — explicit | (1) Connectivity matrix per session; (2) ICC(3,1) bar per connection; (3) Spatial Dice per seed; (4) Bland-Altman test-retest scatter | ICC + Dice + LoA |
| **CoSpine 2025** (cord database, Sci Data) | Group connectivity heatmap; per-segment FC profile; per-vertebra tSNR | Group FC consistency |
| **Eippert 2017 / Wei 2025 group output** | Hemicord adjacency matrix; per-segment seed-to-voxel maps | — |

**Field consensus pattern** for cord-fMRI ROI/FC QC:
1. **ROI timeseries** — required for visual sanity (every tool)
2. **Connectivity heatmap, clustered/ordered** — required (every tool)
3. **Reliability ICC + Dice** — cord-specific signature (Kaptan 2023 is the headline cord reliability paper; we declare the metric in policy + render code but don't wire it)
4. **Per-ROI quality (voxel count + tSNR)** — observability
5. **NOT typically shown**: per-ROI tSNR — the per-vertebra tSNR is owned by S9 (Kaptan 2023 / CoSpine 2025 Fig 6 lives at the preprocessing stage). The former S10 (ROI/connectivity) should focus on FC, not tSNR (which would duplicate S9).

## Reportlet redundancy analysis

| Reportlet | Question answered | Verdict |
|---|---|---|
| `hemicord_timeseries` | "Do the ROI timeseries look sane (no flatlines, no spikes)?" | ✅ unique |
| `hemicord_connectivity` | "What's the FC structure?" | ✅ unique |
| `vertlvl_tsnr` | "Per-vertebra tSNR" | ❌ **redundant with S9's `tsnr_per_level`** |

### Issue 1 — `vertlvl_tsnr` duplicates S9's `tsnr_per_level`

S9's `cord_dice_per_level` (renamed `tsnr_per_level` after S9 audit)
already shows per-vertebra median tSNR — using the same input
(smoothed BOLD + PAM50_spinal_levels). The former S10 (ROI/connectivity) recomputes the same
quantity on the unsmoothed BOLD and renders the same figure with
slightly different defaults.

Even semantically:
- S9 = "preprocessing QC: is each level usable for analysis?"
- former S10 = "ROI/connectivity output"

The per-vertebra tSNR is a preprocessing diagnostic, not an
ROI/FC output. **Drop from the former S10 (ROI/connectivity); keep in S9.**

### Issue 2 — Reliability reportlets defined but not wired

`render_s10_reliability_icc` + `render_s10_reliability_dice` exist
in `reportlets.py` (combined ~60 lines of mature code) but `process.py`
never imports or calls them. The reliability data IS computed
(per-subject `sub-XX_reliability.json` is emitted), but the
reportlets stay un-rendered.

This is the cord-specific FC signature (Kaptan 2023 ICC + Dice
test-retest reliability) — the **most field-distinctive** former-S10 (ROI/connectivity)
diagnostic. Missing it is a real gap.

**Wire them up** when subject has multi-session data
(handgrasp + ds004386_rest in our cohort qualify).

### Issue 3 — Connectivity heatmap lacks block structure ordering

`hemicord_connectivity` renders ROIs in their default column order
(VL_C2, VL_C3, VR_C3, DL_C3, DR_C3, VL_C4, ...). This obscures the
biologically meaningful block structure (4 hemicords × 8 levels).

Two re-ordering strategies improve readability:
- **By hemicord** (group all VL, then all VR, then DL, then DR) →
  4 visible blocks, cross-hemicord connectivity in off-diagonal
- **By level then hemicord** (current default) → 8 visible blocks,
  intra-level connectivity on the diagonal

Either is better than the current arbitrary order. fMRIPrep/CONN
default to the by-region clustering (hierarchical). **Pick one
and apply.**

## Metric redundancy + correctness analysis

| Metric | Verdict | Reason |
|---|---|---|
| `n_volumes` | ✅ keep | downstream needs it |
| `n_rois_vertlvl`, `_spinalseg`, `_hemicord` | ✅ keep | observability — which catalogs fired |
| `n_rois_dropped_low_voxels` | ✅ keep | gating |
| `condition_number_pearson_hemicord` | ✅ keep | gating — design-matrix degeneracy proxy |

**No metric is redundant.**

But three metrics MISSING that the literature highlights:

| Missing metric | Source | Why useful |
|---|---|---|
| `pct_significant_connections` | Kaptan 2023 | Fraction of \|r\| > 0.1 ROI pairs — meaningful-FC density. Currently we only report condition number; adding "what fraction of pairs have detectable connectivity" gives a complementary signal. |
| `fc_mean_strength` | Eippert 2014, Kaptan 2023 | Median \|r\| across all ROI pairs — overall connectivity health. |
| `icc_median` + `n_connections_in_band` | Kaptan 2023 (when multi-session) | The headline reliability metric. We compute it (per-subject reliability JSON) but don't aggregate to per-run qc.json. |

These would land in metrics and could be visualized as a 3-bar
summary in the connectivity reportlet legend.

## Cohort empirics (wf_reg_070 locked former S10, ROI/connectivity)

11/11 runs WARN — same `dropped_rois WARN` reason on every run.
Range of dropped_rois: 4-50 (out of 16-46 total ROIs).

Why so many dropped? The hemicord × spinal-level parcellation has
4 hemicords × 8 cervical segments = 32 ROIs by design, but cord
EPI coverage is ~3-8 contiguous segments per run. Most of the 32
"slots" are guaranteed empty → flagged as dropped.

The current `dropped_rois WARN: >0 / FAIL: >2` gate is firing on
EVERY run because:
- balgrist (11-slice EPI, ~3 segments coverage): 14 dropped of 32
- ds004386 (35-slice): 4 dropped of 32
- handgrasp (multi-slice): 10-12 dropped of 32
- cospine_pain: 38 dropped of 46 hemicord×seg slots
- cospine_motor: 48-50 dropped of 50+ slots

The gate doesn't distinguish "ROI excluded because outside FOV"
(expected) from "ROI excluded because < 5 cord voxels intersected"
(real signal of bad coverage). **The threshold is mis-calibrated**.
Should be based on coverage-fraction-of-expected or on per-segment
coverage rather than a flat count.

## Proposed optimal set

### Reportlets (4 — drop 1 redundant, wire 2 missing)

```
1. hemicord_timeseries        — KEEP. Per-ROI timeseries sanity check.

2. hemicord_connectivity      — KEEP + REORDER. Cluster ROIs by
                                hemicord OR by level so the block
                                structure is visible.

3. reliability_icc            — WIRE. Per-connection ICC(3,1) bars
                                with Cicchetti bands. Only fires when
                                multi-session. (Kaptan 2023 standard.)

4. reliability_dice           — WIRE. Per-seed spatial Dice across
                                sessions. Only fires when multi-session.
```

**DROP**:
- `vertlvl_tsnr` — duplicates S9 `tsnr_per_level`. Per-ROI tSNR is a
  preprocessing-stage diagnostic, not an FC-stage output.

### Metrics

```
KEEP unchanged:
  n_volumes, n_rois_*, condition_number_pearson_hemicord

FIX:
  - n_rois_dropped_low_voxels gate: currently fires on every run
    because the threshold doesn't account for FOV coverage. Change
    to either:
      (A) dropped_fraction relative to ROIs in FOV, OR
      (B) drop the gate entirely (this is observability — coverage
          gaps are expected for cord-fMRI), OR
      (C) loosen threshold to match cohort empirics (4 / 50 actual
          values seen).
    Recommend (B) — gate the user-facing FC quality on
    condition_number + connectivity-strength metrics instead.

ADD:
  - pct_significant_connections (Kaptan 2023, |r| > 0.1)
  - fc_mean_strength (median |r| across pairs)
  - icc_median + n_in_excellent_band (when multi-session)
```

## Truthfulness review

| Claim | True? |
|---|---|
| "3 reportlets is the former-S10 (ROI/connectivity) QC set" | ⚠️ — emitted yes, but 2 more renderers exist as dead code that should be wired |
| "vertlvl_tsnr is the former-S10 (ROI/connectivity) per-level signal" | ❌ — duplicates S9 tsnr_per_level; per-ROI tSNR is S9's job |
| "dropped_rois gate flags real coverage problems" | ❌ — fires on every cohort run (range 4-50); doesn't distinguish FOV coverage from real coverage gaps |
| "condition_number_pearson_hemicord is the design-matrix degeneracy gate" | ✅ |
| "n_rois_* metrics surface ROI catalog coverage" | ✅ |

## Implementation map

| # | Action | Status |
|---|---|---|
| 1 | Drop `vertlvl_tsnr` from process.py reportlets dict + reportlets.py renderer + schema + dashboard registry (S9 owns this signal) | DONE |
| 2 | Wire `render_s10_reliability_icc` — per-subject reportlet rendered by orchestrator into `sub-XX/figures/` and back-attached to every run of that subject so the per-run dashboard shows it; fires only when ≥2 sessions exist (handgrasp sub-02 in current cohort) | DONE |
| 2b | Wire `render_s10_reliability_dice` (spatial Dice across sessions) | DEFERRED — requires building seed-to-voxel maps per session in a shared space; orchestrator has `_seed_to_voxel_map` + `_spatial_dice` helpers but no data pipe wired. Not blocking S10 lock; tracked separately |
| 3 | Reorder ROIs in `hemicord_connectivity` heatmap — group by hemicord (VL → VR → DL → DR) with block divider lines | DONE |
| 4 | Apply chain-wide visual standard (dark theme + status pill) to all former-S10 (ROI/connectivity) reportlets | DONE |
| 5 | Drop the `n_rois_dropped_low_voxels` gate (kept as informational metric; was WARN 11/11 on every cohort run — no signal) | DONE |
| 6 | Add metrics: `fc_mean_strength`, `pct_significant_connections` (per-run, from hemicord Pearson off-diagonals); reliability metrics (`pooled_icc31`, `icc_good_or_excellent_fraction`) already emitted by orchestrator per-subject reliability JSON | DONE |

## Sources

- Whitfield-Gabrieli & Nieto-Castanon 2012 — CONN toolbox
  (*Brain Connectivity*)
- Esteban et al. 2019 — fMRIPrep (*Nat Methods*)
- Esteban et al. 2017 — MRIQC (*PLoS One*)
- Craddock et al. 2013 — C-PAC (*Frontiers in Neuroinformatics*)
- Kaptan et al. 2023 — Reliability of cord rs-fMRI (*NeuroImage*) —
  ICC + Dice + Bland-Altman reliability triad
- Wei et al. 2025 — CoSpine database (*Sci Data*) — group FC consistency
- Eippert et al. 2017 — Spinal cord fMRI denoising (*NeuroImage*)
- Shrout & Fleiss 1979 — ICC formulations
- Cicchetti 1994 — ICC interpretation bands
- Internal: `.claude/specs/reportlet-visual-standard.md`,
  `.claude/specs/s10-roi-timeseries-and-connectivity.md`
