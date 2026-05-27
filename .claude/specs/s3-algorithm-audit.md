---
status: approved
---

# S3 algorithm audit — literature-backed, truthful, correct

A line-by-line review of every algorithmic choice in S3
(`steps/s3/{localize,outlier,crop}.py` + `policy/S3_func_init_and_crop.yaml`)
against the cord-fMRI literature. Verdict per choice + remediation
flags where the chain deviates from a published reference.

## Sub-step summary

| Stage | Operation | Engine |
|---|---|---|
| **S3.1** Dummy drop + cord localization + brain-contamination check | Trim N initial frames, build a coarse median functional reference (`func_ref_coarse`), segment cord via `sct_deepseg seg_sc_contrast_agnostic`, reject runs where the cord seg leaks into brain (pipeline name: "drift gate" — see naming note below) | `sct_deepseg` (SCT ≥ 7.0) |
| **S3.2** Frame-metrics + outlier flagging + robust funcref | Compute mask-aware DVARS + DVARS-ref (Kaptan 2023 "refRMS"; RMS of `(frame − reference)` within the cord mask) per frame, flag outliers via boxplot cutoff, build median funcref over non-outlier frames | NumPy + nibabel |
| **S3.3** Cord-focused crop | 60 mm cylinder around the cord centerline, in-plane dilation, apply to 4D BOLD | SCT `sct_crop_image` |

## Per-choice verdict

### S3.1 dummy drop

| Choice | Value | Literature | Verdict |
|---|---|---|---|
| `dummy.drop_count` | 4 | Eippert 2017: 4–5; Kaptan 2023: 4; CoSpine 2025: 4 (TR ≈ 2 s) | ✅ field-standard |
| `coarse_reference.method` | median | Mohammed 2020 cord moco — median is more robust to motion outliers than mean | ✅ standard |

### S3.1 cord localization

| Choice | Value | Literature | Verdict |
|---|---|---|---|
| `func_localization.method` | `sct_deepseg` `seg_sc_contrast_agnostic` | SCT ≥ 7.0 default; replaces `sct_deepseg_sc -c …`. EPISeg (Valošek 2025) is an emerging alternative tuned to EPI specifically but not yet packaged in SCT batch_processing | ✅ field-standard. Open question: should switch to EPISeg when SCT ships it |
| `min_z_slices` | 5 | No published precedent; sanity floor for narrow-FOV cord acquisitions (12 BOLD slices total at some sites) | ✅ defensible |

### S3.1 brain-contamination check (a.k.a. "drift gate")

Naming: internal symbol stays `drift_gate` for backwards
compatibility (policy YAML key, code paths). Reportlet text, comments,
and docs use **"brain contamination check"** so a field reviewer
reading the dashboard recognises the QC as the documented
brain-leak failure mode for cord-fMRI EPI.

| Choice | Value | Literature | Verdict |
|---|---|---|---|
| `drift_gate.enabled` | true | **No direct literature precedent.** Brain-contamination failure mode is documented in passing by SCT issue threads and CoSpine acknowledges per-acquisition QC. | ⚠️ **Novel** but principled. |
| `area_spike_threshold` | 4.0× | Brain stem CSA ~500 mm² vs cervical cord 50–80 mm² → 6–10× expected. 4× is a sensitivity-favoring cutoff (catches even early-onset drift). | ✅ defensible |
| `absolute_area_cap_mm2` | 200.0 | Cervical cord CSA never exceeds ~80 mm²; 200 mm² is comfortably above the upper bound of healthy cord with margin for swelling or pathology. | ✅ defensible |
| `superior_slices_check` | 5 | Brain leak happens at the top of FOV first; checking the top 5 cord-bearing slices catches early drift without false-flagging mid-cord. | ✅ defensible |

The brain-contamination check (a.k.a. drift gate) is a SpinalfMRIprep contribution. We documented it as
"NOT in the literature; pipeline-specific guard" — that's truthful.
It catches a real failure mode the principle §10 reg-cohort surfaced
(4 KombiShimZBrain runs in balgrist_motor). Worth a methods-paper
mention as an example of the gain from per-acquisition QC.

