# SpinePrep — research candidates ledger

Recorded 2026-07-21. VERIFIED by self-audit 2026-07-21 (data claims checked
against the cohort; novelty claims remain second-hand from research agents).

## Verification pass — what changed and why

Adversarial sweep of every candidate against truthful / important / impactful /
useful. Three material findings, all data-checked:

- **C2 DOWNGRADED (backbone -> descriptive).** The "mixed-effects model of tSNR
  determinants" is largely NOT ESTIMABLE. Each of the 9 datasets sits at ~ONE
  point in (TR, voxel size, vendor, FOV) space, so those predictors are
  collinear with dataset itself: a model cannot separate TR from voxel from
  vendor when none varies within a dataset. n=9 in predictor space, not 450.
  Only WITHIN-dataset predictors are estimable -- spinal level, and z-shim in
  ds004386. Honest version: a descriptive tSNR envelope + a per-level gradient +
  the z-shim contrast, NOT a causal determinants model.
- **C5 CONFIRMED TRUE.** Verified the confounds table carries the six families
  (motion 4, spike 25, CSF aCompCor 155, RETROICOR 32, cosine 11; SpinalCompCor
  off) emitted but not regressed. The 155 CSF columns are the design-width
  finding in the flesh. The whole grid is an analysis over the existing table.
- **C1 CONFIRMED, with a framing caveat.** Parcels span ~8 to ~500 voxels as a
  continuum (196 spinal-level parcels alone), so the curve is genuine, not four
  points. BUT split-half of a parcel-mean timeseries measures the reproducibility
  of whatever DOMINATES the signal, which differs by paradigm (task block vs
  rest fluctuation). The cross-dataset claim must be "the SHAPE of the decline
  replicates", not "reliability is X". Level is not comparable across paradigms.
- **C6 reassessed as framing, not a standalone result.** Output variation across
  datasets is driven mostly by genuine data heterogeneity, not pipeline
  instability, so "the defaults are stable" is hard to falsify as a result. Keep
  it as a Discussion framing of the design philosophy, not a Results pillar.

Verdicts that HELD on audit: C3 (biological validity -- dataset counts and
guardrails sound), C4 (distortion -- reversed-PE confirmed in 2 datasets, result
computed). C4's scope is narrow: 2 CoSpine datasets from one lab.

---

## Tier 1 — recommended paper pillars

### C1. Reliability versus spatial scale, replicated across the cohort  [FLAGSHIP]
- **Question:** at what spatial scale does cord fMRI stop being reliable?
- **Method:** split-half reliability (Spearman-Brown corrected) vs parcel size,
  over the four nested tiers (cord ~462 vox -> hemicord ~230 -> spinal level
  ~50 -> GM horn ~8-9), across all 9 datasets and 5 paradigms.
- **Data:** all 9 datasets (split-half needs one run).
- **Novelty:** NOVEL only as a CROSS-DATASET curve. Dabbagh 2024
  (10.1162/imag_a_00273) already compared two spatial scales, so the direction
  is known; the monotone curve replicated across datasets is the new part.
- **Risk:** GM-horn tier is 8-9 voxels, sampling-noise dominated; report with CIs.

### C2. tSNR determinants model  [BACKBONE]
- **Question:** what predicts cord tSNR across acquisition?
- **Method:** mixed-effects model of tSNR ~ TR + voxel size + vendor + FOV +
  spinal level + shim, with dataset as a random effect.
- **Data:** all 9 datasets; the heterogeneity IS the instrument.
- **Novelty:** NOVEL. Cord tSNR is only ever one descriptive number per study;
  no multi-dataset model exists. Individual predictors known (Kinany 2025 plane
  10.1371/journal.pone.0320188; Kaptan 2022 z-shim 10.1002/hbm.26018).
- **Role:** explains WHY reliability collapses at small scales / caudal levels.

### C3. Biological validity across datasets  [VALIDATION — the ground-truth answer]
- **Question:** does the pipeline recover known cord neuroanatomy?
- **Method:** pain -> dorsal horn, motor -> ventral horn, unilateral -> ipsi
  hemicord. Fraction of datasets/subjects recovering the expected parcel.
