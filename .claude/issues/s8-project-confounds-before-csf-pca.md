# Candidate issue: project motion/spike regressors out before the CSF component analysis

Status: DRAFT, held for review. Do not submit without explicit approval.

## Summary

S8's per-slice CSF component analysis runs on the detrended BOLD with no other
regressors projected out. A component therefore describes whatever dominates
variance in that slice, which on a slice with a severe transient can be the motion
artifact rather than CSF physiology. Projecting the motion parameters and one-hot
spike regressors out of the CSF time-series before `fslmeants --eig` would leave
the components describing the physiological signal they are meant to capture.

## Why this is not urgent

The dominant failure mode found on the 9-dataset cohort was different, and is
already fixed: the CSF mask claimed voxels in slices the scanner never acquired,
so the component analysis ran on an all-zero matrix and fabricated unit deltas.
A live-voxel floor now skips those slices. Projection would not have helped there —
projecting anything out of an all-zero series still leaves zero.

The residual case is smaller: of 202 spike-like components measured across the
cohort, 180 came from dead slices (now fixed), leaving roughly 22 that look like
genuinely artifact-dominated components.

## Precedent

CONN applies this ordering (Morfini et al. 2023, 10.3389/fnins.2023.1092125).
AFNI's censoring achieves a similar effect by removing the frames entirely before
any decomposition. fMRIPrep does not: nipype's CompCor runs on uncensored data
with no variance floor, so artifact-dominated components are possible there by
construction.

## Why it needs its own validation

It changes the CSF components on **every** run, not just affected ones, so it is
not a bug fix and cannot ride along with one. It would need a before/after
comparison on the cohort: do the components change materially, and does tSNR or
the connectivity structure improve or degrade? There is no cord-specific evidence
either way — no cord paper discusses the interaction between CSF components and
spike regressors at all.

## Related open question

The cord field is split on the CSF regressor itself: Barry et al. 2014 uses a
per-slice PCA (SpinePrep's approach), while Eippert 2017, Kaptan 2023, Dabbagh
2024 and the EPFL group use a single mean time course over high-variance CSF
voxels. **These have never been compared head-to-head in the cord.** That
comparison is a genuine potential contribution and is a larger piece of work than
this issue.
