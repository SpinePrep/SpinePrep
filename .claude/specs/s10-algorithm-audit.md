---
status: implemented
implemented_in: wf_reg_093
implemented_at: 2026-05-28
---

# S10 algorithm + release-aggregation audit

Audit of S10 as it shipped at `wf_reg_090` (chain S2..S9 locked → S10
auto-run). 23 deliverables across 4 tiers, 1121 lines in
`steps/s10/process.py`. Compared against fMRIPrep, MRIQC, BIDS-
Derivatives spec, NiPreps boilerplate convention, CoSpine 2025
(Wei Sci Data), Kaptan 2023 (cord rs-fMRI reliability).

## Current state — what S10 emits

`wf_reg_090/logs/S10_qc_aggregation_and_release/qc.json` reports
`status=PASS` with 22 deliverables landing in
`derivatives/spineprep/` plus per-subject HTML reports under
`<dataset>/sub-XX/`. Top-line metrics:
```
n_subjects_aggregated: 10   (real cohort = 5)
n_runs_aggregated:      6   (real cohort = 11)
n_datasets:             5   ✓
sidecar_audit_issues:   0   (only 'checks' reportlet PNGs)
cohort_fc_n_common_rois: 1  (FC summary is non-informative)
```

The aggregation pass/fail tally diverges from reality. The cause is
upstream ID hygiene, not aggregation logic — see B3, B4 below.

## Critical algorithmic bugs

### B1 — `mean_fd_mm` always `n/a` (key mismatch)

`_build_participants_tsv` reads `r.get("fd_max_mm")` but S4 emits
`mean_fd_mm` and `max_fd_mm`. Every participant gets `mean_fd_mm: n/a`.
The same wrong key appears in `policy.aggregation.group_dashboard.
metric_distributions` (`S4.metrics.fd_max_mm`) — but that field is
never consumed anyway (see B7).

**Fix:** Read `mean_fd_mm` (matches S4); update policy key.

### B2 — `subject="all"` leaks into participants/inventory

S1 emits one synthetic row per dataset with `subject="all"`; S9 and
the former S10 (ROI/connectivity) inherit it via their orchestrators. `_flat_run_records` normalises
`sub-` prefix but doesn't filter `"all"`. Result: `participants.tsv`
contains a `sub-all` row per dataset (10 → 5 real + 5 synthetic),
and run_inventory counts inflate.

**Fix:** Drop records where subject ∈ {`all`, `*`, `None`}.

### B3 — Subject + session inconsistency across upstream steps

Steps disagree on ID encoding:
```
S2:  ("02", None), ("ZS002", None), ("02", "01"), ("02", "02")
S4:  + ("sub-02", None), ("sub-02", "ses-01")
S9:         + ("all", None)
former S10: same as S9
```

`_flat_run_records` strips the leading `sub-` but never normalises
`session` from `01` ↔ `ses-01`. The groupby in `_build_run_inventory`
treats `("02","01")` and `("sub-02","ses-01")` as different rows. The
handgrasp cohort shows up as 6 inventory rows instead of 2.

**Fix:** Normalise BOTH `subject` (drop `sub-` prefix) AND `session`
(drop `ses-` prefix, treat `""`/`None` consistently) in
`_flat_run_records`. Apply same in orchestrators upstream so the chain
ID encoding becomes canonical.

### B4 — participants.tsv counts > n_runs

For balgrist sub-02 the row shows `n_runs=9, n_passed=3, n_warn=2,
n_failed=4`, sum=9 across "runs" but the real cohort has 4 runs. The
inflation comes from B3: ID dupes inflate run_groups.ngroups.

**Fix:** Same as B3 (normalisation upstream of groupby).

### B5 — `cohort_fc_summary` placeholder fires (1 common ROI)

`_build_cohort_fc_summary` intersects ROI sets across all 9 matrices;
the cord hemicord×segment parcellation produces different ROI subsets
per run (FOV + horn-prob threshold + spinal-segment coverage vary).
Intersection collapses to 1 ROI → no FC matrix can be built. The code
writes a placeholder PNG with text "Consider stratifying by dataset"
— the recommendation is correct but unimplemented.

Kaptan 2023 handles this by restricting to a fixed segment range
(C3–T1) before any cross-subject FC analysis. CoSpine 2025 doesn't
ship a cohort FC matrix at all. There is no field consensus on
union-with-NaN for cord FC.

**Fix:** Stratify by `dataset_key` AND restrict to a configurable
canonical segment range (default C3–T1, Kaptan 2023). Emit one
per-dataset FC summary + one cross-dataset FC summary on the canonical
subset.

### B6 — `policy_sha256_per_step` mostly NULL

