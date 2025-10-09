# Changelog

All notable changes to SpinePrep will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2025-10-08

### Added

- **CLI scaffold** with `spineprep version|doctor|run` commands
  - `--print-config` flag to emit resolved configuration
  - `-n/--dry-run` flag for workflow validation
  - Automatic DAG export to `out/provenance/dag.svg`
- **Environment diagnostics** (`spineprep doctor`)
  - Color-coded table (green/yellow/red) for SCT, PAM50, Python deps
  - JSON artifact output (`doctor-TIMESTAMP.json`)
  - `--strict` mode to treat warnings as failures
- **Confounds computation** (FD, DVARS, censoring)
  - Power FD from 6 rigid-body motion parameters
  - Standardized DVARS computation
  - Frame censoring with threshold, padding, and contiguity rules
  - aCompCor support (up to 6 components per tissue: cord/WM/CSF)
  - BIDS-compliant TSV and JSON sidecar outputs
- **Registration** (SCT-based, MVP)
  - Minimal EPI→PAM50 registration wrapper
  - Conservative defaults (rigid + affine only, no deformable)
  - SSIM/PSNR quality thresholds (≥0.90, ≥25 dB)
  - Provenance logging with SCT version capture
- **BIDS-Derivatives compliance**
  - Complete directory layout and naming conventions
  - JSON sidecars with `GeneratedBy`, `Sources`, `Parameters`
  - `dataset_description.json` at derivatives root
  - Full provenance snapshot with environment and tool versions
- **Quality Control (QC)**
  - Self-contained HTML reports (no CDN, no JS)
  - Index page with environment check and subject list
  - Per-subject pages with motion summaries
  - Inline CSS for offline viewing
  - DAG visualization links
- **End-to-End Testing**
  - Tiny BIDS fixture (1 subject, 20 volumes, 32×32×16 spatial)
  - CI smoke test workflow with artifact uploads
  - QC bundle zip (30-day retention)
- **Documentation**
  - User guides for all components
  - API reference (auto-generated)
  - Configuration reference (auto-generated)
  - JSON schemas for validation
- **CI/CD**
  - Lint (ruff), format (snakefmt), spell (codespell)
  - Unit and integration tests
  - E2E smoke test on tiny dataset
  - Artifact uploads (QC, DAG, logs, doctor JSON)

### Changed

- Config precedence: CLI args > YAML > defaults
- Workflow imports: sys.path setup for `workflow.lib` modules
- Test coverage: 80+ tests across unit/integration/e2e

### Fixed

- DAG export filters snakemake messages before dot conversion
- PAM50 detection handles missing files gracefully
- Header consistency (qform/sform) preserved in registration

### Infrastructure

- Python 3.9+ required
- Dependencies: numpy, pandas, scipy, nibabel, scikit-learn, scikit-image
- Test framework: pytest with fixtures
- Workflow: Snakemake 8+
- Docs: MkDocs Material with strict mode

## [Unreleased]

### Added

- **[A1] CLI skeleton and doctor with JSON snapshot**
  - Entry point `spineprep` with subcommands: `run`, `doctor`, `version`
  - `doctor` command with complete environment diagnostics
  - JSON output with `--json` flag (file path or `-` for stdout)
  - Required JSON fields: `python.version`, `spineprep.version`, `platform`, `packages`, `sct.present/version/path`, `pam50.present`, `disk.free_bytes`, `cwd_writeable`, `tmp_writeable`
  - Non-zero exit code when SCT is missing
  - Remediation text for missing SCT (Docker/Apptainer or local install)
  - Disk space and write permission checks

### Planned

- Nonlinear registration options
- tCompCor and physiological regressors
- Interactive QC with motion plots
- Performance profiling and caching
- Container packaging (GHCR)