### S3.2 frame metrics

| Choice | Value | Literature | Verdict |
|---|---|---|---|
| **DVARS within cord mask** | Power 2014 RMS of temporal derivative, restricted to cord voxels | Power 2014 (brain) + Smyser 2019 / Kaptan 2023 cord adaptation | ✅ standard |
| **DVARS-ref within cord mask** (Kaptan 2023 "refRMS") | RMS of (frame − reference) | Standard fMRIPrep / MRIQC; Kaptan 2023 / Dabbagh 2024 cord | ✅ standard |
| **Outlier threshold: Tukey 1.5-IQR boxplot** | `Q3 + 1.5·IQR` | **Different family from literature standard.** Kaptan 2023 / Dabbagh 2024 use **3σ above the time-series mean**. | ⚠️ **Deviates from cord literature**. See remediation below. |
| **Combination rule** | DVARS OR DVARS-ref above threshold | Standard dual-criterion (Power 2014 brain + Kaptan 2023 cord) | ✅ standard |
| `outlier_fraction_warn` / `_fail` | 0.30 / 0.50 | Kaptan 2023 reports typical 2 % (range 0.6–5.6 %) for healthy cord rest. 0.30 / 0.50 is conservative — we WARN at the upper end of "still usable" | ✅ defensible (conservative side) |

**Tukey-vs-Z deviation analysis**: For roughly Gaussian DVARS, Q3 +
1.5·IQR ≈ μ + 2.7σ (cutting top ~0.4 %); 3σ cuts top ~0.13 %.
**Tukey flags slightly MORE outliers than 3σ.** On the reg cohort
this produces 1–4 % outlier flags (consistent with Kaptan 2023's
2 % typical). The choice is defensible because:

1. **Parameter-free** — no calibration against a group mean.
2. **Robust to non-Gaussian data** — heavy-tailed cord DVARS at low
   TR isn't well-modelled by σ.
3. **Adaptive to per-run variability** — scanner / sequence
   differences are absorbed automatically.

But it IS a deviation. The audit doc flags it for explicit decision.

### S3.2 robust reference

| Choice | Value | Literature | Verdict |
|---|---|---|---|
| `robust_reference.method` | median | SCT batch_processing; Mohammed 2020 cord moco | ✅ standard |
| `min_good_frames` | 10 | No published precedent; sanity floor for a usable median | ✅ defensible |

### S3.3 crop

| Choice | Value | Literature | Verdict |
|---|---|---|---|
| `crop.mask_diameter_mm` | **60 mm** | **CoSpine 2025: 35 mm** ; SCT batch_processing variable, often 40–60 mm | ⚠️ **Wider than CoSpine.** Defensible (extra context for motion artifacts) but ~70 % more in-plane voxels than CoSpine. |
| `dilate_xyz` | [2, 2, 0] | Standard 2-vox in-plane dilation (SCT convention) | ✅ standard |
| `min_z_slices` | 10 | No published precedent; cord-fMRI typically 12–24 BOLD slices | ✅ defensible |

## What's NOT in S3 (deferred / declined)

| Operation | Status | Rationale |
|---|---|---|
| Slice-timing correction | **declined** | Debated for cord fMRI. CoSpine 2025 + SCT batch_processing skip it (Eippert 2017: low benefit at short TR; cord slices are interleaved with brain in cospine pattern). ✅ standard |
| Spatial smoothing | **deferred to S9** | We use cord-aware `sct_smooth_spinalcord` (in straightened cord space) — better than CoSpine's S3-stage X+Y Gaussian kernel which doesn't account for cord curvature. ✅ improves on CoSpine |
| MP-PCA thermal-noise reduction | **deferred / not done** | Kaptan 2023 applies MP-PCA on raw EPI before preprocessing. We skip. fMRIPrep brain also skips. v2 candidate — could add a pre-S3.1 step. |
| Physiological noise modelling | **deferred to S8** | Correct architectural separation (S8 RETROICOR / PNM + SpinalCompCor). ✅ standard |
| Bandpass filtering | **deferred to S8 / analyst** | Cosine HP basis in S8 columns; analyst applies as part of GLM. ✅ standard (Eippert 2017 / Kaptan 2023) |
| Volume-level FD (frame-wise displacement) | **deferred to S4** | S4 motion correction produces FD from its rigid params; S3's mask-aware DVARS + DVARS-ref are the cord-level analogs. ✅ correct separation |

