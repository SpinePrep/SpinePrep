# SpinePrep — flagship findings

**The verified, novelty-checked core.** Every number computed in-session on the
locked cohort (`preproc-v1`, git `961a779`, `/mnt/ssd1/spineprep_cohort_s2`,
450 runs all S9 PASS). Full detail: `analysis/COMPENDIUM.md` (Round 1) and
`analysis/ROUND2_RESULTS.md` (Rounds 2–3). Scripts: `analysis/experiments/`.

Scope: **pipeline claims only**. Design/power/scan-time belongs to P1
(`/mnt/hdd2/P3_DesignOpt/HANDOFF_FROM_P2_2026-07-25.md`).

> **NOVELTY STATUS — reviewed 2026-07-27.** Round 1 (F1–F5) was checked by dedicated
> literature review; Rounds 2–3 against targeted PubMed searches recorded in
> `analysis/NOVELTY_REVIEW.md`. **Eight claims verified novel**, one novel with a close
> neighbour to cite (Chu 2023), and **one partially scooped**: R3 fingerprinting —
> Ricchi et al., *Imaging Neuroscience* 2026 report the first cord connectivity
> fingerprint. Ours is task activation, not resting connectivity, and it is at chance.
> Reframed below. **No "first" language for fingerprinting.**

Revised 2026-07-27 to fold in Rounds 2 and 3.

---

## THE THESIS

> **Cord fMRI supports group-level detection and does not support individual-level
> inference. Its binding constraint is geometry, not statistics.**

Two halves, each carried by results that point the same way.

**Statistics are sound.** Inference runs at nominal (FWE 5.9% vs 5%), the parametric
null is correct to 1.00–1.02×, cluster inference is *conservative*, prewhitening is
unnecessary and harmful, and in the same EPI volume **the cord behaves better than the
brain** (FWE 10.4% vs 28.7% at a third of the tSNR). High-pass filtering and
physiological modelling are both inert.

**Geometry is not.** Cord distortion is **2.6× the brain's** in the same shot, the
fieldmap-less fallback under-corrects by **6×**, the non-rigid deformation the
pipeline cannot correct is **3.85× the residual rigid motion it does** in 100% of
runs, and the ROI summary measure is the largest single axis of analytic variability.

**Individual-level inference fails on every estimator tried.** Seven of them.

---

# F1 ★★★ Image-based distortion correction harms cord geometry

**The strongest finding: the only one with a physical referee, and it inverts a
recommendation shipped in the field's most-used pipeline.**

80 CoSpine reversed-PE runs, each arm judged on its **own within-run before→after**
change (registration differs between S5 invocations, so absolute across-arm values
are not comparable):

| arm | before | after | reduction | slices worsened | runs made worse |
|---|---|---|---|---|---|
| **measured field (TopUp)** | 3.34 mm | 0.62 mm | **−81%** | 9% | **1%** |
| **image-based SyN** | 1.98 mm | 2.47 mm | **+24% (WORSE)** | 65% | **82%** |

Paired Wilcoxon on per-run reduction **p = 8×10⁻¹⁵**; SyN beats TopUp on **1%** of runs.

**Triple-verified.** Independent metric (per-slice cord Dice): TopUp **+0.33**
worsening 2%; SyN **−0.039** worsening **76%**; paired Wilcoxon **p = 9.5×10⁻¹⁵**.
Per-dataset: SyN worsens **84%** (ds005883, n=37) and **81%** (ds005884, n=43).

### NEW — the premise, measured
F1 rests on the cord being the hard case for distortion. That was asserted, never
measured against the brain in one acquisition. The reversed-PE fieldmaps are full FOV
(128×128×70), so **one topup gives the measured field over both organs at once**:

| | median displacement |
|---|---|
| **cord** | **4.8 mm** |
| brain | 1.6 mm |
| **ratio** | **2.60** (IQR 1.82–5.10) |

54 runs, cord worse in **46/54**, paired **p = 1.9×10⁻⁷**. Same shot, same shim, same
subject, same field.

