---
status: implemented
priority: low
parent: s4-algorithm-audit.md
resolution: 2026-06-10 — 2-DOF FLIRT-on-Z-mean shipped (config/flirt_XY_only.sch), sign-corrected (BUG-1c, shift=[-tx,+ty]). CoSpi's MCFLIRT 3D 6-DOF was A/B-tested on the dev cohort and LOST (cord tSNR 15.26 ≈ no-correction vs FLIRT-2DOF 18.30) → FLIRT-2DOF is the locked Stage-1. See ledger "S4 Stage-1 A/B".
---

# S4 Stage 1: replace phase_cross_correlation with 2D-restricted FLIRT

## Motivation

Stage 1 currently uses `skimage.registration.phase_cross_correlation`
(Guizar-Sicairos 2008) for bulk 2D-translation pre-alignment before
SCT's slicewise Stage 2. The algorithm is mathematically optimal for
the 2D-translation problem and ~50 ms/volume, but **has no precedent
in cord-fMRI motion correction** — the field standard is FLIRT-
family rigid registration (MCFLIRT, FLIRT-loop, sct_fmri_moco's
internal 3D stage).

For literature-defensibility (auditability, methods reproducibility,
alignment with Gergely's lab convention), replace Stage 1 with a
**FLIRT-based 2D bulk** that disables Z. This keeps the empirical
behaviour (XY-only bulk) but uses a tool the cord-fMRI community
recognises.

## Context: why Z must stay disabled

Gergely's lab tried MCFLIRT but "couldn't deactivate the Z dimension"
(SCT-P2 presentation 2026-03-30, with Armin Curt, Julien Cohen-Adad).
Julien explicitly endorsed XY-only ("if there's no Z, don't call it
3D"). Cord has no Z contrast (locally-uniform tube), Z resolution is
~5 mm, and physically the cord can't translate in Z. See
`.claude/specs/s4-algorithm-audit.md` and Slack convo
2026-04-21..05-07 for the trail.

## Approach

FLIRT doesn't have a native XY-only mode. Two options:

**Option A — schedule file (preferred)**:
- Use `flirt -schedule <custom.sch>` with a schedule that locks
  Tz/Rx/Ry/Rz to zero. FSL supports this; the schedule language is
  documented in `$FSLDIR/etc/flirtsch/`.
- Pro: native FLIRT, no post-hoc surgery
- Con: schedule files are undocumented + version-sensitive; needs
  testing across FSL 6.0.x

**Option B — `-dof 3` + post-hoc Tz=0**:
- Run `flirt -dof 3` (3-translation), then zero out the Tz component
  in the output transformation matrix before applying.
- Pro: simpler, robust across FSL versions
- Con: FLIRT still spends optimiser steps on Tz; can theoretically
  bias Tx/Ty toward an XY-Tz minimum (rare in practice for cord EPI
  where Tz has no signal anyway)

Recommendation: prototype Option B first (simpler), validate against
phase-XC + MCFLIRT-loop empirically. Switch to Option A only if Tz-
bias visible in the validation.

## Validation plan

A/B comparison on one cospine + one balgrist run:
1. Current pipeline (phase-XC Stage 1 + sct_fmri_moco Stage 2)
2. New pipeline (FLIRT-2D Stage 1 + sct_fmri_moco Stage 2)
3. MCFLIRT-3D-then-zero-Tz Stage 1 + sct_fmri_moco Stage 2 (sanity ref)

Metrics:
- tSNR_post per slice (S4's existing metric)
- FD distribution (Power 2014)
- Δ(Tx, Ty) between approaches per volume (should be ~0)
- Wall-clock per run

Acceptance: tSNR_post within 2% AND FD distribution KS-test p>0.1 vs
current → safe to switch. Predict: indistinguishable in XY; FLIRT
slower by ~30-50× but still <1 min/run total.

## Out of scope

- 6-DOF rigid with rotations: SCT Stage 2 already handles per-slice
  residuals; bulk rotation isn't worth modelling for cord.
- Replacing Stage 2: sct_fmri_moco is the cord-validated stage and
  stays.
- Iterative target updating (Armin's suggestion at SCT-P2): separate
  audit item; not in this scope.

## References

- Jenkinson & Smith 2001 *Med Image Anal* — FLIRT core algorithm
- Jenkinson et al. 2002 *NeuroImage* — MCFLIRT (FLIRT for fMRI)
- FSL FLIRT user guide — `-dof`, `-schedule` semantics
- Guizar-Sicairos et al. 2008 *Opt. Lett.* — current Stage 1 (phase-XC)
- SCT-P2 presentation vox transcript:
  `/mnt/ssd1/qai/vox/transcripts/2026/03/2026-03-30_*_SCT_P2_Presentation.md`
  (~46:00–50:00 mark)
- Parent audit: `.claude/specs/s4-algorithm-audit.md`
