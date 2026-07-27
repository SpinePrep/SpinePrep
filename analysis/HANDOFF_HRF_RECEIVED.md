# Received: HRF handoff from P1_CoSpi — the paper, read

**Handoff:** `/mnt/hdd2/P1_CoSpi/analysis/HANDOFF_hrf_spineprep.md`, written 2026-07-27.
**Raised by:** Patrick and Gergely, group meeting 2026-07-27.
**Answer needed by 2026-08-11** — after that CoSpi defaults to the canonical HRF.
**Picked up here:** 2026-07-28. Paper located and read; no analysis run yet.

---

## 1. The question CoSpi is asking

Is there a systematic BOLD onset delay in the **dorsal horn** relative to the
**ventral horn**, large enough that the canonical HRF mis-models cord data? If yes,
every cord number in the CoSpi paper needs re-fitting. If no, they cite it as a
limitation and ship.

They want one of two answers back: *keep the canonical HRF*, or *re-fit with a shift of
X s*.

## 2. The paper Patrick was referring to

**Hemmerling KJ, Hoggarth MA, Sandhu MS, Parrish TB, Bright MG.
"MRI mapping of hemodynamics in the human spinal cord."
*Scientific Reports* 2025;15:34880. doi:10.1038/s41598-025-17048-4**

PDF already in the P1 library: `papers/literature/pdf/hemmerling_2025_scvr_hemodynamics.pdf`.
It was never written up in the P1 literature notes, which is why the handoff records
the question without a citation.

**Not** Horn et al. 2025. Horn's phasic/sustained laminar dissociation is a different
result and its only mention of delay is about draining veins (Kay 2020). Checked
directly in the PDF.

### What they did
3 T, ZOOMit gradient-echo EPI, **TR 2000 ms**, 1 mm² in-plane, 3 mm slices, C5–C8.
N = 27 for the group map; 2 highly-sampled participants with 18 runs each. A
**hypercapnic breath-hold** evokes systemic vasodilation; SCVR is modelled with a
subject-specific PETCO₂ regressor, and delay is mapped by **shifting that regressor
±10 s in 2 s increments** and taking the best-fitting shift per voxel.

### The number
| | dorsal-minus-ventral delay |
|---|---|
| group (N=27) | **6.2 ± 4.9 s** — "about 3 times our sampling TR" |
| subject 1 (18 runs) | 6.3 ± 5.2 s |
| subject 2 (18 runs) | 7.6 ± 8.0 s |

So Patrick's remembered "~4–6 s" is real and if anything an under-statement: the
published figure is **6.2 s**. Ventral responds **earlier**, dorsal **later**, and the
early/late boundary reproduces the shape of the grey-matter horns.

### Their mechanism
Vascular supply territory, not neural. The **anterior spinal artery** supplies roughly
two thirds of the cord including the ventral horns and intermediate zone — earlier
response. The paired **posterior spinal arteries** supply the dorsal horns — later
response. Thresholding the delay map cleanly separates the two territories, which is
their headline contribution.

They note that brain arterial transit-time differences are only **1–2 s**, so ~6 s in
the cord is large by comparison.

---

## 3. Assessment — what this does and does not license

### It is not the same quantity as a task HRF delay
This measures the response to a **systemic** vasodilatory challenge. Its timing is
dominated by when a CO₂ bolus arrives in each vascular territory. A task HRF delay is
neurovascular coupling latency to **local** neural activity. The authors say so
themselves: the delay "does not only represent an arterial transit time difference but
also represents variation in the local vasodilatory response as well as variation in
the BOLD signal evolution."

So this paper does **not** establish that the dorsal-horn task response is 6 s late. It
makes it plausible and supplies a mechanism that would apply to any BOLD response in
that tissue — which is a reason to test, not a reason to re-fit.

### The uncertainty is as large as the effect
6.2 ± **4.9** s, estimated on a grid searched in **2 s steps at TR 2 s**. The
individual SDs are 5.2 and 8.0 s. The point estimate is about 3 TRs with a standard
deviation of about 2.5 TRs. Any shift we recommend inherits that.