### NEW — the mechanism
SyN's estimated field against topup's measured one, voxelwise in the cord:
**|r| = 0.47** but magnitude ratio **0.178** (median |SyN| 0.90 mm vs |measured|
5.44 mm). SyN recovers real structure but **under-corrects by ~6×**.

The consistent negative sign is a coordinate convention, resolvable by construction:
images are LAS (anterior-positive), ANTs stores fields in LPS (posterior-positive),
and the phase-encoding axis is that axis.

**⚠ OPEN TENSION, do not gloss.** A warp pointing the right way at 18% strength should
improve geometry slightly, not degrade it in 82% of runs. The two are reconcilable —
F1's metric is per-slice centreline displacement, not global RMS, and a field right on
average but wrong in most voxels can displace tissue locally — but that reconciliation
is an **inference**, not a measurement. Confirming it needs both metrics on the same
voxels of the same run.

**Novelty (Round 1, checked): VERIFIED NOVEL, and it contradicts standing advice.**
No cord fMRI study has compared image-based SDC to a measured field (checked: Horn
2025, Oliva 2025, Neptune, SCT tutorial, Kaptan 2024 review, Kinany 2023 review, FASB,
CoSpine). **Wang et al. 2017** (Front Neuroinform 11:17) explicitly recommends *"If
there is no field map … use nonlinear registration with ANTs"*; **fMRIPrep ships this
as `--use-syn-sdc`.** No paper in brain fMRI or dMRI reports a per-run degraded
fraction. **Schilling 2024** (cord dMRI, n=214) leaves it open: *"nonlinear
registration, which is not investigated in this study."*

**Population affected:** only **83/469 runs (18%)** have a usable reversed-PE pair, so
**~82% of cord runs** are candidates for the harmful fallback.

**Reviewer hazards.** Snoussi 2021 (Cohen-Adad co-author, cord dMRI n=95) ranked
**TOPUP worst** of four measured-field methods. FASB found GRE fieldmaps gave no
significant template-overlap gain. Wang 2017 conceded MI favoured fieldmaps yet still
recommended SyN.

**Honest ceiling:** both datasets are **CoSpine — one lab, one scanner, one whole-CNS
protocol**. This is *"SyN harms cord geometry in whole-CNS EPI"*, not a general law.

---

# F2 ★★★ Analytic variability: the pipeline chooses the answer

**Supersedes and absorbs the old F2.** 54 fully defensible pipelines per dataset over
the axes measured to move the answer (summary measure, censoring fraction, smoothing)
plus the confound set.

| dataset | significant POSITIVE | sign flips | d range |
|---|---|---|---|
| ds004616 | 16/54 (**30%**) | yes | −0.56 to +1.04 |
| ds004926 | 13/54 (24%) | yes | −0.12 to +0.94 |
| ds005883 | 8/54 (15%) | yes | −0.16 to +0.44 |
| ds005884 | 9/54 (17%) | yes | −0.23 to +0.88 |

**The sign flips in all four datasets.** A single published cord pipeline reporting a
positive result was **choosing, not discovering**, and the choice was invisible to the
reader.

| axis | mean spread in group d |
|---|---|
| **summary measure** | **0.329** |
| smoothing | 0.166 |
| censoring fraction | 0.120 |
| confound set | 0.107 |

**The summary measure is the largest single axis** — which is the old F2, now
quantified against its competitors instead of asserted alone. The original sign-flip
result stands: parcel-mean −0.35/+0.10/+0.11/−0.17 against top-10%
+0.90/+0.41/+0.11/+0.44.

**The pruning is part of the result.** Four axes were excluded because this project
measured them inert: high-pass filtering, physiological modelling, prewhitening, and
the inference method. A multiverse over inert axes is padding.

**Lower bound.** Distortion could not enter — changing it means re-running the
pipeline rather than re-analysing its output — and F1 found the largest single effect
on that axis.

