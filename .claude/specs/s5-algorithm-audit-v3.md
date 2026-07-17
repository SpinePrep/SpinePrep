---
status: approved
extends: s5-algorithm-audit-v2.md
---

# S5 algorithm audit v3 — literature pass, truthfulness

Written 2026-07-16. v2 audited the implementation (ANTs flags, mode dispatch,
mask selection) and settled the PE-restriction question empirically. This pass
re-checked S5's **claims** against primary cord-fMRI literature and found the
implementation sound but several stated rationales wrong or unciteable. The
code is largely KEEP; the writing is not.

**Headline: S5's algorithm is defensible, but the story around it is not.** The
doc calls the topup→SyN order "the field-standard susceptibility-distortion
ladder". That is fMRIPrep's **brain** ladder. In cord fMRI the default is to do
**no distortion correction at all**, and the two rungs SpinePrep implements are
precedented by different schools, with the fallback precedented by nobody and
argued against in print.

## What the cord field actually does (verified)

| Group / paper | SDC approach |
|---|---|
| Eippert 2017; Kaptan 2023 (Leipzig) | **None.** Acquisition-side slice-specific z-shimming: "Both functional runs employed slice-specific z-shimming to overcome the signal-loss…" |
| Kinany 2022 (Geneva) | **None.** Shim volume focused on cord; no topup/fieldmap/FUGUE |
| Barry 2014 (Vanderbilt); Weber 2016 | **None** (absence-of-term search — weaker evidence, see caveat) |
| Powers / Stroman 2018 (Kingston) | **Avoids** distortion (HASTE/spin-echo) rather than correcting it: "Slice-specific shimming… does not eliminate the distortions" |
| **Oliva 2025** (Imaging Neuroscience, doi:10.1162/IMAG.a.159; incl. Kaptan, Weber, Glover, Mackey) | Acquired reverse-PE, applied topup **to the brain only**; cord left uncorrected |
| **Vahdat 2015** (PLoS Biol, doi:10.1371/journal.pbio.1002186) | **GRE fieldmap unwarping** of brain *and* cord |
| **FASB** (Vahdat, Landelle, De Leener, Doyon; doi:10.21203/rs.3.rs-3889284/v1) | **FUGUE** (GRE fieldmap), explicitly |
| **CoSpine / Wei 2025** (Sci Data) | **TOPUP** — essentially the only cord TOPUP use found |

Consequence: performing SDC at all puts SpinePrep **ahead of** the cord field,
not in line with it. That is arguably a contribution, but it must be claimed as
a deliberate choice with CoSpine as the evidence, never as "field-standard".

## Findings

### F1 — "field-standard ladder" is a mis-claim — FIX (doc)
`docs/methods/S5_distortion_correction.md`: "The order below is the
field-standard susceptibility-distortion ladder (fMRIPrep SDCFlows; Andersson
2003)." fMRIPrep's ladder is a **brain** ladder. For cord, TOPUP appears
essentially once (CoSpine 2025) and most groups do no SDC. **Never write "TOPUP
is the cord field default"** — a cord reviewer will know. Honest framing: "we
adopt the best-evidenced option available", CoSpine as the evidence.

### F2 — FUGUE is the *most* precedented cord SDC, not a legacy nicety — FIX (framing)
The v1 story treats the unimplemented FUGUE path as a gap "versus fMRIPrep".
It is worse than that: GRE-FUGUE is the one cord SDC method with a consistent
school behind it (Vahdat 2015; FASB — Vahdat/Landelle/De Leener/Doyon). So
SpinePrep omits the method the Montreal group uses. The **reason is still fine**
— no `intended_use: v1_validation` dataset ships a GRE phasediff map, and
shipping an unvalidatable path violates lock-and-ship. State plainly: FUGUE is
unimplemented **for lack of GRE data, not for lack of standing**. Do not lean on
any "fieldmaps are worse" argument (none is present in the specs — verified).

### F3-RESULT — held-out validation: SyN recovers ~26% of the measured field and harms 1 in 4 runs
Ran the held-out test (`scripts/s5_heldout_syn_vs_topup.py`) on all 80 CoSpine
runs that have a reversed-PE pair: corrected each run with topup (measured field =
reference) and with SyN (pretending no fieldmap), and scored SyN's agreement with
the field per slice, never on Dice. Measurement validated: mean uncorrected
distortion 2.75 mm ≈ CoSpine's published 2.73 mm.

`gap_closed = 1 - mean|d_syn - d_topup| / mean|d_before - d_topup|`
(1.0 = SyN reproduces the field; 0 = no better than nothing; <0 = SyN moved the
cord away from the field):

