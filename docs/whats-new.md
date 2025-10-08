# What's New in v0.1.0

**Release Date:** October 8, 2025

SpinePrep v0.1.0 is the first public release! This MVP provides a complete, end-to-end spinal cord fMRI preprocessing pipeline with BIDS compliance and comprehensive QC.

## Highlights

### 🎯 Core Features

- **Complete preprocessing pipeline** from raw BIDS to analyzed derivatives
- **Motion metrics** with Power FD and DVARS computation
- **Confounds extraction** including aCompCor (6 PCs per tissue) and frame censoring
- **SCT-based registration** to PAM50 template (conservative rigid + affine)
- **BIDS-Derivatives** compliant outputs with full provenance
- **Self-contained QC reports** (no external dependencies, works offline)

### 🔧 Command Line Interface

```bash
spineprep version    # Print version
spineprep doctor     # Check environment (SCT, PAM50, Python)
spineprep run        # Execute preprocessing pipeline
```

### 🧪 Quality Assurance

- **105+ passing tests** (unit, integration, end-to-end)
- **Deterministic execution** with fixed random seeds
- **CI/CD pipeline** with artifact uploads
- **Quality gates**: SSIM ≥ 0.90, PSNR ≥ 25 dB for registration

### 📚 Documentation

- **User guides** for all components
- **API reference** (auto-generated)
- **Architecture Decision Records** (ADRs) documenting key choices
- **Quickstart** guide for 5-minute setup

## Key Components

### Environment Diagnostics

```bash
$ spineprep doctor
======================================================================
  SpinePrep Doctor - Environment Diagnostics
======================================================================
  Overall Status: [✓] PASS
======================================================================

Platform:
  OS:       Linux 6.14.0-29-generic
  Python:   3.11.0
  CPU:      8 cores
  RAM:      16.0 GB

Dependencies:
  [✓] SCT: Version 7.1
  [✓] PAM50: /opt/sct/data/PAM50
  [✓] Python Packages: numpy, pandas, scipy, nibabel, snakemake
```

### Confounds

Standard BIDS confounds with:
- **framewise_displacement** (Power method, mm)
- **dvars** (Standardized)
- **frame_censor** (binary 0/1 mask)
- **acomp_{tissue}_pc{N}** (aCompCor components)

### Registration

Conservative SCT-based alignment:
- Rigid (6 DOF) + Affine (12 DOF)
- No deformable in MVP (stability over fit)
- Quality thresholds with soft-fail warnings

### QC Reports

Self-contained HTML with:
- Environment check matrix
- Subject/run summaries
- Motion statistics
- DAG visualization
- No CDN/JS (fully offline)

## Technical Details

### Test Coverage

- **confounds:** 87%
- **ingest:** 86%
- **register:** 86%
- **derivatives:** 83%
- **qc:** 100%

### Dependencies

- Python 3.9+
- Spinal Cord Toolbox 5.8+
- Snakemake
- NumPy, SciPy, pandas, nibabel
- scikit-learn, scikit-image

### Container

```bash
docker pull ghcr.io/spineprep/spineprep:0.1.0
docker run --rm ghcr.io/spineprep/spineprep:0.1.0 spineprep version
```

## What's Not Included (Yet)

These features are planned for v0.2.0:

- Deformable registration (behind feature flag)
- tCompCor confounds
- RETROICOR physiological regressors
- Interactive QC with motion plots
- Public sample dataset
- Performance profiling and caching

## Migration Notes

This is the first public release - no migration needed!

## Known Issues

- Docs deployment to `/stable/` requires release workflow completion
- Some test fixtures use old config API (being refactored)
- Coverage target (85%) will be reached in v0.2.0

## Getting Started

See the [Quickstart Guide](user-guide/quickstart.md) for a 5-minute introduction.

## Acknowledgments

Built with:
- [Spinal Cord Toolbox](https://github.com/spinalcordtoolbox/spinalcordtoolbox)
- [Snakemake](https://snakemake.github.io/)
- [MkDocs Material](https://squidfunk.github.io/mkdocs-material/)

## Links

- **Documentation**: [https://spineprep.github.io](https://spineprep.github.io)
- **Repository**: [https://github.com/SpinePrep/SpinePrep](https://github.com/SpinePrep/SpinePrep)
- **Issues**: [https://github.com/SpinePrep/SpinePrep/issues](https://github.com/SpinePrep/SpinePrep/issues)
- **Releases**: [https://github.com/SpinePrep/SpinePrep/releases](https://github.com/SpinePrep/SpinePrep/releases)