### Delay correction did not rescue the dorsal cord
Their own result: after shifting, the amplitude map is more diffuse but "there are
still dorsal regions without a significant response." **If a 6 s shift does not recover
the dorsal SCVR response, a 6 s shift may not recover dorsal task responses either.**
That is the single most important caveat for CoSpi's decision, and it argues against
expecting a re-fit to change conclusions.

### Group-level delay correction is explicitly sub-optimal
They flag that the group approach "assumes that the timing of the voxelwise SCVR
response is the same across all subjects", and that group-level correction is
sub-optimal given between-subject variability — evidenced by higher SCVR in the two
highly-sampled individuals.

### Provenance worth knowing
Same lab (Bright, Northwestern) as **Hemmerling 2026 SpinalCompCor**, which our A1
result positions against. One coherent body of work, not independent replication.

---

## 4. Why this matters to SpinePrep's own results

**A suggestive pattern, stated with its counter-example.** Our four task datasets split
by which horn is the a-priori ROI:

| dataset | a-priori horn | unbiased CV group d |
|---|---|---|
| ds004616 | ventral | **+0.90** |
| ds005884 | ventral | +0.41 |
| ds005883 | **dorsal** | +0.44 |
| ds004926 | **dorsal** | **+0.11** — inside our null floor of 0.31 |

The strongest dataset is ventral and the weakest is dorsal, which fits. But
ds005884 (ventral, 0.41) and ds005883 (dorsal, 0.44) are indistinguishable, so **this
is a two-of-four pattern, not a clean dorsal/ventral split.** It is a hypothesis worth
testing, not evidence.

**Our multiverse has no HRF-timing axis.** R10 varied summary measure, censoring,
smoothing and confound set. If HRF timing moves the answer it belongs in that space,
and F2's spread is already labelled a lower bound. This would be the second axis added
(after distortion).

**Our sampling is better than CoSpi's for this question.** CoSpi is TR 3.2 s, where 6 s
is under 2 TRs. Our cohort spans **TR 1.55–3.26 s**, so a 6 s delay is 2–4 TRs — still
coarse, but the shorter-TR datasets (ds005075 at 1.55 s, ds004926 at 1.8 s) can resolve
it far better. ds004926 being both the weakest dataset *and* one of the best sampled is
convenient.

---

## 5. What to run, in the handoff's order

1. **Model-free first.** Epoch-average preprocessed timeseries in ventral- and
   dorsal-horn ROIs by condition; measure time-to-peak in each. Do **not** fit an HRF
   to answer this — a fitted delay from a mis-specified model is circular.
2. **Across all 9 datasets**, to separate a general property of cord fMRI from a CoSpi
   artefact. This is the part that only exists here.
3. **Consequence test.** Canonical HRF vs shifted-by-measured-delay vs HRF + temporal
   derivative. The question is *does the conclusion change*, not *does the fit improve*.

Two additions of my own:

4. **Check for a phasic component before fitting one shift.** Horn 2025 found a 3 s
   onset transient and a 30 s sustained response in *different laminae*. Two
   superimposed components with different timing make a single global "delay" the wrong
   model, and would show up as a biphasic epoch average.
5. **Test whether a temporal derivative alone absorbs it** — the handoff flags this as
   useful and non-blocking, and it is much cheaper than re-fitting with a shifted basis.

## 6. Caveats to carry, from the handoff and from the paper

- CoSpi voxels are 1×1×5 mm at TR 3.2 s. State the resolution limit before quoting any
  delay.
- CoSpi's pain cluster is surface-weighted with 0% grey matter, so its "dorsal-horn
  timeseries" is partly white matter and vessel. The ventral horn is the
  better-conditioned ROI; do not treat the dorsal trace as ground truth.
- Hemmerling's delay is a **vascular** measurement. Any transfer to task HRF is an
  inference and must be labelled one.
- The published delay's SD exceeds half its mean.

## 7. Not our work, but someone must do it

Patrick asked **Dario** to check the same ventral/dorsal latency pattern in his Stanford
7 T and 3 T cord data. The handoff notes this will not happen by itself. Flagging it
here so it is not lost — it is the only route to independent replication, since
Hemmerling 2025 and Hemmerling 2026 come from the same lab.
