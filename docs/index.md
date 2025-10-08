# SpinePrep

<div class="hero">
  <h1>Spinal Cord Preprocessing Pipeline</h1>
  <p class="lead">
    A robust, BIDS-compliant preprocessing pipeline for spinal cord neuroimaging data.
    Built for reproducibility, transparency, and scientific rigor.
  </p>
</div>

[➡️ Live Docs](https://spineprep.github.io/){ .md-button .md-button--primary }

<!-- Badges -->

[![Docs Live](https://img.shields.io/badge/docs-live-blue)](https://spineprep.github.io/)
[![Docs CI](https://github.com/spineprep/SpinePrep/actions/workflows/docs.yml/badge.svg)](https://github.com/spineprep/SpinePrep/actions/workflows/docs.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-green)](https://github.com/spineprep/SpinePrep/blob/main/LICENSE)

## Why SpinePrep?

SpinePrep provides a comprehensive preprocessing pipeline specifically designed for spinal cord neuroimaging data. Unlike generic brain preprocessing tools, SpinePrep understands the unique challenges of spinal cord imaging:

- **Spinal cord-specific preprocessing**: Optimized for the anatomical and physiological characteristics of spinal cord data
- **BIDS compliance**: Full support for the Brain Imaging Data Structure standard
- **Quality control**: Comprehensive QC metrics including FD, DVARS, and aCompCor
- **Reproducible science**: Version-controlled, containerized, and fully documented

## Quick Start

Get started with SpinePrep in three simple steps:

### 1. Install

```bash
pip install spineprep
```

### 2. Configure

Create a minimal configuration file:

```yaml
# config.yaml
bids_dir: /path/to/bids
output_dir: /path/to/output
```

### 3. Run

```bash
spineprep config.yaml
```

## Sample Report

See what SpinePrep produces:

<div class="grid cards" markdown>

-   :material-chart-line:{ .lg .middle } **Quality Control**

    ---

    Comprehensive QC metrics including motion, signal quality, and preprocessing artifacts

    [:octicons-arrow-right-24: View QC Report](user-guide/qc.md)

-   :material-graph:{ .lg .middle } **Processing Pipeline**

    ---

    Transparent, versioned processing steps with full provenance tracking

    [:octicons-arrow-right-24: View DAG](user-guide/usage.md#processing-pipeline)

-   :material-database:{ .lg .middle } **BIDS Derivatives**

    ---

    Standardized outputs following BIDS-Derivatives specification

    [:octicons-arrow-right-24: View Outputs](user-guide/outputs.md)

</div>

## What's new

See recent changes and release notes in the [Changelog](CHANGELOG.md).

## Features

### :material-check-circle:{ .green } **Spinal Cord Optimized**

Preprocessing steps specifically designed for spinal cord anatomy and physiology, including spinal cord-specific motion correction and registration.

### :material-check-circle:{ .green } **BIDS Compliant**

Full support for the Brain Imaging Data Structure standard, ensuring compatibility with the broader neuroimaging ecosystem.

### :material-check-circle:{ .green } **Quality Control**

Comprehensive QC metrics including framewise displacement (FD), DVARS, aCompCor, and censor masks with detailed reporting.

### :material-check-circle:{ .green } **Reproducible**

Version-controlled processing with full provenance tracking, containerized execution, and transparent parameter reporting.

## Getting Help

- 📖 [User Guide](user-guide/usage.md) - Learn how to use SpinePrep
- 🔧 [Configuration Reference](reference/config.md) - Complete configuration options
- 🐛 [Report Issues](https://github.com/spineprep/spineprep/issues) - Found a bug?
- 💬 [Discussions](https://github.com/spineprep/spineprep/discussions) - Ask questions

## Citation

If you use SpinePrep in your research, please cite:

```bibtex
@software{spineprep2024,
  title={SpinePrep: Spinal Cord Preprocessing Pipeline},
  author={SpinePrep Contributors},
  year={2024},
  url={https://github.com/spineprep/spineprep}
}
```
