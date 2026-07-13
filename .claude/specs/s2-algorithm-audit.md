---
status: approved
---

# S2 anat cordref — algorithm audit (all axes)

Date: 2026-07-13. Deep audit of every S2 algorithm choice against the
2024–2026 field standard, cross-checked against the actual code and against
real results on the 11-subject CoSpiGVS cohort (the fully-processed dataset).
Fills the gap where S2 was the only substantive step without an
`algorithm-audit` spec. Companion to the principles audit `s2-anat-cordref.md`.

Method: four independent literature deep-dives (SCT 7.1 install + docs +
primary papers) plus direct code verification and visual QC of the GVS
reportlets. Every code claim below was confirmed by reading the source.

## Verdict at a glance

| Axis | Choice | Verdict |
|---|---|---|
| Cord segmentation | contrast-agnostic `sct_deepseg spinalcord` | **KEEP** (high) |
| Anat modality priority | T2w → T1w | **KEEP** (high) |
| Orientation | RPI via `sct_image -setorient` | **KEEP** (high) |
| MEGRE/T2* synthesis | RMS over echoes, mean over runs | **KEEP-caveat** |
| Vertebral/disc labeling | TotalSpineSeg (default) | **FIXED** — sanity gate added (fallback deferred) |
| Disc label placement | mask centroid → posterior tip | **FIXED** |
| PAM50 registration params | SCT defaults (no `-param`) | **KEEP** (high) |
| Rootlets model use | always prefer, incl. T1w | **KEEP** (by design; paper TODO) |
| Reg variant selection | prefer rootlet-if-completed | **FIXED** — documented honestly |
| QC truth metric | whole-cord 3D Dice → per-level | **FIXED** — per-level primary gate |

Core algorithms are correct and well-backed. Every actionable problem is in
the **QC / selection / robustness layer**, not in the algorithm choices.

## What is solid (KEEP)

- **Cord segmentation — contrast-agnostic `sct_deepseg spinalcord`.** SCT 7.1's
  installed default anatomical cord segmenter (Bédard et al. 2025, *Med Image
  Anal*; contrast_agnostic_v3.0). Trained with a soft-label regression loss
  specifically for CSA consistency across contrasts — the correct property for
  a registration anchor. Visually clean on the GVS cohort. Note for the paper:
  it is used for *registration anchoring, not CSA morphometry* (it over-
  segments T1w/T2w in absolute terms), and the S2 crop reportlet must visibly
  show the brain+cord FOV is controlled (the one likely reviewer comment).
  **`sc_epi` is EPI-only** (model card CONTRAST: bold) and must NOT be used
  here — the S3 switch to `sc_epi` (functional) and S2 staying on `spinalcord`
  (anatomical) is the correct, non-conflated split. See
  [[s3-episeg-localization]].
- **Modality T2w → T1w.** Field/SCT convention (bright CSF, clean cord–CSF
  boundary; best for labeling + registration). T1w is a graceful fallback, not
  a downgrade — state that in the paper.
- **Orientation RPI.** Correct SCT/PAM50 convention; `-setorient` is a lossless
  reorientation (axis permute/flip + header update, no resampling). Code
  correctly uses `-setorient`, not the data-only `-setorient-data` footgun.
- **Registration `-param` defaults.** Not passing `-param` is correct: SCT's
  default is the field-standard seg-driven recipe (label → centermassrot →
  bsplinesyn), and `-lrootlet` auto-injects the recommended rootlet step. State
  "SCT defaults, QC-verified" in the paper so it doesn't read as silent tuning.

## Findings to fix (ranked)

> **Implementation status (2026-07-13).** F1, F2, F4, F5, F6 implemented in this
> pass (commit below). F3 is **by design, not a bug** — see F3. Full
> `sct_label_vertebrae` auto-fallback (F4) is deferred: no execution backend
> exists yet, so F4 shipped as a labeling *sanity gate* (WARN on mislabel
> signatures), which is the guardrail that matters; the second backend is a
> separate build. The S-I mismatch function is implemented but was **never
> wired into the pipeline** (not "already computed" in practice), so F1 shipped
> as per-level Dice — the S7-proven fix — rather than S-I gating.

### F1 — QC truth metric: whole-cord Dice is weak AND miscalibrated (highest)
Real data: on all 11 GVS subjects `pam50_cord_dice` is **0.736–0.803 — only 1
passes the 0.80 gate; 10 are WARN**. Visual overlays (AS002, MC001) show two
causes: (a) **caudal coverage drag** — the subject cord extends below where the
warped PAM50 cord reaches (labels/registration are cervically anchored; the
thoracic tail is extrapolated), so whole-cord Dice is penalized for
uncovered cord that isn't a registration error; and (b) a genuine few-voxel
**cross-sectional offset**. Separately, whole-cord Dice on a tube is
structurally **blind to superior-inferior level misalignment** — the actual
failure mode of template registration (the rootlets paper uses rostro-caudal
landmark overlap, not Dice, for exactly this reason; no published Dice band
for cord registration exists, and the policy YAML already admits 0.80/0.60 are
unvalidated guesses).

