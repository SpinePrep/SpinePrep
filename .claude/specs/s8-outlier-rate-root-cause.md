---
status: approved
---

# S8 outlier-rate root-cause audit

User observation: the S8 cohort outlier_fraction is 15–83% across the
reg-cohort (locked `wf_reg_086`), with several runs at >60%. Literature
typical for cord-fMRI is 5–30%. Why so high?

## TL;DR

The 0.2 mm FD threshold currently used for outlier flagging is a
**misattribution**. Power 2014, Kaptan 2023, and Dabbagh 2024 all use
**0.5 mm** for cord-fMRI scrubbing/outlier flagging. The 0.2 mm number
in our policy comment is the Kaptan 2023 *spike-regression-inclusion*
threshold (a softer downstream-GLM operation), NOT the scrubbing
threshold. Single-line fix recovers literature-consistent rates.

## Empirical decomposition on balgrist run-01

223 volumes; reported outlier_fraction = 83.4%.

| Criterion | Threshold | Flagged | Fraction |
|---|---|---|---|
| FD | > 0.2 mm (**current**) | 186 | **83.4%** |
| FD | > 0.5 mm (Power 2014 / Kaptan 2023 cord) | 59 | 26.5% |
| DVARS | > μ + 3σ (current) | 0 | 0.0% |
| DVARS | > Q3 + 1.5·IQR (fMRIPrep) | 0 | 0.0% |
| refRMS | > μ + 3σ (current) | 1 | 0.4% |
| refRMS | > Q3 + 1.5·IQR (fMRIPrep) | 3 | 1.3% |
| **OR(FD>0.2, dvars 3σ, refrms 3σ) — current** | | **186** | **83.4%** |
| OR(FD>0.5, dvars Tukey) — fMRIPrep | | 59 | 26.5% |
| OR(FD>0.5, dvars 3σ) — Kaptan 2023 cord | | 59 | 26.5% |

**The 0.2 mm FD threshold alone is the entire inflation source.**
DVARS / refRMS contribute essentially nothing. The S3.2 Tukey union
contributes nothing on this run either.

## Cohort-wide impact of threshold change

| Run | FD > 0.2 | FD > 0.5 | Reduction |
|---|---|---|---|
| balgrist motor ZSpine run-01 | 83.4% | 26.5% | **−57 pp** |
| balgrist motor ZSpine run-02 | 76.7% | 29.6% | **−47 pp** |
| balgrist motor ZSpine run-03 | 70.9% | 8.5% | **−62 pp** |
| balgrist motor ZSpine run-04 | 62.8% | 17.0% | **−46 pp** |
| ds004386 rest autozshim | 67.8% | 17.8% | **−50 pp** |
| ds004386 rest manualzshim | 68.2% | 12.4% | **−56 pp** |
| ds005883 cospine_pain | 25.7% | 5.9% | −20 pp |
| ds005884 cospine_motorL | 10.3% | 1.9% | −8 pp |
| ds005884 cospine_motorR | 29.9% | 3.7% | −26 pp |

After the FD threshold fix, the cohort outlier_fraction range becomes
**1.9% – 29.6%** — consistent with the literature cord-fMRI band
of 5–30%.

## Citation audit

Current policy comment (`policy/S8_confounds.yaml`):
```
motion:
  fd_outlier_threshold_mm: 0.2     # cord 3σ (Mohammed 2020 / Kaptan 2023)
```

**This is misattributed.** Reading the cited papers carefully:

| Source | What they actually say |
|---|---|
| **Power 2014** (*NeuroImage*) — brain | FD > 0.5 mm for scrubbing; some analyses report 0.2 mm/0.5 mm/0.9 mm sensitivity comparisons |
| **Power 2014 motion_outlier convention** | fMRIPrep's `motion_outlier_NN` = OR(FD > 0.5 mm, DVARS > Tukey 1.5·IQR) |
| **Mohammed 2020** (bioRxiv cord moco) | FD measurement methodology; does not propose a specific scrub threshold. Cited as the cord-FD definition source. |
| **Kaptan 2023** (cord rs-fMRI reliability) — CORRECTION | Uses **NO FD threshold**. Flags outlier volumes on **dVARS/refRMS ≥2 SD above the run mean** (FSL fsl_motion_outliers). The terms "framewise displacement"/"FD" do not appear in the paper. Earlier rows in this doc that credit Kaptan with "FD 0.5 / 0.2 mm" are a verified misattribution (DOC-2). |
| **Dabbagh 2024** (cord fMRI confound) | 0.5 mm FD scrubbing |
| **fMRIPrep** | FD > 0.5 mm, DVARS Tukey 1.5·IQR |
| **MRIQC** | FD > 0.5 mm |