- **Data:** dorsal (pain) x3 (ds004926, ds005883, painmotor); ventral (motor)
  x5; laterality x2 (ds004616 L/R grip, ds005884 L/R hand); painmotor tests
  BOTH within-subject.
- **Novelty:** NOVEL as a cross-dataset validation. Each dissociation is known
  single-lab; using anatomy as a cross-dataset reference standard is new.
- **HARD GUARDRAILS (from the literature check):**
  - Lead on LATERALITY: strong, single-subject reliable, LI 0.96-0.99
    (Hemmerling 2023 10.1002/hbm.26458; Weber 2016 10.1016/j.neuroimage.2015.10.014).
  - Dorsal/ventral: GROUP LEVEL ONLY. Single-subject ICC 0.03-0.24 at 1x1x5 mm
    (Dabbagh 2024). Never claim per-subject D/V.
  - Name the two confounds: draining-vein signal in dorsal pain; motor->dorsal
    reafference leak. Omitting them reads as naive.
- **Why it matters:** converts "no ground truth" from a limitation into a
  strength; the objection that otherwise caps the paper at NeuroImage.

### C4. Distortion falsification against a measured field  [STRONG]
- **Question:** does image-based SyN improve geometric fidelity or merely change it?
- **Method:** on reversed-PE data, correct with the measured field (TopUp, ref)
  and with SyN (pretending no fieldmap); gap_closed statistic.
- **Data:** CoSpine x2 (ds005883, ds005884) reversed-PE pairs.
- **Novelty:** strong; measured ground truth is rare for a pipeline paper.
- **Status:** result already computed pre-crop-fix; re-confirm on re-run.

---

## Tier 1b — the design-space / importance family (RESOLVED 2026-07-21)

The operator's ablation questions resolved via two literature checks. The
governing rule (Kriegeskorte 2009, 10.1038/nn.2303): any number reported as a
result must come from data that played no part in choosing the configuration
that produced it. So: CHARACTERISE the design space (report the landscape, name
no winner) -- do NOT OPTIMISE (pick the config that maximises a metric on the
cohort, then report that metric on the cohort = double dipping, invalidates the
validation). Optimisation is legitimate only via leave-one-dataset-out with
held-out reporting, and at n=9 the honest outcome is usually "the defaults
already generalise".

### C5. Confound-regressor importance -- the cord Ciric 2017  [PROMOTE TO TIER 1]
- **Question:** which of S8's six confound families help, and at what cost in
  temporal degrees of freedom?
- **Method:** the Ciric 2017 / Parkes 2018 template (VERIFIED gap: no cord
  equivalent exists). Fix everything upstream, vary only the confound model as a
  leave-one-family-out / add-one-family grid over the six S8 families. Score on
  ground-truth-free metrics, report the Pareto trade-off, name no single winner.
- **Metrics (both sides, always):**
  - noise removed: QC-FC + distance-dependence (REST ONLY, 2 datasets),
    DVARS/FD residual, tSNR gain.
  - signal/DOF preserved: activation sensitivity (TASK, 7 datasets),
    tSNR-vs-overcleaning, tDOF-loss = regressors + censored frames.
  - benefit-per-DOF is the field-standard denominator (Bright & Murphy 2015,
    PMC4461310): even random regressors remove network-structured variance by
    spending DOF, so every gain is reported net of DOF spent.
- **Why it is unusually cheap and strong here:** S8 EMITS the six families
  WITHOUT regressing them, so the whole grid is an analysis over the existing
  confounds table -- no re-runs. It converts our design-width finding (median
  139 regressors vs 227 frames; 8.7% rank-deficient) from a caution into a
  quantified result: where cord confound models cross into DOF bankruptcy.
- **Task/rest split:** QC-FC only on the 2 rest datasets (report as a sub-
  analysis, do not force it); task datasets use activation sensitivity + tSNR +
  DVARS. Precedent: Hemmerling 2025 judged SpinalCompCor by task activation and
  found NO benefit -- a cautionary result our benchmark would contextualise.
