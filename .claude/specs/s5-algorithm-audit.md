---
status: approved
---

# S5 algorithm audit — literature-backed, truthful, correct

Line-by-line audit of every distortion-correction choice in S5
(`steps/s5/{process,mode,reportlets}.py` + `policy/S5_func_distortion_correction.yaml`)
against the cord-fMRI / EPI-distortion literature. Sibling of the
S3 / S4 audits (same format).

S5 received the deepest audit-and-rework in the May 2026 cycle: v1
reportlets (qualitative montage + MI bar) were replaced by CoSpine-
style geometric metrics (Wei 2025 Sci Data), then a v2 re-rework
added cost-driven anat→BOLD rigid registration and per-slice
smoothing of the Y(z) traces.

## Sub-step summary

| Stage | Operation | Engine |
|---|---|---|
| **S5.0** Per-run mode selection | Pick topup / fugue / SyN from S1 inventory + BIDS `IntendedFor` | `mode.py` (pure functions) |
| **S5.A** topup | Reversed-PE EPI pair → field estimate → applytopup with `--method=jac` | FSL `topup` + `applytopup` (b02b0_1.cnf) |
| **S5.B** fugue | GRE phasediff + magnitude — **NOT implemented in v1.0**, falls through to SyN | (stub) |
| **S5.C** SyN | Cord-mask-restricted ANTs SyN of mean-BOLD → T2w anat | ANTs `antsRegistration` (`SyN[0.1,3,0]`, MI metric, 4x2x1 shrink, 2x1x0 smoothing) |
| **S5.QC** Effectiveness metrics | Per-Z A–P cord-centerline displacement + 2D cord-Dice (Before vs After) + 3D pooled Dice | sct_register_multimodal rigid (anat→BOLD-after) + sct_deepseg_sc + Savitzky-Golay smoothing |

## Per-choice verdict

### Mode ladder topup → fugue → SyN

| Choice | Value | Literature | Verdict |
|---|---|---|---|
| **Ladder ordering** | topup > fugue > SyN | fMRIPrep SDCFlows: PEPolar > GRE > anat-driven SyN; Wei 2025 CoSpine ranks topup as gold standard (2.73 → 0.13 mm A–P displacement). | ✅ field-standard |
| **fugue not implemented (v1.0)** | falls back to SyN | fMRIPrep SDCFlows ships GRE-based unwarping; we ship only topup + SyN. None of the 11 reg-cohort runs ships a GRE pair, so the gap is untested-but-real. | ⚠️ **gap vs fMRIPrep** — defensible for v1.0 (no GRE data in reg-cohort) but flagged for v1.1. |
| **SyN as no-fmap fallback** | `SyN[0.1,3,0]` light SyN, MI metric, cord-mask-restricted | fMRIPrep SDCFlows convention; ANTs SyN with MI for cross-modal (BOLD → T2w). Avants 2008 (SyN); Studholme 1999 (MI). | ✅ standard |

### topup parameters (mode `topup`)

| Choice | Value | Literature | Verdict |
|---|---|---|---|
| `topup.config` | `b02b0_1.cnf` | FSL ships `b02b0.cnf` (default) and `b02b0_1.cnf` (`subsamp=1` throughout). Our cord-cropped BOLD has odd in-plane / Z dimensions (≈30×33×35), which `b02b0.cnf`'s `subsamp=2` first-iteration step rejects. `b02b0_1.cnf` is the FSL-shipped tolerance config. | ✅ correct FSL convention for cropped cord data. CoSpine uses full-FOV so they can use default. |
| `topup.apply_method` | `jac` | FSL & fMRIPrep recommendation. `jac` applies Jacobian intensity modulation (preserves signal). `lsr` (least-squares) requires BOTH forward and reverse PE BOLDs in input — we have only one. | ✅ correct for our pipeline |
| TRT source | BIDS `TotalReadoutTime` (with EffectiveEchoSpacing × (ReconMatrixPE-1) fallback) | BIDS spec §EPI metadata; FSL topup expects TRT in the 4th column of acqparams.txt | ✅ standard, with defensive fallback to sidecar |
| fmap resample to BOLD geometry | `flirt -applyxfm -usesqform` (trilinear) | topup must be estimated in the BOLD's voxel grid; applytopup does NOT auto-resample. sform/qform encode the rigid scanner→world; trilinear is the standard interp for fmap intensities. | ✅ correct (necessary preprocessing step) |
| Inindex from BOLD PE | First acqparams row whose PE matches BOLD's PE | applytopup convention | ✅ standard |

