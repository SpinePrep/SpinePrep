# SpinePrep analysis — real-cohort results

Computed by `analysis/run_all.py` on the crop-fix cohort at
`/mnt/ssd1/spineprep_cohort_s2` (S9: 450/450 runs PASS; top cord slice recovered;
4D `PAM50atlas_probseg` emitted). 324 runs carried a modelled task (126 rest runs
skipped). Every number below traces to a table under `analysis/results/`
(gitignored — regenerate with the one command). Provisional only in the sense
that the distortion arm (C4) still needs its dual-mode run.

Recorded 2026-07-22.

## Q1 (flagship) — reliability degrades with spatial scale

Split-half reliability (Spearman-Brown corrected), median across the cohort, by
tier. Monotone decline confirmed, and it replicates per dataset (F4).

| tier | ROI voxels | n endpoints | median SB r |
|---|---|---|---|
| cord | ~462 | 450 | 0.423 |
| hemicord | ~230 | 900 | 0.386 |
| spinal level | ~50 | 3263 | 0.289 |
| vertebral level | ~50 | 2937 | 0.289 |
| grey-matter horn | ~8-9 | 2698 | 0.243 |

The level is modest even at the cord (~0.42), consistent with the reliability
paradox: task designs optimised for a group effect suppress between-subject
variance. The result is the SHAPE, not the level.

## C3 — biological validity: succeeds at hemicord scale, NULL at horn scale

Laterality (motor -> ipsilateral hemicord), single-subject:

| dataset | fraction of subjects ipsi-dominant | n |
|---|---|---|
| ds004616 handgrasp | 0.917 | 24 |
| ds005884 CoSpine motor | 0.682 | 22 |

Dorsal/ventral horn dissociation (group Cohen's d of expected-minus-other horn).
**This is a null.** Only 1 of 5 datasets shows the expected direction with any
magnitude; the rest scatter around zero or reverse.

| dataset | expected horn | group d | expected-frac |
|---|---|---|---|
| ds004926 pain | dorsal | -0.012 | 0.475 |
| ds005883 pain | dorsal | -0.277 | 0.405 |
| ds004616 motor | ventral | -0.316 | 0.458 |
| ds005884 motor | ventral | +0.368 | 0.591 |
| internal motor | ventral | -0.365 | 0.364 |

Interpretation (honest, and it strengthens Q1): the ~8-voxel horn is below the
reliability floor the Q1 curve locates, so the dissociation is not recoverable in
this cohort even at group level. This matches Dabbagh 2024 (single-subject horn
ICC 0.03-0.24 at 1x1x5 mm). The validation succeeds exactly where the scale
supports it (hemicord) and fails exactly where the scale does not (horn) — the
biology traces the same limit the reliability curve draws.

## C5 — confound-family importance (the cord Ciric benchmark)

Mean over 28 benchmarked runs (4 per dataset). Task sensitivity = top-decile |t|;
DVARS-resid = median residual DVARS; DOF = regressors spent.

| family set | sensitivity | DVARS-resid | DOF |
|---|---|---|---|
| motion | 2.89 | 37.8 | 4 |
| motion+spike+cosine | 2.65 | 36.7 | 28 |
| +retroicor | 2.54 | 33.6 | 49 |
| +csf | 2.19 | 22.8 | 134 |
| +csf+retroicor (full) | 2.20 | 20.3 | 154 |

CSF aCompCor is strictly dominated for task detection: it spends 100+ DOF and
LOSES sensitivity (2.65 -> 2.19). RETROICOR is the sweet spot — 21 extra DOF,
sensitivity nearly held, DVARS reduced. This quantifies the design-width finding
(median 139 regressors vs 227 frames; 8.7% rank-deficient) and matches Hemmerling
2025's SpinalCompCor-shows-no-task-benefit caution.

## Q2 — quality envelope

Cord tSNR median per dataset spans 16.4 (ds004926) to 25.4 (ds005075), a ~1.5x
range across vendors/FOV/TR. The spread is the finding; per-spinal-level
distributions are in F5.

## C4 — distortion falsification: PENDING

Needs each CoSpine reversed-PE run corrected both ways (TopUp reference vs SyN).
The statistic is implemented and unit-verified; the dual-mode run has not been
launched. `distortion.csv` is empty until `qc_syn.json` exists.

## Reproduce

    python3 -m analysis.run_all /mnt/ssd1/spineprep_cohort_s2
    python3 -m analysis.figures
