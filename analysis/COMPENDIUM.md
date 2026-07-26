# SpinePrep — complete analysis compendium

**Single authoritative record of every analysis run in the P2 exploration.**
Consolidates and supersedes: `paper/FINDINGS.md`, `paper/P2_UNSCOOPED.md`,
`analysis/RESULTS.md`, `analysis/replication/REPLICATION_LOG.md`.
Compiled 2026-07-26.

## Provenance

| item | value |
|---|---|
| cohort | `/mnt/ssd1/spineprep_cohort_s2` — 9 datasets, 469 runs entering S3, **450 complete S9 (all PASS)** |
| preprocessing | frozen as **`preproc-v1`**, git `961a779` (`PREPROC_LOCK.md` / `.json`) |
| tools | SCT 7.1, FSL 6.0.7.15, MRtrix 3.0.4, ANTs (SCT-bundled), Python 3.12.3 |
| scripts | `analysis/experiments/` (all committed) |
| tables | `analysis/results/*.csv` (gitignored; regenerate via the scripts) |
| scope | **PIPELINE claims only.** Design/power/scan-time was handed to P1 (`/mnt/hdd2/P3_DesignOpt/HANDOFF_FROM_P2_2026-07-25.md`) |

## The thesis (after all amendments)

**"The cord is not a small brain: preprocessing conventions imported from brain
fMRI misfire in the spinal cord."**

Two conventions are demonstrably harmful, one is wasteful-and-destructive, and
three more turn out unpredictable or inert rather than beneficial. The pipeline's
authority to say so rests on reproducing the field's own published results.

---

# 1. MASTER TABLE — every analysis and its verdict

| # | analysis | n | verdict | strength |
|---|---|---|---|---|
| 1 | Replication of published results | 9 datasets | **1/4 group activations survive unbiased CV**; laterality + reliability replicate | ★★ (corrected) |
| 2 | Distortion, within-run paired | 80 runs | SyN makes geometry WORSE in 82% of runs | ★★★ strongest |
| 3 | FD censoring | 324 runs | **only the FRACTION censored matters**, not the threshold rule | ★★ (corrected) |
| 4 | ROI summary measure | 4 datasets | parcel-mean destroys the effect | ★★★ |
| 5 | Confound families (task) | 324 runs | no family improves sensitivity | ★★ |
| 6 | aCompCor on connectivity | 48 pairs | **destroys** connectivity | ★★ |
| 7 | Peak-voxel localisation | 2 datasets | not reproducible (≈ random) | ★★ |
| 8 | Confound-design degeneracy | 450 runs | 7.8% rank-deficient | ★ |
| 9 | Biological-conclusion robustness | 199 runs | laterality stable | ★ reassurance |
| 10 | Motion regression cost | 199 runs | −23% d, mechanism unresolved | downgraded |
| 11 | Smoothing | 4 datasets | **no universal optimum** | downgraded |
| 12 | Motion correction ablation | 4 datasets | tSNR +0–121%, no consistent d gain | mixed |
| 13 | High-pass filtering | 4 datasets | **null** (justifies inherited 100 s) | null |
| 14 | Physio benefit by cord zone | 4 datasets | not edge-concentrated | null |
| 15 | Effect reliability (between/within) | 5 datasets | confirmatory + partly scooped | supporting |
| 16 | Kaptan connectivity replication | 48 pairs | V–V ✓, D–D unresolved | open |

---

# 2. VALIDATION — what the pipeline actually reproduces

**CORRECTED 2026-07-26.** The first version claimed "7/7 task datasets reproduce
their published group activation (t = 11-21)". Those t-values came from **biased**
top-10% selection — voxels chosen and measured on the same data, which is almost
guaranteed to be positive. Recomputed with unbiased cross-validation (select on
odd timepoints, measure on even):