**⚠ CIRCULARITY DEFENCE — MUST APPEAR IN THE ABSTRACT.** Selecting top-10% voxels and
reporting an effect size from the same data is what Vul 2009 and Kriegeskorte 2009
indict. **Our d comes from odd/even split-half cross-validation.**

**⚠ ESTIMATOR CAVEAT, and it must travel with every number above.** The split-half
top-10% estimator's *magnitude* rises as run noise rises, because odd and even
timepoints are interleaved and share spatially structured noise. Measured on 126
resting runs with no task: ρ(|effect|, tSNR) = **−0.300** and **−0.478**. The group
**mean is unbiased** (group test 5.0% and 4.0% against nominal 5%), so
**method-vs-method comparisons on fixed runs are safe** — F2, the multiverse, the
kernel arms and tier-1 d all qualify. **Comparing magnitudes across runs or datasets
of differing noise is not.**

**Mechanism is geometric, not organ-specific.** In the same EPI volume the brain
dilutes exactly as the cord does when its activation is focal (motor M1) and escapes
when it is distributed (pain network). The governing variable is **activated extent ÷
ROI size**. The cord's problem is that its activation is focal in *every* task. At a
matched 19-voxel ROI the organs are comparable (+0.84/+0.50 brain, +0.47/+0.52 cord).

---

# F3 ★★★ The cord peak is not a measurement of the subject

**Replaces the old F3, which reported across-subject scatter and was open to "your
registration is bad".**

| | between runs, same session, same subject | between subjects |
|---|---|---|
| ds004616 | **12.40 mm** | 11.44 mm |
| ds005884 | **36.40 mm** | 24.80 mm |

**ICC(2,1) on the rostrocaudal peak: +0.16, +0.03, +0.05, −0.04** across four
datasets. The peak moves as much between two runs of one person minutes apart as it
does between different people.

**This closes the rebuttal.** Within-subject repeats pass through the **same
registration**, so an ICC of zero across them cannot be blamed on normalisation. It is
measurement noise.

**Our own frame was audited and came out clean.** The old F3 recorded peaks as native
voxel index × voxel size — each subject's own cropped grid, so crop placement could
have been inside the number. Against a crop-free coordinate the inflation is
**0.95–1.13×**.

### Tightened 2026-07-27 (B4) — the three things this finding needed

**Per-dataset rostrocaudal scatter, with intervals** — replacing the pooled 0.67–1.49
range, which spanned "better than chance" to "worse than chance" and hid the only
thing a reader needs. Observed SD divided by the SD of random placement in the same
ROI (1.0 = chance):

| dataset | N | SD (mm) | obs/random | 95% CI |
|---|---|---|---|---|
| ds004616 | 24 | 11.44 | **0.55** | [0.40, 0.66] |
| ds005883 | 25 | 22.85 | 0.76 | [0.57, 0.90] |
| ds005884 | 15 | 24.80 | 0.84 | [0.55, 1.06] |
| ds004926 | 37 | 18.66 | 0.86 | [0.69, 1.00] |

Every ratio is **at or below 1**, so the honest statement is *at best marginally
better than chance, never clearly so* — tighter and more defensible than the old
range, which implied some datasets were worse than random.

**The 92% laterality, tested** — an untested proportion is not evidence. Against a
50% null: **p = 1.8×10⁻⁵ to 6.2×10⁻⁸** depending on cohort size, 95% CI **[73%, 99%]**
(n=24) to **[78%, 98%]** (n=37). Quote the interval alongside the percentage.

**The random-field-theory null, considered and quantitatively excluded.** A reviewer
will answer the arbitrary-placement null with the noise-based one: for a smooth
Gaussian field the peak's positional SD ≈ FWHM / (Z_max·√(4 ln 2)), which predicts
scatter from smoothness and peak height with no biology in it. For any plausible
values (FWHM 4–10 mm, Z_max 3–5) that predicts **0.5–2.5 mm**. The measured
rostrocaudal scatter is **11–25 mm** — an order of magnitude larger. **The noise-based
null does not explain the scatter**, so the arbitrary-placement null is the right
comparison. State it as excluded, not ignored.

