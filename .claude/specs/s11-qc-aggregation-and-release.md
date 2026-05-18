---
status: approved
supersedes: private/SPEC/S11_qc_aggregation_and_reports.md
---

# Scope Spec: S11 QC Aggregation + Release Readiness v2

## Objective
Aggregate S1–S10 per-step outputs into the v1 release-readiness deliverables: per-subject HTML reports, group QC dashboards, cord-novel cohort transparency views, publication & reproducibility artifacts (CITATION.cff, methods manifest, dataset_description.json, participants.tsv), and a top-level `release_report.html` index.

## Constraints
- **Read-only.** S11 walks finished `qc.json` files + per-run derivative artifacts; never re-runs upstream.
- **Deterministic.** Re-running on the same chain produces byte-identical HTML/JSON output.
- **No statistical inference.** Group-mean FC matrices and consistency maps are descriptive aggregation only — no p-values, no permutation testing (analyst territory).
- **No external dataset bundling.** Every item builds from data the chain already emits. Valošek 2024 normative comparison + CoSpine percentile reference are explicitly v1.1 (require external table bundling).
- **No `bids-validator` invocation** — verified that BIDS-Derivatives validator support is incomplete (April 2023+) and emits non-actionable noise on fMRIPrep-style derivatives. Replaced by an internal sidecar audit.
- **No new step-level QC metrics.** S11 surfaces what S1–S10 already computed; doesn't compute new ones.
- **fMRIPrep convention adopted where applicable** — CC0 boilerplate text pattern (per-step `__desc__` concatenation), per-subject HTML structure, `metrics_index.jsonl` flat table.
- Per-dataset isolation: `logs/S11_qc_aggregation_and_release/<dataset_key>/qc.json`.
- Top-level (cross-dataset) outputs land at `derivatives/spinalfmriprep/` directly, NOT under a `<dataset_key>/` prefix.

## Deliverables (14 items)

### Tier 1 — Aggregation core
1. **Per-subject HTML report** (`derivatives/spinalfmriprep/<ds>/sub-XX/sub-XX_qc_report.html`)
   - Step × run pivot, embedded reportlet thumbnails (link to existing PNGs).
   - Status badge (PASS/WARN/FAIL) per cell.
   - Failure messages inlined for any non-PASS cell.
2. **Group QC dashboard** (`derivatives/spinalfmriprep/group_qc_dashboard.html`)
   - Step × subject status heatmap (rows = subjects, cols = S2..S10, colour = status).
   - Per-step pass-rate bar chart.
   - Per-step metric boxplots (FD, tSNR, cord Dice, condition number) from `metrics_index.jsonl`.
3. **`metrics_index.jsonl`** (`derivatives/spinalfmriprep/metrics_index.jsonl`)
   - One row per (step, dataset_key, subject, session, run_id).
   - Fields: `step, dataset_key, subject, session, run_id, status, failure_message, metrics: {...}`.
4. **Run inventory** (`derivatives/spinalfmriprep/run_inventory.tsv` + `.png`)
   - subjects × runs × tasks × sessions × overall pass/warn/fail pivot.

### Tier 2 — Cord-novel cohort transparency
5. **Per-vertebral-level coverage matrix** (`derivatives/spinalfmriprep/cohort_coverage_matrix.png` + `.tsv`)
   - Rows = subject (within each dataset), cols = vertebral levels C1..T1.
   - Cell = "covered" / "partial" / "absent" based on S9 `*_desc-tsnr_per_level.tsv` row presence.
6. **Cohort cord SNR heatmap by segment** (`derivatives/spinalfmriprep/cohort_tsnr_heatmap.png` + `.tsv`)
   - Rows = subjects, cols = vertebral levels, cell colour = median in-cord tSNR post-smoothing (from S9).
7. **Cohort FC summary** (`derivatives/spinalfmriprep/cohort_fc_summary.png` + 2 TSVs)
   - **Group-mean Fisher-z matrix** across all subjects/runs (intersection of common ROIs).
   - **Consistency map** = fraction of subjects with |Fisher-z| > 0.3 per connection.
   - Both emitted as TSVs + side-by-side heatmap PNG.

