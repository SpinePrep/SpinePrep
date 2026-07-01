# Validation

SpinalfMRIprep is validated end-to-end on **8 datasets / 384 functional runs /
5 paradigms** (rest, motor, pain/heat, hand-grasp, dorsal-horn) spanning public
(OpenNeuro) and internal cohorts, multiple vendors, and a range of acquisition
protocols (with and without fieldmaps; cervical-only and whole-CNS FOV).

> **Note.** Numbers below reflect the locked smoothing kernel (σ = 1/1/8 mm):
> 6 of 7 scopes were reprocessed at the locked policy (all 7 scopes, including whole-CNS
> brainspine, reprocessed). The reliability values proved **robust to the kernel
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
- **Task activation** (per-level beta, active-vs-rest): poor — mean ICC ~0.06
  (handgrasp, dorsalhorn). Consistent with the known low reliability of cord
  *task* fMRI (Dabbagh 2024); the per-level-mean measure also dilutes focal
  (horn-specific) activation — a limitation of the measure, not the pipeline.

These fair-to-moderate values are **consistent with the known difficulty of
cord-fMRI reliability** — connectivity ICC is predominantly poor in the field
(Kaptan 2023; Kowalczyk 2024) and task-activation reliability is poor (Dabbagh
2024). Note split-half temporal stability (Ricchi 2024) runs higher but is
inflated relative to true test-retest; we report between-session ICC. Cross-shim
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

Across **24 runs / 4 cervical scopes** (dorsalhorn, handgrasp, cosmotor, cospain),
our recipe gives **cord-Dice 0.904 ± 0.03 vs SCT-default 0.704 ± 0.10 (+0.20;
Wilcoxon p = 1.2×10⁻⁷; ours higher in 24/24 runs)** — a large, consistent, highly
significant improvement. Note the comparator is SCT's *out-of-the-box* defaults,
not SCT at its best: SCT itself recommends cord-segmentation-driven registration
with structural-warp initialization — the very recipe SpinalfMRIprep automates.
So this quantifies the cost of naive default usage and the value of baking the
recommended recipe into a turnkey pipeline, not a claim to out-register SCT's
best practice.

![Head-to-head cord Dice](../../validation/results/figures/headtohead_dice.png)

## 5. Reproducibility

Every release ships a `reproducibility_receipt.json` (tool versions, per-step
policy SHA-256, pipeline git SHA), BIDS-Derivatives `dataset_description.json`,
auto-generated methods boilerplate, and `CITATION.cff`. Same chain + same policy
+ same git SHA → byte-identical re-run.
