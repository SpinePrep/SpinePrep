---
status: approved
---

# How to choose the cord FD censoring threshold — evidence report

Written 2026-07-16. Question: `fd_threshold_mm: 0.5` fails 12% of the cohort
(49% once FD is composed correctly). What is the rigorous way to set it?

**Bottom line: 0.5 mm is not merely brain-derived, it is not the same QUANTITY
as Power's FD, and Power's own criterion for picking 0.5 gives a different answer
on cord data. There is no voxel-scaling rule to rescue it. Every rigorous option
converges away from an absolute FD number.**

## 1. How Power actually derived 0.5 — and why it inverts here

VERIFIED, Power 2012 ([PMC3254728](https://pmc.ncbi.nlm.nih.gov/articles/PMC3254728/)),
verbatim:

> "After studying the plots of dozens of healthy adults, values of 0.5 for
> framewise displacement and 0.5% ΔBOLD for DVARS were chosen to represent values
> **well above the norm found in still subjects**"

and

> "thresholds are chosen to simply identify the most egregiously suspect frames."

So the criterion is **distributional**: 0.5 was picked because it sits far out in
the tail of a still subject's FD distribution. It was not derived from FD-vs-DVARS
and not from distance-dependent artifact — it was chosen by inspecting plots.

**This is the load-bearing finding.** On our cohort, correctly-composed cord FD
has **median 0.50 mm**. So 0.5 is not "well above the norm" — it *is* the norm.
Applying 0.5 mm to cord does not inherit Power's logic; it **inverts** it. Power's
own criterion, applied honestly to cord data, necessarily yields a different
number.

"Lenient (0.5) / stringent (0.2)" is Power **2014**
([PMC3849338](https://pmc.ncbi.nlm.nih.gov/articles/PMC3849338/)), not 2012 —
cite accordingly. Power 2014 does contain a real empirical derivation
("significant within-subject changes in correlation are detectable down to
FD = 0.15–0.2 mm"), by ordering frames by QC value and permuting the ordering
across 160 subjects. Power explicitly limits it:

> "Most datasets will not tolerate censoring based on such strict thresholds, nor
> it is obvious that this particular analysis should be the only criterion for
> setting thresholds."

## 2. Our FD is not Power's FD (the strongest argument)

SpinePrep's cord FD sums **two** in-plane translation terms (`|Δtx| + |Δty|`).
Power's sums **six** (3 translations + 3 rotations as arc length on a 50 mm
sphere). These are different quantities with the same name.

VERIFIED, Jones et al. 2022 ([PMC9506314](https://pmc.ncbi.nlm.nih.gov/articles/PMC9506314/)):

> "FD and DVARS magnitudes change with the TR of the data, because the TR is the
> sampling rate... different calculations of FD provide different values … and
> thus **any absolute threshold would necessarily be metric specific**."

That is a published, quotable justification that 0.5 cannot transfer to our
metric. The apparent coincidence — Power's 0.5 mm and our 0.50 mm median — is a
collision between two incommensurable numbers, not evidence of agreement.

There is also no volumetric 6-DOF FD available to us even in principle:
`sct_fmri_moco` estimates slice-wise in-plane translations only, and rotation is
ill-defined on a cord-cropped FOV.

## 3. No voxel-fraction rule exists

Searched; **not found** (treat as folklore, not as an exhaustive negative). It is
likely incoherent anyway: Power's FD is a *sum of six absolute displacements*, not
a distance, so there is no voxel to divide by; and cord voxels are wildly
anisotropic (Kaptan: 1.0 × 1.0 × **5.0 mm**). Power's own functionals were
3.75 × 3.75 × 4 mm — so 0.5 mm is ~1/6 to ~1/8 of a voxel *dimension* depending
which one you pick. That ambiguity is itself the argument against the rule.

## 4. FD has no null distribution; DVARS does

VERIFIED, Afyouni & Nichols 2018
([PMC5915574](https://pmc.ncbi.nlm.nih.gov/articles/PMC5915574/)): DVARS

> "does not have any absolute units nor a reference null distribution from which
> to obtain p-values"

and "the typical 'good' values of DVARS varies over sites and protocols" — so they
*supply* a χ² null for DVARS² and recommend flagging on Bonferroni p<0.05 **and**
Δ%D-var > 5%, explicitly "to avoid arbitrary thresholds on DVARS".

**No equivalent null exists for FD.** A principled inferential threshold is
available for the intensity metric and not for the motion metric. That asymmetry
argues for censoring on intensity, not on FD.

## 5. What our own data says (Power's logic, re-run on cord)

Composed FD vs **post-motion-correction** residual DVARS (cord-restricted, DVARS
normalized per run so 1.0 = that run's typical frame), 120 runs / 22,970 frames.
Censoring exists to remove what motion correction could not fix, so the question
is: at what FD does residual signal disruption appear?

| FD bin (mm) | frames | median DVARS | p90 DVARS |
|---|---|---|---|
| 0.00–0.25 | 5182 | 0.97 (baseline) | 1.15 |
| **0.25–0.50** | 6911 | **0.97** | 1.16 |
| 0.50–0.75 | 5116 | 1.00 | 1.25 |
| 0.75–1.00 | 3104 | 1.05 | 1.35 |
| 1.00–1.50 | 2032 | 1.10 | 1.43 |
| 1.50–2.00 | 334 | 1.21 | 1.77 |
| 2.00–3.00 | 150 | 1.33 | 2.98 |
| 3.00+ | 141 | 2.01 | 4.00 |

**DVARS is flat from 0 to 0.5 mm.** Motion correction fully absorbs cord motion
up to ~0.5 mm; there is no signal consequence to censor. Censoring at 0.5 mm
discards ~48% of frames for no measurable benefit. Disruption begins at
**FD ≈ 0.95 mm** (+10% over baseline) and is unambiguous by **~1.55 mm** (+25%,
p90 climbing steeply).

Run-level consequence (466 runs):

| threshold | median censored | runs FAIL (>50%) | runs WARN (>30%) |
|---|---|---|---|
| 0.5 mm (current) | 48.5% | 230 (49%) | 324 (70%) |
| 0.8 mm | 12.4% | 20 (4%) | 100 (21%) |
| **1.0 mm** | **4.5%** | **2** | 21 |
| 1.5 mm | 0.7% | 0 | 2 |

## 5b. Our own data proves the incommensurability

Jones's claim is not just quotable, it is measurable here. The same 466 runs,
scored by two defensible FD definitions:

| FD definition | median mean-FD | runs > 0.4 mm |
|---|---|---|
| bulk + slice-wise (SpinePrep) | **0.55 mm** | 356 (76%) |
| bulk only | **0.28 mm** | 102 (22%) |

The slice-wise term adds **+0.27 mm** to the median. Two reasonable definitions of
"cord FD" on identical data differ by a factor of two. No absolute threshold can
survive that, which is exactly Jones's point demonstrated on our own cohort.

This also bears on Ricchi 2024's `mean FD > 0.4 mm` subject-exclusion criterion,
which uses the same 2-term x/y wording we do. Our bulk-only median (0.28 mm) sits
comfortably under it; our bulk+slice-wise median (0.55 mm) would exclude 76% of
runs. Since no published cord study would adopt a criterion excluding three
quarters of ordinary data, Ricchi's FD is very likely bulk/volumetric, not a
per-slice composition — i.e. **their 0.4 mm is not comparable to our number
either.** (Inference from the arithmetic, not a statement from the paper; Ricchi
is also lumbosacral, a different motion regime, at a different TR/resolution, and
mean-per-subject is not median-per-run.)

## 6. What the field actually does

- **Kaptan 2023** ([PMC10262064](https://pmc.ncbi.nlm.nih.gov/articles/PMC10262064/),
  Eippert last author): the words "framewise displacement"/"FD" are **absent from
  the entire paper**. Censors on intensity — "Volumes presenting with dVARS or
  refRMS values two standard deviations above the mean values of each run were
  selected as outliers" (~<2% of volumes) — and uses the slice-wise translations
  as **regressors**: "Baseline + slice-specific motion-correction estimates (x-
  and y- translation …)".
- **Ricchi, Kinany & Van De Ville 2024** (doi:10.1162/imag_a_00286; PMC12290568) —
  the only cord FD number found — uses **mean FD for SUBJECT-level exclusion**
  ("average FD > 0.4 mm"), *not* frame censoring.
- **No cord paper found publishes a frame-censoring FD threshold.** (Own search;
  not exhaustive — one more sweep of Barry/Vahdat/Weber/Stroman before this goes
  in print as an absolute.)
- **FSL `fsl_motion_outliers`** defaults to the box-plot fence (P75 + 1.5·IQR), a
  *within-run distributional* rule, and supports `--fd`/`--fdrms`. The
  data-relative machinery for FD already exists in the tool we cite.
- **Jones 2022** recommends **frame-percent thresholding**: compute the metric
  across the dataset, then pick the cutoff yielding a target censored fraction
  (they sweep 1/2/5/10/20%). Dataset-relative, not absolute. It also finds
  censoring's gains "frequently comparable to what could be achieved using other
  techniques" and "no single approach consistently outperformed the others".
  Caveat: Jones is **task-based** fMRI, not resting-state.

## 7. Our own pipeline is already inconsistent

`policy/S8_confounds.yaml` uses a **data-relative** rule for the intensity metrics
(`dvars_outlier_iqr_k: 1.5`, `refrms_outlier_iqr_k: 1.5` — the Tukey fence) but an
**inherited absolute** for FD (`fd_outlier_threshold_mm: 0.5`). Two different
philosophies inside one confound file.

## 8. Options, in order of defensibility

1. **Drop FD censoring; censor on dVARS/refRMS; keep motion as regressors.** This
   is Kaptan's exact design, it is what the cord field does, S3 already computes
   the intensity outliers and S8 already consumes them, and DVARS is the metric
   that actually has a principled null (Afyouni & Nichols). FD stays reported,
   plotted, and available to S8 as a nuisance regressor. The tSNR floor remains
   the genuine technical-failure gate.
2. **If FD censoring is kept, make it within-run distributional** (Tukey fence or
   mean+2SD), matching FSL's default and our own DVARS rule — not an absolute mm.
3. **Report a Jones-style sensitivity sweep** (1/2/5/10/20% frame-percent) and
   show the result is stable, rather than defending a single number.

Note on method: fitting 1.5 mm *because* it reproduces Kaptan's ~2% would be
fitting. Sweeping frame-percent and reporting stability is a **sensitivity
analysis** — that distinction is what makes option 3 legitimate.

## 9. Claims we may and may not make

**May** (verified, quotable):
- Power chose 0.5 as "well above the norm found in still subjects" — a condition
  our data does not satisfy.
- "any absolute threshold would necessarily be metric specific" (Jones 2022) — our
  FD is a 2-term metric, Power's is 6-term.
- Kaptan 2023 uses no FD at all; it censors on dVARS/refRMS at 2 SD.
- DVARS has a principled null (Afyouni & Nichols 2018); FD does not.
- Our measured result: residual DVARS is flat to 0.5 mm and rises from ~0.95 mm.

**May NOT** (checked and refuted or unverified):
- ~~"The field chooses thresholds by optimizing QC-FC."~~ **Refuted.** Ciric 2017
  varied 14 confound-regression *pipelines*, not FD thresholds (its scrubbing arm
  fixed FD>0.2 mm). No source recommends optimizing your threshold on your own
  data. Parkes 2018 unverified (403) — check before citing.
- "Cord motion parameters conflate physiological cord motion with subject motion."
  **No source found.** This is our own reasoning and must be labelled as such.
- The ~0.5–0.6 mm physiological cord-displacement figure (Figley & Stroman 2007):
  **primary text not read** (paywall). The qualitative claim (cord oscillates A/P
  with the cardiac cycle) is established; the number is not ours to quote yet.
- Carp 2013 is **NeuroImage 76:436–438**, not Frontiers; primary not read.

## 10. Open before submission
- Parkes 2018: did it vary thresholds or only pipelines?
- Figley & Stroman 2007 primary, for the physiological displacement magnitude.
- One more sweep of Barry / Vahdat / Weber / Stroman for any cord FD threshold.
- Power 2012 Corrigendum (NeuroImage 63(2):999) — amends the paper we cite; unread.