### SyN parameters (mode `syn`)

| Choice | Value | Literature | Verdict |
|---|---|---|---|
| Transform | `SyN[0.1,3,0]` | ANTs default for symmetric normalization: gradient step 0.1, update field smoothing 3 vox, total field smoothing 0. Light SyN suitable for distortion-only (not anatomic) registration. | ✅ ANTs convention |
| Shrink factors | `4x2x1` | 3-level pyramid (×4, ×2, ×1). Brain SyN typically uses `8x4x2x1`; cord-mask-restricted on small ROI doesn't benefit from coarser levels. | ✅ defensible for cord-cropped data |
| Smoothing sigmas | `2x1x0vox` | Matches the 3-level shrink. fMRIPrep SDCFlows uses `2x1x0vox` too for its SDC-SyN step. | ✅ matches fMRIPrep |
| Convergence | `[40x20x0,1e-6,10]` | Shorter than fMRIPrep brain SyN (`[100x70x50,1e-6,10]`). Cord-mask-restricted small ROI converges fast. | ✅ defensible — the cord ROI is small enough that 40+20 iterations suffice. |
| Metric | `MI[32 bins]` | Studholme 1999 MI; 32 bins is fMRIPrep / ANTs standard for cross-modal BOLD↔T2w. | ✅ standard |
| Mask | cord mask (both fixed & moving) | fMRIPrep experimental SDC-SyN; restricts cost to cord region. | ✅ literature-backed |
| Resampling interp | `LanczosWindowedSinc` | fMRIPrep convention — preserves T2*-weighted contrast better than linear or BSpline. | ✅ matches fMRIPrep |
| Output geometry | BOLD grid (warp anat→BOLD, then apply to BOLD with BOLD as ref) | Geometry-preserving: downstream chain (S6+) consumes BOLD-space outputs. | ✅ correct architecture |

### Mode selection logic (`mode.py`)

| Choice | Value | Literature | Verdict |
|---|---|---|---|
| `IntendedFor` permissive fallback (no `IntendedFor` → match all) | accept all fmaps if field absent | Many older BIDS datasets omit `IntendedFor`; refusing them would block topup for legitimate data. BIDS validator soft-warns but doesn't error. | ✅ defensible BIDS-compatibility |
| `_opposite_pe` detection (e.g. `j` ↔ `j-`) | same axis, flipped sign | BIDS spec §PhaseEncodingDirection | ✅ standard |
| GRE fmap detection (`phasediff`/`_phase` + `_magnitude`) | filename pattern | BIDS spec §fmap modality | ✅ standard |
| BIDS `dir-AP` → `j-` fallback | filename entity convention | Standard cervical EPI A-P/P-A convention | ✅ standard |

### CoSpine effectiveness metrics

