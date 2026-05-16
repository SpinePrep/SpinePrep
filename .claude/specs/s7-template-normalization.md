---
status: approved
supersedes: private/SPEC/S7_template_normalization.md
---

# Scope Spec: S7 Template Normalization (Atlas→Native + Stat-only PAM50)

## Objective
Bring the PAM50 template, cord/WM/GM/CSF masks, and white-matter atlas into native func space; persist composite `bold↔PAM50` warps so S8 (regressors), S9 (group stats), and S10 (ROI extraction) can operate on the warps without recomputing them.

## Constraints
- **Never resample 4D BOLD into PAM50.** Per-subject GLM stays native — matches SCT `batch_processing.sh`, CoSpi `spi08_10_registration.sh`, and Eippert 2017. Only S9 will push cope/zstat to PAM50 for group inference.
- **Trust S2's anat↔PAM50 warps.** S7 consumes `warp_anat2template.nii.gz` / `warp_template2anat.nii.gz` from S2 derivatives. Do not re-do the anat→PAM50 step; the rootlet-vs-disc decision belongs to S2's `prefer_rootlets: true` policy.
- **Follow the SCT-canonical recipe.** EPI-template refinement is a `sct_register_multimodal` second pass against `funcref`, initialised via `-initwarp/-initwarpinv` from the composed S2+S6 warps. `-param step=1,type=seg,algo=slicereg,metric=MeanSquares,smooth=2:step=2,type=im,algo=bsplinesyn,metric=MeanSquares,iter=5,gradStep=0.5`.
- **Reference template is `PAM50_t2s`** for the EPI refinement target — best contrast match for T2*-weighted BOLD.
- **Use rootlet-init transparently.** When S2 produced the anat↔PAM50 warp from rootlets, S7 gets the benefit automatically through `-initwarp`. No special-case code in S7.
- **No double-resampling.** The native-func atlas comes from `sct_warp_template -d funcref -w warp_PAM50_to_func.nii.gz` once.
- **BIDS-Derivatives layout, dataset_key prefixed**, matching S2–S6 convention. Per-dataset isolation everywhere (qc.json, work_dir, runs.jsonl).
- **Cervical coverage only.** PAM50 levels C1–T1; do not extend below.
- **Preserve dtype.** Outputs in float32 (no implicit dtype downgrade).
- Cost guardrail: estimated runtime ≤ 2 min/run (one sct_register_multimodal pass + one sct_warp_template + atlas warps).

## Deliverables

### Per-run derivative artifacts (`derivatives/spinalfmriprep/<dataset_key>/sub-XX/[ses-YY]/`)