| dataset | biased d | biased p | **unbiased d** | **unbiased p** | N |
|---|---|---|---|---|---|
| ds004616 handgrasp | +4.24 | <1e-5 | **+0.64** | **0.005** | 24 |
| ds005884 cospine motor | +3.57 | <1e-5 | +0.26 | 0.33 | 15 |
| ds004926 dorsal-horn pain | +2.62 | <1e-5 | +0.11 | 0.52 | 37 |
| ds005883 cospine pain | +3.04 | <1e-5 | +0.13 | 0.52 | 25 |

**Significant with biased selection: 4/4. With unbiased selection: 1/4.**

### What genuinely replicates
- **ds004616 motor group activation** — survives unbiased CV (d = 0.64, p = 0.005).
- **Hemmerling 2023 laterality** — 92% of subjects ipsilateral-dominant vs
  published LI 0.96-0.99. Independent of voxel selection, so unaffected.
- **Dabbagh 2024 pain reliability** — our between-session effect ICC 0.05 vs
  published 0.03. Independent measure.
- **Kaptan 2023 ventral-ventral connectivity** — ICC 0.49 vs published 0.63.

### What does NOT replicate under honest analysis
Cross-validated group task activation in ds005884, ds004926 and ds005883. These are
null. This is **not** a pipeline failure: it agrees with the literature's own
conclusion that cord task effects are weak, and it independently reproduces P1's
leave-subject-out finding that cross-validated cord task effect sizes are near zero.
Two projects, two different estimators, same answer.

**Consequence for the paper:** the "reproduces the field across 9 datasets" moat is
**substantially weaker** than first claimed. The defensible statement is that
SpinePrep reproduces the published *laterality*, *reliability* and *connectivity*
results, and the one genuinely strong task activation — not that it recovers group
activation everywhere.

# 3. SURVIVING FINDINGS

## 3.1 Distortion — use a fieldmap; image-based SyN makes geometry WORSE  ★ STRONGEST
**Corrected 2026-07-26 after a fairness audit.** The first version compared the
absolute post-correction displacement of the two arms. That was **confounded**: S5
re-runs its anat->BOLD registration on every invocation, so the two arms measure
against different anatomical references (median 2.8 mm apart on matched slices,
worst 7.3 mm) — larger than the between-arm difference being claimed. Absolute
after-values across arms are NOT comparable.

Valid analysis: judge each arm on its **own within-run before->after** change
(same registration within a run, so the difference is paired and sound).

| arm | before | after | reduction | slices worsened | runs made worse |
|---|---|---|---|---|---|
| **measured field (TopUp)** | 3.34 mm | 0.62 mm | **−81%** | 9% | **1%** |
| **image-based SyN** | 1.98 mm | 2.47 mm | **+24% (WORSE)** | 65% | **82%** |

Paired Wilcoxon on per-run reduction: **p = 8×10⁻¹⁵**. SyN's reduction beats
TopUp's on **1%** of the 80 runs.

**The corrected result is stronger than the original claim.** Image-based SyN does
not merely underperform the measured field — it actively **increases** cord
displacement from anatomy in **82% of runs** (the earlier figure, "28% worse", was
an understatement produced by the confounded comparison).

- Recommendation both ways: acquire reversed-PE fieldmaps (they remove 81% of the
  distortion); do **not** apply image-based correction without one. This is the
  evidence behind the shipped `none` default.
### Robustness of the distortion finding (deeper verification, 2026-07-26)
Confirmed on a **second, independent metric** and in **both datasets separately**:

| evidence | TopUp | SyN | SyN worsened |
|---|---|---|---|
| displacement reduction, ds005883 (n=37) | **+83%** | −13% | **84%** of runs |
| displacement reduction, ds005884 (n=43) | **+79%** | −19% | **81%** of runs |
| **per-slice cord Dice change** (independent of centroid displacement) | **+0.33** | **−0.039** | **76%** of runs |

Paired Wilcoxon on ΔDice, TopUp vs SyN: **p = 9.5×10⁻¹⁵**. The displacement metric
measures centroid offset; Dice measures mask overlap. They are computed differently
and agree, so the result is not an artifact of either metric.

