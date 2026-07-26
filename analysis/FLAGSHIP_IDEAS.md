# Where the next flagship comes from

Companion to `FLAGSHIP_FINDINGS.md` (what is proven) and `COMPENDIUM.md` (the full
record). This file is **speculative by design**: it holds the reasoning about what to
try next. Nothing here is a result. Novelty claims marked *(unchecked)* have not been
put through a literature review yet and must not enter prose in that state.

---

## 1. The vision shift

Everything proven so far argues by **comparison to the brain literature**: our number
against Power 2012, Wang 2017, Poldrack 2007. That is the weakest form of the argument,
because a reviewer can always answer "different data, different scanner, different
decade."

**Three datasets in this cohort acquire the brain and the cervical cord in the same EPI
volume.** ds005884 and ds005883 (CoSpine task, fmap + physio) are 128 x 128 x 70 at
1.5 x 1.5 x 4 mm, which is 280 mm of through-slice coverage: brain and cord, one run,
one TR, one motion trace, one distortion field. ds005075 adds resting state.

That converts every claim of the form *"the cord is not a small brain"* from a
cross-literature comparison into a **within-run controlled contrast**. Same subject,
same volume, same noise, same pipeline; only the organ differs. No cord methods paper
has done this *(unchecked)*, and it is the highest-leverage change available because it
strengthens findings that already exist rather than requiring new ones:

| existing finding | with the paired-organ control |
|---|---|
| F1 SyN worsens cord geometry | does SyN help the brain in the **same volume** while harming the cord? If yes, the recommendation is not wrong, it is **organ-specific** — a far more publishable and more defensible statement |
| F2 parcel-mean reverses the sign | does the same parcel-mean applied to M1 in the same run behave normally? Isolates the mechanism as **structure size**, not GLM or noise |
| F3 peak scatter at chance | cord peak scatter vs M1 peak scatter, same subjects, same registration pipeline. Removes the "your registration is just bad" rebuttal |
| F4 FD censoring optimum ~10% | is the optimum the same for the brain in the same run? If the cord optimum differs, motion affects the two organs differently — mechanistic, not conventional |

The brain becomes a **positive control with known ground truth**. This is the answer to
"what do we borrow from the brain domain": not the literature. The organ, in the same
run.

---

## 2. The single biggest untapped asset: 504 resting-state runs

All analysis to date used the ~324 task runs. The cohort contains **504 rest runs**,
including a dedicated 48-subject two-session test-retest dataset (ds004386).

A resting run has **no task in it**. Fit a task GLM to it and every positive result is a
false positive, with no modelling assumption required to know that. This is the
Eklund 2016 design (which used resting brain data to show cluster inference runs at
inflated family-wise error, and ran in PNAS).

### Idea N1 — the empirical false-positive rate of cord fMRI inference

**Design.** Take each of the 9 datasets' real task designs. Fit them to resting runs
from the cohort. Apply the thresholds the cord literature actually uses (the specific
p, cluster, and correction choices in Kaptan 2023, Hemmerling 2023, Dabbagh 2024,
Seifert 2024). Count how often a "significant" cord activation appears where none can
exist. Repeat with phase-randomised designs for a second null.

**Why it should be inflated, mechanistically.** Three reasons, all cord-specific and
all measurable in the same experiment:

1. **Aliased cardiac pulsation.** CSF and cord move at ~1 Hz. With TR 2.7 s the
   Nyquist limit is 0.19 Hz, so pulsation aliases into the task band as *structured*
   signal, not white noise. A design regressor at 20-30 s periods can partly match it.
2. **Random field theory does not hold in a 1 cm tube.** RFT assumes a smooth random
   field over a 3D volume. The cord mask is roughly 600 voxels in a tube. Nichols &
   Hayasaka 2003 already recommend permutation for small search volumes in the brain;
   nobody has said it for the cord *(unchecked)*.
3. **Prewhitening is probably mis-specified.** Olszowy 2019 showed FSL, SPM and AFNI
   all misestimate autocorrelation in the brain, inflating false positives. Cord noise
   is worse behaved: aliased, non-stationary, and spatially structured along the CSF
   boundary. Testable directly — fit the standard AR model, then check whether the
   residuals are actually white. If they are not, **every t-statistic in the cord
   literature is inflated by a knowable factor.**

**Why this is the top candidate.**
- Unambiguous ground truth. No task means no true positive. Nothing to argue about.
- Constructive by implication: the fix is permutation or sign-flipping inference, which
  we can then validate and ship in the pipeline.
- It **explains our own null result** (F5: only 1 of 4 datasets survives unbiased
  cross-validation). If the inferential apparatus is inflated, published cord
  activations and our own biased-selection numbers are the same phenomenon.
- Cheap. The GLM machinery exists; only the null data are new.
- With the paired-organ asset, the headline sharpens further: **cord FPR vs brain FPR in
  the same runs.**

**What would kill it.** If the measured FPR sits near nominal, the finding is a clean,
useful, publishable null that validates the field's inference and retires a worry. Low
downside either way.

