---
status: approved
---

# S3 algorithm audit — literature-backed, truthful, correct

Rewritten 2026-07-15. Supersedes the previous version, which predated the EPISeg
switch, cited outlier gates that no longer exist (0.30/0.50), and repeated two
citation errors. Every claim below was verified against code, the installed
SCT/FSL, or primary literature; derivations are labelled as such.

## Sub-step summary

| Stage | Operation | Engine |
|---|---|---|
| **S3.1** | Drop 4 initial volumes, build a coarse median reference, segment the cord with EPISeg, clean the mask, brain-contamination check | `sct_deepseg sc_epi` |
| **S3.2** | Cord-mask DVARS + DVARS-ref per frame, box-plot outlier fence, robust median reference over non-outlier frames | NumPy + nibabel |
| **S3.3** | Bounding-box crop around the cord centreline | `sct_crop_image` |

## Verdicts

| Choice | Value | Verdict |
|---|---|---|
| Dummy drop | 4 volumes, fixed | KEEP-with-caveat (F1) |
| Coarse + robust reference | median, two-stage | KEEP — matches fMRIPrep `RobustAverage` (`np.median`) |
| Cord localization | `sct_deepseg sc_epi` (EPISeg; Banerjee et al. 2025) | KEEP — correct default for BOLD EPI |
| Mask cleanup | bespoke Z-bridge + off-axis drop | KEEP-with-caveat (F6) |
| Brain-contamination check | area spike 4x, cap 200 mm² | KEEP-with-caveat (F5) |
| DVARS / DVARS-ref | cord-restricted, Power 2014 | KEEP — the mask is SpinePrep's choice, not Kaptan's |
| Outlier fence | Q3 + 1.5·IQR | KEEP — FSL `fsl_motion_outliers` default; a real deviation from the cord papers |
| Crop | 60 mm bounding box | KEEP — rationale was falsified (F4) |
| No slice-timing correction | — | KEEP-with-caveat (F7) |

## Findings

### F1 — Dummy drop: physics fine, provenance not
4 volumes is ample at every cohort TR (1.55–3.26 s): worst-case residual is ~0.5%
in CSF and ~0% in tissue, because the approach to steady state is dominated by
`cos(flip)` (70–87° here). Verified empirically: no saturation transient is
visible at any TR, so the saved data already starts at steady state. Three gaps:
- The old citation ("Eippert 2017 / Kaptan 2023 default") was wrong. Eippert ran
  **3 dummies before acquisition** (never written to file); Kaptan states no
  policy. Corrected: 4 is a SpinePrep margin, not a published default.
- **83 runs (ds005883/ds005884) declare `NumberOfVolumesDiscardedByScanner: 6`**
  and SpinePrep ignores it, dropping 4 more. `src/` never reads the field.
- The drop is not propagated (F2).

### F2 — The drop is not propagated to events or metadata — PARTLY OPEN
S3 removes 4 volumes but no derivative sidecar records `StartTime` or
`NumberOfVolumesDiscardedByUser`, and nothing shifts `events.tsv` onsets. BIDS is
explicit that onsets refer to the first volume of the imaging file, so a GLM built
from SpinePrep output plus the raw events file is misaligned by 4 TR with nothing
in the metadata to reveal it. **The physio arm is FIXED**: S8 now skips
`n_dummy_dropped` TRs when cropping, reading the count from S3's qc.json
(`metrics.n_dummy_dropped`). The events/metadata arm remains open and is the
highest-value remaining item.

### F3 — DVARS computed pre-motion-correction, shipped as GLM confounds — OPEN
S3 computes DVARS/refRMS on uncorrected data, which is correct for its own purpose
(choosing good frames for the reference, as fMRIPrep does). But **S8 re-reads
S3's `frame_metrics.tsv`** and ships those values as confound columns and scrub
regressors. Power 2014, Kaptan 2023 and fMRIPrep all compute DVARS *after*
realignment — the metric exists to catch what motion correction failed to fix. FD
in the same file *is* post-hoc (from S4), so the `outliers` column ORs metrics
from both sides of the motion-correction boundary. The fix is scoped to S8:
recompute on the S5 output; S3's own values stay S3's.

