# Changelog

All notable changes to SpinePrep are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses
calendar versioning (CalVer, `YY.MINOR.PATCH`), matching the NiPreps ecosystem
(fMRIPrep, MRIQC).

## [Unreleased]

_Nothing yet._

## [26.1.0] - 2026-10-27

The main user-facing changes since 26.0.0.

### Defaults that changed
- S5: without a field map the default is now `none` (no distortion correction), the cord field's own default,
  not SyN; `none` is a first-class passthrough with no reportlet.
- S9: smoothing is off by default and no template-space 4D series is written; the primary output is the
  unsmoothed `desc-preproc_bold`.
- S4/S8: motion no longer rejects runs, and no absolute FD threshold ships; censoring uses intensity metrics.
- S8: SpinalCompCor is off by default.

### New
- Named settings presets: `SPINEPREP_PRESET=<name>` lays `policy/presets/<name>/` over the defaults.
  Shipped: `cospi` (MP-PCA on, distortion correction none, smoothing on). The receipt records the preset.
- `SPINEPREP_ONLY_SUBJECTS` limits S6-S9 to some subjects, so several invocations can run side by side.
- `SPINEPREP_T2LINK_ROOT`: S7 composes a T2*-to-T2w link warp when S6 registers to a T2* and S2 to a T2w.
- S7 exports the native-space atlas, vertebral levels and rootlet levels.
- S6 reports a cord-restricted mutual-information metric, independent of the segmentation it registers.

### Fixed
- S9: the residual-smoothness (FWHM) estimator was inverted and measured the wrong image.
- S2: a short interior gap in the rootlet levels is interpolated instead of crashing or dropping levels.
- S1-S3: the top cord slice was lost. S3: a failed crop was marked PASS; cord discovery uses EPISeg (`sc_epi`).
- S8: physiological recordings are aligned to the BOLD after the dummy volumes are dropped (RETROICOR phase was
  wrong); an empty or short CSF eigenvector file is refused; a pulse trace whose beats were counted twice is detected and rebuilt with the pulse-oximeter trigger option.
- S1: complete files are no longer flagged as truncated; truncated input is detected by decompressing.
- S9 refuses a malformed `SPINEPREP_SIGMA_MM` instead of ignoring it.
- S2 and S7 run the SCT tools that drop working files (`sct_register_to_template`, `sct_concat_transfo`) in
  the run's own folder: subjects run side by side no longer share those files, and a read-only working directory no
  longer makes the rootlet registration fall back to discs.
- Container: MRtrix3 `dwidenoise` 3.0.4 is included (presets that turn S2B on failed without it); runs as a
  non-root user (`docker run --user`) work; SCT records its real version instead of `git-unknown`.
- Citations and attributions in the methods text and documentation corrected (FD threshold, EPISeg, SpinalCompCor).

### Documentation
- Every step opens with what it does, its input, output, QC picture and usage; the README has a step table and a
  settings section.

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

[Unreleased]: https://github.com/SpinePrep/SpinePrep/compare/v26.1.0...HEAD
[26.1.0]: https://github.com/SpinePrep/SpinePrep/releases/tag/v26.1.0
[26.0.0]: https://github.com/SpinePrep/SpinePrep/releases/tag/v26.0.0