**Scope limit, stated honestly:** both datasets are CoSpine — one lab, one scanner,
one acquisition protocol. The finding is robust *within* that acquisition but has
not been shown across vendors. This is the single most important caveat on the
paper's strongest claim.

- Limitation now documented: the S5 displacement metric carries ~1–3 mm of
  registration variability between invocations, so absolute displacements should be
  quoted with that uncertainty; only within-run before/after differences are exact.

## 3.2 FD censoring — only the FRACTION matters, not the threshold rule
**CORRECTED 2026-07-26.** The first version claimed the brain's 0.5 mm threshold is
"mis-calibrated for the cord" and a cord-derived rule is better. A fraction-matched
control shows that is **wrong**:

| arm | frames removed | median group d (4 datasets) |
|---|---|---|
| no censoring | 0% | +0.197 |
| **worst 10% (light)** | 10% | **+0.425** |
| FD > 0.5 mm (brain rule) | 25% | +0.062 |
| cord percentile matched to 25% | 25% | **+0.062 — identical** |

The cord-derived rule matched to the same fraction gives **exactly** the brain
rule's result. In hindsight this is necessary, not surprising: any threshold on FD
is a monotone selection of the worst frames, so two rules removing the same
fraction remove the *same frames*. The threshold VALUE is irrelevant.

**The honest finding is still useful, and still a corrective:** censoring ~10% of
frames improves detectability (+116% over none), while censoring ~25% badly hurts
it (-69%). The brain's 0.5 mm threshold is wrong for cord data **not because the
rule is mis-calibrated but because in cord data it happens to remove ~25% of
frames — far past the optimum.** Argue about fractions, not thresholds.

## 3.3 aCompCor — wasteful for task, DESTRUCTIVE for connectivity  ★
Task (324 runs):

| family set | sensitivity | residual DVARS | DOF |
|---|---|---|---|
| motion only | 2.54 | 38.3 | 4 |
| +spike+cosine | 2.38 | 37.0 | 27 |
| +retroicor | 2.36 | 33.6 | 47 |
| +csf aCompCor | 2.48 | 22.0 | **125** |
| full | 2.19 | 20.0 | **144** |

Connectivity (ds004386, 48 subject-pairs, band-passed 0.01–0.13 Hz):

| denoising | D–D r | D–D ICC | V–V r | V–V ICC |
|---|---|---|---|---|
| motion only | 0.20 | 0.40 | 0.37 | 0.49 |
| **+ CSF aCompCor** | **0.07** | **0.05** | **0.14** | **0.36** |

No confound family improves task sensitivity; aCompCor spends 125+ regressors for
none, and **collapses** connectivity. RETROICOR is the efficient choice. Related:
median 139 regressors vs 227 frames; **35/450 runs (7.8%) rank-deficient**.
No cord equivalent of Ciric 2017 / Parkes 2018 exists.

## 3.4 The ROI summary measure decides whether you find anything  ★
Same data, same GLM, different summary of the focal horn (group d):

| dataset | parcel-MEAN | top-10% | peak |
|---|---|---|---|
| ds004616 | **−0.35** | +0.90 | +0.25 |
| ds005884 | +0.10 | +0.41 | +0.15 |
| ds004926 | +0.11 | +0.11 | +0.24 |
| ds005883 | **−0.17** | +0.44 | +0.16 |

The parcel-mean costs **~107%** of detectability and can invert the sign.

## 3.5 Inter-subject variability of peak location  ★ (revised 2026-07-26)

**Terminology corrected.** This was headed "peak localisation is not reproducible".
"Reproducibility" conventionally means test-retest *within* subject; what we measured
is scatter *across* subjects. The correct term is **inter-subject variability of peak
location**, and that evidence base is both cleaner and better supported.

### What we measured
Raw across-subject SD of each subject's peak-activation voxel inside the a-priori horn:

| dataset | SD left-right | SD ant-post | SD rostrocaudal |
|---|---|---|---|
| ds004616 | 1.05 mm | 2.15 mm | **13.98 mm** |
| ds004926 | 1.20 mm | 3.87 mm | **18.84 mm** |

