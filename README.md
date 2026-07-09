<p align="center">
  <img src="logo.svg" alt="SpinePrep" width="400">
</p>

<p align="center">
  <strong>Robust preprocessing for human spinal cord fMRI</strong>
</p>

<p align="center">
  <a href="https://github.com/SpinePrep/SpinePrep/actions/workflows/ci.yml"><img src="https://github.com/SpinePrep/SpinePrep/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://github.com/SpinePrep/SpinePrep/releases"><img src="https://img.shields.io/badge/version-1.0.0-blue" alt="Version"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.10%20|%203.11%20|%203.12-blue" alt="Python"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-green" alt="License"></a>
  <a href="https://spineprep.com/"><img src="https://img.shields.io/badge/docs-online-brightgreen" alt="Documentation"></a>
  <a href="https://neurostars.org/tag/spineprep"><img src="https://img.shields.io/badge/help-NeuroStars-orange" alt="NeuroStars"></a>
  <!-- DOI badge added after the first Zenodo-archived release:
  <a href="https://doi.org/10.5281/zenodo.XXXXXXX"><img src="https://zenodo.org/badge/DOI/10.5281/zenodo.XXXXXXX.svg" alt="DOI"></a> -->
</p>

---

## About

**SpinePrep** is an open-source pipeline for preprocessing spinal cord functional MRI data. Given a BIDS-compliant dataset, SpinePrep produces **GLM-ready derivatives** with comprehensive quality control outputs.

SpinePrep is designed with validity-first principles: spinal cord measurement robustness comes before speed or convenience. Every processing step emits machine-readable QC and visual reportlets for transparent, auditable preprocessing.

```
                              SpinePrep Pipeline
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
    │   │ S6: Func→    │◀───│ S5: Distortion│◀──│ S4: Motion Correction    │  │
    │   │    Anat Reg  │    │    Correction │   │     (cord-aware)         │  │
    │   └──────────────┘    └──────────────┘    └──────────────────────────┘  │
    │          │                                                              │
    │          ▼                                                              │
    │   ┌──────────────┐    ┌──────────────┐    ┌──────────────────────────┐  │
    │   │ S7: Template │───▶│ S8: Confounds│───▶│ S9: Primary Derivatives  │  │
    │   │    Warp      │    │    + Physio  │    │     (native + PAM50)     │  │
    │   └──────────────┘    └──────────────┘    └──────────────────────────┘  │
    │                                                   │                     │
    │                                                   ▼                     │
    │                                            ┌──────────────────────────┐  │
    │                                            │ S10: QC Aggregation +    │  │
    │                                            │      Release             │  │
    │                                            └──────────────────────────┘  │
    │                                                   │                     │
    │                                                   ▼                     │
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

### Container (recommended) — build it yourself

SpinePrep ships as a **build recipe**, not a prebuilt image — a deliberate
choice. The container installs FSL, which is free for academic and non-commercial
use but carries non-commercial license terms. By having you build the image
locally instead of redistributing one that bundles FSL, SpinePrep's own Apache-2.0
distribution stays unencumbered by FSL's terms, and you obtain FSL directly under
its own license. Build it locally (Docker or, for HPC, convert to Apptainer):

```bash
git clone https://github.com/SpinePrep/SpinePrep.git
cd SpinePrep
docker build -f Dockerfile.spineprep \
  --build-arg GIT_SHA=$(git rev-parse HEAD) \
  --build-arg GIT_DESCRIBE=$(git describe --always --tags) \
  -t spineprep:1.0.0 .

docker run --rm -v /path/to/bids:/bids:ro -v /path/to/out:/out \
  spineprep:1.0.0 /bids /out participant
```

See the [quickstart](docs/quickstart.md) for the Apptainer invocation and options.

### Local installation (advanced)

The Python package installs with `pip install .` from the repo, but the pipeline
also needs **SCT, FSL, and ANTs** on your `PATH` (the container installs these for
you). Not published to PyPI yet.

```bash
git clone https://github.com/SpinePrep/SpinePrep.git
cd SpinePrep && pip install .
```

## Quick Start

```bash
spineprep /path/to/bids /path/to/output participant \
    --participant-label sub-01
```

For detailed usage, configuration options, and tutorials, see the **[Documentation](https://spineprep.com/)**.

## Documentation

Full documentation is available at **[spineprep.com](https://spineprep.com/)**, including:

- [Quickstart](https://spineprep.com/quickstart/)
- [Install & Use](https://spineprep.com/tutorial/)
- [Processing Methods](https://spineprep.com/methods/overview/)
- [API Reference](https://spineprep.com/reference/api/)

## License

SpinePrep is licensed under the **Apache License 2.0**. See [LICENSE](LICENSE) for details.

## Citation

If you use SpinePrep in your research, please cite:

```bibtex
@software{spineprep,
  title   = {SpinePrep: a containerised BIDS-App for reproducible spinal cord fMRI preprocessing},
  author  = {Sharifi, Kiomars},
  year    = {2026},
  version = {1.0.0},
  url     = {https://github.com/SpinePrep/SpinePrep}
}
```

Please also cite the underlying tools (SCT, FSL, ANTs, PAM50) — see the
`NOTICE` file and the auto-generated methods boilerplate.

See also [How to Cite](https://spineprep.com/cite/) for related tools (SCT, PAM50) that should be cited.

## Contributing

We welcome contributions! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines,
and the [Code of Conduct](CODE_OF_CONDUCT.md). For usage questions, use the
[NeuroStars `spineprep` tag](https://neurostars.org/tag/spineprep) rather than the
issue tracker.

## Acknowledgements

SpinePrep builds upon the excellent [Spinal Cord Toolbox](https://spinalcordtoolbox.com/) and is inspired by [fMRIPrep](https://fmriprep.org/).
