---
status: approved
---

# Scope Spec: S9 PAM50-space preprocessed BOLD + GLM-ready completeness

## Objective
Emit the 4D preprocessed BOLD in PAM50 template space from S9 (cropped to each
run's cord field-of-view), plus the metadata a GLM requires, so the S9 output
set matches fMRIPrep's "analysis-ready" convention for the spinal cord.

## Constraints
- **Do not change native-space outputs' semantics.** `desc-preproc_bold`
  (smoothed) and `desc-unsmoothed_bold` keep their current meaning; the cord
  field's smoothing-as-preprocessing convention (CoSpine, Eippert) stays.
- **Do not disturb running chains.** S9 code changes land while the 4 rollout
  chains / cospain re-run may still be active; re-run S9 only for the `exp`
  scope, in a fresh workfolder.
- **No 17 GB/run blowup.** Never write the full uncropped 0.5 mm PAM50 4D.
  Warp directly into a cord-FOV-cropped 0.5 mm reference (no full-grid
  intermediate).
- **Reportlets must keep working.** The existing full-grid 3D PAM50 funcref/tSNR
  that reportlets consume stay as-is.
- Reproducible: policy versioned, knobs carry literature/justification comments.

## Deliverables
1. **`space-PAM50_desc-preproc_bold.nii.gz`** (smoothed) and
   **`space-PAM50_desc-unsmoothed_bold.nii.gz`** — 4D, 0.5 mm PAM50, cropped to
   the run's cord FOV (~1–2 GB/run).
2. **`space-PAM50_desc-cord_mask.nii.gz`** — PAM50 cord mask cropped to the
   *same* grid as (1), so the template-space BOLD ships with a co-gridded mask
   (GLM needs BOLD + mask in one grid).
3. **JSON sidecars for every BOLD** (native preproc, native unsmoothed, PAM50
   preproc, PAM50 unsmoothed): `RepetitionTime`, `TaskName`, `SkullStripped:
   false`, `SpatialReference`, and `SmoothingFWHM` on the smoothed ones. GLM
   needs `RepetitionTime`; BIDS-Derivatives requires the sidecar.
4. **`dataset_description.json`** (BIDS-Derivatives: `DatasetType: derivative`,
   `GeneratedBy` with tool version + policy SHA) at each dataset's derivatives
   root.
5. **Policy** `S9_*.yaml`: `pam50_4d_output.enabled: true`,
   `emit_unsmoothed: true`, `crop_to_fov: true`, with comments.
6. **`exp` scope re-run** of S9 in a fresh `wf_exp_NNN`, promoted via mark_done.

## Inputs
- `_warp_4d_to_pam50` (exists), `from-bold_to-PAM50_xfm` composite warp (S7),
  `PAM50_t2s.nii.gz` + `PAM50_cord.nii.gz` (SCT $SCT_DIR).
- `desc-preproc_bold` / `desc-unsmoothed_bold` (native, already produced).
- TR from the BOLD nifti header (pixdim[4]); task from run entities.

## Success Criteria
- For a sample exp run: `space-PAM50_desc-preproc_bold` exists, is 4D with the
  same T as native, sits on a 0.5 mm PAM50 grid, and is co-gridded
  (identical affine + shape) with `space-PAM50_desc-cord_mask`. Size ~1–2 GB.
- Every BOLD has a sidecar with a correct non-null `RepetitionTime`.
- `dataset_description.json` validates as BIDS-Derivatives.
- No full-grid 17 GB intermediate is ever written (warp targets cropped ref).
- exp S9 re-run promoted; reportlets still render.

## Next Steps
1. Add cord-FOV bbox + cropped-reference helpers to S9 `process.py`; warp
   smoothed+unsmoothed 4D directly into the cropped ref; crop PAM50 cord mask
   to the same grid.
2. Add sidecar writer + `dataset_description.json` writer.
3. Flip policy knobs.
4. Verify on one exp run (size, co-grid, sidecar, TR).
5. Re-run S9 for `exp`, mark_done, confirm dashboard/reportlets.

## Decision Log
| Q# | Choice | Rationale |
|----|--------|-----------|
| Q1 | 0.5 mm PAM50 cropped to cord FOV (~1–2 GB) | Same space/res as existing PAM50 funcref/tSNR; field-standard; lossless; avoids 17 GB |
| Q2 | Both smoothed + unsmoothed | Mirrors native side; analysis-agnostic/complete |
| Q3 | Re-run exp scope only | Targets the cohort the claim was about; minimal compute; others later |
| (locked) | Sidecars, dataset_description, space-/res- naming, spline interp | Standard + required for GLM/BIDS; not ambiguous |
