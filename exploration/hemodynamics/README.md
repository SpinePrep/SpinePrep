# Hemodynamics: mapping vascular timing with MRI

Literature and feasibility study, opened 2026-07-28. Triggered by the HRF handoff from
P1_CoSpi (`analysis/HANDOFF_HRF_RECEIVED.md`), which turned on a claim about a ~6 s
dorsal-versus-ventral delay in the cord.

The handoff needs one narrow answer. This folder asks the wider question behind it:
**how is vascular timing measured at all, what data does it take, and what could this
cohort measure?**

```
exploration/hemodynamics/
  README.md          this file
  papers/            10 PDFs on disk
  manifest.json      resolved metadata for 17 papers (PMID, PMCID, DOI, OA status)
  fetch_papers.py    re-runnable resolver/downloader
  notes/             per-paper reading notes
```

Papers without a PDF are non-open-access and are recorded with identifiers so they can
be requested through the library. Nothing was taken from behind a paywall.

---

## 1. The core distinction, because it is the thing most easily got wrong

Two different quantities get called "the hemodynamic response", and the handoff
question depends on telling them apart.

| | **Vascular reactivity / transit** | **Neurovascular coupling (the HRF)** |
|---|---|---|
| driven by | a **systemic** vasodilator (CO₂) reaching the tissue | **local** neural activity |
| timing reflects | arterial arrival time + local vessel responsiveness | local coupling latency + BOLD evolution |
| measured with | breath-hold or gas challenge, resting sLFO, ASL | task fMRI, deconvolution, basis sets |
| the cord number | Hemmerling 2025: dorsal is **6.2 ± 4.9 s** later than ventral | **nobody has measured this in the cord** |

Hemmerling's 6.2 s is the **left** column. Patrick's concern is about the **right**
one. They are related — blood that arrives late makes any BOLD response late — but the
magnitude does not transfer automatically, and Hemmerling say so themselves: their
delay "does not only represent an arterial transit time difference but also represents
variation in the local vasodilatory response as well as variation in the BOLD signal
evolution."

**That gap is the opportunity.** The right-hand column is empty for the spinal cord.

---

## 2. How the brain does it — four method families

### A. Vasoactive challenge with end-tidal CO₂ — the reference standard
Evoke systemic hypercapnia (breath-hold, or a gas delivery system), record **end-tidal
CO₂ (PETCO₂)** simultaneously, then fit PETCO₂ as a regressor and **shift it in time**,
voxel by voxel, keeping the best-fitting shift. Amplitude comes out in interpretable
units (%BOLD per mmHg); the winning shift is the delay map.

**Bright & Murphy 2013** is the paper that made this the standard, and its result is
the single most important design fact here: with **PETCO₂ regressors** the
repeatability of CVR is **ICC = 0.82**, while ramp regressors built from the *instructed*
breath-hold timing fail to reach 0.4. Breath-hold performance is variable, and
recording the gas is what rescues it. *If you do not record end-tidal CO₂, you do not
have a reliable CVR measurement* — you have a measurement of task compliance.

Refinements: voxelwise lag optimisation (Moia 2020, 2021), multi-echo acquisition to
separate BOLD from non-BOLD, and comparison of signal models (Domingos 2025,
Nanayakkara 2026, van Niftrik 2016).

### B. Resting-state systemic low-frequency oscillations — no challenge, no hardware
Spontaneous ~0.1 Hz oscillations in blood oxygenation are **systemic**: they are carried
by the circulation and arrive at different tissue at different times. Extract that
signal (global mean, or a seed) and cross-correlate it against every voxel across a
range of shifts. The lag that maximises correlation is a **blood arrival time** map.

**Frederick 2012 (RIPTiDe)** introduced the shifted-regressor machinery;
**Erdoğan 2016** showed the global signal is "composed primarily of systemic low
frequency oscillations that propagate with cerebral blood circulation" and that
correcting for arrival time changes connectivity results. Tachibana 2022 separates the
systemic component from neuronal signal.

