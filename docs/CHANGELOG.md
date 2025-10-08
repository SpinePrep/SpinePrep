# Changelog

## Unreleased

### Added

* `spineprep doctor`: environment diagnostics with JSON artifact and schema validation.
* Strict configuration system: defaults + YAML + CLI precedence with JSON Schema validation.
* `spineprep run --print-config` to inspect resolved config.
* BIDS ingest and manifest cache with hashing and modality inference; integrated into `spineprep run`.
* Motion metrics: FD (framewise displacement) and DVARS computation per functional run with confounds TSV and QC plots.
