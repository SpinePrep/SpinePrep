# Architecture

SpinePrep's design decisions are documented in Architecture Decision Records (ADRs).

## Overview

SpinePrep is built on these core principles:

- **BIDS-first**: Strict adherence to BIDS and BIDS-Derivatives specifications
- **Provenance**: Complete tracking of processing parameters and environment
- **Reproducibility**: Deterministic outputs with pinned dependencies
- **QC-centric**: Visual quality control at every stage
- **Modular**: Optional processing steps controlled by configuration

## Architecture Decision Records

These ADRs document key technical decisions and their rationale:

### [ADR-001: Registration Strategy](../adr/001-registration-strategy.md)

**Decision:** Use SCT with conservative rigid + affine defaults for MVP

- Tool: `sct_register_multimodal`
- Strategy: 2-step (rigid → affine), no deformable in v0.1.0
- Quality gates: SSIM ≥ 0.90, PSNR ≥ 25 dB
- Rationale: Stability over accuracy in MVP; SCT specialization for cord

### [ADR-002: Confounds Policy](../adr/002-confounds-policy.md)

**Decision:** aCompCor with cord-specific masks and contiguity-aware censoring

- aCompCor: Up to 6 PCs per tissue (cord/WM/CSF)
- Preprocessing: Detrend → high-pass (0.008 Hz) → standardize → PCA
- Censoring: FD > 0.5mm OR DVARS > 1.5 → pad ±1 → min 5 contiguous
- Rationale: Reproducibility (deterministic seeds), transparency, BIDS compliance

### [ADR-003: Distribution Strategy](../adr/003-distribution-strategy.md)

**Decision:** GHCR containers + pip install for dual access

- Container: `ghcr.io/spineprep/spineprep:0.1.0` (pinned digest)
- PyPI: `pip install spineprep` (CLI + libraries)
- Docs: MkDocs with mike versioning (/ = latest, /stable = tagged)
- Rationale: Reproducibility via digests, ease of local dev, version-aware docs

## System Architecture

### Pipeline Stages

1. **Validation** - BIDS structure and metadata checks
2. **Discovery** - Scan for subjects, sessions, runs
3. **Samples** - Build run manifest with motion grouping
4. **Motion** - FD/DVARS computation, motion correction
5. **Confounds** - aCompCor extraction, censoring logic
6. **Registration** - EPI→PAM50 alignment (optional)
7. **Derivatives** - BIDS-compliant outputs with sidecars
8. **QC** - HTML report generation

### Technology Stack

- **Orchestration**: Snakemake (DAG-based workflow)
- **Registration**: Spinal Cord Toolbox (SCT)
- **Computation**: NumPy, SciPy, scikit-learn, nibabel
- **Quality**: scikit-image (SSIM/PSNR)
- **Docs**: MkDocs Material with mike versioning
- **CI/CD**: GitHub Actions with artifact caching

### Data Flow

```
BIDS Input
    ↓
  Validation (strict schema)
    ↓
  Discovery (manifest creation)
    ↓
  ┌─────────────────┬─────────────────┐
  ↓                 ↓                 ↓
MP-PCA          Motion           Registration
(optional)      (required)        (optional)
  ↓                 ↓                 ↓
  └─────────────────┴─────────────────┘
                    ↓
                Confounds
                    ↓
                Derivatives
                    ↓
                   QC
```

## Extensibility

SpinePrep is designed for extension:

- **Plugins**: Future physio log parsers via hooks
- **Templates**: Custom templates beyond PAM50
- **Engines**: Pluggable motion correction backends
- **QC**: Modular report components

## Future ADRs

Planned for v0.2.0+:

- ADR-004: Temporal cropping strategy
- ADR-005: Caching and performance optimization
- ADR-006: Multi-session handling
- ADR-007: Container base selection and sizing