The same expression settles the in-plane question: it predicts 0.5–2.5 mm and the
observed in-plane SD is **0.27–0.68 mm**, *smaller* than noise alone would give —
confirming the peak is pinned by the ROI's width rather than well localised.

**⚠ GUARDRAILS.**
- The in-plane SDs (0.27–0.68 mm) are **not** evidence of good localisation. The horn
  is a 15-voxel column, 72 mm long and a couple of voxels across, so in plane the peak
  has nowhere to go. The negative in-plane ICCs are that ceiling.
- **Do NOT claim centre-of-mass beats the peak** — contradicted by Nettekoven 2018 and
  Weiss 2013; the clean evidence is TMS, not fMRI. **Do not cite Morrison 2016**
  (removed from the compendium 2026-07-27; primary source unlocatable).
- **Must scope to TASK activation.** Resting patterns are stable (Kowalczyk 2024,
  Ricchi 2026).

**Convergent cord evidence (Round 1, checked).** Dabbagh 2024 (n=40, two days): group
across-day Dice **0**, only 5/35 subjects overlapping, and the *same anisotropy* —
*"the location on the dorsal-ventral dimension remained similar, the patterns differed
rostrocaudally"*. Seifert 2024 explicitly invites this study. Kowalczyk 2025 Dice
0.01/0.04. **Cord is not worse than brain:** Wang 2021 (n=893) peak-to-hotspot
8.7–20.8 mm.

### What spatial claim IS supportable
A monotone ordering, after the tSNR and mean-signal patterns are regressed out:

| spatial summary | within-subject similarity |
|---|---|
| peak | ICC ≈ 0 |
| pattern (horn × level) | +0.08 to +0.19 |
| **profile (level only)** | **+0.22 to +0.36** |

**Scoped by the repeat axis, and the split is systematic.** The profile reproduces in
exactly the two datasets whose repeats are runs minutes apart in one session
(p = 0.001; p = 0.004–0.028) and fails in both whose repeats span sessions (p = 0.88,
p = 0.18). So **the profile survives minutes and not a session gap.**

Identification accuracy is at chance for the task pattern everywhere, while the
**mean-signal and tSNR maps identify subjects strongly** (0.56–0.60 vs 0.04–0.11
permuted chance). Anatomy and vasculature are a powerful cord fingerprint; the task
response is not.