**func/**
- `*_from-bold_to-PAM50_xfm.h5` — composite warp (S6 ∘ S2 ∘ S7-refine), forward.
- `*_from-PAM50_to-bold_xfm.h5` — composite inverse warp.
- `*_space-PAM50_desc-funcref.nii.gz` — funcref resampled to PAM50 (single 3D image, for QC overlay only; not used downstream).
- `*_desc-PAM50cord_mask.nii.gz` — PAM50 cord mask warped to native func.
- `*_desc-PAM50csf_mask.nii.gz`, `*_desc-PAM50wm_mask.nii.gz`, `*_desc-PAM50gm_mask.nii.gz` — PAM50 tissue masks in native func.
- `*_desc-PAM50spinallevels.nii.gz` — PAM50 spinal level atlas (1–20) in native func, for ROI extraction.

**anat/** (one-off per session, idempotent across runs)
- `*_space-PAM50_desc-funcref.nii.gz` is in func/, but anat-side composite is unchanged from S2. S7 does NOT rewrite anat-space outputs.

### Per-run work artifacts (`work/S7_template_normalization/<dataset_key>/<run_id>/`)
- `funcref_template_refined/` — sct_register_multimodal output dir.
- `composed_init_warp.nii.gz`, `composed_init_warpinv.nii.gz` — pre-refinement composition of S2+S6 warps used as `-initwarp/-initwarpinv`.
- `template_warped_native/` — sct_warp_template output (full PAM50 atlas in native func).
- `qc/pam50_overlay_*.png` — reportlet source PNGs (sagittal, axial 9-slice).

### Logs (`logs/S7_template_normalization/<dataset_key>/`)
- `qc.json` — per-run rows with status, Dice, label offset, runtime, provenance.
- `runs.jsonl` — append-only per-run log entries.

### Reportlet PNGs (`derivatives/.../figures/`)
- `sub-XX[_ses-YY][_run-NN]_desc-S7_pam50_overlay_sagittal.png` — funcref + warped PAM50 cord contour, midsagittal.
- `sub-XX[_ses-YY][_run-NN]_desc-S7_pam50_overlay_axial.png` — 9-slice axial montage, native func with PAM50 cord contour.
- `sub-XX[_ses-YY][_run-NN]_desc-S7_vertebral_alignment.png` — vertebral labels in PAM50 with subject-warped labels overlaid (for label-offset visual check).

### Policy file (new)
- `policy/S7_template_normalization.yaml` — interpolation choices, QC thresholds, refinement on/off (default on).

### Code (new package, mirrors S6 layout)
- `src/spinalfmriprep/steps/s7/__init__.py`
- `src/spinalfmriprep/steps/s7/policy.py` — load + validate `S7_template_normalization.yaml`.
- `src/spinalfmriprep/steps/s7/io.py` — derivative paths, per-dataset keying, helpers.
- `src/spinalfmriprep/steps/s7/process.py` — `_compose_init_warps`, `_run_refinement`, `_warp_template_to_native`, `_compute_qc`.
- `src/spinalfmriprep/steps/s7/orchestrate.py` — runs S7 per dataset/subject/session/run; writes qc.json, reportlets, dashboards.
- `src/spinalfmriprep/steps/s7/reportlets.py` — sagittal + axial overlays from on-disk artifacts (dev-loop re-render path matching `regen_S2_reportlets.py`).

### Schema (new)
- `schemas/qc_S7_template_normalization.schema.json` — JSON Schema for per-run qc.json.

### Dashboard integration
- S7 card in dashboard with reportlet keys: `pam50_overlay_sagittal`, `pam50_overlay_axial`, `vertebral_alignment`.

## Inputs

### From S2 (anat-side, dataset_key-keyed)
- `derivatives/.../anat/*_from-anat_to-PAM50_warp.nii.gz` (== SCT's `warp_anat2template.nii.gz`).
- `derivatives/.../anat/*_from-PAM50_to-anat_warp.nii.gz` (== `warp_template2anat.nii.gz`).
- `derivatives/.../anat/*_desc-cord_dseg_<mod>.nii.gz` — for QC compare.
- `derivatives/.../anat/*_desc-vertebral_labels.nii.gz` — for label-offset QC.

### From S5 (func-side per run)
- `derivatives/.../func/*_desc-funcref.nii.gz` — refinement target.
- `derivatives/.../func/*_desc-cord_dseg.nii.gz` — for refinement `-dseg`.

### From S6 (per run)
- `derivatives/.../func/*_from-bold_to-anat_xfm.h5`.
- `derivatives/.../func/*_from-anat_to-bold_xfm.h5`.

### From PAM50 (read-only, version-locked via S0)
- `$SCT_DIR/data/PAM50/template/PAM50_t2s.nii.gz` (refinement reference).
- `$SCT_DIR/data/PAM50/template/PAM50_cord.nii.gz` (refinement seg + QC).
- `$SCT_DIR/data/PAM50/template/PAM50_csf.nii.gz`, `_wm.nii.gz`, `_gm.nii.gz`.
- `$SCT_DIR/data/PAM50/template/PAM50_spinal_levels.nii.gz`.
- `$SCT_DIR/data/PAM50/atlas/` — for downstream S10 if requested.

### Policy
- `policy/S7_template_normalization.yaml`.

## Success Criteria

### Per-run gating (qc.json `status`)
- **PASS**: cord Dice (PAM50_cord warped to func vs S5 func cord_dseg) ≥ 0.90 AND vertebral label centroid offset ≤ 1.0 mm.
- **WARN**: 0.80 ≤ cord Dice < 0.90 OR 1.0 mm < label offset ≤ 2.0 mm.
- **FAIL**: cord Dice < 0.80 OR label offset > 2.0 mm OR sct_register_multimodal non-zero exit.

### Dataset-level acceptance (for v1 release)
- All 5 v1_validation datasets emit per-run S7 qc.json with status field.
- Median cord Dice across v1_validation runs ≥ 0.92 (refinement should improve on S6's already ~0.95 baseline by tightening at PAM50 boundary slices).
- Dashboard renders all three reportlet types per run; no missing PNGs across the chain.
- Round-trip sanity: `warp_func_to_PAM50` then `warp_PAM50_to_func` on the funcref → mean voxel displacement < 0.5 mm.
- Disk per run < 50 MB for S7 outputs (no 4D resampling means most outputs are small 3D atlases).

## Next Steps

1. Mark `private/SPEC/S7_template_normalization.md` status → `superseded`, add `superseded_by: .claude/specs/s7-template-normalization.md` to its frontmatter.
2. Write `policy/S7_template_normalization.yaml` with the interpolation map, refinement params, QC thresholds.
3. Add `schemas/qc_S7_template_normalization.schema.json`.
4. Scaffold `src/spinalfmriprep/steps/s7/` mirroring S6 layout (policy.py, io.py, process.py, orchestrate.py, reportlets.py).
5. Implement `_compose_init_warps` using `sct_apply_transfo -concatenate` (or ANTs `ComposeMultiTransform`) to fuse S2+S6 warps into `composed_init_warp`.
6. Implement `_run_refinement` — `sct_register_multimodal` with the SCT-canonical param string above, initialised from the composed warps, refined against funcref.
7. Implement `_warp_template_to_native` — `sct_warp_template -d funcref -w warp_PAM50_to_func.nii.gz -a 1` to emit the full PAM50 atlas pack.
8. Implement QC (Dice + label offset + round-trip) and `qc.json` writer (per-dataset keyed).
9. Implement reportlets (sagittal/axial overlays, vertebral alignment plot).
10. Add S7 to chain in `scripts/full_chain_reg.py` (link S6 outputs as predecessors).
11. Run chain S7 on the 5 reg datasets; iterate until median Dice ≥ 0.92.
12. Commit incrementally per the user's atomic-commit preference (one PR/commit per file group).

## Decision Log

| Q# | Choice | Rationale |
|----|--------|-----------|
| Q1 | A — include EPI-template refinement | Matches SCT batch_processing.sh canonical; Valošek 2025 shows alignment quality drives 2.4× group cluster size; runtime cost trivial. |
| Q2 | A — never resample 4D BOLD to PAM50 | Native GLM preserves SNR; saves ~30× disk per run; matches CoSpi-validated lineage; S9 handles cope/zstat→PAM50. |
| Q3 | A — trust S2's anat↔PAM50 warp | Single source of truth for rootlet/disc decision; layered-pipeline separation; rootlet benefit propagates via `-initwarp` automatically. |

## Out of scope (deferred)

- Pushing 4D BOLD into PAM50 (explicitly disallowed by Q2).
- Subject-template optimisation for paediatric / pathological cohorts.
- Non-rigid refinement at PAM50 boundary slices (C1, T1) beyond the bsplinesyn iter=5 step.
- ROI extraction itself (S10 owns this; S7 produces the warped atlases it needs).
- Group-level stat aggregation (S9 owns).
- Smoothing of 4D BOLD in PAM50 space (would imply 4D-in-PAM50, which is disallowed).

## References

- [SCT — Registering fMRI to PAM50](https://spinalcordtoolbox.com/stable/user_section/tutorials/processing-fmri-data/template-registration-for-fmri.html)
- [SCT batch_processing.sh — fMRI block](https://github.com/spinalcordtoolbox/spinalcordtoolbox/blob/master/batch_processing.sh)
- [Valošek et al. 2025 — Rootlets-based registration to PAM50](https://pmc.ncbi.nlm.nih.gov/articles/PMC12381661/)
- [Landelle et al. 2023 — Spinal Cord fMRI review](https://pmc.ncbi.nlm.nih.gov/articles/PMC10623605/)
- [De Leener et al. 2018 — PAM50 template](https://www.sciencedirect.com/science/article/abs/pii/S1053811917308686)
- [Eippert et al. 2017 — Spinal fMRI preprocessing](https://pmc.ncbi.nlm.nih.gov/articles/PMC10623605/)
- CoSpi reference: `/mnt/hdd2/P1_CoSpi/scripts_pilot_motor/spi08_10_registration.sh`, `spi17_stat_standard.sh`.
