---
status: approved
supersedes: private/SPEC/S11_qc_aggregation_and_reports.md
---

# Scope Spec: S11 QC Aggregation + Release Readiness v2

> **Update 2026-06-11 — S10 removed; S11 aggregates S1–S9 only.** S10
> (ROI timeseries / hemicord connectivity / reliability) was removed from
> the active pipeline on 2026-06-11 as analyst-owned analysis (its own
> spec is `status: deferred`). As a result the **Cohort FC summary**
> deliverable (item 7) and the `max_condition_number` participants column
> are **removed** from the shipped S11, and the S10 hemicord-TSV data
> source no longer applies. The references below that mention S10, the FC
> summary, or `max_condition_number` are **struck / deferred** — they do
> not match the shipped code, which now walks S1–S9 only. The rest of the
> spec is current.

## Objective
Aggregate ~~S1–S10~~ **S1–S9** per-step outputs into the v1 release-readiness deliverables: per-subject HTML reports, group QC dashboards, cord-novel cohort transparency views, publication & reproducibility artifacts (CITATION.cff, methods manifest, dataset_description.json, participants.tsv), and a top-level `release_report.html` index.

## Constraints
- **Read-only.** S11 walks finished `qc.json` files + per-run derivative artifacts; never re-runs upstream.
- **Deterministic.** Re-running on the same chain produces byte-identical HTML/JSON output.
- **No statistical inference.** Group-mean FC matrices and consistency maps are descriptive aggregation only — no p-values, no permutation testing (analyst territory).
- **No external dataset bundling.** Every item builds from data the chain already emits. Valošek 2024 normative comparison + CoSpine percentile reference are explicitly v1.1 (require external table bundling).
- **No `bids-validator` invocation** — verified that BIDS-Derivatives validator support is incomplete (April 2023+) and emits non-actionable noise on fMRIPrep-style derivatives. Replaced by an internal sidecar audit.
- **No new step-level QC metrics.** S11 surfaces what S1–S9 already computed; doesn't compute new ones.
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
   - Step × subject status heatmap (rows = subjects, cols = S2..**S9**, colour = status).
   - Per-step pass-rate bar chart.
   - Per-step metric boxplots (FD, tSNR, cord Dice) from `metrics_index.jsonl`. (The `condition_number` boxplot was an S10 input and is dropped with S10.)
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
7. ~~**Cohort FC summary**~~ — **REMOVED 2026-06-11 with S10.** This
   deliverable consumed S10's hemicord connectivity TSVs (group-mean
   Fisher-z matrix + consistency map). Since S10 is no longer in the
   active pipeline, S11 no longer emits a cohort FC summary. Functional
   connectivity is now analyst-owned. (Deliverable count drops from 14
   to 13.)

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
    - Columns: `participant_id, dataset_key, n_runs, n_sessions, n_passed, n_warn, n_failed, mean_fd_mm, median_in_cord_tsnr, included_recommendation`. (`max_condition_number` was an S10-derived column and is dropped with S10.)
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
    - Sections: "Per-subject reports" (N links), "Cohort views" (links to group dashboard + coverage matrix + tSNR heatmap; the FC summary link is removed with S10), "Release artifacts" (CITATION.cff, methods, reproducibility), "Compliance" (sidecar audit).
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
- All `logs/S{N}_*/<dataset>/qc.json` files for N in 1..**9** (walked via chain symlinks). (S10 removed 2026-06-11.)
- Per-run derivative artifacts:
  - S9: `*_desc-tsnr_per_level.tsv`, `*_desc-tsnr_native.nii.gz`.
  - ~~S10: `*_desc-hemicord_pearson_connectivity.tsv`, `*_desc-hemicord_fisherz_connectivity.tsv`.~~ — removed with S10.
  - S2..**S9** figures: `derivatives/.../figures/*_desc-S{N}_*.png` (linked from per-subject HTML).
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
6. ~~Cohort FC summary (item 7) computed across all subjects with hemicord FC matrices.~~ — removed with S10 (2026-06-11); no longer an acceptance criterion.
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
   - ~~`_build_cohort_fc_summary(s10_hemicord_tsvs)`~~ — removed with S10 (2026-06-11).
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

---

# Principles audit (May 2026)

Post-implementation audit of S11 against the `CLAUDE.md` dev principles.
The scope spec above is the *3-round design audit* (opportunity menu →
14-item sweet spot → verification); this section is the
principles-alignment check.

## Audit verdict per principle

