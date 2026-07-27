# Round 2 results — the geometry-not-statistics programme

Every experiment proposed in `FLAGSHIP_IDEAS.md` Round 2, executed end to end on the
locked cohort (`preproc-v1`, git `961a779`, `/mnt/ssd1/spineprep_cohort_s2`).
Scripts: `analysis/experiments/n{1..5}_*.py` and `r{1,2,5..10}_*.py`.
Proven findings live in `FLAGSHIP_FINDINGS.md`; the full record is `COMPENDIUM.md`.

Compiled 2026-07-27.

---

## The headline

**R10, the pruned multiverse, is the strongest result of this round.** Across 54
fully defensible analysis pipelines per dataset:

| dataset | pipelines finding a significant POSITIVE effect | sign flips? | d range |
|---|---|---|---|
| ds004616 | 16/54 (**30%**) | yes | −0.56 to +1.04 |
| ds004926 | 13/54 (**24%**) | yes | −0.12 to +0.94 |
| ds005883 | 8/54 (**15%**) | yes | −0.16 to +0.44 |
| ds005884 | 9/54 (**17%**) | yes | −0.23 to +0.88 |

The sign flips in **all four** datasets. A single published cord pipeline reporting a
positive result was **choosing, not discovering**, and the choice was invisible to
the reader. Which axis matters most, measured as the spread of group *d* across each
axis's levels:

| axis | mean spread in d |
|---|---|
| **summary measure** | **0.329** |
| smoothing | 0.166 |
| censoring fraction | 0.120 |
| confound set | 0.107 |

That independently confirms F2: the ROI summary measure is the single most
consequential analysis choice in cord fMRI. And the number is a **lower bound** —
distortion correction could not enter the multiverse, because changing it means
re-running the pipeline rather than re-analysing its output, and F1 found the largest
single effect on exactly that axis.

The pruning is itself part of the result. Four axes were excluded because this
project had already measured them as inert: high-pass filtering, physiological
modelling, prewhitening, and the inference method. A multiverse over inert axes is
padding.

---

## The thesis, tested

Round 2 opened by withdrawing the Round 1 thesis (that cord fMRI's borrowed
*inferential* machinery misfires) because N1 and the paired-organ control refuted it.
Its replacement was **the cord's problem is geometry, not statistics**. R2 was built
to test that directly rather than assume it.

**R2 did not confirm it, and the honest verdict is a null.** No QC metric predicts
per-run scientific outcome: every family has a negative leave-one-dataset-out R²
(noise −0.491, motion −0.033, geometry −0.026, registration −0.106, template −0.009,
design −0.038, all −0.013), meaning each predicts an unseen scanner worse than that
scanner's own mean. The geometry block does beat the noise block (−0.029 vs −0.452),
the predicted direction, but both are below zero so the ordering carries no weight.

So the thesis survives as a *description* of which findings exist, not as a
predictive claim. It should be presented that way.

---

## Every result

### R10 — pruned multiverse ★★★
See above. 216 pipelines across 4 datasets. Novel for the cord *(unchecked)*.

### R2 — no QC metric predicts scientific outcome ★★
30 metrics from 6 pipeline steps, 7 families fixed in advance, 191 runs. All CV R²
negative. **The metrics flag broken runs; they do not rank usable ones** — which is
the honest supporting statement for a project whose invariant is that visual QC is
the validator.

**It also caught a caveat on our own estimator, which matters more than the null.**
Three metrics reached p<0.05 pointing the wrong way (higher tSNR → *smaller* effect,
ρ = −0.21). Calibrated against N1's 126 resting runs, the same estimator behaves that
way with **no task present at all**: ρ = −0.300 (p=0.003) and −0.478 (p=0.009). The
real-data correlation is *smaller than the null*.

*Mechanism:* odd and even timepoints are **interleaved**, so spatially structured,
temporally persistent signal — residual drift, aliased pulsation, a vessel — sits in
both halves and survives the split-half CV. Same failure family as the retracted
high-pass result.