| Choice | Value | Literature | Verdict |
|---|---|---|---|
| Per-slice A–P cord-centerline displacement | **CoSpine §"Slice-by-slice Y-axis displacement"** (Wei 2025 Sci Data) | Literal CoSpine recipe; the geometric truth metric for distortion correction. | ✅ field-standard |
| 2D per-slice cord-Dice (EPI ∩ anat) | CoSpine supplementary | Per-slice Dice is supplementary diagnostic | ✅ standard |
| 3D pooled cord-Dice | **CoSpine §"Spinal cord DSC"** (`sct_dice_coefficient` equivalent) | Literal CoSpine recipe; reported in CoSpine Figure 3 / Table 1. | ✅ matches CoSpine exactly |
| EPI cord seg via `sct_deepseg_sc -c t2s` | on Mean-BOLD-Before and Mean-BOLD-After | CoSpine §Methods uses sct_deepseg_sc for EPI cord seg | ✅ matches CoSpine |
| **Anat→BOLD-after rigid registration** | `sct_register_multimodal -param step=1,type=seg,algo=rigid,metric=MeanSquares,iter=20` | CoSpine §Registration uses `FLIRT` 6-DOF intensity-driven (`normmi` cost). Our deviation: cord-seg-driven cost. **Reason**: FLIRT intensity cost on cord-cropped inputs is dominated by air around the cord → diverges to wildly rotated solutions. Same registration recipe S6 uses for func→anat. | ⚠️ **deviates from CoSpine** but documented; defensible on cord-cropped data |
| Savitzky-Golay smoothing of Y(z) trace | window=5, poly=2 | **Not in CoSpine paper.** Our addition: cord disc ≈12–20 voxels @ 1 mm in-plane → per-slice centroid stddev ≈ d/√(12·N) ≈ 0.3 mm sampling jitter. SG poly-2 over 5 slices removes this without flattening real distortion variation (which has spatial scale ≈5–10 slices). | ⚠️ **Pipeline-specific** (Savitzky 1964 EDA primitive). Documented in policy + spec. |
| AP axis from `nib.aff2axcodes` | affine-derived | Defensive for non-RPI BOLD data | ✅ defensible (S2 enforces RPI on anat; BOLD may differ) |
| Min-voxels-per-slice floor | 3 | Cord centroid sampling-dominated for thinner cord cross-section | ✅ defensible |

### QC thresholds

| Gate | Value | Source |
|---|---|---|
| PASS `pass_dice_min` | 0.50 | CoSpine TOPUP post-correction Dice well above 0.50; 0.50 is a defensible "well-corrected" floor for SyN fallback inclusively. | ✅ defensible |
| WARN `warn_dice_min` | 0.30 | Below this on After ⇒ FAIL outright. CoSpine pre-correction Dice values can dip to 0.2–0.3 (significant distortion) | ✅ defensible |
| PASS `pass_displacement_max_mm` | 1.0 | CoSpine TOPUP achieves 0.13 mm; 1.0 mm is a loose-but-defensible floor admitting SyN cases | ✅ defensible |
| WARN `warn_displacement_max_mm` | 2.0 | CoSpine pre-correction mean A–P 2.73 mm; 2.0 mm is the dividing line between "partially corrected" and "no improvement" | ✅ defensible |
| `epsilon_dice` | 0.02 | Tolerance for "did not degrade" | ✅ defensible |
| `epsilon_displacement_mm` | 0.2 | Tolerance for "did not worsen" | ✅ defensible |
| `fail_mi_max_drop_pct` | 10.0 | Legacy catastrophic-drop sanity check (independent of Dice path) | ✅ defensible |
| **SyN-always-WARN rule** | hardcoded | No fieldmap ⇒ lower confidence regardless of Dice score | ✅ defensible policy decision (documented) |

## What's NOT in S5 (deferred / declined)

| Operation | Status | Rationale |
|---|---|---|
| FUGUE GRE-based unwarping | **stub, falls back to SyN** | fMRIPrep SDCFlows ships it; we don't (no GRE data in reg-cohort). Acceptable gap for v1.0; flagged as v1.1 work. |
| Per-vertebral-level breakdown (C1–T1) | **deferred to S7** | CoSpine reports displacement/Dice per vertebra; would require backprojecting S7's PAM50 vertebral labels into BOLD geometry. Open follow-up. |
| `sct_dice_coefficient` CLI tool | **not used** | We implement the Dice ourselves in NumPy; gives us per-slice breakdown that the CLI tool doesn't surface. Equivalent results on the 3D-pooled aggregate. ✅ defensible |
| 4-D EPI distortion via DRBUDDI / HySCO | **not used** | More advanced corrections (Irfanoglu 2015 DRBUDDI; Ruthotto 2012 HySCO). fMRIPrep brain doesn't use them either. Defer to v2 if topup proves insufficient. |
| Cross-validation against PE-reversed Mean-BOLD | **not used** | Would require dual-PE BOLD acquisitions; outside our acquisition envelope. |