Normalised against scatter expected from RANDOM placement inside the ROI
(span/√12), all axes sit at 0.67–1.49 — i.e. **no better-than-chance consistency on
any axis**.

**Both readings are true and answer different questions.** The normalised view says
there is no evidence of consistent localisation given how much room each axis has.
The raw view says localisation is strongly **anisotropic**: in-plane position is
determined to 1–4 mm, rostrocaudal position to 14–19 mm. My earlier note treating
the anisotropy as purely an ROI-shape artifact was too dismissive — see below.

### Convergent cord evidence (this is the key support)
**Dabbagh et al. 2024** (*Imaging Neuroscience*, doi:10.1162/imag_a_00273; n=40, two
days, same organ and resolution regime) independently reports the same anisotropy:
group across-day Dice **0** at corrected p<0.05 (0.26 at p<0.05 uncorrected); only
**5 of 35** participants showed any across-day overlap. Verbatim: *"while the
location on the dorsal-ventral dimension remained similar, the patterns differed
rostrocaudally"*, with Day-1 voxels "consistently more caudal in segment C6" than
Day 2. An independent lab, an independent metric, the same in-plane-stable /
rostrocaudally-unstable pattern.

### Brain benchmarks — the cord is NOT worse than the brain
Between-subject peak scatter in brain is of the same order as ours:
- **Wang et al. 2021** (*Quant Imaging Med Surg* 11(2):810–822; n=893): individual
  peak to atlas hotspot **8.7–20.8 mm** (motor 10.7–20.8; language 8.7–16.8).
- **Zhen et al. 2017** (*Hum Brain Mapp* 38(4):2260–2275): scene-selective regions
  show **>20 mm** divergence in peak location; per-axis SD 4–9 mm.

So cord rostrocaudal scatter (14–19 mm) sits inside the brain's range — consistent
with the "cord obeys brain norms" framing rather than a cord-specific defect.

### Honest counter-evidence, to be conceded in half a sentence
Two presurgical studies find the peak **more** stable than the cluster centre:
**Weiss et al. 2013** (*NeuroImage* 66:531–542; fMRI hotspot Euclidean distance
6.2 ± 1.1 mm, peak-voxel ICC > 0.8) and **Nettekoven et al. 2018** (*NeuroImage*
176:215–225; maxima 6.45 ± 1.36 mm vs centres-of-gravity 8.03 ± 2.01 mm,
significantly better). Both used ROI-constrained searches, which bounds how far a
peak can travel — but the concession costs nothing and closes the obvious attack.
The opposite direction is supported by **Morrison et al. 2016**
(*PLoS ONE* 11(2):e0149547; peak displacement up to ~23 mm, centre-of-mass more
reproducible than peak) and **Hu et al. 2022** (*Front Neuroinform* 16:882126), which
gives the cleanest published dissociation: coordinate ICC **0.72–0.80** while the
peak moves **~20 mm** and only **41%** of peaks land within 10 mm.

### Verified NOT available
There is **no** review or meta-analysis of peak-coordinate displacement, so no
pooled "typical peak displacement" exists — every claim must cite individual
studies. **Do not** cite Bennett & Miller 2010 or Elliott 2020 for location: neither
has a peak-location metric (both report amplitude/extent only).

### Consequence
Aggregate measures are sound (92% laterality; top-10% d up to +0.90); **single-peak
and peak-based spinal-segment assignment are not supportable** at this resolution.
This is the mechanism behind the horn-scale null, and it is now supported by an
independent cord dataset rather than by our data alone.

## 3.6 The biological conclusion is robust
Laterality sign is stable across every nuisance arm wherever the effect exists
(ds004616 LI +0.13…+0.19).

---

# 4. WEAKENED / DOWNGRADED

