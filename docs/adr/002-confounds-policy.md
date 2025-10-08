# ADR-002: Confounds and Censoring Policy

**Status:** Accepted
**Date:** 2025-10-08
**Decision Makers:** CEO

## Context

Spinal cord fMRI has unique noise sources (CSF pulsation, respiratory/cardiac artifacts, motion) requiring specialized confound strategies. Standard brain pipelines (fMRIPrep) use tCompCor and ICA-AROMA, which may not translate to cord physiology.

## Decision

Implement **aCompCor with cord-specific masks** and **contiguity-aware censoring**:

- **aCompCor:** Up to 6 PCs per tissue (cord/WM/CSF)
- **Preprocessing:** Detrend → high-pass (0.008 Hz) → standardize → PCA
- **Seeds:** Deterministic (sklearn default, reproducible)
- **Censoring:** FD > 0.5mm OR DVARS > 1.5 → pad ±1 frame → min 5 contiguous kept
- **Columns:** `framewise_displacement`, `dvars`, `frame_censor`, `acomp_{tissue}_pc{N}`

## Rationale

1. **aCompCor over tCompCor:** Anatomical masks more reliable in cord (small ROIs)
2. **Tissue-specific:** Cord/WM/CSF have distinct physiological signatures
3. **Conservative thresholds:** FD 0.5mm balances sensitivity/specificity for cord motion
4. **Contiguity rule:** Prevents isolated "islands" of kept data (unstable GLM fits)
5. **BIDS compliance:** Standard column names, JSON sidecar with provenance

## Consequences

### Positive
- Reproducible confound extraction (fixed seed)
- Transparent censoring logic (documented algorithm)
- Compatible with FSL FEAT and custom GLMs
- Extensible to tCompCor and RETROICOR (future)

### Negative
- aCompCor requires registration-derived masks (coupling)
- High-pass 0.008 Hz may be too aggressive for some task designs
- No physiological recording support (RETROICOR) in MVP

## Alternatives Considered

- **tCompCor:** Temporal PCA without masks; less interpretable for cord
- **ICA-AROMA:** Brain-optimized, not validated for cord
- **Global signal regression:** Controversial, deferred to user's GLM stage

## Configuration Flexibility

Users can disable/tune:

```yaml
options:
  censor:
    enable: false           # Disable censoring entirely
    fd_thresh_mm: 1.0       # Relax threshold
    min_contig_vols: 3      # Allow shorter runs
  acompcor:
    enable: false           # Skip aCompCor
    n_components_per_tissue: 3  # Fewer PCs
```

## Future Evolution

- v0.2.0: tCompCor option, RETROICOR hooks
- v0.3.0: Adaptive thresholds (data-driven)
- v1.0.0: Physiological log parsing