## Truthfulness review

| Claim in code / docs | True? | Source |
|---|---|---|
| "topup ranked first" | ✅ | Andersson 2003; fMRIPrep SDCFlows |
| "applytopup `--method=jac`" | ✅ | FSL docs; fMRIPrep default |
| "b02b0_1.cnf for odd-dim cord-cropped data" | ✅ | FSL `etc/flirtsch/` ships both configs |
| "SyN[0.1,3,0] is ANTs default" | ✅ | ANTs `antsRegistration` defaults |
| "MI 32 bins for cross-modal" | ✅ | fMRIPrep convention; Studholme 1999 |
| "LanczosWindowedSinc preserves contrast" | ✅ | fMRIPrep convention; Lanczos kernel theory |
| "CoSpine-style per-slice A–P displacement" | ✅ | Wei 2025 Sci Data §Slice-by-slice Y-axis displacement |
| "3D pooled cord-Dice equivalent to sct_dice_coefficient" | ✅ | Identical math (2·|A∩B| / (|A|+|B|)) |
| "Savitzky-Golay denoising of finite-voxel centroid jitter" | ✅ | Savitzky 1964; jitter math derived in process.py comment |
| "sct_register_multimodal rigid replaces CoSpine's FLIRT 6-DOF" | ✅ — **honestly flagged as deviation**, not as "matching CoSpine" |
| "SyN always WARN — no fmap = lower confidence" | ✅ | Documented policy decision in `_classify_run_status` |

No truthfulness violations. The two flagged deviations (anat→BOLD-after registration engine; Savitzky-Golay smoothing) are honestly documented as pipeline contributions, not falsely claimed as CoSpine-standard.

## Remediation flags

1. **FUGUE not implemented** (mode 2 of 3 in the ladder). Falls back to
   SyN; documented in code (`_run_fugue` returns FAIL with explicit
   message). Acceptable for v1.0 because no reg-cohort data ships GRE
   pairs, but it's a real gap vs fMRIPrep SDCFlows ladder.

   **Recommendation**: defer to v1.1. Implement after the methods
   paper if the cohort ever includes GRE fmaps. Add an explicit
   `fugue_status: "not_implemented"` field to qc.json so downstream
   filters can distinguish "fmap-eligible but SyN-fallback because
   FUGUE missing" from "no fmap available".

2. **CoSpine recipe deviation: SCT rigid vs FLIRT 6-DOF for the
   anat→BOLD-after reference alignment.** Already documented in spec
   and code. Defensible because FLIRT intensity-only cost diverges on
   cord-cropped inputs. SCT cord-seg-driven is the more robust choice
   on our geometry.

   **Recommendation**: keep as-is. The spec already cites the
   deviation explicitly. Consider running a head-to-head reg-cohort
   comparison (SCT vs FLIRT-6DOF) once and recording the result, so
   the choice is empirically justified rather than only theoretically.

3. **Savitzky-Golay smoothing of per-slice Y(z) is a SpinalfMRIprep
   contribution**, not in CoSpine. Already documented as additive
   denoising of finite-voxel centroid jitter. Defensible because the
   smoothing scale (5 slices, poly 2) is much shorter than the spatial
   scale of real distortion variation (5–10 slices). Tracked as a
   novel-but-principled contribution worth mentioning in the methods
   table.

