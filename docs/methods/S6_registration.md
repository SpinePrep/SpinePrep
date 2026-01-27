# S6: Registration

Functional-to-anatomical alignment.

## Purpose

S6 registers functional data to the anatomical cord reference from S2.

## Algorithm

1. Boundary-Based Registration - Use cord segmentation boundaries
2. Affine Initialization - Rigid + affine registration
3. Nonlinear Refinement - SyN if needed
4. Quality Check - Verify cord alignment

*Implementation in progress*
