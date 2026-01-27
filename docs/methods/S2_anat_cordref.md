# S2: Anatomical Cord Reference

Cord reference selection, standardization, segmentation, and template registration.

## Purpose

S2 creates the anatomical cord reference that anchors all subsequent processing.

## Algorithm

1. Anatomical Selection - Prefer T2w over T1w
2. Standardization - Reorient to RPI
3. Cord Segmentation - Deep learning segmentation with sct_deepseg
4. Vertebral Labeling - Label vertebral levels
5. Rootlet Detection - Detect nerve rootlets if T2w available
6. Template Registration - Register to PAM50 template

## Key Outputs

- work/S2_anat_cordref/{run_id}/cordref_std.nii.gz
- derivatives/.../anat/*_desc-cord_dseg.nii.gz
- derivatives/.../anat/*_desc-vertlabel_dseg.nii.gz
- QC reportlets in derivatives/.../figures/
