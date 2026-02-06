<p align="center">
  <img src="logo.svg" alt="SpinalfMRIprep" width="400">
</p>

<p align="center">
  <strong>Robust preprocessing for human spinal cord fMRI</strong>
</p>

<p align="center">
  <a href="https://github.com/spinalfmriprep/spinalfmriprep/releases"><img src="https://img.shields.io/badge/version-0.0.1-blue" alt="Version"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.10%20|%203.11%20|%203.12-blue" alt="Python"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-green" alt="License"></a>
  <a href="https://spinalfmriprep.github.io/spinalfmriprep/"><img src="https://img.shields.io/badge/docs-online-brightgreen" alt="Documentation"></a>
</p>

---

## About

**SpinalfMRIprep** is an open-source pipeline for preprocessing spinal cord functional MRI data. Given a BIDS-compliant dataset, SpinalfMRIprep produces **GLM-ready derivatives** with comprehensive quality control outputs.

SpinalfMRIprep is designed with validity-first principles: spinal cord measurement robustness comes before speed or convenience. Every processing step emits machine-readable QC and visual reportlets for transparent, auditable preprocessing.

```
                              SpinalfMRIprep Pipeline
    ┌─────────────────────────────────────────────────────────────────────────┐
    │                                                                         │
    │   BIDS Input                                                            │
    │       │                                                                 │
    │       ▼                                                                 │
    │   ┌──────────────┐    ┌──────────────┐    ┌──────────────────────────┐  │
    │   │ S1: Input    │───▶│ S2: Anat     │───▶│ S3: Func Reference +     │  │
    │   │    Verify    │    │    Cordref   │    │     Cord-Focused Crop    │  │
    │   └──────────────┘    └──────────────┘    └──────────────────────────┘  │
    │                                                   │                     │
    │                                                   ▼                     │
    │   ┌──────────────┐    ┌──────────────┐    ┌──────────────────────────┐  │
    │   │ S6: Func→    │◀───│ S5: Cord/CSF │◀───│ S4: Motion Correction    │  │
    │   │    Anat Reg  │    │    Masking   │    │     (cord-aware)         │  │
    │   └──────────────┘    └──────────────┘    └──────────────────────────┘  │
    │          │                                                              │
    │          ▼                                                              │
    │   ┌──────────────┐    ┌──────────────┐    ┌──────────────────────────┐  │
    │   │ S7: Template │───▶│ S8: Confounds│───▶│ S9: Primary Derivatives  │  │
    │   │    Warp      │    │    + Physio  │    │     (native + PAM50)     │  │
    │   └──────────────┘    └──────────────┘    └──────────────────────────┘  │
    │                                                   │                     │
    │                                                   ▼                     │
    │                       ┌──────────────┐    ┌──────────────────────────┐  │
    │                       │ S11: QC      │◀───│ S10: ROI Timeseries +    │  │
    │                       │     Dashboard│    │      Reliability         │  │
    │                       └──────────────┘    └──────────────────────────┘  │
    │                              │                                          │
    │                              ▼                                          │
    │                     GLM-Ready Derivatives                               │
    │                     + QC Reports                                        │
    │                                                                         │
    └─────────────────────────────────────────────────────────────────────────┘
```

## Features

- **BIDS-native**: Input BIDS, output BIDS-Derivatives
- **Cord-focused**: Optimized for cervical spinal cord (C1–T1)
- **Transparent QC**: Every step produces visual reportlets and machine-readable QC JSON
- **Template normalization**: PAM50 template registration via SCT
- **Reproducible**: Deterministic processing with full provenance tracking

## Installation

### Docker (recommended)

```bash
docker pull spinalfmriprep/spinalfmriprep:latest

docker run -v /path/to/bids:/data:ro \
           -v /path/to/output:/out \
           spinalfmriprep/spinalfmriprep:latest \
           /data /out participant
```

### Local installation

SpinalfMRIprep requires [Spinal Cord Toolbox (SCT)](https://spinalcordtoolbox.com/) to be installed and available in your `PATH`.

```bash
# Install SCT first (see https://spinalcordtoolbox.com/installation.html)

# Install SpinalfMRIprep
pip install spinalfmriprep

# Or for development
git clone https://github.com/spinalfmriprep/spinalfmriprep.git
cd spinalfmriprep
pip install -e .
```

## Quick Start

```bash
spinalfmriprep /path/to/bids /path/to/output participant \
    --participant-label sub-01
```

For detailed usage, configuration options, and tutorials, see the **[Documentation](https://spinalfmriprep.github.io/spinalfmriprep/)**.

## Documentation

Full documentation is available at **[spinalfmriprep.github.io/spinalfmriprep](https://spinalfmriprep.github.io/spinalfmriprep/)**, including:

- [Installation Guide](https://spinalfmriprep.github.io/spinalfmriprep/setup/)
- [Quickstart Tutorial](https://spinalfmriprep.github.io/spinalfmriprep/quickstart/)
- [Processing Methods](https://spinalfmriprep.github.io/spinalfmriprep/methods/)
- [API Reference](https://spinalfmriprep.github.io/spinalfmriprep/reference/)

## License

SpinalfMRIprep is licensed under the **Apache License 2.0**. See [LICENSE](LICENSE) for details.

## Citation

If you use SpinalfMRIprep in your research, please cite:

```bibtex
@software{spinalfmriprep,
  title = {SpinalfMRIprep: Robust preprocessing for human spinal cord fMRI},
  author = {SpinalfMRIprep Developers},
  year = {2026},
  url = {https://github.com/spinalfmriprep/spinalfmriprep}
}
```

See also [How to Cite](https://spinalfmriprep.github.io/spinalfmriprep/cite/) for related tools (SCT, PAM50) that should be cited.

## Contributing

We welcome contributions! See [CONTRIBUTING.md](docs/contributing.md) for guidelines.

## Acknowledgements

SpinalfMRIprep builds upon the excellent [Spinal Cord Toolbox](https://spinalcordtoolbox.com/) and is inspired by [fMRIPrep](https://fmriprep.org/).
