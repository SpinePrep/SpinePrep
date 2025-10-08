# API Reference

This page documents the SpinePrep API, including all functions and classes available in the `workflow/lib` modules.

## confounds

Confounds computation utilities for SpinePrep.

### Functions

#### `read_motion_params(tsv_path)`

Read motion parameters from TSV file.

#### `compute_fd_from_params(params, tr_s)`

Compute Framewise Displacement (Power) from motion parameters.

#### `compute_dvars(bold_path, mask_path)`

Compute DVARS from BOLD data.

#### `assemble_confounds(fd, dvars, extra)`

Assemble confounds DataFrame from FD and DVARS.

#### `write_confounds_tsv_json(df, out_tsv, out_json, meta)`

Write confounds TSV and JSON files.

#### `build_censor(fd, dvars, cfg) -> Dict`

Build censor vector based on FD and DVARS thresholds with contiguity rules.

#### `append_censor_columns(df, censor_dict)`

Append censor columns to confounds DataFrame.

#### `load_bold_and_apply_crop(bold_path, crop_json)`

Load BOLD data and apply temporal cropping if specified.

#### `extract_mask_timeseries(bold, mask, standardize)`

Extract time series from BOLD data using a mask.

#### `acompcor_pcs(ts, n_components, highpass_hz, tr_s, detrend, standardize)`

Extract principal components from time series data.

#### `append_acompcor(df, pcs_dict)`

Append aCompCor principal components to confounds DataFrame.


## crop

Temporal crop detection and IO utilities.

### Functions

#### `detect_crop(confounds_tsv, bold_path, cord_mask, opts)`

Detect temporal crop indices using robust z-statistics on cord ROI mean signal.

#### `write_crop_json(out_path, info)`

Write crop information to JSON file.

#### `read_crop_json(path)`

Read crop information from JSON file.

#### `crop_sidecar_path(bold_path, deriv_root) -> str`

Generate crop sidecar path from BOLD path and derivatives root.


## deriv

### Functions

#### `derive_paths(row, deriv_root)`

Given a manifest row with 'bold_path', compute absolute derivative paths

#### `stage_file(src, dst)`

Stage file into derivatives: prefer hardlink, else copy. Create parent dirs.


## provenance

### Functions

#### `write_prov(target, step, inputs, params, tools)`

No documentation available


## qc

Quality control and reporting utilities for SpinePrep.

### Functions

#### `subjects_from_manifest(manifest_tsv)`

Extract unique subject IDs from manifest_deriv.tsv.

#### `rows_for_subject(manifest_tsv, sub)`

Get all rows for a specific subject from manifest_deriv.tsv.

#### `read_confounds_tsv(tsv)`

Read confounds TSV and return as dict of column_name -> list of values.

#### `compute_fd(conf)`

Compute Framewise Displacement (Power) from motion parameters.

#### `read_motion_params(tsv)`

Read motion parameters from motion correction TSV file.

#### `compute_fd_from_motion_params(motion_params_tsv)`

Compute FD from motion parameters TSV file.

#### `compute_dvars(conf)`

Compute DVARS from confounds data.

#### `plot_series(out_png, series, title, ylabel, censor)`

Create a time series plot with optional censor overlays and save as PNG.

#### `plot_ev_series(out_png, ev_data, title)`

Plot explained variance for aCompCor components.

#### `module_decisions(cfg)`

Extract module decisions from config.

#### `collect_provenance(entries)`

Collect provenance file paths from manifest entries.

#### `render_subject_report(sub, manifest_tsv, cfg, deriv_root) -> str`

Generate HTML report for a subject.

#### `generate_methods_boilerplate(cfg, sub, n_runs) -> str`

Generate methods boilerplate text.

#### `get_registration_status(manifest_tsv, sub)`

No documentation available

#### `collect_registration_files(manifest_tsv, sub)`

No documentation available


## registration

Registration utilities for SpinePrep.

### Functions

#### `derive_inputs(row, bids_root)`

Derive input paths for registration from a manifest row.

#### `derive_outputs(row, deriv_root)`

Derive output paths for registration from a manifest row.

#### `mask_paths(row)`

Get mask paths for aCompCor from a manifest row.

#### `write_prov(path, meta)`

Write provenance metadata to a .prov.json file.


## samples

### Functions

#### `assign_motion_groups(rows, mode, require_same)`

Assign motion_group keys to rows based on grouping mode and requirements.

#### `build_samples(discover_json, bids_root, out_tsv) -> int`

Create a normalized per-run manifest for the workflow.

#### `first_row(samples_tsv) -> dict`

Return the first non-header row as a dict. Raises FileNotFoundError or ValueError.

#### `rows(samples_tsv)`

No documentation available

#### `row_by_id(samples_tsv, idx) -> dict`

No documentation available


## targets

Path utilities for SpinePrep targets.

Pure string-only functions for composing derivative paths from BIDS entities.
No global imports, no IO operations - unit testable.

### Functions

#### `bold_fname(sub, ses, task, run) -> str`

Generate BOLD filename from BIDS entities.

#### `deriv_path(deriv_root, sub, ses, modality, fname) -> str`

Generate derivative path from BIDS entities.

#### `motion_bold_path(deriv_root, sub, ses, task, run) -> str`

Generate motion-corrected BOLD path.

#### `confounds_tsv_path(deriv_root, sub, ses, task, run) -> str`

Generate confounds TSV path.

#### `confounds_json_path(deriv_root, sub, ses, task, run) -> str`

Generate confounds JSON path.

#### `mppca_bold_path(deriv_root, sub, ses, task, run) -> str`

Generate MP-PCA denoised BOLD path.

#### `crop_json_path(deriv_root, sub, ses, task, run) -> str`

Generate crop JSON path.


## Summary

The SpinePrep API provides the following modules:

- **confounds**: 11 functions, 0 classes
- **crop**: 4 functions, 0 classes
- **deriv**: 2 functions, 0 classes
- **provenance**: 1 functions, 0 classes
- **qc**: 15 functions, 0 classes
- **registration**: 4 functions, 0 classes
- **samples**: 5 functions, 0 classes
- **targets**: 7 functions, 0 classes
