---
template: home.html
title: Home
hide:
  - navigation
  - toc
  - footer
  - title
---


<div class="grid cards" markdown>

-   :material-robot: **Automated**

    End-to-end pipeline automation for spinal cord fMRI.

-   :material-shield-check: **Robust**

    Tailored processing for the unique challenges of spinal cord imaging.

-   :material-check-decagram: **QC-First**

    Every preprocessing step emits detailed quality reports.

-   :material-repeat-variant: **Reproducible**

    Deterministic execution guarantees identical results, every time.

</div>

## The first BIDS-App for spinal-cord fMRI

SpinalfMRIprep is a turnkey, containerised, reproducible **preprocessing pipeline
for spinal-cord fMRI** — the fMRIPrep-equivalent the field has lacked. It takes a
BIDS dataset and produces GLM-ready, BIDS-Derivatives outputs with literature-
grounded defaults (SCT, FSL PNM, PAM50) and one visual QC reportlet + one
step-local truth metric per step.

```bash
# Standard BIDS-App: participant-level preprocessing, then group-level QC release
spinalfmriprep /data/bids /out participant
spinalfmriprep /data/bids /out group
```

**Validated** end-to-end on 8 datasets / 384 functional runs / 5 paradigms
(rest, motor, pain, hand-grasp, dorsal-horn), with fully reconciled QC attrition,
test-retest reliability of the derivatives, and the first multi-site
per-vertebral-level normative QC reference for cord fMRI. See
[Validation](validation/index.md).
