---
status: superseded
superseded_by: meeting-2026-05-29-task-audit.md (S4 reportlet redesign, 2026-06-10)
note: Motion is sub-voxel in 10/11 reg runs, so a before/after axial/GIF conveys nothing. Replaced by the 3-figure set (trace panel + slicewise heatmap + tSNR/per-slice). Dropped from the schema's required reportlets.
---

# Scope Spec: S4 moco-comparison axial redesign

## Objective
Redesign the `S4_moco_comparison` reportlet so motion correction quality is
visible at a glance: every cord-bearing axial slice rendered as a temporal-mean
image, with the pre-moco column on the left and post-moco column on the right,
stacked vertically. Replaces the current sagittal looping GIF.

## Constraints
- Must not touch the other three S4 reportlets (`motion_traces`, `tsnr_comparison`, `dvars_plot`) — they were validated in the Feb 13 design meeting.
- Output filename must remain a valid reportlet path under `derivatives/.../figures/sub-XX_..._desc-S4_moco_comparison.<ext>`. Changing the extension from `.gif` to `.png` is allowed; the qc.json reportlets key stays `S4_moco_comparison`.
- Must not break the chain dashboard. The reportlet path stays relative to `out_dir` (per the convention that landed in commit `2227f8a`).
- Must not break existing tests. `test_S4_integration.py` only asserts file existence — switching extension is fine, but the path it constructs (line 120) must still match.
- No new heavy dependencies. PIL + nibabel + numpy + imageio already imported.
- Cached-path / `--reportlets-only` mode must regenerate the new PNG from existing nifti outputs without rerunning motion correction.

## Deliverables
1. **`lib/viz_s4.py`** — replace `render_moco_gif()` with `render_moco_axial_comparison()`:
   - Loads pre-moco and post-moco 4D BOLD, computes temporal mean of each.
   - Determines cord-bearing Z slices from the moco mask (non-zero in-plane voxels along Z), caps the count at 12 (`max_slices` policy default), keeps **all** such slices when ≤ 12, uniformly subsamples when > 12.
   - For each selected slice: build a 2-column row (mean-before | mean-after), tight-crop to mask bbox + 5 mm margin in-plane, robust 2–98th percentile normalization **shared across both columns** so the intensity scale is honest.
   - Optional thin blue cord contour (mask edge) overlaid on each tile, matching the S2 cordmask reportlet convention. On by default; controllable via policy `gif.show_mask_contour`.
   - Stack the rows vertically into a single PNG, with per-row slice index label on the left and column headers "Before moco" / "After moco" at the top.
   - Writes `.png`.

2. **`steps/s4/process.py`** — update the call site (lines ~368–376):
   - Change reportlet key value to point to `{prefix}_desc-S4_moco_comparison.png` (was `.gif`).
   - Pass `mean_before`, `mean_after`, mask, zooms, policy to the new renderer.

3. **`steps/s4/orchestrate.py` reportlets-only path** — mirror the call so `--reportlets-only` produces the new PNG.

4. **Policy `policy/S4_func_motion_correction.yaml`** — replace the GIF-specific keys (`fps`, `max_frames`) with axial-specific keys: `max_slices: 12`, `show_mask_contour: true`, `margin_mm: 5`, `percentile: [2, 98]`. Keep `gif:` group renamed to `comparison:` to reflect the static output.

5. **Tests** — `tests/test_S4_integration.py` line 120: change `.gif` → `.png` so existence check still finds the file. Add a tiny unit test in `test_S4_unit.py` that calls `render_moco_axial_comparison` on synthetic 4D data and asserts the output PNG has the expected dimensions (rows ≈ n_slices, columns ≈ 2 × tile_width).

6. **Regen + verify** — after commit, regenerate the wf_reg_035 dashboards (auto via `generate_dashboard_safe`, already wired) and curl-test one PNG via `https://271828.space/p2/`.

## Inputs
- Existing `lib/viz_s4.py` (~360 LOC) with `create_axial_montage` helper (lines 47–156) — reusable for tile assembly.
- Existing `render_tsnr_comparison` (lines 158–199) as a reference implementation for axial-stack PNG.
- `steps/s4/process.py:368–376` — current `render_moco_gif` call site.
- `policy/S4_func_motion_correction.yaml` — has `gif: {fps: 5, max_frames: 20}` to retire.
- Cropped BOLD typical shape for cervical cord: 32 × 34 × 11 voxels, voxel size 1.0 × 0.977 × 4.89 mm (from wf_reg_035 sample) → expect tile ~32 × 34 px before upscaling.

## Success Criteria
1. After regenerating `wf_reg_035`, every `*desc-S4_moco_comparison.png` exists with dimensions of roughly `(2 × tile_w + gutter) × (n_slices × tile_h + labels)` (e.g., 1200 × N×120).
2. Pre and post columns visibly share the same intensity range; cord cross-section sharpens between left and right columns for runs with measurable motion (ZSpine motor runs are a good check — they have non-trivial FD).
3. `tests/test_S4_integration.py` passes; new unit test passes.
4. `generate_dashboard_safe(wf_reg_035)` runs error-free; gallery `https://271828.space/p2/dashboard/reportlets/S4_func_motion_correction/S4_moco_comparison.html` lists the PNGs (no broken images).
5. `--reportlets-only` rerun produces the same PNG without invoking SCT or motion-correction code.
6. The old `.gif` files in `wf_reg_035/derivatives` are obsolete; we'll leave them for now (chain symlinks may still reference them — they can be pruned in a follow-up).

## Next Steps
1. Implement `render_moco_axial_comparison()` in `lib/viz_s4.py`. Keep the old `render_moco_gif` symbol exported temporarily as a thin shim that delegates, so any caller outside `process.py` doesn't break — then remove the shim in a follow-up after a clean run.
2. Update `steps/s4/process.py` call site + qc.json reportlet path.
3. Update `steps/s4/orchestrate.py` reportlets-only path.
4. Update policy YAML (rename `gif:` → `comparison:`).
5. Update `tests/test_S4_integration.py` extension; add unit test.
6. Run `poetry run pytest tests/`; expect 55/55 + new unit test = 56/56.
7. Re-run S4 reportlets-only on `wf_reg_035` to refresh outputs without re-running motion correction.
8. Curl-test the new PNG via the public dashboard.
9. Commit as one feature.

## Decision Log
| Q# | Choice | Rationale |
|----|--------|-----------|
| Q1 | A — Static PNG | Matches Gergely's literal description; dashboard already serves PNGs cleanly; no animation cost. |
| Q2 | A — All cord slices, capped at 12 | Adaptive to actual cord coverage; ZSpine 12-slice acquisitions show 12, longer cords show 12 evenly. |
| Q3 | A — Temporal mean before vs after | Canonical motion-correction QC: motion blurs the mean before, sharpens after. Honest single-image-per-side comparison. |
| Defaults (not scoped) | Tight crop to mask bbox + 5 mm margin; robust 2–98% normalization shared across before/after; thin blue cord contour overlay on by default | Stated in the offer message; user did not override. |