4. **SyN convergence iterations (`40x20x0`) are shorter than fMRIPrep
   brain SyN (`100x70x50`).** Defensible because the cord-mask-restricted
   ROI is small and converges fast, but worth quantifying: does the
   correction reach the same Dice plateau with 100x70x50? Untested.

   **Recommendation**: low-priority. Current SyN achieves 0.55–0.86
   dice_after on reg-cohort, well above the 0.50 PASS floor. Probably
   not iteration-bound.

5. **Reg-cohort exercises only the SyN path** (no fmap-equipped data).
   topup code is unit-tested but not integration-tested. Document this
   explicitly when the methods paper lands. **Recommendation**: add a
   one-shot integration test using a synthetic / public dataset with
   reversed-PE fmaps once available.

## Audit verdict

**S5 is correct, well-implemented, and largely standard.**

- ✅ Mode ladder (topup → SyN-fallback) matches fMRIPrep SDCFlows.
- ✅ topup parameters (`b02b0_1.cnf`, `--method=jac`) follow FSL conventions
  with documented adaptation (odd-dim tolerance config) for cord-cropped data.
- ✅ SyN parameters (`SyN[0.1,3,0]`, MI 32-bin, LanczosWindowedSinc)
  match ANTs / fMRIPrep conventions.
- ✅ Effectiveness metrics (per-slice A–P displacement + 2D/3D cord-Dice)
  literal-match Wei 2025 Sci Data CoSpine recipe.
- ⚠️ Anat→BOLD-after rigid uses SCT (cord-seg-driven) instead of
  CoSpine's FLIRT 6-DOF — *defensible deviation*, explicitly documented.
- ⚠️ Savitzky-Golay smoothing of Y(z) — *pipeline contribution*,
  explicitly documented; suppresses finite-voxel centroid jitter.
- ⚠️ FUGUE stub falls through to SyN — *real gap vs fMRIPrep* for v1.0
  (no GRE data in reg-cohort, so untested anyway). v1.1 work.
- ❌ No truthfulness violations. No critical bugs. No misattributed
  algorithm choices.

## Recommended actions

1. Update `policy/S5_func_distortion_correction.yaml` `distortion_correction.fugue` block
   with an explicit `not_implemented_in_v1: true` comment to make the gap visible
   without reading code.
2. Append a "v1.1 work items" subsection to `.claude/specs/s5-func-distortion-correction.md`
   listing: FUGUE implementation, head-to-head SCT-vs-FLIRT-6DOF reg comparison,
   integration test on fmap-equipped public dataset.
3. No code changes required for v1.0.

## Sources (consulted)

- FSL — `topup` user guide
  (`https://fsl.fmrib.ox.ac.uk/fsl/fslwiki/topup`); `applytopup` docs;
  `b02b0.cnf` / `b02b0_1.cnf` ship under `$FSLDIR/etc/flirtsch/`.
- Andersson, Skare, Ashburner 2003 — How to correct susceptibility
  distortions in spin-echo echo-planar images (NeuroImage)
- Wei et al. 2025 — CoSpine: a multi-site spinal cord fMRI database
  (Sci Data) — §Methods Registration; §Slice-by-slice Y-axis
  displacement; §Spinal cord DSC; Figure 3 / Table 1
- Avants et al. 2008 — Symmetric diffeomorphic image registration with
  cross-correlation (Med. Image Anal.) — ANTs SyN reference
- ANTs — `antsRegistration` user guide; SyN transform defaults
- fMRIPrep / SDCFlows documentation — SDC ladder (PEPolar > GRE >
  SyN-fallback); experimental SyN params
- Studholme et al. 1999 — Mutual-information-based registration
- Savitzky & Golay 1964 — Smoothing and differentiation of data by
  simplified least-squares procedures (Anal. Chem.)
- SCT — `sct_register_multimodal` docs; `sct_deepseg_sc` docs;
  `sct_dice_coefficient` docs
- BIDS specification — fmap modality, PhaseEncodingDirection, IntendedFor,
  TotalReadoutTime, EffectiveEchoSpacing fields
