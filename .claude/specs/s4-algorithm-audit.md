---
status: approved
---

# S4 algorithm audit — literature-backed, truthful, correct

Rewritten 2026-07-16. Supersedes the previous version, which predated the
current research pass, judged the moco mask acceptable (it is a deviation, F2),
called FD "Power 2014" (the shipped FD is Kaptan's x/y form, F4), and did not
examine the public doc (wrong, F1), the tSNR mask (F5), the dead reference
(F6), or the tests (F7). Every claim below was verified against the S4 code,
the installed SCT 7.1 (`sct_fmri_moco -h`), SCT's vendored fMRI tutorial
(`docs/vendor/sct/7.2/...`), or primary literature (quotes + DOIs in the
research log). SpinePrep ships **SCT 7.1** (`Dockerfile.spineprep`:
`ENV SCT_VERSION=7.1`); version-sensitive claims are scoped to it.

## What S4 does (verified against code)

Two-stage motion correction on the cord-cropped 4D EPI from S3.

| Stage | Operation | Engine |
|---|---|---|
| **S4.1** | (optional, off by default) inter-run Z-shift detect/correct | `skimage.phase_cross_correlation` |
| **S4.2** | Stage 1 — coarse in-plane X/Y bulk translation, estimated by FLIRT 2-DOF on the Z-mean projection of each volume, applied identically to every slice | FSL `flirt` + `scipy.ndimage.shift` |
| **S4.3** | Stage 2 — slice-wise in-plane translation regularized by a polynomial along Z | `sct_fmri_moco` (SliceReg, ANTs) |
| **S4.4** | metrics (FD, DVARS, tSNR before/after) + 3 reportlets | NumPy |

Downstream: S5 consumes the moco'd `desc-mocoref_bold`; **S8 reads S4's
slicewise `moco_params_x/_y.nii.gz` as GLM motion confounds** — so S4's motion
estimates are load-bearing, not observability-only.

## Verdicts

| Choice | Value | Verdict |
|---|---|---|
| Slice-wise engine | `sct_fmri_moco` (SliceReg) | KEEP — the field standard (Kaptan, CoSpine, SCT) |
| Two-stage design | FLIRT-2DOF bulk + `sct_fmri_moco` | KEEP-with-caveat (F3): Stage-1 is bespoke, partly duplicates SCT's internal 3D, A/B is 11 retired runs |
| Moco mask | cord segmentation interior | DEVIATION (F2): field uses a 30–41 mm cylinder; no citation for cord-interior |
| Framewise displacement | `\|Δtx\|+\|Δty\|`, in-plane only | KEEP — matches Kaptan verbatim; fix the code comments (F4) |
| tSNR / DVARS mask | whole-crop nonzero | FIX (F5): field measures cord-restricted |
| Robust reference at Stage 2 | symlinked, never passed | DOCUMENT (F6): SCT 7.1 cannot take an external ref |
| Motion gate | high-motion fraction + tSNR floor | KEEP — relative, self-normalizing |
| Public doc | single-stage, `-ref`, wrong outputs | FIX (F1): describes a pipeline that does not exist |

## Findings

### F1 — The public doc describes a pipeline that does not exist — FIX (done)
`docs/methods/S4_motion_correction.md`, verified against the code, is wrong in
four load-bearing ways:
- It shows single-stage `sct_fmri_moco -i ... -ref func_ref.nii.gz -g 1 -param
  params.txt -x spline`. The code runs **two stages**, and **`sct_fmri_moco` in
  SCT 7.1 has no `-ref` flag** (`-r {0,1}` is "remove temp files", verified from
  `sct_fmri_moco -h`) — the documented command would error. Stage 1 (the FLIRT
  bulk step) is not mentioned at all.
- The QC-status logic ("max displacement > 3 mm → FAIL, mean FD > 0.5 → FAIL")
  is stale. The `max_fd` FAIL gate was retired 2026-06-16; the real gate is
  high-motion fraction (> 0.50 FAIL, > 0.30 WARN) plus a tSNR floor.
- Outputs are wrong: the doc claims `desc-moco_bold.nii.gz` and a
  `desc-moco_mean.nii.gz` that the code never writes (real name:
  `desc-mocoref_bold.nii.gz`), and lists a retired `S4_dvars_plot.png`.
- `-ref func_ref.nii.gz` also implies the S3 robust reference drives the
  slice-wise stage; it does not (F6).
The "no slice-timing correction" note is correct and kept. Doc rewritten to the
verified two-stage description in the field register.

### F2 — The moco mask deviates from the field, and the deviation is uncitable — OPEN (key)
SpinePrep passes the **cord segmentation interior** to `sct_fmri_moco -m`
(`process.py:93-102`, hardcoded — not even a policy knob). The field passes a
**dilated cylinder around the cord centerline**, verified against three primary
sources:
- SCT `batch_processing.sh` / vendored tutorial:
  `sct_create_mask -i fmri.nii.gz -p centerline,seg.nii.gz -size 35mm` → then
  `sct_fmri_moco -m mask_fmri.nii.gz`.
- CoSpine (Wei 2025, Sci Data): "a 3D binary mask (35 mm diameter)".
- Kaptan 2023 (NeuroImage): a cord-centred cylindrical mask, 30–41 mm.
The `-m` mask "limits the voxels considered by the registration metric" (SCT
docs). Rationale (SCT developer forum + analysis): the cord interior is nearly
uniform EPI signal; the cross-correlation/MI metric needs the high-contrast
**cord↔CSF boundary**, which the 30–41 mm cylinder brackets and a
cord-interior-only mask starves. No paper endorses a cord-interior moco mask.

By invariant 1 (use the field's choice when you cannot cite your own), the
default should include the cord/CSF boundary. Nuance that must be measured, not
assumed: S3 already crops to a tight box (~32 mm in-plane in the ZSpine
example), so a literal 35 mm cylinder ≈ the whole cropped FOV, while the cord
seg ≈ cord interior. The right cohort A/B is therefore cord-seg vs a **dilated
cord mask** (cord + a few mm to include the boundary), scored by cord-restricted
tSNR (F5). Decision deferred to that A/B; do not flip the default silently — it
changes results for every run and must be validated visually.

### F3 — Stage-1 is bespoke, partly redundant with SCT, evidence is 11 retired runs — OPEN
Single-stage `sct_fmri_moco` is the field norm (Kaptan, CoSpine, SCT tutorial).
SliceReg already runs an **internal 3D rigid initialization** before its
slice-wise pass (SCT docs: "first step using 3D rigid-body realignment …
followed by a second step performing 2D slice-wise realignment"). So the real
chain is three stages: **[custom FLIRT-2DOF] → [SCT internal 3D rigid] → [SCT
SliceReg]** — the custom Stage 1 partly duplicates SCT's own 3D step.

A two-stage design is documented (Barry group, bioRxiv 2020.05.20.103986: **3D
FLIRT** → SliceReg), but SpinePrep's Stage 1 is **not** that — it is a 2-DOF
in-plane fit on the **Z-mean projection**, which collapses all slices to one
plane and discards the through-plane information a 3D rigid uses. No source
documents that variant; treat it as bespoke, defensible only as a coarse
pre-align feeding Stage 2.

Its entire justification is an A/B on the retired 11-run reg cohort
("FLIRT-2DOF cord tSNR 18.30 vs MCFLIRT 15.26 vs none 15.35"), and **S4 has zero
outputs on the current 466-run cohort** — the design has never been validated at
the scale the paper claims. Required: a cohort A/B with three arms — no Stage 1
(SCT-internal only), FLIRT-2DOF, and MCFLIRT — scored by cord tSNR, or scope the
claim to the dev cohort. The ledger also flags a lighter option: make Stage 1
conditional on measured motion (helps high-motion runs, ~no-op on low-motion).

### F4 — Framewise displacement: correct, but the code reads as unfinished — FIX (done)
The 2-DOF in-plane FD (`|Δtx|+|Δty|`, no rotation, no tz) is **exactly the
field's cord FD**, verified against Kaptan 2023: "framewise displacement (FD)
was computed by summing the absolute values of the derivatives of the motion
parameters in x and y." It also falls out of `sct_fmri_moco`, which only
estimates in-plane slice-wise translations. Dropping rotation is the field's
deliberate adaptation for a cord-cropped small FOV, not an oversight — Power
2012's 6-parameter FD is the brain definition SpinePrep correctly departs from.

The defect is presentation: `compute_framewise_displacement` shipped with
unresolved authoring comments ("Assume rotations are in degrees? Or radians?",
"Need to verify input source") in a published toolbox. Rewritten to state the
Kaptan x/y definition, cite it, and note the rotation branch is dead for this
engine (kept only so a 6-column consumer still gets a full frame).

### F5 — tSNR and DVARS are measured over the wrong mask — FIX (done)
`process.py:320` computes the tSNR gate, the tSNR-improvement metric, and DVARS
over `np.mean(after_data, axis=-1) > 0` — the whole cropped FOV, which includes
the pulsatile CSF ring. The field measures tSNR **cord-restricted** (Kaptan:
cord/gray-matter tSNR = voxel temporal mean / temporal SD, averaged within the
cord ROI). Over the whole crop, CSF pulsatility deflates tSNR and the "cord"
truth metric is not cord-specific (violates invariant 2). The ledger already
listed this as open ("tSNR montage uses FOV mask not cord-seg"). Fixed to use
the cord segmentation (the same cropped seg passed to moco), with the
nonzero-FOV mask kept only as a fallback. This changes the tSNR/DVARS values, so
it lands before the first cohort S4 run (no S4 cohort outputs exist to
invalidate).

### F6 — The robust reference is dead at Stage 2 — DOCUMENT (done)
`process.py:271-273` symlinks the S3 robust reference as `sct_ref.nii.gz`, but
it is **never passed to `sct_fmri_moco`** — in SCT 7.1 the tool has no
external-reference flag and builds its own target by iterative averaging
(`iterAvg`, `num_target`). So the robust reference governs Stage 1 (FLIRT) and
the tSNR comparison only; Stage 2's target is SCT's internal average. The dead
symlink is a fossil of unachievable intent; removed. Version note for the paper:
SCT **7.2** (2025-11-28) added a `-ref` flag, so "no external reference" is true
for 7.1 (shipped) and must be scoped to it.

### F7 — Two tests shadow the logic instead of exercising it — FIX (done)
`test_s4_picks_cropped_moco_mask_when_present` and
`test_s4_aggregates_top_level_status` re-implement the selection/aggregation
rule inline in the test body, so a regression in `process.py`/`orchestrate.py`
would not fail them. Replaced with tests that import and call the real code.

### F8 — Output naming — NOTE
`desc-mocoref_bold` is a non-standard BIDS-Derivatives `desc-` value (it
conflates "moco" and "ref"; fMRIPrep uses `desc-preproc_bold`). Not changed (S5
reads this exact name; renaming is a cross-step change), but recorded so the
paper's derivatives table is accurate.

### F9 — tSNR degradation is computed but not gated — NOTE
`tsnr_improvement_pct` is written to qc.json but never gates. A run where moco
lowers cord tSNR (moco actively hurt, seen on severely motion-contaminated
runs) still passes on that axis. Low priority — the tSNR floor and high-motion
fraction catch the worst cases — but a WARN on `tsnr_improvement_pct < 0` would
name the failure mode directly. Deferred until F5's cord-restricted tSNR lands,
since the sign is only meaningful once the metric is cord-specific.

## Open items, by priority
1. **F2** — cohort A/B: cord-seg vs dilated-cord moco mask, by cord tSNR; then
   set the default and make it a policy knob.
2. **F3** — cohort A/B for Stage 1 (none/SCT-internal vs FLIRT-2DOF vs MCFLIRT),
   or scope the claim to the dev cohort; consider motion-conditional Stage 1.
3. Run S4 on the 466-run cohort (none exist yet) and validate reportlets visually.
4. **F9** — add the tSNR-degradation WARN after F5 lands.
5. **F8** — decide whether to migrate `desc-mocoref_bold` → a standard `desc-`.

## Fixed in this audit
- **F1** — public doc rewritten to the verified two-stage description.
- **F4** — FD comments rewritten, Kaptan cited, dead rotation branch documented.
- **F5** — tSNR/DVARS now cord-restricted.
- **F6** — dead `sct_ref` symlink removed; SCT-7.1 version scoping recorded.
- **F7** — shadow tests replaced with real-path tests.
