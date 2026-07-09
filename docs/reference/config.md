# Configuration

SpinePrep's behaviour is governed by a set of **policy files** — one YAML file
per pipeline step, kept in the `policy/` directory of the repository. Each file
holds that step's knobs: algorithm choices, numeric thresholds, and the
pass/warn/fail QC bands. The pipeline reads these at run time; you configure
SpinePrep by editing them (or, for one knob, overriding it on the command line —
see `--smoothing-sigma-mm` in the [CLI Reference](cli.md)).

Design intent (see the project's development principles):

- **Literature-grounded defaults.** Most knobs carry an inline comment citing
  the paper or reference pipeline the value comes from. The intent is to *tune
  knobs, not reinvent algorithms* — the shipped defaults are the values the
  pipeline has been tested with.
- **One truth gate per step.** Each file has a `qc_thresholds:` block defining
  the step's own pass/warn/fail bands, independent of downstream steps.
- **Versioned in git.** The policy YAML is committed. Each file starts with a
  `version:` integer.

!!! info "Reproducibility receipt"
    At the group step (S10), the reproducibility receipt records a SHA-256 hash
    of every policy YAML (`policy_sha256_per_step`), alongside tool versions and
    the pipeline's git SHA. Two runs with the same policy files and code produce
    the same hashes — this is how a run's exact configuration is pinned and
    re-checked. If you change a policy value, its hash changes and the receipt
    reflects it.

Common structure across the per-step files:

- `qc_thresholds:` — the step's pass/warn/fail bands.
- `cost_controls:` — runtime estimate and `skip_existing_pass` (skip a run that
  already passed with the same code hash).
- `reproducibility:` — `strict` (fix random seeds / single-thread when true) and
  `capture_provenance`.

The rest of this page lists each policy file, what it controls, and its notable
knobs. Only keys that actually exist in the files are listed. For the structure
of the QC JSON each step emits, see the [Schemas Reference](schemas.md).

---

## Per-step policy files

### `policy/S2_anat_cordref.yaml` — anatomical cord reference

Selects the anatomical image, segments the cord, labels vertebrae, and registers
to the PAM50 template.

- `selection.preference` — ordered list of anatomical contrasts to use as the
  primary anat (default `T2w`, then `T1w`); `secondary_cordref_preference`
  (default `T2star`) supplies a matched-contrast reference for S5/S6 when present.
- `megre_synthesis` — how multi-echo MEGRE is combined into a single T2* image
  (`echo_combine: rms`, `run_combine: mean`).
- `standardize.orientation` — reorient to `RPI`.
- `segmentation.cord_method` — cord segmentation method (`contrast_agnostic` =
  `sct_deepseg` spinal cord).
- `labeling.method` — vertebral labeling (`totalspineseg`) with
  `qc_thresholds` (minimum vertebral levels, coverage ratio, inter-level gap,
  confidence).
- `registration.template` — `PAM50`; `prefer_rootlets`.
- `qc_thresholds` — `pam50_cord_dice_pass_min` (0.80) / `warn_min` (0.60);
  `min_vertebral_levels` (5). The step-local truth metric is 3-D cord Dice
  between the PAM50 cord warped to native anat space and the native segmentation.

### `policy/S2B_func_denoise.yaml` — optional thermal-noise denoising

MP-PCA denoising (Veraart 2016; MRtrix3 `dwidenoise`) of the raw 4-D BOLD.

- `enabled` — **`false` by default.** When off, S2B passes the raw BOLD through
  unchanged. It must run before any interpolation, so it sits at the head of the
  functional chain.
- `nthreads` — `dwidenoise` thread pool (default 1).
- `extent` — denoising patch size; `null` lets `dwidenoise` auto-size.
- `qc_thresholds` — `warn_residual_corr` / `fail_residual_corr` (structure
  leaking into the removed noise means over-denoising); `warn_min_tsnr_gain_pct`.

### `policy/S3_func_init_and_crop.yaml` — functional reference and crop

Builds the functional reference, flags motion-corrupted frames, and crops to the
cord.

- `dummy.drop_count` — initial unstable frames to drop (default 4).
- `coarse_reference.method` / `robust_reference.method` — reference aggregation
  (`median`).
- `func_localization` — cord localization on the functional reference
  (`deepseg`), with a caudal-completion refinement and a drift gate to reject
  brain/airway contamination.
- `outlier_gating` — Tukey P75 + 1.5·IQR cutoff (`iqr_multiplier`) on cord DVARS
  and DVARS-ref (`metrics`); `min_good_frames`.
- `crop.mask_diameter_mm` — cord-focused crop cylinder diameter (default 60 mm),
  `dilate_xyz`, `min_z_slices`.
- `qc_thresholds` — `outlier_fraction_pass_max` (0.20) / `warn_max` (0.40),
  after Kaptan 2023. Outlier fraction is a soft WARN gate; it never fails a run.

### `policy/S4_func_motion_correction.yaml` — motion correction

- `motion_correction.mode` — `3d+2d` (default), `3d`, or `2d`. `3d+2d` is a
  coarse bulk in-plane correction (`stage1_coarse`, FLIRT 2-DOF) followed by
  slice-wise correction (`stage2_slicereg`, `sct_fmri_moco`).
- `stage2_slicereg` — `poly_order`, `metric` (`MeanSquares`), `iterations`,
  `smooth`.
- `z_shift_correction` — optional inter-run Z-shift correction (off by default).
- `qc_thresholds` — `fd_threshold_mm` (0.5, Power 2012 per-frame censoring
  threshold); `max_high_motion_fraction` (0.50, FAIL when a majority of frames
  are high-motion); `min_tsnr`; WARN bands (`warn_high_motion_fraction`,
  `warn_fd_mm`, `warn_tsnr`). A run is dropped on the *fraction* of high-motion
  frames, never on a single frame.

### `policy/S5_func_distortion_correction.yaml` — distortion correction

Mode is chosen automatically per run from the S1 inventory: `topup` (when a
reversed phase-encode EPI pair exists) with an image-based `syn` fallback.

- `distortion_correction.prefer_mode` — `auto` (default), or force `topup`/`syn`.
- `topup` — `config` (`b02b0_1.cnf`, tolerant of odd dimensions), `apply_method`
  (`jac`).
- `syn` — ANTs SyN knobs (`metric`, `transform`, `shrink`, `smoothing`).
- `qc_thresholds` — CoSpine-style geometric gates (Wei 2025): per-slice cord
  Dice (`pass_dice_min` 0.50 / `warn_dice_min` 0.30) and A–P cord-centerline
  displacement (`pass_displacement_max_mm` 1.0 / `warn` 2.0);
  `cord_roi_max_level` restricts the metric to cervical levels;
  `syn_displacement_distortion_limited` lets a fieldmap-free SyN run that misses
  the displacement ceiling but still registered be flagged WARN rather than FAIL.

### `policy/S6_func_to_anat_registration.yaml` — functional-to-anatomical

Segmentation-driven, contrast-invariant registration (Kaptan 2023 lineage):
three slice-wise steps — `centermassrot`, `columnwise`, `bsplinesyn`.

- `registration.step1/step2/step3` — the three registration stages and their
  parameters; `anat_crop` (dilated cord crop); `interpolation` (`spline`).
- `qc_thresholds` — cord Dice is the truth metric: `pass_dice_min` (0.85,
  Cohen-Adad 2014 / De Leener 2017 band), `pass_dice_min_syn_fallback` (0.80),
  `fail_dice_below` (0.65). HD95 and centerline-drift thresholds are
  observability-only (WARN, never FAIL).

### `policy/S7_template_normalization.yaml` — PAM50 normalization

Composes the S2 anat↔PAM50 and S6 bold↔anat warps; never resamples the 4-D BOLD
into template space (Eippert 2017 lineage).

- `template.name` — `PAM50`; `reference_modality` (`T2s`).
- `refinement.enable` — extra bsplinesyn refinement, **off by default** (adds
  noise without gain given S6's registration).
- `atlas` — which PAM50 masks/atlas to warp into native func (`PAM50_cord`,
  `_csf`, `_wm`, `_gm`, `_spinal_levels`).
- `interpolation` — per-output-type resampling (`spline` for BOLD, `nn` for
  masks/labels, `linear` for anat).
- `qc_thresholds` — primary gate is the **median per-level cord Dice**
  (`per_level_pass_min` 0.90, coverage-independent), with a `per_level_broken_below`
  guard; whole-volume `pass_dice_min` (0.80) / `fail_dice_below` (0.65) is the
  legacy fallback.

### `policy/S8_confounds.yaml` — confounds and physiological regressors

Extracts confound regressors into a BIDS `desc-confounds_timeseries.tsv`. Five
families; it never regresses them out (the analyst's GLM owns that). Toggle each
family on/off.

- `motion` — FD outlier threshold (`fd_outlier_threshold_mm` 0.5, Power 2014
  lenient scrub) and Tukey IQR cutoffs for DVARS/refRMS.
- `csf_slicewise` — slice-wise CSF aCompCor (Behzadi 2007) via FSL `fslmeants`,
  `n_components` (5 PCs/slice), `mask_source`.
- `retroicor` — FSL PNM RETROICOR (auto-disabled when physio is absent):
  `cardiac_order`, `respiratory_order`, `interaction_order`, `aggregation`,
  `hr_rvt_enabled`.
- `cosine` — DCT high-pass basis (`cutoff_hz` 0.01, = 1/100 s; Kaptan 2023 cord
  standard).
- `spinalcompcor` — SpinalCompCor noise regressors (Hemmerling 2025):
  `dilation_mm`, `component_selection` (`fixed_n` default), `fixed_n_components`.
- `qc_thresholds` — design-matrix `condition_number` bands; outlier-fraction
  bands (soft WARN only).

### `policy/S9_primary_functional_derivatives.yaml` — final derivatives

Produces the final preprocessed 4-D BOLD (native and PAM50), tSNR references, and
per-vertebral-level tSNR. Cord-aware anisotropic smoothing; no high-pass on BOLD
(the S8 cosine basis handles that); no confound regression.

- `smoothing.method` — `sct_cord` (`sct_smooth_spinalcord`) or
  `gaussian_inplane`; `sigma_mm` — kernel widths in mm, order R-L, A-P, S-I
  (default `[1.0, 1.0, 5.0]`, Eippert 2017 / CoSpine convention). This is the
  knob `--smoothing-sigma-mm` overrides.
- `pam50_4d_output` — whether to emit the 4-D BOLD in PAM50 space
  (`enabled`, `emit_unsmoothed`, `fov_pad_vox`, `parallel_emit`).
- `per_level_tsnr.enabled` — per-vertebral-level tSNR TSV.
- `fwhm_estimate` — verify achieved smoothness against the requested kernel
  (tolerance bands).
- `qc_thresholds` — post/pre tSNR ratio (`pass_tsnr_ratio_min` 1.5), median
  in-cord tSNR (`pass_median_in_cord_tsnr` 5.0), pre/post cord Dice.

### `policy/S10_qc_aggregation_and_release.yaml` — aggregation and release

Aggregates S1–S9 outputs into release deliverables (group level). Toggle each
deliverable on/off.

- `aggregation` — per-subject HTML reports (`per_subject_html`, with the chosen
  thumbnail per step), the group dashboard (`group_dashboard.metric_distributions`
  — which per-step metrics get a boxplot), `metrics_index`, `run_inventory`.
- `cohort_views` — vertebral-level coverage matrix and a per-level tSNR heatmap.
- `publication` — `reproducibility_receipt` (which packages to capture),
  `citation_cff`, `references_bib`, `dataset_description`, `participants_tsv`
  (with inclusion-flag thresholds), `methods_manifest`.
- `compliance.release_report` — the top-level `release_report.html` index.
- `qc_thresholds` — minimum subject-report fraction and maximum
  missing-QC/sidecar fractions.

---

## Dataset registry

`policy/datasets.yaml` is a manifest of registered datasets (key, title, source,
counts, modalities, and `intended_use` — e.g. `v1_validation`). The per-step
interface's `--scope`/`--dataset-key` options resolve keys against it (see the
[CLI Reference](cli.md)). It is validated against `policy/datasets.schema.yaml`
by the loader in `src/spineprep/policy/datasets.py`. The standard BIDS-App
interface does **not** require a dataset to be registered here — it runs any
dataset ad hoc from `bids_dir`.