## Truthfulness review

| Claim in code/docs | True? | Source |
|---|---|---|
| "DVARS as Power 2014" | ✅ | Power 2014 NIMG: RMS of temporal derivative |
| "DVARS-ref as standard cord metric" (Kaptan 2023 refRMS) | ✅ | Kaptan 2023 / Dabbagh 2024 |
| "Tukey 1.5-IQR boxplot cutoff" | ✅ | Tukey 1977 EDA; parameter-free outlier definition |
| "median robust funcref" | ✅ | Mohammed 2020 cord; SCT batch_processing |
| "60 mm cord crop" | ⚠️ | CoSpine uses 35 mm; we are wider |
| "brain-contamination check (drift gate) is literature-backed" | ❌ | **Pipeline-specific innovation; honest documentation in this audit doc.** |

## Remediation flags

1. **Outlier threshold deviation** (Tukey vs Kaptan 3σ). Two options:
   - **Keep Tukey** (current) — parameter-free, robust to non-Gaussian
     cord DVARS. Document the deviation in S3's principles-audit
     spec; cite Tukey 1977 explicitly.
   - **Switch to 3σ** — matches Kaptan 2023 / Dabbagh 2024 cord-fMRI
     standard exactly. Lose adaptivity to per-run variability.

   **Recommendation: keep Tukey** and document. Tukey is more robust
   on the heterogeneous reg cohort. But the policy YAML's comment
   "Kaptan 2023" is inaccurate — should say "Tukey 1977" instead.

2. **Crop diameter 60 mm vs CoSpine 35 mm.** Two options:
   - **Keep 60 mm** — more cord-surround context, easier registration
     in S6 (more anatomical landmarks).
   - **Switch to 35 mm** — matches CoSpine + Hemmerling; tighter crop
     means less out-of-cord signal in S8 confound regression.

   **Recommendation: keep 60 mm as default** but expose the policy
   knob more prominently. Add a comment citing CoSpine 35 mm as the
   alternative for cord-only acquisitions.

3. **Drift gate documentation.** It's a real, principled innovation
   that catches a documented failure mode. Document it in the
   principles spec as a SpinalfMRIprep contribution; cite the
   failure mode (brain CSA >> cord CSA + SCT seg behavior at FOV
   edge).

## Audit verdict

**S3 is correct, well-implemented, and largely standard.**

- ✅ Choices that match literature exactly: dummy drop, coarse +
  robust funcref strategy, cord localization tool, dilation,
  deferred-to-S8/S9 boundaries.
- ⚠️ Choices that deviate intentionally and defensibly: Tukey
  outlier threshold (vs Kaptan 3σ), crop diameter 60 mm (vs CoSpine
  35 mm), brain-contamination check / drift gate (pipeline-specific).
- ❌ One documentation bug: policy YAML cites "Kaptan 2023" for an
  outlier rule that's actually Tukey 1977. Fix the comment;
  algorithm stays.

## Recommended actions

1. Update `policy/S3_func_init_and_crop.yaml` comments:
   - `outlier_gating.iqr_multiplier: 1.5` — cite Tukey 1977 (EDA),
     not Kaptan 2023. Note the deviation explicitly.
   - `crop.mask_diameter_mm: 60` — add `# CoSpine 2025 uses 35 mm;
     60 mm gives more anatomical context but ~70% more voxels`.
2. Append a "Drift gate: pipeline-specific QC guard" subsection to
   `.claude/specs/s3-func-init-and-crop.md` documenting the novel
   guard with the literature gap explicit.
3. No code changes required.