### F4 — Crop: rationale falsified, arithmetic wrong — FIXED (docs)
The policy justified 60 mm as "more landmarks for S6". S6 registers with
`type: seg` on all three steps and is intensity-agnostic, so nothing consumes the
context. "~70% more voxels" mistook the linear ratio (60/35 = 1.71) for the area
ratio ((60/35)² = 2.94, i.e. **+194%**). Also corrected: `sct_crop_image -m`
extracts a bounding **box**, and the comparable field values (SCT
`batch_processing.sh`, CoSpine 2025) are 35 mm **moco masks**, not crops — SCT
never crops the 4D, and the crop is lossless (index box, no interpolation). The
number is kept; the reasoning is now honest.
Related and **open**: S4 passes the **cord segmentation** (~3% of voxels) to
`sct_fmri_moco -m`, where SCT/CoSpine/Kaptan pass a 35–41 mm cylinder that
deliberately includes the cord/CSF boundary the registration metric keys on.
Needs an A/B on cord tSNR.

### F5 — Brain-contamination check: right idea, wrong number — FIXED (docs)
No published guard exists for a cord segmentation leaking into the brain, and a
broad search found no issue or paper documenting the failure, so this is a genuine
SpinePrep contribution. Its stated basis was wrong: **~500 mm² is the pons**, not
the medulla. Cord is ~60–90 mm² (Piaggio 2018: 88.9 ± 6.0 at the foramen magnum),
the lower medulla ~130–175 mm² (derived from published volumes; no axial medulla
CSA appears to be published) — only ~1.4x over the first centimetre. So the
200 mm² cap sits above the lower medulla and is a gross-contamination backstop,
not an early-leak detector; the relative 4x spike test does the real work. A
gradient test (cord tapers ~1.2 mm²/mm, measured on PAM50_cord, vs ~8.6 mm²/mm
into the medulla) or a PMJ-referenced extent cap (`sct_detect_pmj`) would be
sensitive and citable. **Threshold change still open.**

### F6 — Mask cleanup: now well-grounded, but unbenchmarked — OPEN
EPISeg emits off-axis brain specks on brain+cord FOVs and can split the cord
across the anterior-curve gap. This is a **documented SCT-side gap**, not a
mystery: `sct_deepseg.py:449` applies `keep_largest=1` only for the `spinalcord`
task and explicitly not for `sc_epi`, commenting that the model "sometimes
predicts pixels outside the cord". SCT applies the same reasoning to
`sc_canal_t2`. So post-hoc component filtering is SCT's own answer, and a naive
largest-component keep is what would be wrong here (it re-truncates the fragmented
cord). Unresolved: the bespoke Z-bridge is gap-sensitive (re-truncates at gaps
≥3 slices) and has never been benchmarked against `sct_get_centerline -method
fitseg` (documented to interpolate missing slices) or size-based small-object
removal. Manual masking is the field norm (Hoggarth 2022: "no reliable algorithms
for segmenting the spinal cord in functional data"), so there is no published
standard being deviated from.

### F7 — No slice-timing correction: defensible, one gap — OPEN
Eippert 2017, Kaptan 2023 and SCT all omit STC. But **CoSpine (Wei 2025) applies
it** (FSL `slicetimer`, TR 2.68 s, 70 slices, task-based) precisely because the
enlarged brain+cord FOV lengthens TR — and ds005883/ds005884 (CoSpine pain/motor)
are in this cohort. The no-STC spec's own carve-out for simultaneous brain+cord
acquisition therefore applies to our own data and should say so.

### F8 — Citations — FIXED
- **"Smyser 2019" does not exist.** It was rendered in the tutorial's public
  reference list and credited as the "cord adaptation" for mask-restricted DVARS.
  The real Smyser DVARS work is infant *brain* fMRI (Cereb Cortex 2010). Removed;
  Power 2014 alone licenses the claim (it defines DVARS within a spatial mask).
- **The cord-restricted mask is SpinePrep's, not Kaptan's.** Kaptan uses a 41 mm
  cord-*centred* cylinder containing CSF, muscle and vertebrae.
- **The box-plot fence is FSL's default, not "the fMRIPrep convention"** —
  fMRIPrep thresholds standardised DVARS > 1.5 and FD > 0.5 mm, with no IQR rule.
  Fixed in the public S8 page, the policy, and the S8 spec.
- **Kaptan 2023 uses 2 SD; Dabbagh 2024 uses 3 SD** (previously conflated), and
  the "2% [0.6–5.6%]" figure is Dabbagh's, not Kaptan's. Dabbagh is *Imaging
  Neuroscience*.
- **EPISeg is Banerjee et al. 2025**, not Valošek (verified against SCT's model
  card, `deepseg/models.py`).

### F9 — Dead config — FIXED
- `dilate_xyz` was read in `crop.py` but never passed to any SCT command; the
  documented "2-voxel in-plane safety margin" never happened. Knob removed rather
  than switched on, since enabling it would change the geometry of an
  already-validated cohort.
- `outlier_fraction_warn_max: 0.40` was never read by any code, and its comment
  claimed a FAIL tier that does not exist. Removed; the gate is a soft WARN above
  `pass_max` only.
- The gate is uncalibrated: 0.20 is a round number, not derived from the cohort,
  and neither Kaptan nor Dabbagh proposes a run-level gate. Their thresholds do
  not transfer, because SpinePrep's metric differs (tighter mask, MP-PCA-denoised
  input).

