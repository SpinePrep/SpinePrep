---
status: approved
supersedes_sections_of: s10-qc-aggregation-and-release.md
created: 2026-06-23
---

# Spec: S10 subject-level and group-level reports (redesign)

This refines the **report layer** of S10 (the human-facing HTML) to field
standard. The S10 aggregation core (metrics_index, participants.tsv,
reproducibility receipt, CITATION.*, dataset_description, cohort coverage/tSNR
views) is sound and stays. What changes is the two HTML reports that humans
actually read: the **per-subject report** and the **group report**.

S10 remains **read-only and deterministic** — it aggregates the per-step truth
metrics and embeds the per-step reportlet PNGs; it computes no new image-level
metrics. Group statistics (mean ± SD, percentiles, distributions) are
aggregations and are allowed.

## Two readers, two questions (the anchor)

- **Subject report** → the analyst who will model this subject's data + the QC
  rater. Question: *"Can I trust this subject/run, and if not — what failed,
  why, and what do I do?"*
- **Group report** → the study lead / methods author / reviewer. Question:
  *"Is the cohort sound? Who are the outliers? What's the quality distribution?
  Is it reproducible?"*

## Principles (binding)

1. **Visual QC is the validator; metrics are supporting evidence** (principle
   #5). Figure-first; every number sits next to the picture that justifies it.
2. **S10 invents no new image metrics** (principles #3/#4). Aggregate + embed.
3. **Cord resolution is the unit.** Anything per-vertebral-level is shown per
   level (tSNR/level, coverage/level, Dice/level) — CoSpine/Kaptan convention.
4. **Flag, don't gate; show distributions, not verdicts** (MRIQC/COBIDAS). The
   report *recommends* include/review/exclude with a reason; the human decides.
5. **Per-dataset, not pooled** (principle #10). Each dataset is its own group
   report; a thin cross-dataset overview sits on top.
6. **Truthful provenance.** Every figure has a one-line "what to look for"
   caption; methods boilerplate auto-generated from live policy + version
   stamped; attrition shown with reasons (no silent drops).

## Subject report — sections (per subject, one self-contained HTML)

`derivatives|release/.../<dataset>/sub-XX/sub-XX_qc_report.html`

1. **Summary card** — subject, dataset, n sessions/runs; overall recommendation
   (Include / Review / Exclude) + the single most important reason in plain
   words; headline numbers (mean FD mm, median in-cord tSNR, n runs passed);
   step strip S1→S10 with PASS/WARN/FAIL chips.
2. **Anatomical (S2)** — cord-seg + vertebral-labeling reportlet, PAM50
   registration overlay, with a "good vs bad" caption.
3. **Per-run functional cards** (one per BOLD run) — the core. Each card:
   - run verdict + per-step chips;
   - **embedded headline reportlets** (S4 motion traces, S5 distortion
     before/after, S9 tSNR map + per-level tSNR) and **linked** secondary ones
     (S3 funcref, S5 dice-per-slice, S6 bold-on-anat, S7 PAM50 overlay, S8
     carpet);
   - a **metric micro-table**: FD mean/max, % frames censored, S5 cord-Dice +
     A–P displacement (with the honest *distortion-limited / no-fieldmap* label
     when present), S6 Dice, S7 worst per-level Dice, S8 condition number, S9
     tSNR pre/post + measured FWHM;
   - if not PASS: a **structured explanation** — what failed (metric vs
     threshold), why (class), recommended action.
4. **Confound model (S8)** — plain summary of regressors built (motion,
   aCompCor/CSF, RETROICOR, cosine, outliers), column count, condition number —
   so the analyst knows what to put in the GLM.
5. **Methods boilerplate** (collapsible, embedded — NiPreps convention).
6. **Provenance footer** — tool versions, policy SHAs, git SHA, timestamp.

## Group report — sections (per dataset + cross-dataset overview)

Per-dataset: `.../group_report_<dataset>.html`. Overview: `release_report.html`.

1. **Cohort summary card** — N subjects/runs; PASS/WARN/FAIL tallies; n
   include/review/exclude; acquisition profile (domain, fieldmap y/n).
2. **Inclusion table** — participants.tsv rendered; per subject n runs, mean FD,
   median in-cord tSNR, recommendation + reason; review/exclude rows highlighted
   and linked to the subject report.
3. **QC-metric distributions** (MRIQC-style) — for each headline metric a
   strip/box plot across the cohort, one dot per subject, threshold lines drawn,
   outliers labeled: FD (S4), displacement & cord-Dice (S5), Dice (S6), per-level
   Dice (S7), condition number (S8), in-cord tSNR + FWHM (S9).
4. **Per-vertebral-level cohort views** — tSNR per level (mean ± SD, Kaptan
   2023), coverage matrix (subject × level), per-level Dice (S7).
5. **Attrition flow (CONSORT-style waterfall)** — run count S1→S10 with how many
   dropped at each step and why. The truthfulness centerpiece.
6. **Failure stratification** — WARN/FAIL counts by step.
7. **Reproducibility panel** — human-readable receipt (tool versions, per-step
   policy SHAs, git SHA, determinism statement).
8. **Methods boilerplate + references** (links).

## Architecture / engineering

- **Model → render separation.** New module `steps/s10/reports.py`: pure
  builders that assemble a typed report model from the flat records + chain_qc,
  and small HTML render functions. process.py keeps the aggregation builders;
  orchestrate.py delegates the two HTML reports to reports.py.
- **Reportlet embedding by convention.** Figures are addressed by the pattern
  `{run_id}_desc-{STEP}_{key}.png` under `**/sub-{sub}/figures/`, resolved by
  glob against the chain derivatives and referenced via a relative path. Robust
  when the per-run `reportlets` dict is sparse. Headline figures embedded;
  secondary figures linked (page-weight balance).
- **Self-contained static HTML** (no server), portable in the derivatives tree.
- Reuse the `reportlets_common.py` palette; new S10 figures (attrition
  waterfall, per-dataset distributions) are matplotlib PNGs.

## Truthfulness guarantees

- Attrition shown with per-step drop counts + reasons (no silent loss).
- Fieldmap-less / distortion-limited runs labelled honestly in the run card.
- Distributions over single numbers; thresholds drawn, never hidden.
- "Recommendation," not "decision" — the human rates.
- Every figure carries a one-line what-to-look-for caption.

## Acceptance criteria

1. Each subject report has the 6 sections; per-run cards embed ≥3 headline
   reportlets and a metric micro-table; non-PASS runs show a structured reason.
2. Each dataset has a group report with the 8 sections; the attrition waterfall
   reconciles exactly (drop at step N == FAILs at N−1, matching the cohort
   audit).
3. The cross-dataset `release_report.html` links every per-dataset group report
   and every subject report.
4. Reports render with real content on all 7 production scopes; no broken image
   links for runs that have figures.
5. S10 stays read-only/deterministic; unit tests cover the report-model
   builders (recommendation logic, attrition reconciliation, figure resolution).
6. `poetry run pytest` green.

## Literature backing

fMRIPrep subject report + visual-reportlet philosophy (Esteban 2019); MRIQC
group IQM distributions + outlier flagging (Esteban 2017); per-slice cord-Dice /
A–P displacement (Wei/CoSpine 2025); per-level tSNR + FD threshold (Kaptan
2023); carpet plot (Power 2017); reporting distributions + exclusions-with-
reasons + provenance (Nichols/COBIDAS 2017); PAM50 levels (De Leener 2018).

## Phasing

- P1: `reports.py` model + subject report (summary card, per-run cards, confound
  summary, provenance). 
- P2: per-dataset group report (summary, inclusion table, distributions,
  per-level views, attrition waterfall, failure strat, reproducibility panel).
- P3: cross-dataset `release_report.html` overview + wire into orchestrate;
  tests; re-run all 7 scopes to validate.