**⚠ POSITION AGAINST Ricchi et al. 2026** (*Imaging Neuroscience*, "Spine-prints:
Transposing brain fingerprints to the spinal cord"), which reports the **first cord
connectivity fingerprint** — 53.3% identification against 8.3% chance, from
resting-state functional connectivity. **Do not claim priority on cord
fingerprinting, and use no "first" language.** Two things here survive, and both are
worth more as a caveat on that paper than as a claim of our own:

1. **Task activation does not fingerprint while resting connectivity does** — a
   dissociation between the two, not a contradiction of either.
2. **Their acknowledged limitation may be a confound.** They attribute the lower
   spine-print score to low tSNR. We measured that anatomy and tSNR patterns *on their
   own* identify subjects far above chance, so a cord connectivity fingerprint could
   partly ride on them. That control does not appear in their paper.

---

# F4 ★★★ Individual-level cord fMRI fails on every estimator tried

**New, and the most defensible claim in the set**. Seven independent
estimators, one answer.

| what | measured |
|---|---|
| effect magnitude | ICC ≈ **0.05** (Dabbagh 2024: 0.03) |
| peak location | ICC ≈ **0**; between-run noise ≥ between-subject variance |
| response pattern | identification at **chance** |
| rostrocaudal profile | reproduces within session, **not** across sessions |
| trial-wise behavioural coupling | **absent** (grip force, pain intensity, unpleasantness) |
| run-level rating coupling | **absent**; the only significant result is in the *control* ROI |
| binary responder call | kappa **+0.184** (p = 0.061) and **−0.052** |

**The behavioural referee is the important one.** Every earlier effect analysis tested
a response against zero; this tests whether it tracks something measured outside the
BOLD data. Grip force — a 100 Hz physical measurement, the strongest referee
available — gives ipsi-horn ρ = +0.055 (p = 0.43).

### The consequence, as arithmetic
With effect ICC 0.05:

| | |
|---|---|
| max correlation with a well-measured clinical score | **0.21** |
| N to detect it at 80% power, if the true relation is perfect | **172** |
| independent sessions to reach ICC 0.75 | **57** |

Largest published cord studies run n = 20–48. **Constructive half:** resting
connectivity at ICC 0.49 (Kaptan 0.63) needs 3 sessions for the good band and has a
ceiling correlation of 0.66. **If the field wants an individual-level spinal measure,
the arithmetic points at connectivity, not task activation.**

### Where group detection does work
- **Group inference is valid**: FWE 5.9% [5.3, 6.6] vs nominal 5%; cluster inference
  conservative at 1.4%; parametric null correct to 1.00–1.02×.
- **A null effect-size floor**: |d| p95 = **0.31** using the identical estimator, from
  resting data with random designs. ds004926's d = 0.11 sits inside it.
- **Uncorrected p<0.001 declares activation in 53% of runs containing none.**
- **Multivariate detection can rescue a univariate null but does not reliably.** In
  ds005883 the univariate mean sits at exactly 0.500 while multivariate reaches
  **0.639 from the whole cord** (p = 0.0001) — no anatomical guess needed. Pooled
  across datasets nothing is significant, and 3 of 5 are null.
- **Model-free ISC works at 1–3%**: ds004616 whole cord +0.0295 against a shift null of
  −0.0004. Against 0.3–0.6 for brain sensory cortex. *Caveat:* ISC cannot separate
  shared neural response from shared task-locked artifact, since every subject grips at
  the same times; the whole-cord ISC exceeding the horn's argues for the artifact
  reading.

---

# F5 ★★ Pipeline defects with measured costs

Three concrete, actionable findings about the pipeline itself.

**The confound model spends most of the run.** Across 450 runs: CSF (slice-wise
aCompCor) is **110 columns, 78%** of all confound regressors. **85.8% of runs spend
more than half their frames on confounds**; **7.8% have no residual degrees of freedom
at all** (ds005884: 115 frames vs 168 columns → **dof = −54**). The count is 5
components *per slice*; no published implementation uses a per-slice count, and against
the totals those papers report ours is 12× Hemmerling 2026, 18× Behzadi 2007, 22×
Ricchi 2024, 37× Muschelli 2014.

**And applying it correctly settles a live disagreement.** The retracted analysis
applied the slice-wise design flat; done correctly:

| endpoint | slice-wise vs none | p |
|---|---|---|
| task detection | −0.019 | 0.582 |
| V–V connectivity | **−0.121** | **2.3×10⁻³⁵** |

Connectivity falls ~35% while task detection is unchanged. If the removed component
were neural, the task effect should have fallen with it. **Supports Kaptan 2023's
reading over Hemmerling 2026's.** Slice-wise beats flat on every axis: same task
detection, less connectivity destroyed, **38 dof recovered per run**.

**The deformation the pipeline cannot correct is 4× what it does.** Residual rigid
motion after S4 is 0.014 mm; non-rigid centreline deformation is 0.053 mm, a ratio of
**3.85**, and non-rigid exceeds rigid in **416/416 runs (100%)** across all nine
datasets. S4 removes what it models; what it does not model is four times larger. A
cord-specific failure mode with no brain analogue.

**The QC metrics measure the site, not the person.** Variance split across 33 metrics:
**48% dataset, 19% subject, 33% run**, and dataset dominates subject in **27 of 33**.
The exceptions are the anatomical ones (cord CSA 82% subject). No QC family predicts
per-run scientific outcome — every leave-one-dataset-out R² is negative. **The metrics
flag broken runs; they do not rank usable ones.** A6 explains that null: half the
variance is between-dataset, leaving little within one.

---

# SUPPORTING

**Scoped replication.** Laterality **92%** ipsilateral vs Hemmerling's LI 0.96–0.99,
competitive with the fMRI–Wada clinical standard (86–97%). Pain reliability ICC 0.05
vs Dabbagh 0.03. V–V connectivity 0.49 vs Kaptan 0.63. **What does NOT replicate:**
universal group task activation — under unbiased CV only **1 of 4** is significant.
Not a pipeline failure; it independently reproduces P1's leave-subject-out result.

**Smoothing — largely published, do not lead.** Best kernel differs per dataset. Two
observations worth more than the ranking: **no arm changes the effect** (every paired
test p > 0.18 — the group-d spread comes from smoothing shrinking the between-subject
SD, not raising the effect), and **the field's "isotropic" kernel is not isotropic**
(at 4 mm slices a 2 mm FWHM kernel has σ_z = 0.21 voxels; iso2 and inplane2 return
bit-identical results).

**Motion correction** — tSNR gain +0%, +3%, +118%, +121%; no consistent transfer.
**High-pass filtering** — null. **Physio** — not edge-concentrated, null.
**Global signal** — 1–2% of cord variance on preprocessed data and ~1% on raw, neither
large nor task-locked; no basis for global signal regression.

---

# RETRACTED — do not use

1. **"7/7 replication"** → 1/4 under unbiased CV.
2. **Reliability-vs-spatial-scale decline** — aggregation artifact.
3. **"Laterality flips across preprocessing arms"** — false alarm (LI ≈ 0, noise).
4. **Suprathreshold-count effect size** — invalid test.
5. **High-pass "costs 33–56%"** — CV shared drift.
6. **Motion-correction ablation v1** — three confounds.
7. **aCompCor v1** — slice-wise design applied flat. **Now superseded by A1**, which
   redoes it correctly; the finding is different from the retracted one.
8. **Two invalid N3 designs** — leave-one-out bias below chance, then baseline
   sampling confounded with time-in-run (event-free frames at mean index 157 vs 77).

---

# FAILED PREDICTIONS — kept visible

Of the predictions made across Rounds 2–3, these were wrong:

| prediction | outcome |
|---|---|
| cord inference is inflated | valid at nominal; cord *better* than brain |
| cord-shaped smoothing beats isotropic | isotropic won |
| QC metrics predict scientific outcome | every family negative |
| cord BOLD tracks behaviour trial-wise | null on all three criteria |
| the global signal explains the anomaly | 1–2%, twice; still unexplained |
| dilution curves superimpose across organs | they do not; extent÷ROI governs |
| SyN's field is unrelated to the truth | |r| = 0.47; it under-corrects instead |

**Nine self-caught errors in Round 1 and seven failed predictions since. Every claim
checked hard either gained a caveat or died. That is the reason to trust what
remains.**

---

# VENUE

**Imaging Neuroscience** solid; NeuroImage/HBM a reach. **Not Nature-tier** — Neptune
(Rangaprakash & Barry 2026) removes the "first tool" claim.

The two strongest cards are now **F2's analytic variability** (a NARPS-shaped result
the cord field does not have) and **F4's seven-estimator convergence** on individual
level failure, which has a direct clinical consequence. F1 remains the finding with a
physical referee, and it now has both its premise and its mechanism measured.

# OPEN

- **The ds005884 whole-cord anomaly** (mean d +0.72 at 657 of ~848 voxels). Two
  explanations attempted, both failed.
- **F1's tension**: under-correction at 18% strength should not worsen geometry in 82%
  of runs. Needs both metrics on the same voxels of the same run.
- **All Round 2–3 novelty marks are unchecked.** The search budget ran out.
- **R10 excludes distortion**; adding it requires re-running S5 per arm.
