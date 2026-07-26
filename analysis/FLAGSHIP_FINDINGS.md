# SpinePrep — flagship findings

**The verified, novelty-checked core.** Every number computed in-session on the
locked cohort (`preproc-v1`, git `961a779`, `/mnt/ssd1/spineprep_cohort_s2`,
450 runs all S9 PASS). Every novelty verdict checked against the literature by
dedicated review. Full detail and all retractions: `analysis/COMPENDIUM.md`.
Scripts: `analysis/experiments/`.

Scope: **pipeline claims only**. Design/power/scan-time belongs to P1
(`/mnt/hdd2/P3_DesignOpt/HANDOFF_FROM_P2_2026-07-25.md`).

---

## THE UNIFYING THESIS

> **Cord activation is focal relative to every spatial unit the field currently
> analyses it with.**

One measured fact explains three findings:
- **parcels dilute it** (F2 — ROI summary reverses the answer)
- **its peak is unlocatable** (F3 — peak scatter ≈ random)
- **kernels wider than a horn erase it** (S1 — smoothing)

**Mechanism, measured:** an individual grey-matter horn is median **4.5 mm²**
(2–5 mm × 2–3 mm) against a cervical cord cross-section of 58–88 mm². A **4–6 mm
FWHM kernel is wider than a single horn.** Dabbagh's 61-voxel group map and the
4.5 mm² horn are the same observation from two directions.

**Why this framing:** each finding is *partially* known, so presented separately
they invite "already published". The unifying claim is **not** published, and it
converts three partial novelties into one argument with a measured mechanism.

---

# F1 ★★★ Image-based distortion correction harms cord geometry

**The strongest finding: the only one with a physical referee, and it inverts a
recommendation shipped in the field's most-used pipeline.**

80 CoSpine reversed-PE runs, each arm judged on its **own within-run
before→after** change (registration differs between S5 invocations, so absolute
across-arm values are not comparable):

| arm | before | after | reduction | slices worsened | runs made worse |
|---|---|---|---|---|---|
| **measured field (TopUp)** | 3.34 mm | 0.62 mm | **−81%** | 9% | **1%** |
| **image-based SyN** | 1.98 mm | 2.47 mm | **+24% (WORSE)** | 65% | **82%** |

Paired Wilcoxon on per-run reduction **p = 8×10⁻¹⁵**; SyN beats TopUp on **1%** of runs.

**Triple-verified**
- Independent metric (per-slice cord Dice): TopUp **+0.33** worsening 2%; SyN
  **−0.039** worsening **76%**; paired Wilcoxon **p = 9.5×10⁻¹⁵**.
- Per-dataset: SyN worsens **84%** (ds005883, n=37) and **81%** (ds005884, n=43).
- Two differently-computed metrics agree → not a metric artifact.

**Novelty: VERIFIED NOVEL, and it contradicts standing advice**
- No cord fMRI study has *ever* compared image-based SDC to a measured field
  (checked: Horn 2025, Oliva 2025, Neptune, SCT tutorial, Kaptan 2024 review,
  Kinany 2023 review, FASB, CoSpine).
- **Wang et al. 2017** (Front Neuroinform 11:17) explicitly recommends: *"If there
  is no field map … use nonlinear registration with ANTs to correct distortion."*
  **fMRIPrep ships this as `--use-syn-sdc`.** Montez 2023, Schilling 2019,
  Yu 2023 all report fieldmap-less as comparable or better.
- **No paper in brain fMRI or dMRI reports a per-run degraded fraction** — the
  "82% of runs worsened" statistic is unprecedented in either field.
- Closest prior work leaves it open — **Schilling 2024** (cord dMRI, 214
  participants): *"nonlinear registration, which is not investigated in this study."*