**Requires nothing but resting BOLD.** Long duration and short TR help. This is the
family that scales to any dataset.

### C. Respiratory-belt regressors — the middle ground
Respiration volume per time, or respiratory variation, derived from a belt alone,
convolved with a response function and lagged. Cheaper than a gas analyser, less
reliable than PETCO₂, but requires only equipment most cord studies already run.

### D. Estimating the HRF itself
Deconvolution or flexible basis sets recover response **shape and latency** per voxel
from task or resting data. **Rangaprakash 2018 / 2023** are the key references, and
their point is directly relevant here: HRF variability is not a nuisance but a
**confound** — it biases connectivity and any timing-sensitive result. Their 2023 rat
work compares HRFs from resting-state fMRI against invasive electrophysiology.

*(A fifth family — ASL, IVIM, DSC perfusion — measures blood flow directly rather than
timing. See §3.)*

---

## 3. What exists in the spinal cord — a very short list

| paper | what it did | limitation |
|---|---|---|
| **Hemmerling 2025**, *Sci Rep* 15:34880 | The only cord CVR study. Breath-hold + PETCO₂, lagged GLM, ±10 s in 2 s steps, TR 2000 ms, C5–C8. N=27 group; 2 subjects × 18 runs | Delay **6.2 ± 4.9 s** — SD is most of the mean. Group correction assumes identical timing across subjects. **Delay correction did not rescue the dorsal cord**: "there are still dorsal regions without a significant response" |
| **Duhamel 2008**, *MRM* | Cord blood flow by arterial spin labelling | Technically hard; little uptake since |
| **Lévy 2020**, *MRM* | Cord perfusion by IVIM at 7 T | "Single-subject data SNR at 7T was insufficient for reliable perfusion estimation" — group averaging only |
| **Hemmerling 2026**, *Imaging Neurosci* | Data-driven PCA denoising for cord fMRI | Denoising, not timing — but the same lab, and what our A1 result speaks to |
| **Horn 2025** (preprint) | 7 T layer-specific cord responses; phasic vs sustained in **different laminae** | Not a delay paper. But two response components with different timing make a single global "delay" the wrong model |

**The mechanism Hemmerling propose** is vascular territory: the **anterior spinal
artery** supplies roughly two thirds of the cord including the ventral horns
(early response); the paired **posterior spinal arteries** supply the dorsal horns
(late). Thresholding the delay map separates the two territories. For scale, they note
that arterial transit-time differences **across the brain are only 1–2 s** — so ~6 s
within a structure 1 cm across is striking, and worth independent confirmation.

**Everything else in this literature is brain.** Families B, C and D have **no spinal
cord application at all.**

---

## 4. What this cohort could do

### The asset that changes things

**ds004616 records CO₂ and O₂ at 100 Hz on every run.** Verified on the traces: real
breath-by-breath capnography, 1–51 mmHg, with a PETCO₂ standard deviation of 4–5 mmHg
across a run — a genuine dynamic range, not a flat line. And its **TR is 2.00 s, the
same as Hemmerling's**, with 296 volumes (~10 min) per run.

That is not an approximation of their method. It is the same measurement.

| dataset | runs | TR | dur | physio | rest/task | brain+cord |
|---|---|---|---|---|---|---|
| **ds004616** | 42 | **2.00** | 592 s | **CO₂, O₂**, resp, cardiac, grip @100 Hz | task | no |
| ds004386 | 96 | 2.31 | 569 s | none | **REST** | no |
| ds005075 | 30 | **1.55** | 405 s | cardiac, resp | **REST** | **yes** |
| ds004926 | 80 | 1.80 | 317 s | cardiac, resp | task | no |
| ds005883 | 37 | 2.68 | 616 s | PULS | task | **yes** |
| ds005884 | 40 | 2.68 | 308 s | PULS | task | **yes** |
| balgrist_painmotor | 37 | 3.26 | 636 s | cardiac, resp, gripper | task | no |
| balgrist_cospigvs | 42 | 1.66 | 596 s | cardiac | task | no |
| balgrist_motor | 46 | 2.60 | 590 s | none | task | no |