*Scope, stated precisely because it touches published numbers.* The group **mean** is
unbiased (N1's group test 5.0% and 4.0% against nominal 5%; null mean −0.058,
p=0.27). Comparisons that hold runs fixed and vary the method are therefore safe —
**F2, the N4 kernel arms, tier-1 group d, and R10 all qualify.** What is *not* safe is
comparing the estimator's magnitude across runs or datasets of differing noise, or
correlating it with anything noise-related.

### N1 — false-positive rate of cord inference: valid ★★
126 resting runs × 200 random designs. Bonferroni FWE 5.9% [5.3, 6.6] vs nominal 5%;
FDR 6.3%; cluster inference **1.4%, conservative** — the reverse of Eklund's brain
result. Parametric t null correct to 1.00–1.02×. Residuals already white (−0.050) and
AR(1) prewhitening makes FWE *worse* (8.6%), so it should not be applied.

Two keepers: uncorrected p<0.001 declares activation in **53%** of runs containing
none; and the **null effect-size floor**, |d| p95 = **0.31**, which puts ds004926's
d = 0.11 inside the null band and independently confirms the F5 non-replication.

### Paired-organ control — the cord is better behaved than the brain ★★★
ds005884/ds005883/ds005075 acquire 70 slices at 4 mm — 280 mm of coverage, cord and
brain in **one EPI volume**. Verified: S3's cord segmentation occupies slices 0–34 and
brain tissue 42–65 of the same grid. Same raw data, same nuisance model, 107 runs.

| | FWE | FDR | cluster | t p99.9/theory | tSNR |
|---|---|---|---|---|---|
| brain | 28.7% | 30.1% | 57.8% | 1.19× | 50.1 |
| **cord** | **10.4%** | **11.1%** | **2.9%** | **1.05×** | 18.0 |

Paired Wilcoxon p = 3.3×10⁻¹⁸. The cord is closer to nominal on every inference
measure at a third of the brain's tSNR. Within-run, so no confound remains to name.

**The dilution prediction FAILED, informatively.** The curves do not superimpose: in
the pain dataset the brain's mean *rises* with ROI size (+0.84 → +1.18) while the
cord's collapses and inverts (+0.47 → −0.01); in the motor dataset the brain dilutes
too. The governing variable is **activated extent ÷ ROI size**, not the organ — the
brain dilutes exactly as the cord does when its activation is focal (M1). The cord's
problem is that its activation is focal in *every* task. At a matched 19-voxel ROI the
organs are comparable (+0.84/+0.50 vs +0.47/+0.52).

*Anomaly recorded, not explained:* ds005884's cord mean rises to +0.72 at 657 of ~848
cord voxels. R5 below shows a global signal cannot account for it in the locked
preprocessing.

### N5 — the peak carries no subject information ★★★
Audit first, and it came out clean: F3 recorded peaks as native voxel index × voxel
size, i.e. each subject's own cropped grid, so crop placement could have been inside
the number. Against a crop-free coordinate the inflation is 0.95–1.13×. **F3's frame
was fine.**

The replacement is stronger than F3's claim:

| | between runs, same session, same subject | between subjects |
|---|---|---|
| ds004616 | **12.40 mm** | 11.44 mm |
| ds005884 | **36.40 mm** | 24.80 mm |

ICC(2,1) on the rostrocaudal peak: **+0.16, +0.03, +0.05, −0.04**. Within-subject
repeats share the *same registration*, so an ICC of zero across them cannot be blamed
on normalisation — it is measurement noise. The claim becomes *the single-run cord
peak is not a measurement of that subject.*

*Guardrail:* the in-plane SDs (0.27–0.68 mm) are **not** evidence of good
localisation. The horn is a 15-voxel column, 72 mm long and a couple of voxels across,
so in plane the peak has nowhere to go. The negative in-plane ICCs are that ceiling.

### R3 + R4 — coarser summaries reproduce; nothing survives a session gap ★★
Solved the common-space problem that killed the earlier leave-one-subject-out attempt
by abandoning voxels: each run becomes a vector over anatomical cells (6 GM horn
parcels × spinal level) from the warped PAM50 atlas.

A monotone ordering, after the tSNR and mean-signal patterns are regressed out:

| spatial summary | within-subject similarity |
|---|---|
| peak (N5) | ICC ≈ 0 |
| pattern, horn × level | +0.08 to +0.19 |
| **profile, level only** | **+0.22 to +0.36** |

**But scoped by the repeat axis, and the split is systematic.** The profile result is
significant in exactly the two datasets whose repeats are runs minutes apart in one
session (balgrist_motor p=0.001; balgrist_painmotor p=0.004–0.028) and absent in both
whose repeats span sessions (ds004616 p=0.88, ds004926 p=0.18). So **the profile
reproduces across runs minutes apart and does not survive a session gap**, agreeing
with N5's large between-session variance.

*What fails:* identification accuracy is at chance for the task pattern everywhere,
while the **mean-signal and tSNR maps identify strongly** (0.56–0.60 vs 0.04–0.11
permuted chance, p<0.0001). Anatomy and vasculature are a powerful cord fingerprint;
the task response is not. The anatomy control was essential — the tSNR *profile* shows
a larger within-vs-between gap (+0.885 vs +0.622) than the task profile does.

### R1 — no behavioural coupling ★★
The external criterion the project never had. **Two corrections to the plan first:**
ds004926's `temperature` is constant at 48.00 °C across all 1600 trials, and its
`rating` is a **run-level** value, identical across all 20 trials (within-run SD
exactly 0 in all 76 runs). Only ds005883's PR/UpR are trial-wise; only ds004616's
grip force is a physical measurement.

| criterion | ipsi horn | contra horn | whole cord |
|---|---|---|---|
| grip force (100 Hz, physical) | +0.055 (p=0.43) | +0.036 | −0.027 |
| pain intensity | −0.097 (p=0.044) | −0.022 | +0.029 |
| unpleasantness | −0.043 | +0.011 | +0.025 |

The one nominal hit is **negative**, is 1 of 15 tests, and its criterion correlates
with trial-wise DVARS (ρ=+0.137, p=0.011). Run-level rating: ρ=+0.107 (p=0.36),
+0.049 partialling tSNR and FD; the within-subject paired change gives −0.111 in the
target and its only significant result (+0.458, p=0.032) is in the **contralateral
control** — evidence against a real effect.

### R6 — the biomarker ceiling ★★
Arithmetic over measured reliabilities. With a between-session effect ICC of 0.05:

| | |
|---|---|
| max correlation with a well-measured clinical score | **0.21** |
| N to detect it at 80% power, if the true relation is perfect | **172** |
| independent sessions per subject to reach ICC 0.75 | **57** |
| independent sessions to reach ICC 0.60 | 28 |

Largest published cord studies run n = 20–48. **Constructive half:** resting
connectivity at ICC 0.49 (Kaptan 0.63) needs 3 sessions for the good band and has a
ceiling correlation of 0.66. If the field wants an individual-level spinal measure,
the arithmetic points at connectivity, not task activation.

### R7 — the confound model spends most of the run ★★
From the per-run S8 metrics the pipeline already writes, 450 runs.

| family | median columns | share |
|---|---|---|
| **CSF (slice-wise aCompCor)** | **110** | **78%** |
| RETROICOR | 16 | 11% |
| outlier / spike | 13 | 9% |
| cosine drift | 11 | 8% |
| motion | 5 | 4% |

- **85.8%** of runs spend more than half their frames on confounds
- **7.8%** have regressors ≥ frames, i.e. no residual degrees of freedom
- ds005884: 115 frames vs 168 columns → **dof = −54**; ds005883: 230 vs 209 → dof 21

The CSF count is 5 components *per slice*. No published implementation uses a
per-slice count; against the totals those papers report, ours is 12× Hemmerling 2026,
18× Behzadi 2007, 22× Ricchi 2024, 37× Muschelli 2014. Analytic cost (t scales as
√dof): replacing it with 5 components **total** recovers 105 dof per run, worth **48%
more t per unit effect**. The confound-family benchmark already found no family
improves sensitivity, so nothing sits on the other side of the ledger.

### R8 — the binary call is no better ★
| responder definition | pooled kappa |
|---|---|
| unselected horn mean > 0 | +0.184 (p=0.061) |
| cross-validated top-10% > 0 | −0.052 (p=0.712) |