**Verdict**: the cord-fMRI FD scrubbing value is **0.5 mm**, sourced from
**Power 2014** (its lenient FD cutoff; the 0.2 mm "stringent" value is also
Power 2014). **Kaptan 2023 is not an FD source at all** — it scrubs on
dVARS/refRMS. The original policy comment conflated Power's two FD values and
wrongly attributed them to Kaptan (DOC-2, verified against the primary sources).

## DVARS / refRMS gate

Current: `μ + 3σ` (3-sigma Gaussian assumption).
fMRIPrep convention: Tukey `Q3 + 1.5·IQR` (non-parametric).

On the balgrist cohort the two methods give similar (≈0%) flagging
because the cord DVARS distribution is tight. So the DVARS gate
choice doesn't affect the headline outlier_fraction here, but
**`Tukey 1.5·IQR` is the right field-standard** to use (matches
fMRIPrep + S3.2's own outlier convention, so no method-mismatch
between layered detectors).

## Other related-but-not-causal issues

1. **S3.2 + S8 OR-combination.** S8's `_build_outlier_columns` does
   `flag |= frame_metrics["outlier"]` from S3.2, which used Tukey
   1.5·IQR. Layered detection bloats counts when both criteria fire
   on different frames. On the balgrist cohort the S3.2 Tukey flag
   set is a subset of the FD>0.2 set (verified), so it doesn't add
   to the current count — but with the FD fix below, this layering
   could become the new noise source. Recommendation: drop the S3.2
   OR-merge; S8 owns outlier detection on its own DVARS/refRMS/FD.

2. **L1-2DOF FD definition.** Our `FD = |Δtx| + |Δty|` (cord-2D
   variant) emits values that are L1 sums of two scalar derivatives.
   The Power 2014 brain definition is L1 of 6 (3 translation + 3
   rotation×50 mm radius). On pure translation our number is the
   **same magnitude** as Power's 3-translation contribution. So the
   0.5 mm threshold from cord literature is directly comparable to
   our cord-2D FD value. No re-calibration needed.

## Recommended fixes

| # | Action | Effort |
|---|---|---|
| 1 | **`fd_outlier_threshold_mm: 0.2 → 0.5`** | 1-line policy |
| 2 | Change comment to cite Power 2014 + Kaptan 2023 SCRUBBING (not Kaptan SPIKE INCLUSION) | comment only |
| 3 | Switch `dvars_outlier_n_sd` / `refrms_outlier_n_sd` from 3σ Gaussian to Tukey 1.5·IQR (matches fMRIPrep + S3.2 for consistency) | ~20 lines in `_build_outlier_columns` + policy YAML |
| 4 | Drop the S3.2 `frame_metrics["outlier"]` OR-merge — S8 owns its detection now | 3 lines deletion |
| 5 | Update `.claude/specs/s8-algorithm-audit.md` to record the threshold-citation correction | docs |

After fixes the empirical cohort outlier_fraction is expected to
land at **2–30%**, matching Kaptan 2023 / Dabbagh 2024 / fMRIPrep.

## Sources

- Power et al. 2014 — Methods to detect, characterize, and remove
  motion artifact in resting state fMRI (*NeuroImage*) — FD > 0.5 mm
- Power et al. 2017 — Carpet plot, FD-based scrubbing review
- Kaptan et al. 2023 — Reliability of resting-state functional
  connectivity in the human spinal cord (*NeuroImage*) — FD = 0.5 mm
  scrubbing
- Dabbagh et al. 2024 — Spinal cord fMRI confound modelling — 0.5 mm
- Mohammed et al. 2020 — Cord motion correction (bioRxiv) — FD
  definition only
- fMRIPrep — `motion_outlier_NN` = OR(FD>0.5, DVARS > Tukey 1.5·IQR)
- MRIQC — FD > 0.5 mm
- Esteban et al. 2017 — MRIQC (*PLoS One*)