### Four things worth doing, ranked

**1. Cord SCVR from PETCO₂ on ds004616 — an independent replication of the only cord
CVR paper, with an intervention on top.**
Family A, the reference standard, with the exact signal it requires. 42 runs, 26
subjects, two sessions at matched TR. Hemmerling's group N was 27, and theirs is the
only cord CVR dataset in existence — so this would be the **first independent test of
the 6.2 s dorsal-ventral delay**, which matters because Hemmerling 2025 and 2026 come
from the same lab.

The extra: **ds004616 ses-02 follows a 30-minute acute intermittent hypoxia protocol.**
`glm_spec` already flags that the two sessions are not repeat measurements. For a
reliability analysis that is a nuisance; for a vascular analysis it is a **within-subject
vascular intervention**, and measuring SCVR before and after one has not been done in
the cord.

**2. Resting-state lag mapping on 126 rest runs — family B, which needs no physio at
all.**
No cord application exists. ds004386 gives 96 runs across 48 subjects with two sessions
(test–retest of a lag map), and ds005075 gives the shortest TR at 1.55 s. If sLFO lag
mapping works in the cord, it makes vascular timing measurable in **any** cord dataset,
retrospectively — which is a much larger contribution than one more CVR study.

**3. Brain-versus-cord lag in the same volume — the paired-organ asset again.**
Hemmerling contrast their ~6 s cord delay against 1–2 s across the brain, but those are
different studies, different subjects, different scanners. Three of our datasets acquire
both organs in **one EPI volume**. The same comparison becomes within-run, which is the
design that made our inference and dilution results unarguable. ds005075 is resting
(family B) and ds005883/4 are task.

**4. The handoff question — model-free response timing, ventral versus dorsal, across
all 9 datasets.**
Family D, and the thing P1 actually asked for by 11 August. Epoch-average and measure
time-to-peak; do **not** fit an HRF to measure a delay, which is circular. Our TRs span
1.55–3.26 s, so a 6 s delay is 2–4 samples — coarse, but better than CoSpi's 3.2 s
alone, and ds004926 is conveniently both our weakest dataset and one of our
best-sampled at 1.8 s.

### What we cannot do

- **No perfusion imaging.** No ASL, no IVIM, no contrast. Blood flow in absolute units
  is out of reach; only timing and relative reactivity are available.
- **No gas delivery.** ds004616 has capnography during a *motor* task, not a controlled
  hypercapnic challenge. PETCO₂ will vary with natural breathing and task-related
  breathing changes, which gives a smaller and less structured dynamic range than a
  breath-hold. This is the main threat to opportunity 1 and must be checked before
  claiming a CVR map.
- **No multi-echo**, so BOLD and non-BOLD contributions cannot be separated the way
  Moia 2021 does.
- **Not at Hemmerling's resolution.** They used 1 mm² in-plane; our cohort is coarser,
  and separating a ~2–3 mm horn matters for a ventral-versus-dorsal contrast.

---

## 5. The honest risk

Every one of these opportunities rests on a delay of a few seconds being measurable at a
TR of 1.5–3.3 s. Hemmerling's own estimate is 6.2 ± 4.9 s on a grid searched in 2 s
steps — the uncertainty is most of the effect. Anything we produce inherits that, and
the resolution limit must be stated **before** any number is quoted, not after.

The second risk is circularity, and it is the one the handoff already warns about:
a delay estimated by fitting a model that assumes a delay is not evidence. Model-free
first, always.

---

## 6. Immediate next step

Check whether ds004616's PETCO₂ has enough task-independent variance to support a CVR
fit at all. That is one script over 42 runs and it decides whether opportunity 1 is real
or a dead end — before any modelling is built on top of it.
