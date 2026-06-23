# S10: QC Aggregation & Release

**Step Code:** `S10_qc_aggregation_and_release`
**Depends on:** S1–S9 (all finished per-run QC and outputs)
**Required by:** — (final step)

---

## Purpose

S10 turns the per-run results of the whole pipeline into a **release**: a set of
cross-dataset quality-control views, a reproducibility receipt, ready-to-paste
methods text, and a BIDS-Derivatives compliant manifest. It runs no image
processing; it walks the QC files every earlier step wrote and assembles them
into human- and machine-readable deliverables.

---

## Deliverables

### Aggregation core

- **Per-subject HTML report** linking each step's key reportlet thumbnail
  (cord-mask montage, functional localization, motion tSNR comparison, crop box,
  BOLD-on-anatomy overlay, PAM50 overlay, confound columns, tSNR map).
- **Group dashboard** in the MRIQC style: one boxplot per metric (mean FD,
  cord Dice, native and template registration Dice, post-smoothing tSNR), with
  one dot per subject coloured by dataset.
- **Metrics index** and **run inventory** tables across all datasets.

### Cord-specific cohort views

- **Coverage matrix** — which vertebral levels each subject covers.
- **tSNR heatmap** — per-spinal-level tSNR (from S9's per-level table), one box
  per level across the cohort.

### Publication and reproducibility

- **Reproducibility receipt** capturing tool and package versions (the policy SHA
  and git SHA make any run re-creatable).
- **Methods manifest** — auto-generated methods boilerplate in Markdown, LaTeX
  and HTML.
- **References bibliography** of every method the chain used.
- **Citation file** (CITATION.cff) and **dataset_description.json**
  (BIDS-Derivatives manifest, `DatasetType = derivative` with `GeneratedBy`).
- **participants.tsv** summarising per-subject counts, mean FD, median in-cord
  tSNR, and an inclusion recommendation (flagging mean FD > 0.5 mm or tSNR < 5).

### Navigation

- A top-level **release_report.html** index tying the above together.

---

## Step Metric and QC

S10's checks are about completeness of the release, not image quality.

| Metric | PASS | WARN |
|--------|------|------|
| fraction of subjects with a report | ≥ 0.80 | ≥ 0.50 |
| fraction of missing per-step QC | ≤ 0.05 | — |

---

## Outputs

```
derivatives/spinalfmriprep/{dataset}/
├── release_report.html              # top-level index
├── group_dashboard.html
├── dataset_description.json          # BIDS-Derivatives manifest
├── participants.tsv
├── CITATION.cff
├── references.bib
├── methods.{md,tex,html}             # methods boilerplate
└── reproducibility_receipt.json      # tool/package versions, policy + git SHA

derivatives/spinalfmriprep/{dataset}/sub-{id}/
└── sub-{id}_report.html              # per-subject aggregated report
```

---

## References

1. **Group QC dashboard convention:** Esteban et al. (MRIQC). *PLOS ONE* 12(9):e0184661 (2017). [DOI](https://doi.org/10.1371/journal.pone.0184661)
2. **BIDS Derivatives:** Markiewicz et al. *eLife* 10:e71774 (2021). [DOI](https://doi.org/10.7554/eLife.71774)

---

*Last updated: June 2026*