| | value |
|---|---|
| median gap_closed | **+0.22** |
| SyN reproduces field (gap > 0.5) | 20/80 (25%) |
| SyN helps somewhat (0–0.5) | 40/80 (50%) |
| **SyN moved cord AWAY from field (gap < 0)** | **20/80 (25%)** |
| baseline (topup moved the cord) | 2.75 mm |
| residual (SyN missed by) | 2.03 mm |

So SyN recovers ~26% of the distortion the fieldmap measures, and on a quarter of
runs it makes the alignment worse — the FASB "twisted warping" failure, measured.
This is on CoSpine's whole-CNS (brain+cord) acquisition, the highest-distortion
regime; the 386 fallback runs in the real cohort are mostly cervical-only and
milder, where SyN is untested and might do relatively better or worse. But the
decisive asymmetry stands: we cannot tell per-run whether SyN helped or harmed
(cord Dice is circular), so a `syn` default silently degrades ~1 in 4 runs with no
way to detect it. Recommendation: flip the fieldmap-less default to `none` (the
cord field's own default, honest, detectable), keep `syn` as a documented opt-in.

### F3 — a published cord-specific objection to the SyN fallback — ANSWERED by F3-RESULT
FASB considered nonlinear warping of cord EPI and **argued against it**:
"Spinal cord EPI images are often spatially distorted at the disk level, and
performing a nonlinear transformation generates **non-optimal twisted warping
fields**." They chose slice-wise centerline alignment to a same-angle T2w
instead. So SpinePrep's SyN fallback is not merely unprecedented in the cord —
the pipeline paper that reasoned hardest about this exact problem rejected the
approach. This must be **cited and rebutted** in the deviation spec, not left
for a reviewer to find. The rebuttal material exists (cohort Dice/displacement
gains, and the metric is reported per-slice so a twisted warp would show), but
it has to be written and, ideally, backed by a held-out-TOPUP validation:
correct a CoSpine reverse-PE run with SyN, compare against its TOPUP result.

### F4 — the cervical-ROI rationale attributes the effect to the wrong cause — FIX (policy)
`policy/S5_func_distortion_correction.yaml:53` justifies `cord_roi_max_level: 8`
by "the lung-adjacent thoracic cord, where susceptibility distortion is
uncorrectable without a fieldmap (10-17 mm A-P vs ~0.4 mm in the cervical
cord)". Three problems:
- **Wrong mechanism.** Beghini 2026 (MAGMA, doi:10.1007/s10334-026-01349-4):
  "Fourier-based field simulations confirmed the **vertebrae** to be the main
  contributors to the local static field in the spinal canal." Lungs drive the
  **dynamic** part ("Dynamic B0 field fluctuations are mainly caused by
  variations of air volume in the lungs"). The static distortion S5 corrects and
  gates on is mostly vertebral.
- **Unsourced number.** "10-17 mm A-P vs ~0.4 mm" appears nowhere but this
  comment. No thoracic-vs-cervical distortion comparison has been published —
  every quantified profile stops at T1 (cervical coils/FOVs). Millimetres are
  also not an anatomical constant: displacement scales with echo spacing, so no
  general mm figure exists to quote.
- **Cuts the other way.** Kowalczyk 2025 (susceptibility-matched padding):
  "greater effects were observed in the **cervical** cord" than lumbar.

**Keep the ROI restriction — fix the reason.** Safe, cited framing: B0 offset
rises steeply toward the cervicothoracic junction, ~20 Hz at C1 to ~154 Hz at T1
at 7T (Beghini 2026; cf. Verma & Cohen-Adad 2014, "maximum of 74 Hz at C7…
0.58 ppm"), so the metric is restricted to the levels where the field profile is
characterized — **the data ends at T1**. Do not write "thoracic is worse than
cervical".

### F5 — the 2-level SyN justification is unverified — SCOPE
Policy justifies `convergence 40x20x0` (0 iterations at full resolution) with
"A-P distortion is low spatial frequency and converges at the coarser levels".
That premise is **UNVERIFIED** — no source was found for it. The empirical
result (cohort Dice gains) stands on its own. Reword as a design assumption
tested empirically, not a physical fact; or test `40x20x10` on the cohort and
lock whichever wins. Do not state the low-spatial-frequency claim as fact.

### F6 — "jac matches the fMRIPrep default" is wrong — FIX (doc)
The doc says `--method jac` matches "the FSL and fMRIPrep default".
**fMRIPrep never calls `applytopup`** — SDCFlows resamples with its own
machinery. `jac` is correct as FSL's standard apply method and the right choice
here (`lsr` needs both PE directions of the BOLD itself, which we lack); drop
the fMRIPrep attribution.

### F7 — EPISeg mis-citation — FIXED
"EPISeg, Valošek 2025" in four places, two of them in shipped code
(`process.py:474,607`), plus `s5-algorithm-audit-v2.md` and
`s5-distortion-effectiveness-reportlet.md`. EPISeg is **Banerjee et al. 2025**
(SCT model card, doi:10.1101/2025.01.07.631402); Valošek 2024 is rootlets. Same
error corrected in S3. All four fixed.

### F8 — public-doc truthfulness — FIX (doc)
Verified against code:
- The doc names `sct_deepseg_sc` for the EPI cord segmentation; the code uses
  `sct_deepseg sc_epi` (EPISeg) — the v2 audit switched models precisely because
  the legacy one undersegmented (219 vs 1081 cord voxels on handgrasp).
- The doc still publishes "two handgrasp runs FAIL on genuine A-P mismatch" —
  a claim the v2 audit **explicitly retracted** ("This was wrong… the methods
  paper can drop the previous 'handgrasp = real mismatch' caveat"). After the
  model switch the cohort had **0 FAIL**. A retracted falsehood is live on the
  public site.
- "On the 11-run validation cohort" — that is the retired reg cohort. The real
  cohort is 466 runs, and S5 has not run on it (F9). Do not present 11 runs as
  the validation.
- The doc implies SyN is "treated as lower confidence than topup regardless of
  how good its geometry score looks"; the code **removed** the SyN-always-WARN
  rule (2026-05-28, "too conservative"). SyN can PASS on good geometry.

### F9 — S5 has never run on the 466-run cohort — OPEN
Every S5 empirical number (Dice, displacement, mode split, the PE-restriction
reversion) comes from 11 runs of the retired reg cohort. S5 depends on S4, which
is only now having its first cohort run. Until S5 runs on the 466, its numbers
are not the paper's numbers.

## What stands (verified, KEEP)
- **CoSpine metric definition and numbers** — post-TOPUP ≈ 0.13 mm vs ≈ 2.73 mm
  uncorrected, verified verbatim from Wei 2025.
- **`b02b0_1.cnf`** — a real FSL-shipped config; the right choice for the odd
  in-plane/Z dims of cord-cropped BOLD (default `b02b0.cnf` subsamp=2 needs even
  dims).
- **`--method jac`** — correct (see F6 for the attribution fix).
- **The PE-restriction reversion (v2)** — restricting deformation to the PE axis
  and tightening the mask to the cord seg *degraded* Dice on the cohort;
  cord-only SyN is signal-starved where brain-wide SDC-SyN is not. A genuine,
  non-obvious empirical finding worth a sentence in the paper — and note that
  fMRIPrep **does** restrict to PE, so the deviation must be stated as measured,
  not as convention.
- **Mode selector** (`mode.py`) — clean, honest, `IntendedFor` + opposite-PE.

## Citation hazards (do not repeat)
- **Do not cite Islam 2019 for "−100 to −250 Hz."** Traced to a secondhand
  attribution in Alonso-Ortiz 2022, which itself cautions the level
  correspondence "was not given"; the Islam primary has no such values.
- **PMC10831202** ("segmental organisation… test–retest") is **Kowalczyk et al.
  2024** (HBM, doi:10.1002/hbm.26600), **not Kaptan**.
- The "no SDC" findings for **Eippert 2017, Barry 2014, Weber 2016** rest on
  absence-of-term searches. Kinany 2022 and FASB were verified by direct
  pdftotext+grep. **Before any "the field does not correct distortion" sentence
  enters the paper, grep those three PDFs directly** — it is a strong claim
  currently resting on the weakest evidence type available.

## Open items, by priority
1. **F3** — cite and rebut FASB's twisted-warping objection; ideally validate
   SyN against a held-out CoSpine TOPUP run.
2. **F9** — run S5 on the 466-run cohort after S4 lands; re-derive every number.
3. **F5** — test `40x20x10` vs `40x20x0`, or reword the justification.
4. Verify the three "no SDC" papers by direct PDF grep before claiming it.

## Fixed in this audit
- **F7** — EPISeg citation corrected in 4 places (2 in shipped code).
- **F1, F6, F8** — public doc rewritten (see below).
- **F4** — policy rationale corrected to the vertebral mechanism + the
  characterized-levels justification; unsourced mm figure removed.
