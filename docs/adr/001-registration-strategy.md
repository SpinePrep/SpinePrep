# ADR-001: Registration Strategy

**Status:** Accepted  
**Date:** 2025-10-08  
**Decision Makers:** CEO  

## Context

Spinal cord fMRI requires specialized registration due to small anatomical size, high susceptibility artifacts, and CSF pulsation. Standard brain registration tools (FSL FLIRT, ANTs) often fail without cord-specific constraints.

## Decision

Use **Spinal Cord Toolbox (SCT)** with **conservative rigid + affine** defaults for MVP:

- **Tool:** `sct_register_multimodal`
- **Stages:** 2-step (rigid → affine), **no deformable** in v0.1.0
- **Parameters:** `step=1,type=seg,algo=rigid:step=2,type=seg,algo=affine`
- **Template:** PAM50 (0.5×0.5×0.5mm, C1-C7 coverage)
- **Quality gates:** SSIM ≥ 0.90, PSNR ≥ 25 dB
- **Soft-fail:** Warnings logged in QC, processing continues

## Rationale

1. **SCT specialization:** Designed for spinal cord, handles anatomical constraints
2. **Conservative approach:** Rigid + affine avoids over-fitting, more stable
3. **Provenance:** SCT version captured, command logged
4. **Quality thresholds:** SSIM/PSNR balance sensitivity vs. false positives
5. **Graceful degradation:** Soft-fail with QC warnings allows manual review

## Consequences

### Positive
- Stable, reproducible registration
- Lower risk of catastrophic misalignment
- Clear provenance chain
- Framework for future nonlinear options

### Negative
- May underfit in high-quality data
- EPI distortion not corrected (no fieldmaps in MVP)
- Limited to PAM50 (no custom templates)

## Alternatives Considered

- **FSL FLIRT:** Failed in cord ROI without heavy tuning
- **ANTs:** High quality but slow, parameter-sensitive
- **Multi-stage SCT:** More accurate but brittle; deferred to v0.2.0

## Future Evolution

- v0.2.0: Optional deformable step (user-gated)
- v0.3.0: Fieldmap-based distortion correction
- v1.0.0: Custom template support

