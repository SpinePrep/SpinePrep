# Changelog

All notable changes to SpinePrep are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses
calendar versioning (CalVer, `YY.MINOR.PATCH`), matching the NiPreps ecosystem
(fMRIPrep, MRIQC).

## [Unreleased]

_Nothing yet._

## [26.0.0] - 2026-07-10

First public release: a fully automated, containerised BIDS-App for reproducible
preprocessing of human spinal-cord fMRI, with per-vertebral-level quality control.

### Pipeline
- Steps **S1–S10**: input verification, anatomical cord reference (SCT /
  TotalSpineSeg), functional reference and cord-focused crop, motion correction,
  distortion correction (topup / PNM with an image-based fallback),
  functional→anatomical registration, PAM50 template normalization, confounds and
  physiological regressors, GLM-ready derivatives with per-vertebral-level tSNR,
  and QC aggregation with a reproducibility receipt.

### Quality control & reproducibility
- One step-local truth metric and one diagnostic reportlet per step; subject- and
  group-level HTML reports with a reconciled attrition waterfall.
- Deterministic runs, versioned per-step policy, and a provenance receipt
  (tool + policy + git SHAs).

### Project
- Governance and community files: `CONTRIBUTING`, `CODE_OF_CONDUCT` (Contributor
  Covenant 2.1), `GOVERNANCE`, `SECURITY`, issue and pull-request templates.
- Publishing workflows: PyPI release via OIDC Trusted Publishing, an opt-in GHCR
  container build, and a conda-forge recipe.
- Documentation at [spineprep.com](https://spineprep.com).

[Unreleased]: https://github.com/SpinePrep/SpinePrep/compare/v26.0.0...HEAD
[26.0.0]: https://github.com/SpinePrep/SpinePrep/releases/tag/v26.0.0
