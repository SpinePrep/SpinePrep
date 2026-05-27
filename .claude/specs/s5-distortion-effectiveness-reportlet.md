---
status: approved
---

# Scope Spec: S5 third reportlet — visual distortion-correction effectiveness

## Objective

Add a third S5 reportlet that gives a direct **visual** A/B comparison
of mean BOLD Before vs After distortion correction, with the anat
cord boundary overlaid as the geometric ground truth. Complements the
existing two quantitative reportlets (`slice_displacement`,
`cord_dice_per_slice`) so the QC dashboard has both numbers and an
image-level confirmation that the cord moved where it should.

## Constraints

- **Must not break the existing two reportlets** — same `qc.json`
  reportlets dict, same caller signature, same dashboard registry.
- **Must follow `.claude/specs/reportlet-visual-standard.md` verbatim**:
  dark theme (#0f1115), actual-voxel rendering (`interpolation="nearest"`),
  yellow contour-only for the anat cord mask (no fill), pixel-aspect-
  aware sagittal for anisotropic data, header + footer + status pill
  chrome from `reportlets_common.py`.
- **Must not regenerate or re-run any pipeline step**: the renderer
  consumes existing `bold_before_mean.nii.gz`, `bold_after_mean.nii.gz`,
  and `anat_cord_dseg_in_bold.nii.gz` already produced by
  `_compute_cospine_metrics` under `<run>/cospine/`.
- **Must never raise**: missing inputs → placeholder PNG with the
  same `_placeholder()` helper the other S5 reportlets use.
- **Must not redo the registration**: the anat cord overlay is the
  already-warped `anat_cord_dseg_in_bold.nii.gz` from the CoSpine
  pipeline; we read it, we don't recompute it.
- **No additive dataset assumptions**: works for both topup-mode runs
  (where Before-correction is the distorted mocoref) and SyN-mode
  runs (same).

## Deliverables

- New renderer `render_s5_distortion_effectiveness(metrics, output_path, mode, work_dir)`
  in `src/spinalfmriprep/steps/s5/reportlets.py`.
- Wire-up in `src/spinalfmriprep/steps/s5/process.py`:
  - Emit a third PNG path under `figures_dir / f"{prefix}_desc-S5_distortion_effectiveness.png"`.
  - Add `distortion_effectiveness` key to the `reportlets:` dict in
    `run_S5_func_distortion_correction`'s return.
- `policy/S5_func_distortion_correction.yaml` — under the existing
  `qc:` block, add three knobs (n_axial_tiles, contour width, dpi).
- `schemas/qc_S5_func_distortion_correction.schema.json` — add
  `distortion_effectiveness` to the required `reportlets` keys.
- `src/spinalfmriprep/qc_dashboard_html.py` `REPORTLET_ORDER` +
  `REPORTLET_LABELS` for `S5_func_distortion_correction` — append
  the new key with label "S5 - Distortion Correction (Before vs After)".
- Update `.claude/specs/s5-func-distortion-correction.md` reportlet
  table to list three rows.

## Inputs

For each S5 run, the CoSpine pipeline already saves these in
`work_dir / "cospine" /`:
- `bold_before_mean.nii.gz` — mean BOLD Before correction, BOLD geom
- `bold_after_mean.nii.gz` — mean BOLD After correction, BOLD geom
- `anat_cord_dseg_in_bold.nii.gz` — anat cord mask warped into BOLD
  geometry via cord-aware rigid registration (sct_register_multimodal
  step=1,type=seg,algo=rigid)
- Optional: `bold_after_cord_seg.nii.gz` — `sct_deepseg sc_epi` cord
  on Mean-BOLD-After (already computed for the existing Dice metric).
  Used as a SECONDARY contour (cyan) to show where the EPI says the
  cord is after correction.

When `cospine_skip_reason` is present, the renderer emits a
placeholder PNG explaining why (same pattern as the other two).

## Success Criteria

- A reader of the PNG can answer **in under 10 seconds**: "Did the
  EPI cord move toward the anat cord contour after correction?"
- Both topup-mode runs (cospine_pain, cospine_motor) and SyN-mode
  runs (balgrist, ds004386_rest, handgrasp) render without raising
  and show a meaningful comparison.
- All 11 reg-cohort runs produce a PNG; cohort-pass count is at
  least 9/11 (allowing for sub/ses edge cases).
- The render time is < 5 s per run (matches existing reportlets).
- File size < 500 KB per PNG (matches existing reportlets).

## Layout (Option A from MCQ)

```
+----------------------------------------------------------+
|  HEADER: SpinalfMRIprep · S5 — Distortion Effectiveness  |
|  pill: mode=topup | sub-02 | task-pain | dice 0.81       |
+----------------------------------------------------------+
|                                                          |
|     SAGITTAL BEFORE       |     SAGITTAL AFTER           |
|     (mean BOLD,           |     (mean BOLD,              |
|      midcord slice)       |      same slice)             |
|     yellow anat-cord      |     yellow anat-cord         |
|     contour overlay       |     contour overlay          |
|                                                          |
+----------------------------------------------------------+
|  AXIAL TILES (3 cord-bearing Z slices, each Before|After) |
|                                                          |
|   Z=8           Z=14            Z=20                     |
|  [B|A]         [B|A]           [B|A]                     |
|  yellow contour on each tile                             |
+----------------------------------------------------------+
|  FOOTER: anat cord contour  |  Y-axis: A-P  |  dpi=120   |
+----------------------------------------------------------+
```

Implementation notes:
- Use `reportlets_common.render_sagittal_plus_montage` as the
  primitive if its signature accommodates two grayscale backgrounds
  (Before / After); otherwise factor a tighter helper that takes two
  (image, label) pairs + one overlay mask.
- Sagittal slice = midcord Z (use `reportlets_common.midcord_sagittal_slice`).
- Axial Z picks = `reportlets_common.uniform_z_picks` over the
  cord-bearing range, count = `n_axial_tiles` policy knob (default 3).
- Intensity windowing: `intensity_window(arr, (2, 98))` on the
  pooled Before+After to keep both panels on the SAME color scale.
- Cyan secondary contour (EPI cord seg from `sc_epi`) — toggleable
  via policy knob `show_epi_cord_contour: true`; default off in v1
  to keep the panel uncluttered; the existing two reportlets already
  carry the EPI-cord side of the comparison.

## Next Steps

1. Read `src/spinalfmriprep/reportlets_common.py` to identify the
   right primitive (`render_sagittal_plus_montage` vs lower-level
   `render_sagittal` + `render_axial_tile`).
2. Implement `render_s5_distortion_effectiveness` in
   `steps/s5/reportlets.py`, mirroring the `render_s5_slice_displacement`
   error-handling pattern.
3. Wire the new reportlet into `process.py`'s `reportlets` dict.
4. Update policy YAML, schema, REPORTLET_ORDER/LABELS, S5 principles spec.
5. Smoke-test on one cospine_pain run (topup) and one handgrasp run
   (SyN) before the full cohort regen.
6. Cohort regen on wf_reg_081; verify dashboard picks it up.

## Decision Log

| Q# | Choice | Rationale |
|----|--------|-----------|
| Q1 | A: sagittal Before vs After + axial row, yellow anat contour | Matches fMRIPrep/qsiprep/CoSpine/SCT QC consensus; direct visual A/B without occluding overlays; cord-centric not whole-FOV; predictable footprint |
| (locked) | Yellow contour-only on anat mask, no fill | Visual standard §5.2 — contour-only for binary masks |
| (locked) | Dark theme, actual voxels (no interp), pixel-aspect sagittal | Visual standard §1–§3 |
| (locked) | Status pill: mode + Dice After in subtitle | Mirrors existing S5 reportlet titling |
| (locked) | Placeholder PNG on missing inputs (never raise) | Existing pattern in `render_s5_slice_displacement` |
| (deferred) | EPI cord contour (cyan secondary) | Defer to v2 — keep v1 uncluttered; existing two reportlets carry EPI-side already |
| (deferred) | tSNR Before/After thumbnail | Out of scope — covered by S4 / S8 |
| (deferred) | Jacobian determinant of warp | Out of scope — DRBUDDI-style; not field-consensus for cord |

## Sources

- Esteban et al. 2019 — fMRIPrep (NatMethods) SDC report layout
- Cieslak et al. 2021 — qsiprep (NatMethods)
- Wei et al. 2025 — CoSpine database (Sci Data) Figure 3
- De Leener et al. 2017 — SCT (NeuroImage) QC tool
- Mohammed et al. 2020 — Cord moco evaluation (bioRxiv)
- Irfanoglu et al. 2015 — DRBUDDI (NeuroImage)
- Valošek et al. 2025 — EPISeg / sct_deepseg sc_epi