Chance agreement computed from the observed marginal rate (0.40–0.67), not assumed to
be 50%. One cell reaches significance (ds004616 left, kappa +0.538) while its mirror
condition in the same runs does not (right, −0.025) — a criterion that works for one
hand and not the other in the same subjects is noise.

### R9 — model-free detection works, at 1–3% ★
Validity checked rather than assumed: onset sequences compared across runs give 17
runs sharing timing in ds004616 and all 46 / 43 in the balgrist datasets, while
ds004926 and ds005883 have fully subject-specific jitter (60 and 39 distinct
sequences) and are **excluded rather than fudged**.

| dataset | ROI | ISC | shift null | p |
|---|---|---|---|---|
| ds004616 | whole cord | **+0.0295** | −0.0004 | <0.001 |
| ds004616 | a-priori horn L | +0.0125 | +0.0007 | 0.035 |
| balgrist_motor | a-priori horn R | +0.0075 | +0.0001 | <0.001 |
| balgrist_cospigvs | all | ≈ 0 | — | ns |

So shared stimulus-driven signal **is** detectable with no HRF and no design matrix —
but at 1–3% correlation, against 0.3–0.6 for brain sensory cortex, i.e. one to two
orders of magnitude smaller.

**Caveat that limits it, and it is serious.** ISC cannot separate shared neural
response from shared task-locked *artifact*: every subject grips at the same times, so
movement and respiration are synchronised by the stimulus exactly as neural activity
is. Motion regression was applied but is imperfect. The whole-cord ISC being *larger*
than the a-priori horn's (+0.0295 vs +0.0125) argues for the artifact reading rather
than against it.

### R5 — the cord has no large global signal (null)
Motivated by the paired-organ anomaly. 191 runs. Median variance explained by the
whole-cord mean timeseries: **0.008–0.020** (90th percentile 0.078–0.130) — 1–2%,
against tens of percent in the brain. Task coupling reaches p<0.01 in 3 of 4 datasets
but the correlations are −0.043, +0.027, −0.010, +0.109, i.e. negligible; reported as
magnitudes rather than significance for that reason. RETROICOR explains 14–27% of it,
motion 9–18%, so most is unexplained by anything modelled. Removing it is
inconsistent (ds004616 improves 0.26→0.43 p=0.034; ds004926 and ds005884 degrade). No
basis for adding global signal regression.

**The anomaly is not explained.** 2% of variance cannot produce d = +0.72 over 657
voxels. The two analyses do not share an input — the anomaly was raw EPI with cosine
drift only, this is preproc-v1 with the lean set — so the consistent reading is that
a raw-data global component exists and the locked preprocessing already removes most
of it. Testing that needs the global signal measured on raw data, which was not done.

### N4 — cord-shaped smoothing FAILED (negative result)
12 kernel arms, 191 runs. Prediction was rostrocaudal > isotropic > in-plane, on the
reasoning that a 4–6 mm isotropic kernel is wider than a 4.5 mm² horn. Measured
medians: iso **+0.482**, rostrocaudal +0.285, in-plane +0.173. **Not confirmed.** Two
side observations worth more than the ranking:

1. **No arm changes the effect.** Paired subject-level Wilcoxon against no smoothing:
   every arm p > 0.18. The group-d spread from +0.189 to +0.482 comes from smoothing
   shrinking the **between-subject SD**, not from raising the effect. Any claim that
   smoothing "improves sensitivity" in the cord must say which of the two it means.
2. **The field's "isotropic" kernel is not isotropic.** At ~4 mm slices a 2 mm FWHM
   kernel has σ_z = 0.21 voxels and a 4 mm kernel 0.42; iso2 and inplane2 return
   bit-identical results for that reason. Only at 6 mm does an isotropic kernel blur
   across slices. So what the literature calls isotropic smoothing is in practice
   in-plane smoothing, and the rostrocaudal arms are the only ones doing something
   genuinely different — which is why their failure is informative rather than trivial.

### N3 — multivariate detection: design repaired twice, still running
Two invalid designs were built and discarded before a valid one:

1. **Leave-one-block-out with a trained classifier is biased below chance.** The bias
   tracked exactly which arms train — untrained univariate mean 0.518, voxel selection
   0.430, LDA 0.362 — and the permutation null it shipped with read 0.25–0.47 instead
   of 0.50. Replaced with 5-fold CV, AUC computed *within* each fold and averaged, no
   cross-fold pooling of decision values. That fixed the null to 0.488–0.504.
2. **The baseline sampling was confounded with time-in-run.** In ds004926 only 13% of
   frames are event-free and their mean index is **157 against 77** for task windows,
   so the classifier was learning position in the run. Replaced with an interleaved
   condition-vs-condition design wherever a second condition exists, plus removal of a
   linear time trend fitted on the training fold only, plus the class time gap
   reported next to every result.

**Final numbers, valid design** (permAUC 0.492-0.505 everywhere; class time gap 0.0
frames on the interleaved arms):

| dataset | design | ROI | AUC mvpa | p | AUC uni-mean |
|---|---|---|---|---|---|
| ds005883 | cond-vs-cond | **whole cord** | **0.639** | **0.0001** | 0.500 |
| ds005883 | cond-vs-cond | hemicord | 0.614 | 0.0005 | 0.500 |
| ds005883 | cond-vs-cond | a-priori horn | 0.563 | 0.051 | 0.500 |
| balgrist_painmotor | cond-vs-cond | whole cord | 0.557 | 0.049 | 0.499 |
| ds004616 | cond-vs-cond | all | 0.466-0.503 | ns | 0.500-0.661 |
| ds004926 | task-vs-rest | all | 0.442-0.518 | ns | 0.502-0.509 |

**One clean positive, and it is the constructive twin of F2.** In ds005883 the
univariate mean sits at exactly 0.500 while multivariate detection reaches 0.639 from
the **whole cord** -- no anatomical guess required. There the signal is present and
averaging discards all of it.

**But it does not generalise.** Pooled across datasets nothing is significant (horn
0.521 p=0.13, hemicord 0.520 p=0.28, cord 0.532 p=0.076), and 3 of 5 datasets are
null. So multivariate detection can rescue a univariate null but does not reliably do
so.

*Caveat retained:* ds004926 and ds005884 could not use the interleaved design (single
condition) and their class time gap is -85 and -79 frames, so those two rows stay
confounded with time-in-run and are not interpretable.

---

## What this round changed

**Withdrawn.** The Round 1 thesis, refuted by N1 and the paired-organ control.

**Qualified.** Every split-half top-10% magnitude in the project — safe for
method-vs-method comparison on fixed runs, unsafe across runs of differing noise.

**Strengthened.** F3 becomes N5 (peak ICC ≈ 0, registration exonerated). F2 becomes
the dominant axis of a 216-pipeline multiverse.

**New.** R10's analytic variability; the paired-organ inference comparison; the null
effect-size floor; the DOF budget; the biomarker ceiling.

**Failed predictions, kept visible.** Cord-shaped smoothing (N4), QC-predicts-outcome
(R2), behavioural coupling (R1), the global-signal explanation of the anomaly (R5),
the dilution superposition (paired-organ B). Five of eleven predictions were wrong.

## Coherent picture across the individual-level results

Nothing tested supports a statement about an individual cord:

| what | measured |
|---|---|
| effect magnitude | ICC ≈ 0.05 |
| peak location | ICC ≈ 0; between-run noise ≥ between-subject variance |
| response pattern | identification at chance |
| profile | reproduces within session, not across sessions |
| behavioural coupling | absent at trial and run level |
| binary responder call | kappa ≈ 0 |
| required repeats for usable reliability | 57 sessions |

Group-level detection works; individual-level inference does not. That is one
consistent message from seven independent estimators, and it is the most defensible
claim this round produced after R10.

## Open

- N3's final numbers.
- The ds005884 whole-cord anomaly, still unexplained; needs the global signal measured
  on raw rather than preprocessed data.
- Novelty marks throughout are *(unchecked)* and must clear a literature review before
  entering prose, on the F1 standard.
- R10 excludes distortion; adding it requires re-running S5 per arm and would raise the
  reported spread.