---

## 3. Borrowed from the brain, no cord analogue yet

Ranked by (novelty x impact) / cost. All novelty marks are *(unchecked)*.

### N2 — Cord-shaped smoothing (the constructive answer to our own thesis)

Our thesis says a 4-6 mm isotropic kernel is wider than a 4.5 mm² horn. The brain solved
exactly this problem for focal structures by **stopping isotropic volume smoothing**:
surface-constrained smoothing (Glasser 2013), spatially adaptive Bayesian models
(Mejia 2020). The cord has an obvious geometry to exploit and nobody exploits it.

Three arms, each defensible and each new to the cord:
- **Rostrocaudal-only kernel.** The cord is a tube. Smooth along z, not across the
  2-3 mm horn. Anisotropic kernels are standard in dMRI, absent in cord fMRI.
- **Mask-constrained smoothing.** Never average across the cord/CSF boundary. The
  segmentation already exists at every step.
- **Within-horn geodesic smoothing.** Restrict the neighbourhood to the parcel.

If any arm gains sensitivity *without* Kaptan's smoothing-induced sign change, that is a
concrete, adoptable method with a measured mechanism. It converts the paper's spine from
a warning into a tool, and tool adoption is what makes a methods paper canonical.

### N3 — Multivariate detection as the correct summary measure

F2 shows the parcel-mean destroys and can invert the effect, and top-10% recovers it.
Both are univariate summaries of a focal pattern. The brain answer to focal signal in a
small ROI is **multivariate** (cross-validated classification, not averaging), which is
immune to the dilution mechanism because it never averages.

**Design.** Cross-validated task-vs-rest classification within the a-priori horn,
against univariate d on the same runs and the same folds. If MVPA recovers the three
datasets that are null under unbiased univariate CV, then the field's nulls are a
**summary-measure artifact, not an absence of signal** — which is the constructive twin
of F2, and a much better story than "use top-10%".

Cheap, uses existing parcels and designs, and the cross-validation structure that already
protects F2 from circularity protects this too.

### N4 — Decomposing the peak scatter into registration error and biology

F3 reports 14-19 mm rostrocaudal peak scatter at chance level, and it is descriptive:
it invites "so what" and "your normalisation is bad."

**Design.** Measure the scatter of *anatomical* landmarks after the same normalisation
(vertebral level boundaries, cord centreline, C2/C3 disc) in the same subjects. That
partitions the 14-19 mm into a registration component and a residual biological
component. Both answers are strong and they point in opposite directions:
- registration dominates → the fix is normalisation, and this is a **pipeline
  development target** with a number attached
- biology dominates → **group-level vertebral-level claims are not supportable**, which
  invalidates a class of published statements

Elevating F3 from a description to a variance decomposition is the difference between two
stars and three.

### N5 — The cord multiverse

NARPS (Botvinik-Nezer 2020) had 70 teams analyse one dataset and reach conflicting
conclusions; Carp 2012 enumerated 34,560 brain pipelines. **The cord has no multiverse
analysis** *(unchecked)*, and the cord is where it is actually tractable: the defensible
choice space is small enough to enumerate exhaustively rather than sample.

Our knobs, each with published precedent for more than one setting: distortion
(topup / SyN / none), smoothing (0 / 2 / 4 / 6), censoring fraction (0 / 10% / 25%),
summary measure (mean / top-10% / peak), confound family, high-pass. That is a few
hundred fully defensible pipelines, all runnable.

The deliverable is a distribution of the **scientific conclusion**, not of a metric:
across all defensible pipelines, what fraction find the published effect? F2's sign flip
is a one-dimensional slice of this. The full version is a different class of paper, and
SpinePrep is the only thing that can run it because the knobs are already policy YAML.

Cost is the highest here, and the risk is that the answer is "conclusions are stable,"
which is a valuable but unexciting null.

### N6 — Normative cord fMRI quality distributions (the MRIQC move)

We have 450 harmonised runs across 9 datasets and vendors, plus a 397-participant
segmentation database (ds005143). Nobody else has this; the largest cord fMRI studies are
single-site with n around 40.

Publish the **normative distributions** of tSNR, FD, cord cross-sectional area, DVARS and
the distortion gap statistic, per vendor and protocol, so any new study can locate itself
in a reference population. This is what MRIQC did for the brain and it is cited forever.
Pair it with a **variance decomposition** (dataset vs subject vs run), which directly
tests the project's own invariant that heterogeneity is signal: if dataset dominates
subject, multi-site cord fMRI needs harmonisation before pooling, and that is the first
such statement in the field *(unchecked)*.

Lower ceiling on excitement, highest floor on citation, and near-zero risk. Strong
candidate for a companion paper rather than the flagship.

### N7 — Physio-free respiratory estimation

The brain field learned to recover respiration from the fMRI data itself when the belt is
missing (Power 2020, Lynch 2020). In the cord, where B0 shifts are respiration-driven and
belts are frequently absent, recovering the respiratory trace from CSF or edge voxels
would be immediately useful. Four of our datasets have physio, which gives a **measured
ground truth to validate against**. Constructive, self-validating, moderate cost.