The receipt collects per-step policy SHAs by walking
`out_dir/work/<step>/<ds>/<run>/qc_metrics.json`. In the chain runner
`out_dir/work` is symlinked to wf_reg_073 (S1's workfolder), so only
steps whose own `qc_metrics.json` write succeeded under the *current*
chain-runner's symlinked tree are found (S7-S10 in our case; S1-S6
NULL).

**Fix:** Walk through ALL upstream `work/done/reg/{step}/work` paths
when those symlinks exist, AND fall back to reading the policy YAMLs
directly and hashing them — that's the actual source of truth.
Hashing the YAML matches the "policy SHA" semantics regardless of
chain-runner symlink topology.

### B7 — `metric_distributions` boxplots never rendered

Policy declares 5 metric paths to boxplot; `_build_group_dashboard_data`
ignores the field entirely and only renders a status heatmap + per-
step pass-rate bars. The group dashboard is the closest analogue to
MRIQC's group report — which is fundamentally a boxplot dashboard
(Esteban 2017). We have the metrics, the policy, and `pd.DataFrame`
already in hand. Missing implementation.

**Fix:** Implement boxplot rendering. One subplot per declared metric,
strip plot of subject dots (Kaptan 2023 / MRIQC convention), labels
by dataset_key.

### B8 — `methods_manifest.tex` is malformed

`out_tex.write_text(md.replace("# ", "\\section{").replace("## ",
"\\subsection{") + "}")` is a regex one-liner with broken brace
balance, no Markdown bold/italic stripping, no citation-key handling
(`[@cite]` carries through verbatim), one trailing `}` to close
everything. The output starts with `\section{Methods…` (no closing
brace) and includes lines like `#\section{Preprocessing` because `#`
inside `## Preprocessing` was matched first.

**Fix:** Either (a) use Pandoc (`pandoc md → tex`), the convention used
by fMRIPrep CITATION.tex, or (b) build LaTeX from a structured dict
rather than re-mangling Markdown. Pandoc is the field standard.

### B9 — `methods_manifest` text is hardcoded, drifts from policy

The methods text states "Bandpass 0.01–0.1 Hz [@eippert2017]" and
"σ = 1, 1, 5 mm" as literals. If policy changes (already happened for
S5 and S9 in recent commits), the manifest drifts silently. The whole
point of an auto-generated methods section is that it reflects what
actually ran.

**Fix:** Read the policy YAML for each step and substitute the values
into the template — at minimum bandpass, smoothing sigma, FD threshold,
SCT/FSL/Nilearn versions, ROI catalog counts, confound family list.

### B10 — `fsl_version` capture buggy

`fslversion` shell output starts with the env-var banner
`FSLDIR:  /usr/local/fsl` followed by `6.x.x` on a separate line.
The recipe takes the first line ⇒ `fsl_version: "FSLDIR:  /usr/local/fsl"`.

**Fix:** Parse the actual version with a regex `^\d+\.\d+(\.\d+)?$`
across lines, OR use `cat $FSLDIR/etc/fslversion` (canonical), OR
strip the env-var banner. Same pattern check for `sct_version`.

### B11 — `sidecar_audit` doesn't audit BIDS sidecars

Function name promises BIDS sidecar coverage check; implementation
only verifies that the reportlet PNG paths in `records` resolve to
files. NIfTI dtype + shape + affine checks listed in policy are not
implemented (`nifti_issues_list` is always empty).

**Fix:** Either (a) wrap `bids-validator` (the field standard;
Markiewicz 2021 *eLife*) and capture its JSON output, or (b) rename to
`reportlet_audit` and drop the policy/spec claim of BIDS sidecar
coverage. Don't promise what isn't delivered.

### B12 — `methods_manifest.{md,tex,html}` naming diverges from field

NiPreps (fMRIPrep / sMRIPrep / ASLPrep / dMRIPrep / NiBabies) all
emit `logs/CITATION.{md,bib,tex,html}` and the user is told to reuse
it verbatim (CC0). Our `methods_manifest.*` is the same content under
a non-standard name and lives in `derivatives/spineprep/` not
`logs/`. Diverges from the convention the field already standardised
on.

**Fix:** Rename to `CITATION.{md,bib,tex,html}` and write to
`derivatives/spineprep/logs/` to match NiPreps. Keep the
filename `references.bib` for the auto-bibliography (or merge into
`CITATION.bib` per convention).

### B13 — `CITATION.cff` + `dataset_description.json` overlap unmanaged

BIDS spec: when `CITATION.cff` is present, the overlapping fields
(`Authors`, `License`, `HowToAcknowledge`, `ReferencesAndLinks`) MUST
be removed from `dataset_description.json`. We emit both; nothing
deduplicates.

