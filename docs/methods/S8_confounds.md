---
search:
  boost: 2
---

# S8: Confounds and physiological regressors

S8 builds the nuisance regressor matrix for each functional run and writes it as a
table for the downstream general linear model. It regresses nothing itself and
does not resample the BOLD.

## What it does

S8 computes the time-courses an analyst removes from the BOLD signal so that
physiological pulsation, motion and scanner drift are not mistaken for neural
activity. The regressors are built in native functional space and written to one
BIDS-Derivatives `*_desc-confounds_timeseries.tsv` per run, with a JSON sidecar
describing each column. The pipeline never temporally resamples the BOLD; the
slice-timing metadata is used only to phase the RETROICOR regressors, following
the cord-fMRI field standard of leaving the timeseries unfiltered and native
(Eippert et al., 2017; Kaptan et al., 2023).

## Regressor families

S8 emits four families by default, mixing single columns and per-slice columns. The
CSF and RETROICOR families are computed per slice because cord GLMs are often fit
slice by slice.

Motion. Two translations, `trans_x` and `trans_y`, taken as the slice-mean
in-plane translation per volume from S4, plus their first derivatives. This
matches the cord field: Kaptan et al. (2023) regress exactly the slice-wise x and y
translations, because the axial-slice cord motion correction estimates only
in-plane translation. The through-plane and rotational terms of a full brain
motion model are not estimated for the cord and are not emitted. Framewise
displacement is reported but is **not** a regressor and does **not** flag frames.

Outliers. One-hot spike regressors for frames flagged by DVARS or reference-RMS
above a within-run box-plot fence (third quartile plus 1.5 times the interquartile
range), the default rule of FSL `fsl_motion_outliers`. Censoring is on these
intensity metrics only, as in the cord field (Kaptan et al., 2023, censor on
DVARS/refRMS at two standard deviations; Dabbagh et al., 2024, at three). An
absolute framewise-displacement threshold is deliberately not used; the evidence
is in the S4 audit.

CSF regressors. The top five principal components of the cerebrospinal-fluid
signal in each slice (`csf_slice{z}_pc{k}`), computed with FSL `fslmeants --eig`
after per-voxel constant-and-linear detrending. This is the aCompCor idea (Behzadi
et al., 2007) applied slice by slice to a subject-specific CSF mask (the S2 canal
segmentation minus cord, warped to native functional space through S6, falling
back to the PAM50 CSF mask). Applying the component analysis per slice suits the
cord, where the CSF space is a thin ring that changes shape along the cord axis; a
single volume-wide analysis would blur those differences. Five components per slice
is SpinePrep's choice on numerical-stability grounds, not a cord-community
standard. The cord field's own CSF regressor is different (a single mean signal
from high-variance CSF voxels; Kaptan et al., 2023), and this is a documented
departure.

RETROICOR. Cardiac and respiratory phase regressors built with FSL PNM (`popp`
then `pnm_evs`), auto-disabled when physiology recordings are absent. With cardiac
and respiratory orders of 4 and second-order interactions, this is 16 cardiac and
respiratory regressors plus 16 interaction regressors, 32 per slice, aggregated to
one column each by averaging across cord-bearing slices. This is the cord standard
established by Brooks et al. (2008), who adapted RETROICOR (Glover et al., 2000) to
the cord as slice-wise PNM, and used at fourth order by Eippert et al. (2017) and
Kaptan et al. (2023). Slice-wise phasing is essential because cord slices are
acquired at different times and cord physiology varies along the axis. Optional
heart-rate and respiration-volume-per-time regressors are added.

Cosine drift basis. A discrete-cosine high-pass basis with a 0.01 Hz (100 s)
cutoff, the cord standard (Eippert et al., 2017; Kaptan et al., 2023, both
high-pass at 100 s). Emitting the basis as regressors rather than filtering the
data keeps all nuisance removal in one simultaneous GLM, which avoids the
order-of-operations artifact that filtering before censoring can introduce (Carp,
2013); this follows the fMRIPrep convention and departs from the cord papers'
explicit-filter practice.

A fifth family, SpinalCompCor (Hemmerling et al., 2025), which takes principal
components of a dilated noise region outside the cord and CSF, is available but
**off by default** in v1, pending validation.

## Quality control

The reported check is the design-matrix condition number, which flags regressors
so correlated that the GLM becomes numerically unstable. Because the per-slice CSF
regressors are applied slice-locally downstream, S8 scores each slice's real
design (the global regressors plus that slice's own columns) and reports the worst
slice. A run warns when the worst-slice condition number exceeds 1000 and the
per-slice check is otherwise informational. A condition-number check on the
confound matrix is prudent GLM hygiene rather than a named cord-community metric,
and the thresholds are SpinePrep's own. The outlier fraction (the share of frames
flagged by the intensity metrics) is reported and soft-warns above 0.20, but never
fails a run: whether to drop a high-motion run is the analyst's call at GLM time.

## Inputs and outputs

```
derivatives/spineprep/sub-<id>/[ses-<id>/]func/
├── sub-<id>_..._desc-confounds_timeseries.tsv   # all regressor columns
└── sub-<id>_..._desc-confounds_timeseries.json  # column descriptions
```

## Limitations

The confound matrix is emitted for the analyst to regress, following the fMRIPrep
contract; SpinePrep does not choose the GLM. With slice-wise physiology and CSF
components, the per-slice regressor count can approach the degrees of freedom of a
short run over a small cord region, so the condition-number report matters and the
analyst should confirm the design is well-conditioned for their run lengths. The
CSF component count and the condition-number thresholds are SpinePrep choices, not
cord-community standards.

## References

- Behzadi, Y., et al. (2007). A component based noise correction method (CompCor)
  for BOLD and perfusion based fMRI. NeuroImage 37(1), 90–101.
- Brooks, J. C. W., et al. (2008). Physiological noise modelling for spinal
  functional MRI studies. NeuroImage 39(2), 680–692.
- Carp, J. (2013). Optimizing the order of operations for movement scrubbing.
  NeuroImage 76, 436–438.
- Eippert, F., et al. (2017). Denoising spinal cord fMRI data. NeuroImage.
- Glover, G. H., et al. (2000). Image-based method for retrospective correction of
  physiological motion effects in fMRI: RETROICOR. Magnetic Resonance in Medicine
  44(1), 162–167.
- Hemmerling, K. J., et al. (2025). Data-driven denoising in spinal cord fMRI
  (SpinalCompCor). bioRxiv.
- Kaptan, M., et al. (2023). Reliability of resting-state functional connectivity
  in the human spinal cord. NeuroImage 275, 120152.

Running S8: see the [CLI reference](../reference/cli.md).

---
*Parameters reflect `policy/S8_confounds.yaml`, shipped with SpinePrep; verified
against the implementation and primary sources on 2026-07-18. Audit:
`.claude/specs/s8-algorithm-audit.md`.*