## 4.1 Smoothing — NO universal optimum (was "~4 mm, +30%")
| dataset | 0 mm | 2 mm | 4 mm | 6 mm | best |
|---|---|---|---|---|---|
| ds004616 | +0.64 | +0.64 | **+1.15** | +1.13 | 4 mm |
| ds005884 | +0.26 | **+0.34** | −0.06 | −0.01 | 2 mm |
| ds004926 | +0.11 | +0.03 | +0.27 | **+0.30** | 6 mm |
| ds005883 | +0.13 | **+0.32** | +0.27 | +0.26 | 2 mm |
| **median** | +0.20 | **+0.33** | +0.27 | +0.28 | — |

The original "+30% at 4 mm" was **ds004616 alone (n=1)**. Best kernel differs per
dataset (4/2/6/2 mm) and 4–6 mm **destroys** the effect in ds005884. Honest claim:
light (~2 mm) smoothing gives a modest median gain; heavier is dataset-dependent
and can harm. Separately: smoothing inflates apparent extent **2.7×** (42→115
"active" voxels) while **halving peak effect** (0.275→0.127); specificity unaffected.

## 4.2 Motion regression costs detectability — mechanism unresolved
Median Δd = **−23%** across 4 datasets. Motion regressors do carry task
correlation (median max |r| **0.16 motor vs 0.10 pain**, directionally as
predicted), but magnitudes are modest and pain was hurt too, so
"removes task-correlated signal" cannot be separated from "spends degrees of
freedom" (Bright & Murphy 2015).

## 4.3 Motion correction — large but heterogeneous tSNR gain, no consistent transfer
| dataset | tSNR off → on | group d off → on |
|---|---|---|
| ds004616 | 22.2 → 22.9 (**+3%**) | +0.61 → +0.58 |
| ds005884 | 9.1 → 19.8 (**+118%**) | +0.25 → +0.32 |
| ds004926 | 16.5 → 16.5 (**0%**) | +0.07 → +0.15 |
| ds005883 | 9.7 → 21.4 (**+121%**) | +0.01 → −0.08 |

The most universally applied step buys large quality gains in some datasets and
none in others, and those gains do not reliably become statistical power.
Detectability estimates are noisy (n = 15–37), so stated as "no consistent
translation", NOT "moco does not help detection".

## 4.4 Reliability — confirmatory and partly scooped
Between-session effect ICC: pain **0.05** (= Dabbagh 0.03), motor **0.51**
(AIH-confounded floor). Within-session split-half **0.84** and tSNR-ICC **0.75**
overstate both. Verified against Dabbagh 2024, Kowalczyk 2024, Kaptan 2023,
Elliott 2020 (brain mean ICC 0.397). **Scooped** for the cord by Kowalczyk 2026
(bioRxiv 2025.09.07.674708) and for the framing by Kragel 2021. Keep as
characterisation benchmarked to brain; do not headline.

---

# 5. NULLS (reported as nulls)

- **High-pass filtering has no material effect.** Valid design (fixed a-priori
  ROI, no selection): median group d = 0.035 / 0.015 / 0.010 / −0.020 across
  none→quarter→half→all. Within noise. This **justifies the inherited 100 s
  cutoff as harmless** and confirms the retraction in §7.2.
- **Physio noise is not edge-concentrated.** RETROICOR variance-explained gain,
  cord rim (next to CSF) vs core: 1.29 / 0.99 / 1.20 / 1.02 (median ≈ 1.1). No
  case for spatially targeted denoising. RETROICOR does explain **10–17%** of cord
  variance uniformly — it removes variance without removing the limiting noise.

---

# 6. OPEN / UNRESOLVED

- **Kaptan dorsal–dorsal connectivity.** Ours 0.20 r / 0.40 ICC vs published
  0.48 / 0.59; V–V replicates reasonably (0.37 / 0.49 vs 0.43 / 0.63). No
  denoising arm recovers D–D. Likely causes we cannot adjudicate: Kaptan used
  physio recordings **absent from this OpenNeuro release** (ds004386 ships zero
  RETROICOR columns), and possibly different horn seeds. Recorded as an open
  discrepancy — not a replication success, not a pipeline failure.
- **Tier-3 ablations** needing pipeline re-runs: slice-timing, registration,
  normalization. Triggers defined; none fired. (Motion correction turned out
  post-hoc testable — see §4.3.)