| # | Principle | Verdict |
|---|---|---|
| 1 | Small dev cohort | ✅ runs on 11-run reg set (5 subjects × {1–4} runs) |
| 2 | Literature defaults | ✅ BIDS-Derivatives spec, CFF v1.2.0, fMRIPrep CC0 boilerplate, Citation File Format v1.2.0, Kaptan / Hemmerling / Eippert / Brooks / De Leener / Cicchetti / Shrout-&-Fleiss bibliography |
| 3 | Step-local truth metric | ✅ `n_subjects_aggregated`, `n_runs_aggregated`, `n_datasets`, `n_subject_reports`, `subject_report_fraction` (headline gate), `missing_step_qc_count`, `sidecar_audit_issues`. (`cohort_fc_n_common_rois` was an S10/FC-summary metric and is dropped with S10, 2026-06-11.) |
| 4 | Diagnostic reportlet | ✅ **dashboard banner** (not per-run reportlet — S11 is global). Banner shows status badge + links to `release_report.html` and `group_qc_dashboard.html` + headline metrics. Plus the release-grade deliverables under `derivatives/spinalfmriprep/` (per-subject HTML reports, cohort coverage matrix, tSNR heatmap, methods manifest, CITATION.cff, references.bib, reproducibility receipt, …). (The cohort FC summary is no longer among them — removed with S10, 2026-06-11.) |
| 5 | Visual QC validator | ✅ The release_report.html is the single-page index linking all 23 artifacts. A human opens it and eyeballs everything. |
| 6 | Lock and ship | ✅ policy + schema + 3-round-audited spec |
| 7 | No chain backtracking | ✅ S11 *consumes* the entire chain's qc.json files but emits self-contained release artifacts; nothing downstream of S11 |
| 8 | Full cohort = deliverable | ✅ **S11 is the release deliverable itself** by design. The CITATION.cff, methods_manifest.tex, dataset_description.json are all paper-time outputs. |
| 9 | Reproducible | ✅ S11 *emits* the reproducibility receipt (SCT/FSL/Python tool versions + policy SHA256 + git SHA). The whole step exists to make the pipeline reproducible by third parties. |
| 10 | Heterogeneity is the test | ✅ The **per-vertebral-level coverage matrix** + **cohort tSNR heatmap** are the heterogeneity surfaces — they show directly which levels are covered across the 5 reg datasets so the analyst stratifies rather than pools blindly. (The earlier headline finding `cohort_fc_n_common_rois: 1` came from the now-removed S10/FC-summary path; the coverage matrix carries the same message without S10.) |

## Why S11 doesn't have per-run reportlets

S11 is **global / cross-dataset**, not per-run. The dashboard layer
(qc_dashboard_html.py:331+) adds a top-of-index "S11 — Release
Readiness" banner with status + links rather than trying to fit S11
into the per-run reportlet gallery. The per-subject HTML reports
under `derivatives/spinalfmriprep/<ds>/sub-XX/sub-XX_qc_report.html`
ARE the per-subject views; release_report.html is the cohort index.

## Step-local truth metric rationale

| Metric | What it answers |
|---|---|
| `subject_report_fraction` | **Headline gate.** Of the (dataset, subject) pairs that have qc data on the chain, what fraction got a successful per-subject HTML report rendered? PASS gate 0.80. |
| `missing_step_qc_count` | How many (step, dataset) qc.json files couldn't be parsed. 0 expected; > 0 ⇒ chain integrity issue. |
| `sidecar_audit_issues` | Internal reportlet PNG existence check (bids-validator's derivatives support is incomplete, so we audit ourselves). 0 expected. |
| ~~`cohort_fc_n_common_rois`~~ | **Removed 2026-06-11 with S10.** Was the number of hemicord ROIs with usable timeseries across all aggregated runs — the cohort-FC summary's usable axis. No longer computed; heterogeneity is now read off the coverage matrix + tSNR heatmap. |
| `n_subjects_aggregated` / `n_runs_aggregated` / `n_datasets` | Cohort scale at this run; reproducibility receipt. |

## Decision: no code change

S11 received the deepest design audit in this cycle (3 rounds:
opportunity menu → 14-item sweet spot → verification). The
implementation matches the spec; the dashboard banner is the
principle §4 surface; the release_report.html is the principle §5
visual validator; the entire step *is* the principle §8 deliverable.

This audit doc records the verdict for completeness — every other
step in the pipeline now has a principles audit, S11 should too.

## Remaining gaps (acceptable / deferred)

- *(Historical, no longer applicable.)* The cohort FC summary and its
  `cohort_fc_n_common_rois` axis were removed with S10 on 2026-06-11.
  The old gap — hemicord FC across the 5 reg datasets being
  uninformative because coverage doesn't overlap enough — is moot now
  that FC is analyst-owned. The cohort coverage matrix still surfaces
  the underlying level-coverage limitation, which is the part S11
  keeps.
