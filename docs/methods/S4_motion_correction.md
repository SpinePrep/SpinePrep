# S4: Motion Correction

Volume-to-volume realignment for spinal cord fMRI.

## Purpose

S4 corrects for subject motion during the functional acquisition using cord-optimized registration.

## Algorithm

1. Reference Volume Selection - Use robust reference from S3
2. Iterative Registration - Register each volume to reference
3. Motion Parameter Extraction - Extract 6 DOF parameters
4. Outlier Detection - Flag high-motion volumes
5. Interpolation - Apply transforms with sinc interpolation

## Key Features

- Cord-centric cost function
- Regularized transforms for spinal cord geometry
- Frame-wise displacement calculation
- Integration with confound regression

*Implementation in progress*
