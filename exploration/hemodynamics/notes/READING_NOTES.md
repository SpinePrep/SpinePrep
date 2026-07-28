# Reading notes — key numbers, so they need not be re-extracted

## Hemmerling KJ et al. 2025, *Sci Rep* 15:34880 — "MRI mapping of hemodynamics in the human spinal cord"
PDF: `papers/hemmerling_2025_scvr_hemodynamics.pdf` · PMC12504414 · doi:10.1038/s41598-025-17048-4

- 3 T, ZOOMit gradient-echo EPI, **TR/TE 2000/30 ms**, 1 mm² in-plane, 3 mm slices, 25 slices, C5–C8.
- Group: **N = 27**, 2 breath-hold runs across 2 sessions. Individual: **2 subjects × 18 runs** over 3 sessions.
- Analysis: PETCO₂ regressor in a first-level GLM → SCVR in **%BOLD/mmHg**. Delay by shifting
  the regressor **±10 s in 2 s increments** and keeping the best fit per voxel.
- **Delay, dorsal minus ventral: 6.2 ± 4.9 s** (group, "about 3 times our sampling TR");
  **6.3 ± 5.2 s** and **7.6 ± 8.0 s** for the two highly-sampled subjects.
- Amplitude before delay correction is **ventral-dominant**; after correction it is more diffuse
  but **"there are still dorsal regions without a significant response"** ← the caveat that matters most.
- Delay-corrected SCVR: 0.04 ± 0.02 %BOLD/mmHg cord, 0.05 ± 0.02 ventral grey matter.
- Mechanism: **anterior spinal artery** supplies ~2/3 of the cord incl. ventral horns (early);
  paired **posterior spinal arteries** supply dorsal horns (late). Thresholding the delay map
  separates the two territories.
- Their own scale check: **arterial transit-time differences across the brain are only 1–2 s.**
- Stated limits: group delay correction "assumes that the timing of the voxelwise SCVR response is
  the same across all subjects"; the breath-hold response is transient; group-level correction is
  sub-optimal versus individual.
- **They explicitly say the delay is not purely transit time**: it "does not only represent an
  arterial transit time difference but also represents variation in the local vasodilatory response
  as well as variation in the BOLD signal evolution."

## Bright MG & Murphy K 2013, *NeuroImage* 83:559–568
PDF: `papers/bright_murphy_2013_petco2_reliable_cvr.pdf`

The design paper. 12 volunteers, 3 T, six functional scans, each six breath-holds of 10/15/20 s
interleaved with paced breathing, deliberately simulating variable patient compliance.
Compared three regressor types: uniform ramps, time-scaled ramps, **end-tidal CO₂**.

- **PETCO₂ regressors: ICC = 0.82** ("excellent") in average grey matter, and > 0.4 in every
  smaller region tested.
- **Ramp regressors: ICC < 0.4** in several regions — they do not absorb variable breath-hold
  performance.
- Conclusion: recording end-tidal CO₂ is what makes breath-hold CVR viable clinically.

**The operational rule for us: without end-tidal CO₂ you are measuring task compliance, not CVR.**

## Erdoğan SB et al. 2016, *Front Hum Neurosci* — blood arrival time
PDF: `papers/erdogan_2016_blood_arrival_time.pdf`

"The global signal from resting state fMRI is composed primarily of systemic low frequency
oscillations (sLFOs) that propagate with cerebral blood circulation." Correcting for arrival time
before global-mean regression changes connectivity results. Establishes that a **lag map is
obtainable from resting BOLD alone** — no challenge, no physio.

## Frederick B et al. 2012, *NeuroImage* — RIPTiDe
Metadata only (PMC3593078, not in the OA subset).
Introduces Regressor Interpolation at Progressive Time Delays: the shifted-regressor machinery
that families A and B both use.

## Rangaprakash D et al. 2018 *MRM* / 2023 *Front Neurosci*
PDF (2023): `papers/rangaprakash_2023_hrf_confound_review.pdf`
HRF variability is a **confound**, not a nuisance: it biases resting-state connectivity. The 2023
rat study (`papers/rangaprakash_2023_hrf_rat_cord_electrophysiology.pdf`) compares HRFs estimated
from resting-state fMRI against invasive electrophysiology. Directly relevant to whether a
data-estimated cord HRF can be trusted.

## Lévy S et al. 2020, *MRM* 84:1198–1217 — cord IVIM at 7 T
Metadata only. Grey matter shows higher microvascular fraction than white matter, but
**"single-subject data SNR at 7T was insufficient for reliable perfusion estimation"** — required
b=0 SNR of 159 for 10% error. Group averaging only. The realistic ceiling on cord perfusion imaging.

## Duhamel G et al. 2008, *MRM* — cord blood flow by ASL
Metadata only (PMID 18383283). The feasibility paper for cord ASL; little uptake since.

## Horn U et al. 2025 (preprint) — 7 T layer-specific cord responses
PDF: `papers/horn_2025_7T_layer_specific_dorsalhorn.pdf`. Full note in
`/mnt/hdd2/P1_CoSpi/papers/literature/NOTES_horn2025_layers.md`.
Not a delay paper — its only "delay" mention is about draining veins (Kay 2020). **But** it puts a
3 s onset transient and a 30 s sustained response in *different laminae*, which means a single
global delay is the wrong model if both components are present. Check for a phasic component
before fitting one shift.