### F10 — refRMS is not the literature's refRMS — FIXED (code)
FSL computes RMS-to-reference and then **differences it** ("to remove slow
trends"), so Kaptan's and Dabbagh's refRMS is differenced. SpinePrep thresholded
the **raw** RMS-to-reference, which therefore carried scanner drift. Now
differenced to match (`outlier.py`, verified against the FSL source).

**Measured, and it corrected a prediction.** The fix did *not* reduce the
censoring rate: cohort median went 5.28% → 5.68%. This was expected to fall and
did not, for a reason worth recording: the Tukey fence is **distribution-relative**
(P75+1.5·IQR on the run's own values), so it re-centres on whatever spread the
metric has. Differencing changed *which* frames are censored (real motion rather
than slow drift — the correctness win) but not *how many*. Any argument for this
fix must be made on correctness, not on flagging fewer frames.

### F11 — censoring rate is ~3x the cord papers' — KEEP (verified; my criticism was wrong)
Measured over 261 completed cohort runs (58,735 frames):

| rule | frames flagged |
|---|---|
| DVARS alone | 3.44% |
| refRMS alone | 4.96% |
| **union, `dvars \| ref_rms` (shipped)** | **6.32%** |
| both metrics agree | 2.09% |

Reported cohort `outlier_fraction`: median 5.68%, p90 10.16%, max 19.11%, vs
Kaptan 2023 "<2%" and Dabbagh 2024 "2% [0.6–5.6%]".

**The OR-union is NOT a SpinePrep invention — this audit's first draft was wrong.**
Verified against primary sources:
- Kaptan 2023: "Volumes presenting with dVARS **or** refRMS values two standard
  deviations above the mean values of each run were selected as outliers."
- Dabbagh 2024: same OR, 3 SD.
- fMRIPrep ORs FD with standardised DVARS —
  `mask = reduce(operator.or_, mask.values())` in
  `niworkflows/interfaces/confounds.py`, defaults `--fd-spike-threshold 0.5`,
  `--dvars-spike-threshold 1.5`.

`policy/S3_func_init_and_crop.yaml` already credited the OR to Kaptan and already
gave the correct rationale; the draft finding contradicted our own policy.

**The real difference is the threshold rule, and it explains the rate.** They use
mean + k·SD; we use the box-plot fence. SD is **not robust**: the spikes censoring
exists to catch inflate the SD and so raise the threshold, which is why 2 SD flags
~2% on heavy-tailed cord data. The IQR is robust, so the fence stays tight and
flags more. Our higher rate is largely SD-inflation in the comparator, not
over-aggression in ours — and this is exactly the reason the policy already gives
("robust to the non-Gaussian heavy-tailed cord DVARS distribution"). **Keep.**

Honest caveats to carry into the paper:
- Both cord numbers come from the **same group** (Eippert lab). "The field censors
  ~2%" is really "one lab reports ~2% under its own SD rule." Do not state it as a
  field-wide norm.
- Our metrics + OR follow Kaptan/Dabbagh; our fence follows FSL's default. That
  hybrid is defensible but should be stated plainly, not implied to be one source.
- FSL's box-plot fence is the **fallback when `--thresh` is omitted**, not "the
  `--thresh` default"; `--thresh` replaces it with an absolute value. FSL's default
  *metric* is refRMS, and it takes ONE metric per call, so the OR comes from the
  papers, not from FSL.
- The 6.32% union does cost degrees of freedom at GLM time (S8 consumes
  `frame_metrics.tsv`). That is a real trade, made deliberately.

**Rejected argument (do not revive):** "a per-run relative fence flags a similar
fraction on clean and noisy runs, so it isn't really outlier detection." It is
scale-invariant, not shape-invariant — under *spiky* degradation (the case that
matters) the fence still catches the spikes; it only holds under *uniform*
degradation. It is also not a published criticism: Power 2014 does not make it,
and Jones 2022 (Aperture Neuro, DOI 10.52294/ApertureNeuro.2022.2.NXOR2026) argues
the other way ("any absolute threshold would necessarily be metric specific").
Kaptan's 2 SD is per-run relative too, so the argument would hit the comparator
equally. The one defensible version — per-run relative discards between-run
differences, where Jones computes the fence "across the entire dataset" — is our
argument to make and defend, not a citation.

### F12 — the run-level gate is inert — OPEN
`outlier_fraction_pass_max: 0.20` fires on 0 of 261 runs (max 19.11%). It is a
round number, not derived from the cohort, and neither cited paper proposes a
run-level gate. It is currently a catastrophe backstop that has never fired.
Either calibrate it to the cohort distribution or state plainly that it is a
backstop, not a QC criterion.

## Open items, by priority

1. **F3** — recompute DVARS/refRMS in S8 on the S5 output.
   (F11 is CLOSED: the OR is Kaptan's, the fence is FSL's, the rate gap is
   SD-inflation in the comparator. Keep as shipped.)
3. **F5** — replace the area cap with a gradient or PMJ-referenced test.
   (Gradient test added; the cap remains as a gross backstop.)
4. **F6** — benchmark the Z-bridge against `fitseg` / small-object removal.
5. **F4** — A/B the moco mask (cord-seg vs 35 mm cylinder) on cord tSNR.
6. **F7** — name CoSpine in the no-STC spec.
7. **F12** — calibrate or re-scope `outlier_fraction_pass_max`.
8. **F13** — S3 is not dataset-keyed, unlike S2. `session.py` builds
   `run_id = <bold filename>` and `work_dir = runs/S3_func_init_and_crop/<run_id>`,
   and figures land flat at `derivatives/spineprep/sub-XX/figures/`. It accepts
   `dataset_key` but uses it only to LOOK UP S2's output. Two datasets sharing
   `(sub, ses, task, acq, run)` would therefore share a work dir and overwrite
   each other's figures. S2 already fixed this (keyed work dir + 
   `derivatives/spineprep/<dataset_key>/sub-XX/`); S3 did not inherit it.
   **Measured on this cohort: 466 runs -> 466 unique run_ids, 0 collisions** — the
   task/acq labels happen to differ, so nothing is currently corrupted. Latent,
   not active: a dataset with a plain `sub-01_task-rest_bold` would clobber.
   Fix before adding datasets, not after.
9. `docs/methods/S3_func_init_and_crop.md` is still stale.

### Fixed since the audit
- **F1** — `NumberOfVolumesDiscardedByScanner` now read (83 runs declare 6).
  The first fix was incomplete: the applied count never left S3.1, so qc.json
  reported the policy default and S8 would have re-applied the 4-TR physio
  misalignment F1 existed to remove. Now carried through localize → session →
  outlier, including both skip paths.
- **F2** — `StartTime` + `NumberOfVolumesDiscardedByUser` on the derivative sidecar.
- **F10** — refRMS differenced (see above).
- Cached S3.2 no longer hardcodes `PASS`; the gate is re-applied from the cached
  fraction, so a verdict cannot depend on whether the work was redone.
- The multi-dataset batch path ignored `batch_workers` while printing "with N
  workers"; it now parallelises, collecting by session index so `runs.jsonl`
  stays byte-identical regardless of worker count.
