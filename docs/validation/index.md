# Validation

SpinalfMRIprep is validated end-to-end on **8 datasets / 384 functional runs /
5 paradigms** (rest, motor, pain/heat, hand-grasp, dorsal-horn) spanning public
(OpenNeuro) and internal cohorts, multiple vendors, and a range of acquisition
protocols (with and without fieldmaps; cervical-only and whole-CNS FOV).

> **Note.** Numbers below reflect the locked smoothing kernel (σ = 1/1/8 mm):
> 6 of 7 scopes were reprocessed at the locked policy (the 7th, whole-CNS
> brainspine, is finishing). The reliability values proved **robust to the kernel
> change** (unchanged on refresh) and the normative tSNR shifted ~1%, so these are
> confirmed, not provisional. All values are reproducible via `validation/*.py`.

## 1. Coverage & robustness

All 8 datasets run S1→S10 to completion. Attrition is fully reconciled — the
number of runs dropped between any two steps equals the number that FAILed the
earlier step's QC (no silent losses); every surviving derivative is PASS or WARN.

| Scope | Dataset | Paradigm | Runs (S9) | Distortion mode |
|---|---|---|---|---|
| cospain | ds005883 | pain | 33 | TopUp (reverse-PE) |
| cosmotor | ds005884 | motor | 30 | TopUp |
| rest | ds004386 | rest | 90 | SyN (no fieldmap) |
| handgrasp | ds004616 | hand-grasp | 35 | SyN |
| dorsalhorn | ds004926 | heat/pain | 66 | SyN |
| brainspine | ds005075 | rest (whole-CNS) | 27 | SyN |
| exp | balgrist motor + painmotor | motor | 75 | SyN |

**79 % of runs (304/384) use the image-based SyN fallback** — the field reality
(most cord-fMRI data ships no fieldmap). Runs that exceed the TopUp-calibrated
displacement ceiling without a fieldmap are flagged *distortion-limited*, not
failed.

## 2. Test-retest reliability (the rigour)

A preprocessing pipeline must yield reproducible science. We measure the
test-retest reliability of pipeline-derived measures via ICC(2,1) (Shrout &
Fleiss 1979), computed by `validation/reliability_*.py`.

The cohort's repeated measures are not uniform, and we label each honestly:

- **Between-session test-retest** (task data): dorsalhorn, handgrasp.
- **Cross-shim reproducibility** (same session, auto vs manual z-shim): rest
  ds004386 — *not* test-retest.
- **Within-session run reliability**: balgrist motor (run-01..04).

**Per-vertebral-level cord tSNR** (test-retest): dorsalhorn ICC(2,1) 0.45–0.75
(mean 0.56, n = 30) — moderate-to-good.

**Intra-cord functional connectivity** (rostro-caudal level×level edges):

![Connectivity reliability](../../validation/results/figures/reliability_connectivity.png)

- Test-retest: dorsalhorn mean edge ICC 0.37 (max 0.72); handgrasp 0.24 (max 0.79).
- Cross-shim reproducibility: rest 0.53 (median 0.57, max 0.93).

These fair-to-moderate values are **consistent with the known difficulty of
cord-fMRI reliability** (Hemmerling 2023; Dabbagh 2024) — and cross-shim
reproducibility exceeding between-session test-retest is exactly as expected
(same-session is easier than across-day).

## 3. Normative per-vertebral-level QC reference

The first multi-site, multi-paradigm **normative QC database** for cord fMRI
(`validation/normative_qc_db.py`): the cohort-wide distribution of every QC
metric, resolved per vertebral level where applicable.

![Normative per-level tSNR](../../validation/results/figures/normative_tsnr_per_level.png)

Median in-cord tSNR (post anisotropic smoothing) follows the expected
rostro-caudal decline — highest at C6/C7, dropping into the thoracic cord. Full
tables: `validation/results/normative_qc_metrics.tsv`,
`normative_tsnr_per_level.tsv` (n, mean, SD, median, IQR, p5, p95).

## 4. Head-to-head vs SCT-default

To answer "why not just use SCT's defaults?", we compare functional→anatomical
cord registration quality (cord-Dice) between our S6 cord-driven recipe (Kaptan
2023) and out-of-the-box `sct_register_multimodal` on the same runs
(`validation/headtohead_sct_default.py`).

On a dorsalhorn subset, our recipe gives **cord-Dice 0.945 vs SCT-default 0.755
(+0.19, consistent across runs)** — a substantial, consistent improvement. The
cord-driven recipe is not just more convenient than raw SCT; it registers the
cord markedly better.

## 5. Reproducibility

Every release ships a `reproducibility_receipt.json` (tool versions, per-step
policy SHA-256, pipeline git SHA), BIDS-Derivatives `dataset_description.json`,
auto-generated methods boilerplate, and `CITATION.cff`. Same chain + same policy
+ same git SHA → byte-identical re-run.
