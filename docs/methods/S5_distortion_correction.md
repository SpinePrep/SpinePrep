# S5: Distortion Correction

Susceptibility artifact correction for spinal cord fMRI.

## Purpose

S5 corrects geometric distortions caused by magnetic susceptibility differences near the spinal cord.

## Algorithm

1. Fieldmap Processing - Prepare fieldmaps if available
2. Unwarping - Apply distortion correction
3. Fallback Methods - Use SyN registration if no fieldmap

## Approaches

- Fieldmap-based correction (preferred)
- Reverse phase-encode (TOPUP)
- Fieldmap-less registration

*Implementation in progress*
