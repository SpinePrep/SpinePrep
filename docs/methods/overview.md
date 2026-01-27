# Methods Overview

SpinePrep implements an end-to-end preprocessing pipeline for spinal cord fMRI, designed for robustness against the unique challenges of spinal imaging: physiological noise, small anatomical targets, and susceptibility artifacts.

## Pipeline Architecture

```mermaid
flowchart LR
    S0[S0: Setup] --> S1[S1: Input Verify]
    S1 --> S2[S2: Anat Cord Ref]
    S2 --> S3[S3: Func Init & Crop]
    S3 --> S4[S4: Motion Correction]
    S4 --> S5[S5: Distortion Correction]
    S5 --> S6[S6: Registration]
    S6 --> S7[S7: Normalization]
    S7 --> S8[S8: Segmentation]
    S8 --> S9[S9: Smoothing]
    S9 --> S10[S10: Confounds]
    S10 --> S11[S11: Export]
```

## Design Principles

| Principle | Implementation |
|-----------|----------------|
| **Validity-first** | Spinal cord measurement validity takes precedence over processing speed |
| **Determinism** | Same inputs + policy → identical outputs, guaranteed |
| **Fail-fast** | No silent downgrades; clear error messages on failure |
| **QC-embedded** | Every step emits machine-readable QC JSON and visual reportlets |

## Step Summaries

| Step | Name | Purpose |
|------|------|---------|
| S0 | Setup | Environment validation, container bootstrapping |
| S1 | Input Verify | BIDS validation, inventory generation |
| S2 | Anat Cord Ref | Anatomical cord segmentation, reference creation |
| S3 | Func Init & Crop | Dummy drop, cord localization, FOV cropping |
| S4 | Motion Correction | Volume-to-volume realignment |
| S5 | Distortion Correction | Susceptibility artifact correction |
| S6 | Registration | Functional-to-anatomical alignment |
| S7 | Normalization | Template space transformation |
| S8 | Segmentation | Tissue classification, GM/WM/CSF masks |
| S9 | Smoothing | Spatial filtering within cord mask |
| S10 | Confounds | Nuisance regressor extraction |
| S11 | Export | BIDS-derivative output, final QC aggregation |

---

*For detailed technical descriptions of each step, see the per-step pages in this section.*
