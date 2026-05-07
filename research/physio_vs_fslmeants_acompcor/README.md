# physio_vs_fslmeants_acompcor

Method-comparison artifact: does `fslmeants --eig` reproduce TAPAS PhysIO
aCompCor noise-ROI PCs after a per-voxel linear detrend?

Tested Apr 29, 2026 on a single subject's BOLD run (slices 01 and 09,
199 volumes, TR 3.26 s). Subject data is not committed.

## Files committed here

- `run_physio.m`, `run_physio_s09.m` — Matlab/SPM driver scripts that run
  TAPAS PhysIO `noise_rois` (5 components) on a slice mask.
- `detrend_lstsq.py` — per-voxel constant + centered-linear detrend
  (numpy lstsq). This is the step that aligns `fslmeants --eig` with PhysIO.
- `README.md` — this file.
- `.gitignore` — keeps subject-derived outputs local.

## Files kept local (gitignored)

- `bold.nii`, `bold_detrended.nii`, `mask_slice0{1,9}.nii`,
  `noiseROI_mask_slice0{1,9}.nii`, `pc0[1-5]_scores_*.nii` — NIfTI
  inputs/outputs, ignored via the repo-wide `*.nii` rule.
- `physio_slice0{1,9}.{mat,txt}` — PhysIO outputs.
- `fsl_pcs_slice0{1,9}{,_detrended}.txt`, `fsl_pcs_slice01_n6.txt` —
  fslmeants outputs.
- `matlab*.log` — Matlab run logs.

## What ran for the detrend

The detrend was a numpy lstsq step, not `fsl_glm`. The Apr 29 Slack
message in #spinalfmriprep called it "one fsl_glm step"; that label was
imprecise. The math is the same as PhysIO's internal aCompCor detrend:
design matrix = `[constant, centered linear ramp]`, per voxel, residuals
→ detrended. The exact code is `detrend_lstsq.py`.

Slice-level fslmeants on the detrended BOLD:

```bash
fslmeants -i bold_detrended.nii -m mask_slice01.nii --eig --order=5 \
          -o fsl_pcs_slice01_detrended.txt
```

## Result

`fsl_pcs_slice0{1,9}_detrended.txt` matches `physio_slice0{1,9}.txt` to
within numerical noise — i.e. `fslmeants --eig` on detrended data
reproduces PhysIO aCompCor.

`fsl_pcs_slice0{1,9}.txt` (no detrend) does not match: fslmeants demeans
only, PhysIO demeans and removes a linear trend.

## fsl_glm equivalent (untested)

If the pipeline switches to FSL-only, the equivalent of `detrend_lstsq.py`
is a 2-column design (constant + centered linear ramp) passed to
`fsl_glm`:

```bash
N=$(fslnvols bold.nii)
awk -v n=$N 'BEGIN{ for(i=1;i<=n;i++) print 1, i-(n-1)/2 }' > design.txt
Text2Vest design.txt design.mat
fsl_glm -i bold.nii -d design.mat --out_res=bold_detrended.nii
```

Not run or compared against PhysIO yet.