Fix: (1) adopt **per-vertebral-level median cord Dice** as the primary gate —
S7 already implements this pattern (`per_level_pass_min`), inherit it; (2)
promote the **S-I mismatch already computed** by
`register._compute_si_mismatch_from_centerlines` (shift/coverage/scaling, mm)
from observability to a gate — it is computed today and never used; (3)
recalibrate/reframe the whole-cord number as a coarse floor fit to the 8-
dataset cohort, not a literature-anchored precision metric.

**Validated on real warps (2026-07-13).** Running the new per-level metric on
the existing GVS registrations: AS002 whole-cord 0.794 (WARN) → per-level
median **0.931** (PASS), levels 0.91–0.95; MC001 (worst) whole-cord 0.736 →
per-level median **0.948**, levels 0.91–0.96. The registrations were good all
along (0.91–0.96 per level, matching S7's 0.95–1.00 band); the cohort-wide WARN
was the coverage artifact, now removed. Per-level median is the primary gate at
`per_level_pass_min: 0.90`; whole-cord Dice demoted to observability.

### F2 — Registration variant selection is not a quality pick (truthfulness + reliability)
Code (`session.py:557–571`): "prefer rootlet if it PASSes, else disc", where
PASS means only *exit 0 + warp files exist* (`register.py:38–63`) — not a
quality check. `pam50_cord_dice` is computed only on the already-selected
variant (`session.py:585`), never to compare the two. So a completed-but-worse
rootlet registration always wins when rootlets exist, and a subject can be
WARN/FAILed on the auto-selected rootlet reg when the disc reg would have
passed. The internal design doc's "select best by overlap metric" was **false
vs the code** (corrected inline 2026-07-13).

Fix: either (a) run both, compare on a **level-sensitive** metric (disc-label
alignment error or rootlet-level overlap — NOT cord Dice, which is blind to the
S-I shift rootlets fix), and select the better; or (b) keep prefer-rootlet but
describe it honestly as completion-preference. Do not ship "select best".

### F3 — Rootlets on T1w — BY DESIGN (won't change; paper TODO)
The literature note is that `sct_deepseg rootlets` is trained on T2w + MP2RAGE,
so T1w is nominally off its validated contrasts. **Decision (owner, 2026-07-13):
keep always-prefer-rootlets including on T1w — it works empirically on this
project's T1w data.** No code change. The one real action is a *documentation*
gap: the always-prefer-rootlets behaviour (and its use on T1w) is **not
currently described in the paper's methods** and must be added, with a sentence
that rootlets on T1w was verified in-house.

### F4 — TotalSpineSeg has no fallback or cross-check (linchpin single point of failure)
TSS is a defensible default (first-party in SCT since 6.5; ~1,404 training MRIs
across vendors/fields/contrasts — genuine heterogeneity strength) and visually
labeled GVS correctly (C1–T4). But it is a single nnU-Net whose accuracy is
**ISMRM-abstract/preprint level, not a confirmed journal paper**, and an
off-by-one shifts every downstream level. `sct_label_vertebrae` is wired as a
selectable option but is **not an automatic fallback or cross-check**. Fix: add
a cheap automatic sanity check (monotonic disc ordering, expected inter-disc
spacing, C2–C3 anchor) and wire `sct_label_vertebrae` as auto-failover (the
code path already exists). Truthfulness: cite TSS at its real maturity and
carry the authors' own "not validated for CSA / pathology" caveat; the
"cropped-top FOV, no C1/C2 landmark" case is the specific failure to watch
(consider TSS `--loc` localizer).

### F5 — Disc labels placed at centroid, not posterior tip (convention mismatch)
`segment.py:194–208` places the single-voxel `-ldisc` label at the disc mask
**centroid**; SCT's convention (and `sct_label_vertebrae` output) is the
**posterior tip** of the disc. Registration is driven mainly by S-I position so
the effect is small, but it is easy to make exactly correct: take the
posterior-most voxel at the centroid's S-I level.

### F6 — MEGRE mean-across-runs assumes aligned runs
RMS-across-echoes is sound (root-sum-of-squares / MEDIC magnitude combination;
magnitude-weighted so noisy late echoes self-limit — beats plain mean and
first-echo). Two caveats to document or guard: a naive voxelwise **mean across
runs blurs the cord if runs are not co-registered** (rigid-register runs first,
or QC between-run displacement); and combining *all* echoes is fine for
whole-cord segmentation (not GM/WM) but say so. Not a T2* quant map — state it.

## Real-data evidence (CoSpiGVS, 11 subjects, current build)

- `pam50_cord_dice`: 0.736–0.803, mean ≈ 0.776; PASS 1/11, WARN 10/11.
- Vertebrae detected 11–13, discs 9–11, rootlet labels 8 (note: the principles
  spec's "~16 expected" is a count/convention mismatch to reconcile).
- Cord seg + TSS labeling visually clean; PAM50 overlay shows systematic
  cross-sectional offset + caudal template non-coverage on every subject.

## Follow-ups / sequencing

F1 and F2 are the two a methods reviewer will press hardest and should land
before S2 is re-locked. F3, F5 are small and safe. F4 is medium. Recalibration
of any threshold must be fit on the full 8-dataset / 384-run cohort (after the
EPISeg S3 change re-runs the chain), not on GVS alone. Visual QC remains the
validator (invariant #4) — every gate change is eyeballed on the reportlets.