- **Cerebro-spinal somatotopy** (Landelle 2024) is out of scope for a cord-only
  pipeline.

---

# 7. RETRACTED / INVALID — my own errors, caught by self-check

Recorded deliberately: six design failures in this exploration, each of which
would have produced a plausible but false headline.

1. **Motion-correction ablation v1 — INVALID.** Unequal nuisance models (moco arm
   penalised by motion regressors that exist only because moco ran) and arms that
   were "full pipeline vs crop-only", not moco vs no-moco. *Partial correction:* I
   also cited a tSNR discrepancy (+3% vs the pipeline's +32%) as proof of a bug —
   that was **real dataset heterogeneity**, not an error (see §4.3). The
   retraction stands on the other two grounds only.
2. **High-pass test v1 — INVALID.** Appeared to show filtering costs 33–56% of
   detectability. Odd/even CV cannot test filtering: low-frequency drift is smooth
   in time, so both halves share it, inflating agreement when the filter is
   removed. Confirmed by the valid design (§5).
3. **Suprathreshold-count effect size — INVALID.** Gave d ≈ 2.0–2.7, but a
   one-sample t-test of a **non-negative count** against zero cannot be negative;
   the "effect" was an artifact of the test.
4. **"Laterality flips across preprocessing arms" — FALSE ALARM.** Signs appeared
   to flip in 3/4 datasets, but those have LI ≈ 0.00, so noise flips sign
   trivially. Where laterality exists it is stable — the opposite of the alarming
   reading.
5. **Reliability-vs-spatial-scale decline — ARTIFACT.** Caused by taking the
   median across all six horn parcels, mixing activated with non-activated tissue.
   There is no honest scale-decline result.
6. **Leave-one-subject-out design — NOT COMPUTABLE.** Parcels live in each
   subject's native voxel grid, so the cross-subject coordinate intersection is
   empty. LOSO needs a common template space this pipeline does not provide for
   BOLD. Replaced by per-question designs (§8).

Plus one **process** failure: a stray `cat >` with no input consumed stdin, so a
script was never written while I reported it as running. Fixed by writing scripts
with a file tool and verifying CPU time climbs before claiming a job is alive.

---

# 8. METHODS NOTES

**Designs, matched to each threat**
- *Detection claims:* cross-validated selection (select voxels on odd timepoints,
  measure on even) so the reported effect is never selected on itself.
- *Filtering comparisons:* fixed a-priori ROI, no selection — nothing for shared
  drift to inflate.
- *Ablations:* identical nuisance models across arms, adjacent pipeline stages
  only (S4 input vs S4 output).
- *Effect summary:* top-10% of the a-priori focal horn (the field's convention;
  §3.4 shows why the mean fails).

**Anti-circularity rules applied throughout**
1. Report curves and landscapes, never "the best config and its effect size on the
   same data" (Kriegeskorte 2009).
2. Any result contradicting the pipeline's own metrics is treated as an analysis
   bug until proven otherwise. *(This caught #1; it also over-fired — see the
   partial correction.)*
3. Nulls are reported as nulls.
4. Promotion to flagship requires: surprising, actionable, unscooped, survives an
   adversarial check.

**Literature verification.** Five research agents checked novelty and numbers
against Dabbagh 2024, Kowalczyk 2024/2026, Kaptan 2023, Landelle 2024, Wei 2025,
Hemmerling 2023, Elliott 2020, Kragel 2021, Noble 2019, Han/Kragel/Wager 2022,
Hedge 2018, Marek 2022, Botvinik-Nezer 2020, Caceres 2009, Bright & Murphy 2015.

---

# 9. SCRIPT AND DATA INVENTORY

| script (`analysis/experiments/`) | produces |
|---|---|
| `run_c4_syn.py` | distortion 3-way (§3.1) → `results/distortion.csv` |
| `tier1_all.py` | motion-task correlation, FD censoring, ROI summary, robustness (§3.2–3.4, §3.6, §4.2) |
| `tier2_all.py` | physio-by-zone, high-pass v1 (invalid), peak scatter (§3.5, §5) |
| `gapclose2.py` | smoothing ×4, valid high-pass, clean moco (§4.1, §4.3, §5) |
| `smoothing_tradeoff.py` | extent inflation / peak halving (§4.1) |
| `t25_ranking.py` | integrative figure (**needs rebuild** — carries the invalidated +30% smoothing bar) |
| `duration_scaling.py` | handed to P1 |
| `../effect_reliability.py` | between/within-session effect ICC (§4.4) |
| `../run_confound_benchmark.py` | confound families (§3.3) |

---

# 10. NOT DONE

1. **Integrative figure is stale** — its smoothing bar is the invalidated n=1
   number (§4.1). Rebuild required; it is the paper's centrepiece.
2. **No paper figures** built around this thesis; the F4–F8 files on disk belong
   to the abandoned reliability framing.
3. **No prose** — no Methods, Results, Introduction or Discussion.
4. `paper/OUTLINE.md` still encodes the superseded reliability-led structure.
5. **P1 blocked:** its v5 results were computed on pre-crop-fix derivatives and
   its harness has not been re-run on `preproc-v1`.
6. Housekeeping: 31 GB in `/mnt/ssd1/spineprep_c4_syn` (safe to delete);
   `.pre_csffix` backup still served as a live dashboard section; schema drift
   (S3 requires a `failure_class` it no longer emits; S1/S8 have no schema).

## Realistic venue

**Imaging Neuroscience** solid; NeuroImage/HBM a reach. Not Nature-tier — Neptune
(Rangaprakash & Barry 2026) removes the "first tool" claim, and corrective
preprocessing findings do not carry that tier without Marek-scale samples or a
NARPS-scale design. Honest strengths: SCOPE (9 datasets, one pipeline),
REPRODUCIBILITY (containerised BIDS-App + receipt), and a measured physical ground
truth in the strongest arm.

---

# 11. VERIFICATION AUDIT (2026-07-26) — what an adversarial re-check changed

Every headline claim was re-tested against the data rather than re-read from
notes. Three of the strongest claims were confounded; all three are corrected
above. This section records what changed, because the pattern matters more than
any single number.

| claim | first version | after audit | direction |
|---|---|---|---|
| Distortion (§3.1) | "SyN harms 28% of runs" (arms compared against **different** anat registrations, 2.8 mm apart) | within-run paired: SyN **worsens 82% of runs**, +24% displacement; TopUp −81% | **stronger** |
| Replication (§2) | "7/7 task activations reproduced, t = 11–21" (**biased** selection) | **1/4** survive unbiased CV; laterality/reliability/connectivity do replicate | **much weaker** |
| FD censoring (§3.2) | "the brain's threshold is mis-calibrated for the cord" | fraction-matched control is **identical**; only the FRACTION censored matters | **reframed** |

**Why the errors clustered.** All three shared one root cause: a comparison that
looked fair but wasn't. Two arms measured against different references; selection
and measurement performed on the same data; two rules that differ in name but
remove identical frames. None was a coding bug — every one produced clean,
plausible, publishable-looking numbers.

**What this implies for the paper.** The corrected claims are the ones to write:
the distortion result is now the single strongest finding and is stated more
strongly; the replication claim must be scoped to laterality, reliability and
connectivity rather than universal group activation; the censoring result becomes
"censor ~10%, not 25%" rather than "the brain's threshold is wrong".

**Convergent validation with P1.** The unbiased replication result (3 of 4 task
datasets null) independently reproduces P1's leave-subject-out finding that
cross-validated cord task effects are near zero. Two projects, two estimators, one
answer — which raises confidence in both, and confirms this is a property of cord
fMRI rather than of either analysis.

## Running total of self-caught errors

Nine, across the exploration: six design failures (§7), one process failure
(a shell error left a script unwritten while it was reported as running), and now
three confounded comparisons found by this audit. Each would have produced a
plausible but false headline. They are recorded rather than quietly fixed because
the reliability of everything else here depends on that being visible.

---

# 12. MAJOR RETRACTION (2026-07-26): the aCompCor findings are confounded by MISUSE

An external novelty audit flagged that the degrees-of-freedom argument only bites
if the slice-wise CSF design is applied **flat**. It was. Verified in the code:

- `confound_benchmark.family_builder` selects **all** `csf_sliceNN_pcMM` columns
  and returns them as one matrix;
- `glm.fit_run` applies that matrix to **every cord voxel**
  (`X = column_stack([Xtask, Xn, ones])`);
- **S8's own spec states: "The design is built for a SLICEWISE GLM"** — each
  slice's 5 components belong only to that slice's voxels. Applied correctly the
  cost is **5 regressors per slice, not 125–140 for the whole cord.**
- The same flat selection was used in the G4 connectivity arm.

## What is RETRACTED

- **"aCompCor spends 125+ regressors for no sensitivity gain."** The 125 figure is
  an artifact of flat application. Correctly applied, the budget is 5/slice.
- **"aCompCor destroys connectivity (D–D ICC 0.40 → 0.05)."** Same flat misuse.
- The **7.8% rank-deficiency** figure is also a property of the flat design, i.e.
  of a design nobody should build, and must be requalified rather than quoted.

These were listed as flagship-grade. They are not. Both must be recomputed with
slice-wise application before any version is claimed.

## What SURVIVES, and is now better sourced than my own benchmark

**The fixed per-slice component count has no precedent in 20 years of CompCor** —
established from the literature, independent of my flawed benchmark:

| implementation | stopping rule | CSF components |
|---|---|---|
| Behzadi 2007 (original) | broken-stick vs null | 6.3 ± 0.5 **total** |
| Muschelli 2014 (aCompCor50) | 50% variance | **3.0 ± 1.1** for CSF |
| Barry 2014 (cord) | 50% variance / eigenvalue gap | adaptive **2–6 per slice** |
| Ricchi 2024 (cord) | fixed K | **5 total** |
| Hemmerling 2026 (cord) | parallel analysis | median **9 total** |
| **SpinePrep** | **fixed 5 per slice** | **125–140** |

Muschelli's number is decisive: the canonical variance criterion yields ~3 CSF
components because CSF variance is low-rank, and 5 PCs already explain 70% of it.
A fixed per-slice count is an unforced design error in SpinePrep itself — a
**pipeline fix**, not a research finding.

## And the direction was already published — four times

The novelty audit found the "stricter cord denoising reduces connectivity"
direction is **not ours**: Kaptan 2023 (D–D ICC 0.71 → 0.59), Ricchi 2024
(12 pipelines, 0–40 regressors, non-denoised strongest), and above all
**Hemmerling et al. 2026, Imaging Neuroscience** (Barry & Bright; D–D difference
0.170, p = 0.006; "group-level activation maps did not show a clear benefit from
including SpinalCompCor regressors"; already recommends using it only when physio
recordings are unavailable). Brain analogues are stronger still: Hoeppli 2023
(aCompCor collapsed an auditory effect from 0.357 to 0.006), Parkes 2018
(aCompCor50 lowest test–retest reliability), Bright & Murphy 2015.

**The one genuinely novel inference remains available** — but only if the
slice-wise recomputation supports it. Kaptan interpreted reduced connectivity as
*increased validity* (removing "reliable artefacts"); Hemmerling could not rule out
that real signal was removed. Neither could resolve it, because a rest-only design
cannot. A paired task arm can: if the denoising bought validity, task detection
would rise. That inference is the publishable core, and it is currently
**unproven** because the arm that would prove it was misapplied.

## Traceability fix also required

Finding §3.2 states FD > 0.5 mm censors ~25% of frames. That figure comes from the
`framewise_displacement` column of the confounds TSV. A project spec
(`s4-fd-threshold.md`) reports median **48.5%** using a *composed* (bulk +
slice-wise) FD. Two FD definitions, a 2× spread — the same critique this section
makes of borrowed thresholds. The paper must name which FD definition it uses; all
analyses here used the TSV column.