**Fix:** Strip overlapping fields from `dataset_description.json` when
CITATION.cff is being emitted. Or omit one of the two.

### B14 — `dataset_description.json` has placeholder CodeURL

```json
"CodeURL": "https://github.com/[org]/SpinePrep"
```
literal `[org]` placeholder in the released file.

**Fix:** Either resolve from `git remote get-url origin` or remove the
field.

### B15 — S10 writes into upstream symlinked derivatives

Chain runner sets `wf_reg_090/derivatives -> wf_reg_089/derivatives
-> wf_reg_088/derivatives`. S10 writes to
`out_dir/derivatives/spineprep/` — which resolves to
`wf_reg_088/derivatives/spineprep/`. The release artifacts land
in the S8-locked workfolder, not the S10 one. From the user's POV,
running S10 silently mutates a previous step's directory.

This is a chain-runner symlink design issue, but it's also S10's
responsibility to either (a) detect the symlink and materialise its
own derivatives, or (b) emit to a separate `release/` directory it
owns.

**Fix:** In `run_S10`, if `out_dir/derivatives` is a symlink, switch
to `out_dir/release/` for all aggregation outputs. Per-subject HTML
can remain in the upstream `<dataset>/sub-XX/` paths since they
reference upstream artifacts anyway.

### B16 — `n_subjects_aggregated` counted over flattened records

The metric counts unique subjects across the flattened record stream,
which inherits the B2+B3 ID inconsistency: "10" includes `sub-all`
fakes and `sub-02`/`02` dupes. Real value is 5.

**Fix:** Auto-resolves after B2 + B3.

## Field-standard composition gaps

From the literature scan (full sources in audit file):

| Item | Field convention | S10 today |
|---|---|---|
| Per-subject HTML | fMRIPrep `sub-XX.html` — segmentation, registration, fieldmap, carpet, **CITATION boilerplate embedded** | step pivot × thumbnails, no boilerplate inline |
| Group HTML | fMRIPrep has NONE; MRIQC has `group_<modality>.html` driven by `group_<modality>.tsv` long-format `(iqm, value, label, units)` with **boxplots per IQM** | status heatmap + pass-rate bars only; declared boxplots unimplemented |
| Cohort FC matrix | Kaptan 2023 restricts to C3–T1 + intersection; CoSpine 2025 doesn't ship one. No consensus | Global intersection (collapses to 1 ROI) + placeholder |
| Subject-level tSNR by level | Kaptan 2023: per-segment box plots + subject dots (NOT subject × level heatmap) | subject × level heatmap with 0-50 range (cord typical 8-20) |
| Coverage matrix | Not in field — net-new contribution | subject × level coverage matrix, current implementation conflates "level in FOV" with "S9 tSNR computed" |
| Methods boilerplate | NiPreps `logs/CITATION.{md,bib,tex,html}`, Pandoc-converted | `methods_manifest.{md,tex,html}` in derivatives root; tex malformed; text hardcoded |
| dataset_description.json | BIDS-Derivatives v1.11 spec; `GeneratedBy` required; CITATION.cff overlap must be deduplicated | overlap unmanaged, CodeURL has `[org]` placeholder |
| participants.tsv | Study-level, modality-agnostic; only `participant_id` required | extends with QC-derived columns (n_pass/warn/fail, FD, tSNR, inclusion recommendation) — legitimate extension if sidecar documents it (✓ done) |
| metrics_index | MRIQC: long-format TSV `group_<modality>.tsv` | JSONL — equivalent data, non-standard format |
| sidecar audit | bids-validator (Markiewicz 2021) | reportlet PNG existence only — misnamed |
| Reproducibility receipt | fMRIPrep: tool versions + Singularity hash in `GeneratedBy.Container.Tag`; no separate receipt file | separate JSON file with policy SHAs (useful extension); fsl_version parsing buggy |

## Proposed S10 redesign

### Drop / rename
- **Drop**: `sidecar_audit_{json,html}` (replace with `bids_validator.json`
  if implementing; otherwise drop entirely — non-blocking by policy)
- **Rename**: `methods_manifest.{md,tex,html}` → `CITATION.{md,tex,html}`
  + `references.bib` → `CITATION.bib`, move to `logs/`

### Keep + fix
- per-subject HTML — add inline CITATION boilerplate (NiPreps convention)
- group_qc_dashboard.html — add the missing boxplots (MRIQC pattern)
- run_inventory — fix B2 + B3
- metrics_index.jsonl — keep, plus emit long-format `metrics_index.tsv`
  (MRIQC convention)
