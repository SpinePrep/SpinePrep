# Changelog

All notable changes to SpinePrep are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- Renamed the project from **SpinalfMRIprep** to **SpinePrep** across the code,
  container recipe, docs, package, and public GitHub/website presence.
- Corrected the FSL distribution rationale in the README, `NOTICE`, and docs:
  FSL *may* be redistributed under its non-commercial terms; SpinePrep ships a
  build recipe **by choice** to keep its Apache-2.0 distribution unencumbered.

### Fixed
- S2.2 TotalSpineSeg reportlet: the C1–TX vertebral level labels were vertically
  mirrored (C1 printed at the bottom); they now read top-to-bottom in correct
  anatomical order, aligned with the vertebral bodies.

### Added
- Project governance and community files: `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`
  (Contributor Covenant 2.1), `GOVERNANCE.md`, `SECURITY.md`, issue/PR templates.
- Publishing workflows: PyPI release via OIDC Trusted Publishing, an opt-in GHCR
  container build, and a conda-forge recipe.
- Versioned documentation via `mike`.

## [1.0.0] - 2026-07-08

Initial public release of the pipeline (as SpinalfMRIprep). A fully automated,
BIDS-App, container-reproducible preprocessing pipeline for human spinal-cord
fMRI with per-vertebral-level quality control. Steps S1–S10: input verification,
anatomical cord reference, functional reference and cord-focused crop, motion
correction, distortion correction, functional→anatomical registration, PAM50
template normalization, confounds and physiological regressors, GLM-ready
derivatives, and QC aggregation with a release report.

[Unreleased]: https://github.com/SpinePrep/SpinePrep/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/SpinePrep/SpinePrep/releases/tag/v1.0.0