### Tier 3 — Publication & reproducibility
8. **Reproducibility receipt** (`derivatives/spinalfmriprep/reproducibility_receipt.json`)
   - `sct_version`, `fsl_version`, `python_version`.
   - `package_versions`: nilearn, nibabel, scipy, numpy, pandas, matplotlib, scikit-image, scikit-learn, joblib.
   - `policy_sha256` per step (read from S2..S10's qc_metrics.json provenance).
   - `pipeline_git_sha` (current HEAD), `pipeline_git_describe` (latest tag if any).
   - `os`, `hostname`, `timestamp_utc`.
9. **`CITATION.cff` + `references.bib`** (`derivatives/spinalfmriprep/CITATION.cff` + `.../references.bib`)
   - SpinalfMRIprep self-citation (template).
   - Auto-bibliography of every methods reference the chain depends on:
     Kaptan 2023, Hemmerling 2025/2023, Eippert 2017, Brooks 2008, De Leener 2018 (PAM50), Valošek 2024 (rootlets registration), Shrout & Fleiss 1979 (ICC), Cicchetti 1994 (ICC thresholds), Marrelec 2006 (partial correlation), Dabbagh 2024, Forman 1995 (FWHM estimation), Schreiber & Schmitz 1996 (IAAFT), Behzadi 2007 (CompCor), Power 2014 (FD/DVARS).
10. **`dataset_description.json`** (`derivatives/spinalfmriprep/dataset_description.json`)
    - `Name`, `BIDSVersion: "1.10.0"`, `DatasetType: "derivative"`.
    - `GeneratedBy`: list with `Name: "SpinalfMRIprep"`, `Version`, `Container`, `Description`.
    - `SourceDatasets`: list of BIDS source datasets (from S1 qc.json `bids_root` fields).
11. **`participants.tsv` + `participants.json`** (`derivatives/spinalfmriprep/participants.tsv` + `.json`)
    - Columns: `participant_id, dataset_key, n_runs, n_sessions, n_passed, n_warn, n_failed, mean_fd_mm, median_in_cord_tsnr, max_condition_number, included_recommendation`.
    - `participants.json` sidecar describes each column (BIDS requires sidecar for non-standard columns).
12. **Methods manifest** (`derivatives/spinalfmriprep/methods_manifest.md` + `.tex` + `.html`)
    - fMRIPrep-style: one paragraph per step, citing the method, listing key parameters from the policy YAML.
    - CC0 boilerplate adapted for cord pipeline.
    - Pipeline_version + policy_SHA stamp in header.

### Tier 4 — Compliance + navigation
13. **Internal sidecar audit** (`derivatives/spinalfmriprep/sidecar_audit.json` + `.html`)
    - For each emitted `.nii.gz`: matching `.json` (where expected per family — confounds, xfm, atlas, level-tsnr, etc.).
    - For each emitted `.tsv`: header row + matching `.json` sidecar OR documented schema column.
    - NIfTI dtype + shape + affine validity sanity check.
    - Cross-check expected output paths from each step's QC `output_paths` against actual files on disk.
    - Output: count of files audited, count of missing sidecars, count of malformed NIfTIs, list of issues. Non-blocking.
14. **`release_report.html`** (`derivatives/spinalfmriprep/release_report.html`)
    - Single-page index linking items 1–13.
    - Sections: "Per-subject reports" (N links), "Cohort views" (links to group dashboard + coverage matrix + tSNR heatmap + FC summary), "Release artifacts" (CITATION.cff, methods, reproducibility), "Compliance" (sidecar audit).
    - Embedded summary stats: total subjects, total runs, pipeline version, dataset list.

### Code + policy + schema
- `src/spinalfmriprep/steps/s11/__init__.py`
- `src/spinalfmriprep/steps/s11/process.py` — all 14 generators.
- `src/spinalfmriprep/steps/s11/orchestrate.py` — global walk + per-dataset coordination.
- `src/spinalfmriprep/steps/s11/reportlets.py` — boxplots, heatmaps used in group dashboard.
- `src/spinalfmriprep/steps/s11/templates/` — Jinja-like or f-string HTML templates for per-subject report + release_report + methods manifest.
- `src/spinalfmriprep/S11_qc_aggregation_and_release.py` (CLI re-export).
- `policy/S11_qc_aggregation_and_release.yaml`
- `schemas/qc_S11_qc_aggregation_and_release.schema.json`

### Spec housekeeping
- Mark `private/SPEC/S11_qc_aggregation_and_reports.md` → `superseded`.

## Inputs
- All `logs/S{N}_*/<dataset>/qc.json` files for N in 1..10 (walked via chain symlinks).
- Per-run derivative artifacts:
  - S9: `*_desc-tsnr_per_level.tsv`, `*_desc-tsnr_native.nii.gz`.
  - S10: `*_desc-hemicord_pearson_connectivity.tsv`, `*_desc-hemicord_fisherz_connectivity.tsv`.
  - S2..S10 figures: `derivatives/.../figures/*_desc-S{N}_*.png` (linked from per-subject HTML).
- S1 BIDS source dataset paths (for `SourceDatasets` field).
- Policy SHAs from per-step `qc_metrics.json` `provenance.policy_sha256`.
- Tool versions: subprocess `sct_version`, `fslversion`, `importlib.metadata.version(*)`.
- Pipeline Git SHA: `git rev-parse HEAD` from the project root.

## Success Criteria
- **PASS**: all 14 deliverable artifacts emitted; `dataset_description.json` passes BIDS-spec field check (DatasetType, GeneratedBy); `CITATION.cff` parses (`cffconvert --validate` if available); ≥ 80% per-subject reports produced relative to expected subject count.
- **WARN**: 50–80% per-subject reports OR > 5% missing per-step qc.json OR sidecar audit reports > 10% missing sidecars.
- **FAIL**: < 50% per-subject reports OR `release_report.html` not emitted OR `dataset_description.json` malformed.

## Acceptance criteria (v1)
1. All 14 items emit output on the reg chain (11 runs across 5 datasets).
2. `release_report.html` opens in a browser and successfully links the 13 other artifacts (each link resolves to a real file).
3. `dataset_description.json` validates against BIDS spec (DatasetType=derivative, GeneratedBy non-empty array, BIDSVersion string).
4. `CITATION.cff` parses by `cffconvert --validate` (when installed) OR by simple YAML schema check.
5. `participants.tsv` has matching column count in `participants.json` sidecar.
6. Cohort FC summary (item 7) computed across all subjects with hemicord FC matrices (5 datasets, 11 runs).
7. Methods manifest cites at least: Kaptan 2023, Hemmerling 2025, Eippert 2017, Brooks 2008, De Leener 2018, Cicchetti 1994, Shrout & Fleiss 1979.
8. Re-running S11 on same chain produces byte-identical `metrics_index.jsonl` (deterministic).

## Next Steps
1. Mark `private/SPEC/S11_qc_aggregation_and_reports.md` superseded.
2. Write `policy/S11_qc_aggregation_and_release.yaml`.
3. Write `schemas/qc_S11_qc_aggregation_and_release.schema.json`.
4. Scaffold `src/spinalfmriprep/steps/s11/` (process, orchestrate, reportlets, templates).
5. Implement 14 generators in `process.py`:
   - `_walk_chain_qc()` — load all step qc.jsons across datasets.
   - `_build_metrics_index_jsonl()`.
   - `_build_run_inventory()`.
   - `_build_per_subject_html(subject_runs)`.
   - `_build_group_qc_dashboard(all_runs)`.
   - `_build_cohort_coverage_matrix(s9_per_level_tsvs)`.
   - `_build_cohort_tsnr_heatmap(s9_per_level_tsvs)`.
   - `_build_cohort_fc_summary(s10_hemicord_tsvs)`.
   - `_build_reproducibility_receipt()`.
   - `_build_citation_cff_and_bib()`.
   - `_build_dataset_description_json(s1_qc)`.
   - `_build_participants_tsv_and_json(per_subject_summary)`.
   - `_build_methods_manifest(policy_sha_per_step)`.
   - `_run_sidecar_audit(expected_paths)`.
   - `_build_release_report_html()`.
6. CLI + dashboard registry + chain script wiring.
7. Run S11 on the reg chain; verify `release_report.html` opens; verify each item.
8. Commit autonomously per saved feedback memory.

## Decision Log
| # | Choice | Rationale |
|---|--------|-----------|
| D1 | 14 items (4 baseline + 3 cord-novel + 5 publication + 2 compliance/nav) | All four audiences covered; cost-bounded (~3.5 days); cord-novel premium realized. |
| D2 | No external dataset bundling (no Valošek 2024 normative, no CoSpine percentiles) | v1.1 candidates; require S2 morphometry emit changes too. Ship-without-external-deps wins. |
| D3 | Internal sidecar audit replaces bids-validator | bids-validator support for BIDS-Derivatives is incomplete (April 2023+); generates non-actionable noise. Our audit verifies OUR contract. |
| D4 | Cohort FC summary is descriptive aggregation only (no p-values) | Statistical inference is analyst territory; S11 stays a pipeline preprocessing aggregator. |
| D5 | CC0 boilerplate text pattern (fMRIPrep convention) | Public-domain adaptable; nipreps `__desc__` workflow attribute pattern is field-standard. |
| D6 | `release_report.html` single-page index added (14th item) | Without it, users have to memorize 13 different file paths. Trivial cost (~50 LOC); large usability win. |
| D7 | Per-subject HTML emits links to existing reportlet PNGs (not base64 embed) | Smaller HTML files; v1.1 can add base64 mode for single-file portability. |
| D8 | Run inventory is a separate item from metrics_index.jsonl | Different views: metrics_index is the source-of-truth flat table; run_inventory is the human-readable pivot. Trivial to derive both. |
| D9 | `participants.json` sidecar required alongside `participants.tsv` | BIDS spec requires sidecar for non-standard columns. We emit both. |
| D10 | Idempotent + deterministic output | Required for reproducibility claims. No randomness anywhere in S11. |

## Out of scope (deferred to v1.1 / v2)

- **Valošek 2024 PAM50 morphometry normative comparison** — high-value, but requires S2 to emit per-vertebral-level CSA/AP/transverse-diameter metrics first.
- **CoSpine 2025 percentile benchmarks** — requires bundling CoSpine 2025 cohort distributions; v1.1.
- **Cross-pipeline reproducibility benchmark** (vs SCT batch_processing, CoSpi) — research project, not pipeline step.
- **Permutation testing / cluster-extent corrected group maps** — analyst territory.
- **Interactive web nav drill-down beyond release_report.html linking** — existing dashboard_server.py serves per-workfolder; v1.1 extends.
- **Provenance DAG visualization** — text-form reproducibility receipt (item 8) captures the same info; deferring viz.
- **ML / data-driven threshold optimization** — requires N >> 11; v1.1 once v1_validation (146 subjects) chain runs.
- **Auto-emailed QC alerts** — deployment-side, not pipeline.
- **Manual rater interface** — clinical adoption feature; v2.

## References (verified round-2)
- [BIDS — Derivatives intro (DatasetType, GeneratedBy)](https://bids-specification.readthedocs.io/en/stable/derivatives/introduction.html)
- [BIDS — Dataset description fields](https://bids-specification.readthedocs.io/en/stable/modality-agnostic-files/dataset-description.html)
- [BIDS — Data summary files (participants.tsv)](https://bids-specification.readthedocs.io/en/stable/modality-agnostic-files/data-summary-files.html)
- [Citation File Format standard v1.2.0](https://citation-file-format.github.io/)
- [fMRIPrep — Citing + CC0 boilerplate convention](https://fmriprep.org/en/stable/usage.html)
- [fMRIPrep — Outputs + per-subject HTML structure](https://fmriprep.org/en/stable/outputs.html)
- [nipreps `__desc__` workflow boilerplate convention](https://www.nipreps.org/intro/transparency/)
- [bids-validator — BIDS-Derivatives support is incomplete (rationale for internal audit)](https://github.com/bids-standard/bids-validator)
- Round-1 + Round-2 audit (above), all cited.
