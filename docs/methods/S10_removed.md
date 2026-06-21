# S10: Removed

**Status: removed from the active pipeline on 2026-06-11.**

S10 used to perform region-of-interest (ROI) timeseries extraction, functional
connectivity, and reliability analysis. This is **analyst-owned analysis**, not
preprocessing, so it was removed from SpinalfMRIprep's preprocessing release. The
pipeline now goes directly from **S9 (Primary Functional Derivatives)** to **S11
(QC Aggregation & Release)**.

If you need ROI timeseries or connectivity, run them downstream on the S9
outputs: the PAM50-space BOLD that S9 emits is co-gridded with its cord mask and
GLM-ready, and the S8 confounds table provides the nuisance regressors.

> Note: this is not the same thing the older documentation called "S10:
> Confounds". Confound and physiological-noise regressors live in **S8**, not
> S10. The old S10-confounds page was doubly wrong (S10 was never confounds, and
> it has since been removed) and has been deleted.