- **Novelty:** VERIFIED open gap. Ciric 2017 (10.1016/j.neuroimage.2017.03.020)
  and Parkes 2018 (10.1016/j.neuroimage.2017.12.073) are heavily cited brain
  papers with no cord analog.

### C6. Cross-dataset stability of the pipeline defaults  [TIER 1b, the generalizability answer]
- **Question:** do SpinePrep's fixed, literature-grounded defaults produce
  stable, generalizable outputs across 9 heterogeneous datasets, without
  per-dataset tuning?
- **Method:** multiverse-across-datasets (Steegen 2016; Carp 2012; Demidenko
  2024, 10.1162/imag_a_00262). Report how each endpoint moves across defensible
  configs and across the 9 datasets; show the defaults sit in the stable region.
  Name no winner. This is CHARACTERISATION, zero circularity exposure.
- **Why it is the right form of the operator's "optimise for generalizability"
  question:** optimising for generalizability across all 9 and reporting on all
  9 still overfits to the SET. The defensible version is to CHARACTERISE
  stability, or -- only if a recommendation is truly wanted -- leave-one-
  dataset-out with held-out spread and selection stability (Dadi 2019,
  10.1016/j.neuroimage.2019.02.062). At n=9 the outer loop is small; report CIs.
- **On-brand:** validates the "literature defaults, lock the step" philosophy
  (invariant 5 + 8) rather than replacing it.

### C6-step. Full preprocessing-step ablation  [TIER 2, characterisation only]
- Re-run with each step ablated; measure endpoint change. EXPENSIVE (multiple
  cohort re-runs) and more exposed to the optimise/characterise line. Keep as
  multiverse only. Note: the distortion step already HAS its ablation for free
  (topup vs SyN vs none = C4), so the highest-value step-ablation is already
  covered.

## Tier 2 — supporting / demoted (kept, with reasons)

- **C7. Rostrocaudal quality gradient per level** — INCREMENTAL; folds into C2.
- **C8. z-shim effect on reliability** — tSNR effect ALREADY DONE (Kaptan 2022);
  only z-shim->reliability is open; folds into C2. NB ds004386's two runs are
  auto/manual z-shim, NOT repeats (driver corrected 2026-07-21).
- **C9. Physiological-noise geometry** (cardiac/resp variance per level/tissue)
  — 7 datasets have physio, but Barry/Eippert characterised this; incremental.
- **C10. Detectability x scale** — strong but is the effect-family companion to
  C1; better inside C1 than standalone.
- **C11. Vertebral vs spinal level parcellation** — does the choice change
  localisation? Niche methods point; now feasible (both emitted).
- **C12. Confound design-matrix degeneracy** (8.7% rank-deficient) — a
  cautionary note, not a headline; pairs with C5.

## Dropped (done or low-value)
- Resting-state connectivity reliability — done thoroughly (Kaptan 2023).
- Denoising-strategy comparison as a standalone — SpinalCompCor (Hemmerling
  2025) partly covers; better as C5.
- Re-analysing paradigm effects to restate original findings — adds nothing.

---

## The recommended spine (pre-ablation-research)

    C1 flagship (reliability vs scale, cross-dataset)
      + C2 backbone (tSNR determinants -- explains the curve)
      + C3 validation (biological, laterality-led)
      + C4 strong (distortion falsification)

RESOLVED: C5 (confound importance, the cord Ciric 2017) PROMOTES TO TIER 1 --
verified open gap, cheap (analysis over existing confounds), turns the design-
width finding into a result. C6 (cross-dataset stability) is the on-brand
generalizability contribution. Neither optimises; both characterise.

    C1 flagship   reliability vs scale, cross-dataset
    C5 method     confound-family importance (Ciric-style, cord-first)
    C2 backbone   tSNR determinants -- explains the curve
    C3 validation biological, laterality-led
    C4 strong     distortion falsification (also the free step-ablation)
    C6 framing    defaults generalise across 9 datasets (validates the design)
