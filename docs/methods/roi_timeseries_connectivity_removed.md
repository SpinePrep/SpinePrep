# Removed: ROI timeseries & connectivity (former S10)

**Status: removed from the active pipeline on 2026-06-11.**

This step — formerly step S10 — used to perform region-of-interest (ROI)
timeseries extraction, functional connectivity, and reliability analysis. This is
**analyst-owned analysis**, not preprocessing, so it was removed from
SpinePrep's preprocessing release. The pipeline now goes directly from
**S9 (Primary Functional Derivatives)** to **S10 (QC Aggregation & Release)**,
which has reused the S10 step number for the release step.

If you need ROI timeseries or connectivity, run them downstream on the S9
outputs: the PAM50-space BOLD that S9 emits is co-gridded with its cord mask and
GLM-ready, and the S8 confounds table provides the nuisance regressors.

> Note: this is not the same thing the older documentation called "S10:
> Confounds". Confound and physiological-noise regressors live in **S8**. The
> old S10-confounds page was wrong (this step was never confounds) and has been
> deleted. Note also that the S10 step number now refers to QC aggregation &
> release, not to this removed ROI/connectivity analysis.