- coverage_matrix — keep (cord-novel, Principle 10), but source from S7
  (registration coverage) not S9 (tSNR computation)
- tsnr_heatmap — keep, replace with Kaptan 2023 per-segment boxplots
  with subject dots; color range 0-30 (cord realistic)
- fc_summary — implement per-dataset stratification + C3-T1 canonical
  subset; emit per-cell N alongside mean Fisher-z
- participants.tsv — fix B1, B2; sidecar already done
- dataset_description.json — fix B14; dedupe overlap with CITATION.cff
- reproducibility_receipt — fix B6, B10
- release_report — automatic update once underlying artifacts are
  consistent

### Net change
- 23 → 22 deliverables (drop sidecar_audit's two files, add
  metrics_index.tsv; rename 3 methods files)
- Algorithm fixes for 16 distinct bugs (B1–B16)
- One destination-scoping fix (B15) that affects the whole step

## Implementation map

| # | Action | Tier | Effort |
|---|---|---|---|
| F1 | ID normalisation in `_flat_run_records` (B2, B3, B16) | aggregation | ~30 lines |
| F2 | participants.tsv fix `fd_max_mm` → `mean_fd_mm` + drop sub-all (B1) | publication | ~5 lines |
| F3 | Group-dashboard boxplots from `metric_distributions` policy (B7) | aggregation | ~80 lines |
| F4 | FC summary: stratify by dataset + C3-T1 canonical subset (B5) | cohort views | ~80 lines |
| F5 | tSNR heatmap → Kaptan-style boxplots; color range 0-30 | cohort views | ~50 lines |
| F6 | Coverage matrix: switch source from S9 tSNR TSV to S7 vertebral_level_coverage metric | cohort views | ~40 lines |
| F7 | Reproducibility receipt: walk all upstream wf trees + hash policy YAMLs directly (B6); fix fsl_version parser (B10) | publication | ~30 lines |
| F8 | Methods manifest: rename to CITATION.{md,tex,html} + move to logs/; convert via Pandoc not regex (B8, B12); read policy values not hardcoded (B9) | publication | ~80 lines |
| F9 | dataset_description: resolve CodeURL from git remote; dedupe with CITATION.cff (B13, B14) | publication | ~20 lines |
| F10 | Sidecar audit: drop or wrap bids-validator (B11) | compliance | ~10 / ~60 lines |
| F11 | Destination scoping: emit aggregation outputs to `out_dir/release/` when derivatives is a symlink (B15) | architecture | ~20 lines |
| F12 | Inline CITATION boilerplate in per-subject HTML (NiPreps convention) | aggregation | ~30 lines |
| F13 | Emit metrics_index.tsv (long-format MRIQC convention) alongside JSONL | aggregation | ~20 lines |

Total: ~495 lines of code change across ~13 focused fixes.

## Truthfulness review

| Claim | True? |
|---|---|
| "S10 emits 23 deliverables" | ✓ as counted by qc.json `deliverables` dict |
| "S10 status PASS" | ⚠ PASS is reported but reflects only existence of files; multiple are broken (B1, B5, B7, B8) |
| "n_subjects_aggregated: 10" | ❌ real cohort is 5; ID hygiene bug inflates |
| "cohort FC summary informative" | ❌ intersection collapses to 1 ROI |
| "sidecar audit clean" | ❌ no sidecar audit actually performed |
| "methods manifest reflects pipeline" | ❌ hardcoded; drifts from policy; tex malformed |
| "reproducibility receipt complete" | ⚠ S1-S6 policy SHAs are NULL; fsl_version garbled |

## Sources

- Esteban et al 2019 — fMRIPrep (*Nat Methods*)
- Esteban et al 2017 — MRIQC (*PLoS One*)
- Markiewicz et al 2021 — OpenNeuro + bids-validator (*eLife*)
- Wei et al 2025 — CoSpine database (*Sci Data*)
- Kaptan et al 2023 — Cord rs-fMRI reliability (*NeuroImage*)
- BIDS-Derivatives v1.11 spec —
  https://bids-specification.readthedocs.io/en/stable/derivatives/
- CITATION.cff v1.2 — https://citation-file-format.github.io/
- NiPreps boilerplate convention —
  https://neurostars.org/t/fmriprep-boilerplate-reuse/4663
- fmriprep-group-report — https://github.com/transatlantic-comppsych/fmriprep-group-report
- MRIQC group module —
  https://mriqc.readthedocs.io/en/stable/_modules/mriqc/reports/group.html
- Internal: `.claude/specs/s11-qc-aggregation-and-release.md`,
  `policy/S10_qc_aggregation_and_release.yaml`,
  `src/spineprep/steps/s11/process.py`