### N8 — Residual non-rigid motion after slicewise correction

The cord stretches and compresses with breathing and swallowing; the brain does not. Our
motion correction is slicewise rigid. Measure cord centreline **length** over time after
correction: any variance left is uncorrected non-rigid deformation, and it is a
cord-specific failure mode with no brain analogue. This is a plausible mechanism for the
S2 heterogeneity (tSNR gain ranged +0% to +121% across datasets with no consistent
transfer to detectability). Cheap; the centrelines already exist.

### N9 — Quantified winner's curse

We hold the same data as the publications. Compare each paper's published effect size
against our cross-validated estimate on their own data. That yields a **measured
inflation factor for the cord literature**, which no one can produce without this cohort.

High impact, high political cost, and it must be framed as a structural consequence of
small-n plus flexible selection (Button 2013, Ioannidis) rather than as criticism of
individual papers. Handle late, and only if N1 lands, because N1 supplies the mechanism
that makes this fair rather than accusatory.

### Deliberately not pursued

- **Multi-echo / tedana.** No multi-echo data in the cohort. Name it in the Discussion
  as the field's most valuable missing acquisition; do not attempt it.
- **ICA-based denoising (AROMA/FIX for the cord).** Needs labelled components. Cost is
  out of proportion to the remaining schedule.
- **Precision / dense-sampling imaging.** Maximum is two sessions per subject. Not
  enough.
- **Sample-size and scan-duration scaling.** Belongs to P1 by the agreed boundary
  (`/mnt/hdd2/P3_DesignOpt/HANDOFF_FROM_P2_2026-07-25.md`).

---

## 4. Which thesis carries the most weight

Three candidate framings, in ascending order of ceiling.

**A. Focality (current).** *Cord activation is focal relative to every spatial unit the
field analyses it with.* Unifies F2, F3 and smoothing with a measured mechanism
(4.5 mm² horn). Its weakness is that it **excludes F1**, which is our strongest finding,
and it is descriptive: it tells the reader what is wrong with their ROI, not what to do.

**B. The borrowed apparatus fails.** *Cord fMRI inherited its inferential machinery from
the brain, and in a 1 cm pulsing tube that machinery misfires.* A bigger tent: it holds
F1 (SyN), F2 (summary measure), F4 (FD threshold), and N1 (false-positive rate, AR
misspecification, RFT invalidity). With a measured FPR it has teeth that focality lacks,
and the paired-organ contrast supplies the control that makes "because it is the cord"
credible rather than asserted.

**C. B plus cord-shaped replacements.** Every corrective finding paired with a
constructive fix, validated across 9 datasets: cord-shaped smoothing for isotropic
kernels (N2), multivariate detection for parcel-means (N3), permutation for RFT (N1),
fraction-based censoring for imported thresholds (F4), measured fields for image-based
SDC (F1).

**Recommendation: C.** A pipeline paper is cited when people adopt the pipeline, and
people adopt fixes, not warnings. C keeps every existing finding, absorbs F1 properly,
and gives each critique a deliverable. It is also the only framing where the honest
weakness of the current set — that most findings say "stop doing this" — disappears.

---

## 5. Execution order

| | idea | cost | ceiling | risk if it fails |
|---|---|---|---|---|
| 1 | **N1** empirical false-positive rate on 504 rest runs | low | very high | clean useful null |
| 2 | **paired-organ control** retrofitted to F1-F4 | low | high (raises 4 findings) | brain behaves the same, weakening "cord-specific" |
| 3 | **N3** multivariate detection | low | high | MVPA also null, which then strengthens F5 |
| 4 | **N2** cord-shaped smoothing | medium | high | no arm beats isotropic; still the first test |
| 5 | **N4** peak-scatter decomposition | medium | raises F3 | either answer is publishable |
| 6 | **N8** residual non-rigid motion | low | medium | no residual, which validates S4 |
| 7 | **N6** normative distributions | medium | steady | none; companion paper |
| 8 | **N7** physio-free respiration | medium | medium | fails validation against belts |
| 9 | **N5** multiverse | high | very high | conclusions stable |
| 10 | **N9** winner's curse | low compute | high | political |

The first three are all cheap, and each one either raises an existing finding or creates
a new one. Start there.

## 6. Standing cautions

- Every novelty mark above is *(unchecked)*. Each must survive a dedicated literature
  review before it reaches prose, on the F1 standard.
- The audit record in `FLAGSHIP_FINDINGS.md` is the relevant prior: nine self-caught
  errors, and three findings that looked like headlines and were artifacts. Any result
  here that looks like a headline should be assumed confounded until the fair-comparison
  check is done. For N1 specifically, the trap is a null that is not truly null (a
  resting run still contains cardiac and respiratory structure that a task regressor may
  legitimately correlate with, which is the finding, not an error, but the two readings
  must be separated explicitly).
- Do not let N9 lead. It reads as an attack unless N1 has already supplied the mechanism.
