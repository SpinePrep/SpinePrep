# Novelty review — Rounds 2 and 3

Run 2026-07-27. Clears the `(unchecked)` marks on `FLAGSHIP_FINDINGS.md`.

**Method.** Targeted PubMed title/abstract searches, one per claim, each written to be
specific enough that the prior work would have surfaced if it existed. Every search
term and its raw count is recorded below so the search can be repeated or attacked.
The standard is F1's: a claim counts as novel only if the search was specific enough
to have found the prior work.

**Limits, stated up front.** PubMed indexes titles and abstracts, so a paper that does
the work without naming it in either is invisible to this. bioRxiv is partially
indexed — the Ricchi preprint did surface, which is some reassurance. Papers in
non-indexed venues, conference abstracts, and work described only in a Methods section
would all be missed. This review lowers the risk of a scoop; it does not eliminate it.

---

## The one that changed a claim

### R3 fingerprinting — **PARTIALLY SCOOPED**

**Ricchi I, et al. "Spine-prints: Transposing brain fingerprints to the spinal cord."
*Imaging Neuroscience* 2026 (PMID 41674679); bioRxiv 2025 (PMID 40501925).**

Their abstract claims *"the first evidence of a spinal cord connectivity fingerprint"*.
Three multi-site datasets; **53.3% identification for spine-only against 8.3% chance**,
versus 93.3% brain-only.

**What this does and does not take.**

| | Ricchi 2026 | ours (R3) |
|---|---|---|
| quantity | resting-state **functional connectivity** | **task activation** pattern |
| result | identification well above chance | identification **at chance** |
| anatomy/tSNR control | acknowledged as a *limitation* | **measured**: mean-signal and tSNR maps identify at 0.56–0.60 vs 0.04–0.11 chance |

So the *concept* of cord fingerprinting is taken, and we must not claim it. Two things
survive, and they are worth more as a caveat on their paper than as a claim of our own:

1. **Task activation does not fingerprint**, while resting connectivity does. That is a
   dissociation between the two, not a contradiction of them.
2. **Their acknowledged limitation may be a confound.** They attribute the lower
   spine-print score to low tSNR. We measured that anatomy and tSNR patterns *by
   themselves* identify subjects far above chance — so a cord connectivity fingerprint
   could partly ride on them. They do not appear to have run that control.

**Action:** reframe R3 as a scoped negative plus a control, cite Ricchi 2026
prominently, and drop any "first" language. The project's existing F3 guardrail
already said *"must scope to TASK activation; resting patterns are stable (Kowalczyk
2024, Ricchi 2026)"* — that guardrail was right and this confirms it.

---

## Verified novel

### R10 — analytic variability / multiverse in cord fMRI
`("spinal cord"[TIAB] AND fMRI[TIAB]) AND (multiverse OR "analytic variability" OR
"analytical flexibility" OR "pipeline variability")` → **ZERO RESULTS.**
No cord fMRI multiverse or analytic-variability study exists in the indexed
literature. **VERIFIED NOVEL.**

### N1 — empirical false-positive rate of cord fMRI inference
`("spinal cord"[TIAB] AND (fMRI OR "functional MRI")[TIAB]) AND ("false positive rate"
OR "false-positive" OR familywise OR "family-wise error" OR "cluster inference")` →
45 results, **none** on cord fMRI inference validity; the hits are clinical diagnostic
false positives (cord compression, monitoring, serology). The only methodological
neighbours are physiological-noise papers (Brooks 2008, Kong 2012), which do not test
error rates. **VERIFIED NOVEL.**

### R9 — inter-subject correlation in the cord
`("spinal cord" AND (fMRI OR "functional MRI")) AND ("inter-subject correlation" OR
"intersubject correlation")` → **ZERO RESULTS.** **VERIFIED NOVEL.**

### R7 — degrees-of-freedom audit of the cord confound model
`("spinal cord" AND fMRI) AND ("degrees of freedom" OR "nuisance regressors" OR
"confound regressors")` → 7 results, of which one is relevant: **Hemmerling KJ,
Vigotsky AD, Glanville C, Barry RL, Bright MG, "Data-driven denoising in spinal cord
fMRI with principal component analysis," *Imaging Neuroscience* 2026** (bioRxiv 2025).
It is a denoising method paper and does not audit degrees of freedom consumed.
**VERIFIED NOVEL**, with Hemmerling 2026 as the paper to position against — it is also
the one A1's dissociation speaks to.

