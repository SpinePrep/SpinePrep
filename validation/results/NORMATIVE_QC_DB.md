# Normative cord-fMRI QC database (SpinalfMRIprep v1)

The first multi-site, multi-paradigm **normative QC reference** for spinal-cord
fMRI: the cohort-wide distribution of each pipeline QC metric across the v1
validation cohort (8 datasets, 5 paradigms — rest, motor, pain/heat, handgrasp,
dorsal-horn). Built by `validation/normative_qc_db.py` from the per-run
`metrics_index.tsv` + per-level tSNR TSVs the pipeline emits. No field equivalent
exists ("MRIQC normative IQMs, for cord").

## Files
- `normative_qc_metrics.tsv` — per (step, metric): n, mean, sd, median, IQR,
  p5, p95 across all PASS/WARN runs.
- `normative_tsnr_per_level.tsv` — per vertebral level (C1…T5): the same summary
  of median in-cord tSNR (Kaptan 2023 convention).

## How to use
For a new cord-fMRI run, compare its QC metrics against these distributions to
flag outliers (a value below p5 / above p95 is unusual for the field). This is
the normative side of the visual-QC + metrics framework.

## Honest caveats
- **Smoothed tSNR.** `S9.tsnr_post_median` and the per-level tSNR are POST
  anisotropic cord-aligned smoothing (σ 1/1/8 mm; heavy S-I) — substantially
  higher than raw EPI tSNR. They characterise the GLM-ready derivative, not raw
  acquisition SNR. Report the kernel alongside any tSNR norm.
- **Numbers refresh after the locked-σ full re-run** (current derivatives predate
  σ=1/1/8). The aggregation machinery is the deliverable; the table is provisional.
- **Per-level n falls off caudally** (T3–T5 have <6 runs) — thoracic norms are
  under-powered and flagged by n. Cervical (C1–T1) is well-powered.
- Distributions pool paradigms; a per-paradigm split is a straightforward
  extension when framing against published per-paradigm values.