- The one prior assertion (**FASB**, Research Square preprint: *"performing a
  nonlinear transformation generates non-optimal twisted warping fields"*) is a
  Discussion sentence with **zero measurement**.

**Population affected:** only **83/469 runs (18%)** have a usable reversed-PE pair,
so **~82% of cord runs** are candidates for the harmful fallback. First such count.

**The strongest lever — lead with this.** TopUp removing 81% is a concrete case for
adding a ~30 s reversed-PE pair to cord protocols. **Horn 2025 and Oliva 2025
already acquire opposing-PE data and discard it for the cord.**

**Reviewer hazards to pre-empt**
1. **Snoussi 2021** (arXiv:2108.03817, Cohen-Adad co-author, cord dMRI n=95) ranked
   **TOPUP worst** of four measured-field methods, "significant deterioration at C2".
2. **FASB** found GRE fieldmaps gave no significant template-overlap gain (p > 0.05).
3. **Wang 2017** conceded MI favoured fieldmaps yet still recommended SyN.

**Honest ceiling:** both datasets are **CoSpine — one lab, one scanner, one
whole-CNS protocol** (the highest-distortion regime). This is *"SyN harms cord
geometry in whole-CNS EPI"*, **not a general law**, until it replicates on
cervical-only reduced-FOV data from another vendor.

---

# F2 ★★★ The ROI summary measure reverses the answer

**Most citable: every cord task-fMRI paper must choose a summary measure.**

Same data, same GLM, different summary of the a-priori focal horn (group Cohen's d):

| dataset | parcel-MEAN | top-10% | peak |
|---|---|---|---|
| ds004616 | **−0.35** | **+0.90** | +0.25 |
| ds005884 | +0.10 | +0.41 | +0.15 |
| ds004926 | +0.11 | +0.11 | +0.24 |
| ds005883 | **−0.17** | +0.44 | +0.16 |

The parcel-mean costs ~all detectability and **inverts the sign in 2 of 4 datasets**.

**Novelty: PARTIALLY KNOWN — the sign flip is novel**
- Brain, already published: **Poldrack 2007** states the mechanism verbatim;
  **Nieto-Castañón & Fedorenko 2012** derive "partial coverage" (0.05 %BOLD where
  truth is 1.02 — 20-fold dilution); **Tong et al. 2016** compared **ten** summary
  measures across **four** datasets — structurally this study, in brain, ten years
  ago; **Mitsis 2008** found top-20% most reliable.
- Cord: **Dabbagh 2024 used our exact three measures.** Table 1 (left dorsal horn
  C6, β): ROI-average ICC **0.03**, peak **0.20**, top-10% **0.20** — the average is
  worst every time. They wrote the dilution argument down and **dismissed it**.
  **Oliva 2025**: *"Averaging across all spinal cord segments could hide activation."*
- **Genuinely ours:** (1) the **sign flip** — no documented case in brain or cord
  where summary choice *reverses the direction* of a group effect; (2) framing as
  **group detection / effect size** rather than reliability — and **none of the five
  key cord papers reports a group Cohen's d at all**, which is exactly why the sign
  problem went unnoticed.

**⚠ CIRCULARITY DEFENCE — MUST APPEAR IN THE ABSTRACT.** Selecting top-10% voxels
and reporting an effect size from the same data is what Vul 2009 and
Kriegeskorte 2009 indict as double dipping. **Our d comes from odd/even split-half
cross-validation** — voxels selected on one half, measured on the other. State this
prominently or the finding reads as circular.

---

# F3 ★★ Inter-subject variability of peak location

**The random-placement null appears to be novel in either organ.**

Across-subject scatter of each subject's peak-activation voxel inside the a-priori
horn, normalised against RANDOM placement in that ROI (span/√12; 1.0 = chance):

| dataset | raw SD L-R | raw SD A-P | raw SD rostrocaudal | obs/random x, y, z |
|---|---|---|---|---|
| ds004616 | 1.05 mm | 2.15 mm | **13.98 mm** | 0.73, 1.49, 0.67 |
| ds004926 | 1.20 mm | 3.87 mm | **18.84 mm** | 1.04, 1.41, 0.93 |

Two true readings: normalised, **no better-than-chance consistency on any axis**;
raw, localisation is **anisotropic** — in-plane to 1–4 mm, rostrocaudal to 14–19 mm.

**Terminology:** this is *inter-subject variability*, **not** test-retest
reproducibility. Use the correct term.

**Convergent cord evidence**
- **Dabbagh 2024** (n=40, two days, same organ): group across-day Dice **0** at
  corrected threshold; only **5/35** subjects overlapped. Verbatim: *"while the
  location on the dorsal-ventral dimension remained similar, the patterns differed
  rostrocaudally"* — the **same anisotropy**, independent lab and metric.
- **Seifert 2024** (HBM, doi:10.1002/hbm.26597): peak S-I location varies *"up to
  1½ vertebral levels"* within subjects, and explicitly invites this study: *"The
  cause for this variation is unclear without conducting a reproducibility study."*
- **Kowalczyk 2025**: Dice 0.01 within-visit, 0.04 between-visit.

**Cord is not worse than brain:** Wang 2021 (n=893) individual peak to atlas
hotspot **8.7–20.8 mm**; Zhen 2017 scene regions **>20 mm**. Our 14–19 mm sits
inside that range.

**Aggregate/peak dissociation is well supported:** Wilson 2018 (LI ICC **0.88** vs
voxel Dice **0.66** on the same data); Sanchez Panchuelo 2024 (ICC 0.76 vs overlap
≥52%); **Hu 2022** — best citation — component ICC **0.72–0.80** while the peak moves
**18.8–21.5 mm**, only **41%** within 10 mm; Zhao N 2022 (CoG 3.8–7.3 mm vs FC peak
~30 mm); Kolasinski 2016 (relational α **0.84–0.97** despite five-fold spread).

**Must scope to TASK activation** — resting-state patterns are stable
(Kowalczyk 2024 DSC 0.88 group / 0.67 subject; Ricchi 2026 connectivity fingerprint).

**Impact:** invalidates a class of published claims — Hemmerling 2023 (*"most
concentrated in the C7 segment"*), Kowalczyk 2025 (*"peaks at levels C6 and C7"*),
Seifert 2024 (C6). High ceiling, high variance.

**Tightening required**
- Report **per-dataset values with intervals**, not the 0.67–1.49 range (which spans
  "somewhat better than random" to "worse than random").
- Give the **binomial test** for the 92% laterality (chance = 50%).
- Pre-empt the RFT alternative: SD(peak) ≈ FWHM/(MaxZ·√(4log2)), 95% half-widths
  3–10 mm (Ma/Worsley/Evans) — a *noise-based* null. Justify why an
  arbitrary-placement null is the right comparison.

**⚠ GUARDRAIL — do NOT claim centre-of-mass beats the peak.** Unestablished in fMRI
and contradicted by **Nettekoven 2018** (maxima 6.45 ± 1.36 mm beat CoG
8.03 ± 2.01 mm, significantly) and **Weiss 2013** (peak ICC > 0.8). The clean
CoG-beats-hotspot evidence is **TMS**, not fMRI (Nazarova 2021, Kahl 2023). Also:
**do not cite Morrison 2016** — the primary paper could not be located.

---

# F4 ★★ The borrowed FD censoring threshold sits in the known-harmful regime

| rule | frames removed | median group d (4 datasets) |
|---|---|---|
| no censoring | 0% | +0.197 |
| **worst 10% (light)** | 10% | **+0.425** |
| FD > 0.5 mm (brain rule, Power 2012) | 25% | +0.062 |
| cord percentile **matched to 25%** | 25% | **+0.062 — identical** |

Censoring ~10% improves detectability (**+116%** over none); ~25% badly hurts it
(**−69%**).

**Correction to my own framing:** the fraction-matched control is *identical*,
because any FD threshold is a monotone selection of the worst frames. The threshold
**value is irrelevant — only the fraction matters.** Jones 2022 already adopted
frame-percent thresholding for exactly this reason, so the "fraction beats threshold"
argument is a framing device, not a discovery.

**What IS novel and verified:** **no cord paper publishes a frame-censoring FD
threshold.** Ricchi 2024 excludes *subjects* (mean FD > 0.4 mm); **Kaptan 2023
censors ~1.9%** via dVARS. So the brain-imported FD > 0.5 mm is **~12× more
aggressive than actual cord practice**, squarely in the regime Siegel 2014,
Jones 2022, Pham 2023 and Mejia 2026 independently call harmful. Brain consensus
optimum is ~1–5%.

**Traceability fix required:** our 25% comes from the `framewise_displacement`
column. A project spec (`s4-fd-threshold.md`) reports **48.5%** using a *composed*
FD. Name the definition used.

---

# F5 ★ Scoped replication

| what replicates | ours | published |
|---|---|---|
| **Laterality** (Hemmerling 2023) | **92%** ipsilateral | LI 0.96–0.99 |
| **Pain reliability** (Dabbagh 2024) | effect ICC **0.05** | β-avg **0.03** |
| **V–V connectivity** (Kaptan 2023) | ICC **0.49** | 0.63 |
| Motor group activation (ds004616) | **d 0.64, p=0.005** (unbiased CV) | — |

**92% is competitive with the clinical standard:** fMRI–Wada concordance runs
**86–97%** (Campbell 2023: 91.4%, 96.9%; Herfurth 2022: 85.7%); Gerrits 2025 gives
97% categorical reproducibility for strongly-lateralised vs 51% bilateral.

**⚠ What does NOT replicate:** universal group task activation. The earlier
"7/7, t = 11–21" used **biased** selection; under unbiased CV only **1 of 4** is
significant. This is *not* a pipeline failure — it independently reproduces P1's
leave-subject-out finding that cross-validated cord task effects are near zero.
Two projects, two estimators, one answer.

---

# SUPPORTING (not flagship)

**S1 Smoothing — largely published; do not lead with it.** Best kernel differs per
dataset (4/2/6/2 mm) and 4–6 mm destroys the effect in ds005884 (+0.26 → −0.06).
But brain settled it in 2008 (**Weibull 2008**: optimum depends on CNR), and both
cord numbers are already published — **Hemmerling 2023** on active-voxel inflation
(*"Unsurprisingly…"*, ~50→200 voxels; our 2.7× is a replication) and **Kaptan 2023**
on a smoothing-induced **sign change**, concluding *"even modest smoothing kernels
such as 2 mm should only be employed with great caution."* **Ours:** the first cord
kernel sweep on **task effect size**, plus a direct correction of Hemmerling's
conclusion that "smoothing … improved sensitivity", with the 4.5 mm² horn as the
mechanism.

**S2 Motion correction — heterogeneous, no consistent transfer.** tSNR gain +0%,
+3%, +118%, +121% across datasets; detectability change inconsistent. Stated as "no
consistent translation", not "moco does not help".

**S3 High-pass filtering — null.** Median group d 0.035 → −0.020 across
none→quarter→half→all (fixed-ROI design). Justifies the inherited 100 s cutoff as
harmless.

**S4 Physio noise is not edge-concentrated — null.** RETROICOR rim/core gain ≈ 1.1.
It explains 10–17% of cord variance uniformly without improving detection.

---

# RETRACTED — do not use

1. **aCompCor findings** — I applied a **slice-wise** CSF design **flat** (125 columns
   to every voxel; S8's spec: *"The design is built for a SLICEWISE GLM"*). Both the
   task and connectivity arms are invalid. **Also scooped four times** — Kaptan 2023,
   Ricchi 2024, **Hemmerling 2026** (Imaging Neuroscience, Barry & Bright: D–D
   difference 0.170, p=0.006; already recommends restricting SpinalCompCor), plus
   brain analogues Hoeppli 2023, Parkes 2018.
   *Survives as a **pipeline bug**, sourced from literature not my benchmark:*
   SpinePrep's fixed **5 components per slice** (125–140 total) has **no precedent** —
   Behzadi 6 total, Muschelli **3 for CSF**, Barry adaptive 2–6, Ricchi 5 total,
   Hemmerling median 9. Fix the pipeline.
2. **"7/7 replication"** → 1/4 under unbiased CV.
3. **Reliability-vs-spatial-scale decline** — aggregation artifact.
4. **"Laterality flips across preprocessing arms"** — false alarm (LI ≈ 0, noise).
5. **Suprathreshold-count effect size** — invalid test (non-negative vs zero).
6. **High-pass "costs 33–56%"** — CV shared drift.
7. **Motion-correction ablation v1** — three confounds.

---

# VENUE

**Imaging Neuroscience** solid; NeuroImage/HBM a reach. **Not Nature-tier** — Neptune
(Rangaprakash & Barry 2026) removes the "first tool" claim, and corrective
preprocessing findings do not carry that tier without Marek-scale samples or a
NARPS-scale design. Honest strengths: **scope** (9 datasets, one pipeline),
**reproducibility** (containerised BIDS-App + receipt), and a **measured physical
ground truth** in the strongest arm.

# THE PATTERN WORTH KNOWING

Nine self-caught errors and three confounded headline claims were found by auditing
this work. **Every claim checked hard either gained a caveat or died; nothing
survived unchanged.** Three that looked like headlines — "motion correction hurts
cord fMRI", "filtering costs half your signal", "preprocessing flips your
conclusions" — were all artifacts. That is the reason to trust what remains.