### R2 — do image-quality metrics predict scientific outcome?
`("image quality metrics" OR "quality control" OR MRIQC) AND fMRI AND (predict OR
association) AND ("effect size" OR "statistical power" OR detection)` → 17 results,
**none** testing whether imaging QC metrics predict a statistical outcome **in any
organ**. Closest: **Elsayed et al., "Garbage in, garbage out: stringent quality control
of behavioral data boosts signal in brain-behavior associations," *Cereb Cortex* 2026**
— which is behavioural QC, not image QC. **VERIFIED NOVEL, and open in the brain too.**

### R1 — trial-wise coupling of cord BOLD to behaviour
`"spinal cord" fMRI single-trial pain rating BOLD correlation` → **ZERO RESULTS.**
**VERIFIED NOVEL** (as a null).

### F4's biomarker ceiling — attenuation and ICC-based sample size for cord fMRI
`"spinal cord" AND fMRI AND (reliability OR reproducibility OR "test-retest") AND
(biomarker OR "individual differences" OR attenuation OR "sample size")` → 50 shown of
107. **Zero** derive a ceiling on clinical correlations from measured reliability, and
**zero** compute required N or sessions from an ICC for cord fMRI. The reliability
literature returned is structural (atrophy, MTR, DTI, multi-parameter mapping).
**VERIFIED NOVEL.**

### A8 — residual non-rigid cord deformation after motion correction
`"spinal cord" AND fMRI AND ("non-rigid" OR nonrigid OR deformation OR centerline OR
centreline) AND (motion OR "motion correction")` → 10 results, **none** measuring
residual non-rigid deformation left after fMRI motion correction. Adjacent work to
cite: Yuan 1998 (cord deformation in flexion), Morozov 2018 (cardiac translational
motion in cord dMRI), Stoner 2019 (in vivo cord displacement and strain fields),
Figley & Stroman 2009 (RESPITE cord motion time-courses). **VERIFIED NOVEL** for the
residual-after-correction question.

---

## Novel with a close neighbour

### A2b — cord versus brain distortion magnitude in the same acquisition
`(simultaneous OR concurrent OR "brain and spinal cord") AND fMRI AND ("susceptibility
distortion" OR "B0 distortion" OR "geometric distortion" OR topup OR "field map")` →
80 results. Exactly one covers both regions in one acquisition: **Chu Y, et al.,
"Improving T2*-weighted human cortico-spinal acquisitions with a dedicated algorithm
for region-wise shimming," *NeuroImage* 2023.** That is a shimming method paper; it
addresses the two regions' differing field requirements but does not report a measured
displacement ratio between them. **NOVEL, with Chu 2023 as the closest prior work and
the obvious citation.**

---

## Status of every Round 2–3 claim

| claim | verdict |
|---|---|
| R10 multiverse | **verified novel** |
| N1 false-positive rate | **verified novel** |
| R9 inter-subject correlation | **verified novel** |
| R7 degrees-of-freedom audit | **verified novel** (position against Hemmerling 2026) |
| R2 QC predicts outcome | **verified novel**, open in brain too |
| R1 trial-wise behavioural coupling | **verified novel** (null) |
| F4 biomarker ceiling arithmetic | **verified novel** |
| A8 residual non-rigid deformation | **verified novel** |
| A2b cord vs brain distortion | **novel**, cite Chu 2023 |
| A2a SyN under-correction | covered by F1's Round 1 review (no cord study compares image-based SDC to a measured field) |
| A1 aCompCor slice-wise | **not a novelty claim** — it settles a disagreement between Kaptan 2023 and Hemmerling 2026 and must be framed that way |
| **R3 fingerprinting** | **PARTIALLY SCOOPED by Ricchi 2026** — reframe as scoped negative plus control |
| A6 variance decomposition | not searched; low-risk supporting result |
| A4 raw global signal | not searched; reported as a null |
| N3 multivariate detection | not searched; MVPA in cord is established, so this is not claimed as novel |
| N4 kernel shape | not searched; reported as a negative result |

**Two claims were not searched and are not asserted as novel** (A6, A4), and three are
explicitly not novelty claims (A1, N3, N4). Nothing in the flagship document now
carries an unchecked novelty assertion.
