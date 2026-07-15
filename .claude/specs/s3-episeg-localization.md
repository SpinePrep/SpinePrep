---
status: approved
---

# S3 cord localization: switch to EPISeg (`sct_deepseg sc_epi`)

Date: 2026-07-13. Owner: p2-spineprep. Origin: `HANDOFF_EPISEG/DELEGATION.md`
(from p1-cospi-gvs) — cord discovery failed on the CoSpiGVS dataset.

## Problem

On BOLD-EPI functional references S3 cropped the cord to roughly the upper
half. Worst case sub-AS002 run-01: discovery mask = 17 axial slices, stopping
at the mid-cervical curve; the crop follows the mask, so downstream S4–S9 lost
the lower cord.

## Root cause (verified on real data)

S3 discovery hard-coded `sct_deepseg spinalcord` — the **contrast-agnostic**
model, trained mostly on high-resolution *anatomical* scans. On BOLD EPI (low
resolution, susceptibility distortion, dropout, inferior coil-sensitivity
falloff) it is out-of-distribution and quits exactly where the lower cervical
cord **curves anteriorly**. Measured on AS002: the cord centroid shifts from
y≈59 (upper) to y≈45 (lower) — a genuine forward curve of ~22 mm.

The old mitigations (`_caudal_union` via propseg + `_caudal_trace` intensity
trace) extrapolate the centreline **straight down**, so they walk off the
forward-curving cord and stop in the same place. They were a patch on the wrong
model, and one knob (`band_area_max: 3.0`, "the empirical separatrix") was tuned
to a 0.3× margin on four named dev runs — fragile.

The rest of the pipeline (S5–S9) **already** uses `sct_deepseg sc_epi` (EPISeg,
Banerjee et al. 2025, *Imaging Neuroscience*), the EPI-specific model (nnU-Net 3D, 406
subjects, 15 sites; Dice 0.87 on EPI vs 0.83 contrast-agnostic, 0.77 deepseg,
0.56 propseg). Only S3 lagged — so S3 truncated the cord *before* the good model
ever ran.

## The fix

1. **Model swap.** S3 discovery now runs `sct_deepseg sc_epi`, config-driven
   from `policy/S3_func_init_and_crop.yaml` (`func_localization.task: sc_epi`).
   The legacy `spinalcord` path is still reachable (keeps its `-largest 1`).
   Input is the coarse temporal-median reference `func_ref_fast` (already a
   median, not a single frame; pre-moco — acceptable, `sc_epi` is robust to it).

2. **Cleanup that does NOT re-truncate (the non-obvious part).** Raw `sc_epi`
   output on AS002 has 35 components: the cord is **split into two on-axis
   fragments** across the curve gap (upper 507 vox Z16–37, lower 331 vox Z0–14)
   plus ~33 off-axis brain specks. A naive `-largest 1` would keep only the
   bigger fragment and re-truncate the cord. Instead `localize._cleanup_epi_cordseg`:
   - dilates the mask **along Z only** (`cleanup.bridge_z_slices`, default 2) to
     close the 1–2 slice curve gap so the cord fragments merge, while the
     superior off-axis specks stay in separate components;
   - keeps the bridged group holding the most *original* cord voxels and masks
     back to the original voxels (no erosion — exact cord voxels preserved);
   - drops everything else (the specks).

   Verified on the real AS002 seg: **17 → 37 contiguous cord slices**, both
   fragments unioned, 33 specks dropped. Regression frozen in
   `tests/test_S3_episeg_cleanup.py`.

3. **Retire the straight-line caudal patches.** `caudal_completion.enabled` and
   `caudal_completion.trace.enabled` default to `false`. Code kept for one
   release as a fallback, then delete. Do not re-enable with `sc_epi`.

## Scope of impact (must re-validate)

S3 defines the crop for **every** dataset, so this changes all datasets, not
just GVS. Because `skip_existing_pass` keys on `code_hash`, S3→S9 re-runs
cohort-wide. This reopens a "locked" step (invariant #5): validate on the full
cohort, not a spot check. Confirm cord-only acquisitions did not regress (no
brain-speck leakage; no shorter crops), and re-check S6/S7 Dice now that more
caudal cord is in-FOV (watch WY001 run-03, which previously attrited after a
fuller crop).

## Follow-ups (not in this change)

- Persist the `_cleanup_epi_cordseg` stats into S3 `qc.json` (+ schema) and the
  `func_localization` reportlet caption.
- Add EPISeg (Banerjee et al. 2025) to the S10 methods manifest / `references.bib` for
  S3 as well as S5–S9.
- Optional: segment a cheap rigid-moco mean instead of the pre-moco median.
