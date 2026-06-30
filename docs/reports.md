# QC reports

Every run of SpinalfMRIprep produces self-contained HTML QC reports (no server
needed) — the human-facing layer of the "visual QC is the validator" philosophy.
There are two, mirroring the BIDS-App levels.

## Subject report (participant level)

`derivatives/.../sub-XX/sub-XX_qc_report.html` — one per subject. Sections:

1. **Summary card** — an Include / Review / Exclude recommendation with a one-line
   reason, headline mean FD and median in-cord tSNR, and a step strip (S1→S10
   PASS/WARN/FAIL chips).
2. **Anatomical** — cord segmentation + vertebral labelling and PAM50 registration.
3. **Per-run functional cards** — for each BOLD run: per-step chips, **embedded
   headline reportlets** (S4 motion, S5 distortion before/after, S9 tSNR), a metric
   micro-table (FD, % censored, cord-Dice, A-P displacement, condition #, tSNR
   pre→post), and a structured *what-failed-and-why* note for non-PASS runs
   (including the honest "distortion-limited, no fieldmap" label).
4. **Confound model** — the nuisance regressors emitted for your GLM.
5. **Methods boilerplate** (auto-generated, CC0) + a provenance footer.

## Group report (group level, per dataset)

`group_report_<dataset>.html` + the cross-dataset `release_report.html`. Sections:
cohort summary; an **inclusion table** (per-subject recommendation, shaded +
linked); **MRIQC-style QC-metric distributions** with literature reference lines;
**per-vertebral-level views**; a **CONSORT-style attrition waterfall** (every drop
reconciles to the prior step's FAILs — no silent losses); WARN/FAIL stratification;
and a reproducibility panel.

## Example figures (from the validation cohort)

These are produced by the same machinery that feeds the reports:

![Normative per-level tSNR](../validation/results/figures/normative_tsnr_per_level.png)
![Connectivity reliability](../validation/results/figures/reliability_connectivity.png)
![Head-to-head vs SCT-default](../validation/results/figures/headtohead_dice.png)

> A fully interactive gallery (live subject + group reports embedded) ships with
> the hosted site; the report HTML lives in each run's `derivatives/.../release/`.
