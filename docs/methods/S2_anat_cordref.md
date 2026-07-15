# S2: Anatomical cord reference

S2 builds a native-space anatomical cord reference for each subject and session
and registers it to the PAM50 template. The reference anchors the
functional-to-anatomical registration (S6) and the template normalization (S7).
Its outputs are the cord segmentation, the spinal canal, vertebral and disc
labels, optional dorsal rootlets, and the anatomy-to-PAM50 warps.

## Reference selection

The anatomical reference is chosen by contrast preference, T2w before T1w. On
T2-weighted images the cerebrospinal fluid is bright and the cord dark, giving the
cord-CSF boundary that segmentation and vertebral labeling rely on. When a
T2\*/MEGRE acquisition is also present, a second reference is produced in that
contrast for the functional-to-anatomical registration (S5, S6), where a
T2\*-anatomy to T2\*-EPI pairing gives the closest intensity match. A multi-echo
gradient-echo acquisition is combined into a single image by the root-mean-square
across echoes and then the mean across runs; the runs are rigidly aligned before
averaging so that between-run motion does not blur the cord. The reference is
reoriented to RPI, the orientation the SCT and PAM50 tooling assume, which
permutes and flips axes and updates the header together without resampling.

## Cord segmentation

The cord is segmented with `sct_deepseg` using the contrast-agnostic model
(Bédard et al., 2025), the current SCT default for anatomical cord segmentation.
The model is trained across contrasts with a soft-label regression objective that
holds the cross-sectional area consistent between contrasts, which is the property
a registration anchor needs; the segmentation drives registration and is not used
as a morphometric measurement. A cord-focused crop is then taken around the
segmentation centerline, a 60 mm cylinder that retains the cord with enough
surrounding anatomy for the downstream registration landmarks.

## Vertebral and disc labeling

Vertebral bodies, intervertebral discs, and the spinal canal are labelled in one
pass with TotalSpineSeg (`sct_deepseg totalspineseg`; Warszawer et al., 2024),
which segments the whole spine and its levels. The disc labels are converted to
the single-voxel point labels `sct_register_to_template` expects, placed at the
posterior tip of each disc at its mid-superior-inferior level to match the
`sct_label_vertebrae` convention.

TotalSpineSeg is a single network whose labeling anchors every downstream level
assignment, so the disc labeling is sanity-checked. The disc numbers covering the
imaged span must be contiguous, and their superior-inferior order must be
monotonic with disc number; a non-contiguous or reversed labeling is flagged for
review.

## Rootlets and PAM50 registration

Dorsal spinal rootlets are segmented with `sct_deepseg rootlets` (Valošek et al.,
2024) when the reference contrast is eligible. The reference is registered to the
PAM50 template (De Leener et al., 2018) with `sct_register_to_template` at its
default segmentation-driven parameters. Rootlets mark the true spinal level, which
the vertebral discs only approximate, so the rootlet-driven registration is used
when it completes and the disc-driven registration is the fallback. The forward
and inverse warps are written for S7.

## Parameters

`selection.preference`: anatomical contrast order (default `T2w`, then `T1w`).
`megre_synthesis`: multi-echo combination (`echo_combine: rms`, `run_combine: mean`).
`segmentation.cord_method`: cord model (default `contrast_agnostic`).
`labeling.method`: vertebral labeling (default `totalspineseg`).
`crop.mask_diameter_mm`: cord-crop cylinder diameter (default `60`).
`registration.prefer_rootlets`: prefer the rootlet-driven registration (default `true`).

## Inputs and outputs

The input is the subject's anatomical images from S1. Under the output root, S2
writes, per subject and session, the cropped reference, the cord segmentation, the
canal, the vertebral and disc labels, the TotalSpineSeg output, the optional
rootlets, the anatomy-to-PAM50 and PAM50-to-anatomy warps, and the reportlets.

## Quality control

Registration is graded by the median per-vertebral-level cord Dice between the
PAM50 cord warped into native space and the native cord segmentation, with a pass
threshold of 0.90 (Kaptan et al., 2023; Valošek et al., 2025). Per-level Dice is
used rather than a single whole-cord Dice because whole-cord overlap is confounded
by how many cord levels the anatomy covers and because a tube-shaped mask hides
along-cord misalignment; the whole-cord value is reported for observability only.

Five reportlets accompany the metric: the cord-mask montage, the TotalSpineSeg
montage of vertebrae, discs, cord and canal, the rootlets montage, the crop box on
the sagittal, and the PAM50 overlay of the warped template cord on the native
anatomy. The human inspects the PAM50 overlay for cross-sectional and along-cord
agreement and the TotalSpineSeg montage for correct level labeling.

## Limitations

The contrast-agnostic segmentation is used to anchor registration, not to measure
cross-sectional area, for which it carries a contrast-dependent bias.
TotalSpineSeg is a single network with no automatic second labeling backend; the
sanity check catches gross mislabels, but a cropped field of view that omits the
C1/C2 landmark is its known failure mode. The rootlet-driven registration is
validated in the literature by downstream functional sensitivity rather than a
direct geometric error. Whole-cord Dice is coverage-confounded and is not gated.

## References

- Bédard, S., et al. (2025). Towards contrast-agnostic soft segmentation of the
  spinal cord. Medical Image Analysis.
- Warszawer, Y., et al. (2024). TotalSpineSeg: whole-spine segmentation and
  labeling. ISMRM.
- Valošek, J., et al. (2024). Automatic segmentation of the spinal cord nerve
  rootlets. Imaging Neuroscience.
- Bédard, S., Valošek, J., et al. (2025). Rootlets-based registration to the
  PAM50 spinal cord template. Imaging Neuroscience.
- De Leener, B., et al. (2018). PAM50: unbiased multimodal template of the
  brainstem and spinal cord. NeuroImage.
- Kaptan, M., et al. (2023). Reliability of resting-state functional connectivity
  in the human spinal cord. NeuroImage.

Running S2: see the [CLI reference](../reference/cli.md).

---
*Parameters reflect `policy/S2_anat_cordref.yaml`, shipped with SpinePrep;
verified against the implementation on 2026-07-15.*
