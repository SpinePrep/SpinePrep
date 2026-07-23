# Preprocessing lock — `preproc-v1`

Preprocessing is **frozen** as of git `961a779` (clean tree). Steps S1–S10 and the
cohort at `/mnt/ssd1/spineprep_cohort_s2` are the locked baseline; all downstream
analysis reads from this state and nothing in S1–S10 changes without unlocking.

Machine-readable companion: `PREPROC_LOCK.json` (policy hashes, per-step tallies,
tool versions). Re-run the generator and diff it to detect drift.

## What is locked

| item | locked value |
|---|---|
| Code | git `961a779`, working tree clean |
| Cohort | `/mnt/ssd1/spineprep_cohort_s2` |
| Policy | 12 YAML files, SHA-256 recorded per file |
| Tools | SCT 7.1, FSL 6.0.7.15, MRtrix 3.0.4, ANTs (SCT-bundled), Python 3.12.3 |
| Receipt | `derivatives/spineprep/reproducibility_receipt.json`, git SHA matches HEAD |

## Cohort state at lock

| step | runs | PASS | WARN | FAIL | reportlets |
|---|---|---|---|---|---|
| S1 input verify | 9 (datasets) | 6 | 2 | 1 | – |
| S2 anat cordref | 310 | 300 | 9 | 1 | 1545 |
| S3 init + crop | 469 | 468 | 0 | 1 | 2469 |
| S4 motion correction | 468 | 466 | 1 | 1 | 1401 |
| S5 distortion correction | 467 | 73 | 391 | 3 | 243 |
| S6 func→anat | 464 | 390 | 68 | 6 | 928 |
| S7 template norm | 458 | 384 | 66 | 8 | 912 |
| S8 confounds | 450 | 450 | 0 | 0 | 2250 |
| S9 derivatives | 450 | 450 | 0 | 0 | 900 |
| S10 release | – | PASS | – | – | – |

**Attrition** 469 → 450, monotone, every drop traced to a prior-step FAIL
(1+1+3+6+8 = 19). **450 runs complete S9.**

Reading the non-PASS counts: S5's 391 WARN are overwhelmingly the honest
`mode=none` passthrough flag (386 runs have no fieldmap, so distortion is
measured and reported but not corrected). S1's one FAIL is ds005883 sub-22, a
genuinely truncated download, correctly excluded.

## Known-good properties verified before locking

- Every referenced reportlet exists; **zero missing images** across the dashboard.
- Reportlets render **actual voxels** (no interpolating resample anywhere).
- S4 tSNR shows the mean EPI with tSNR overlaid only inside the cord.
- S5 ships reportlets **only** for the 81 runs where a correction actually ran.
- No fabricated values: unmeasured FWHM is `None` not `0`; CSF components are not
  invented on thin slices; every run carries its real sidecar TR.
- Reproducibility receipt present and current.

Full audit: `analysis/QC_AUDIT.md`.

## Carried forward as known limitations (not blockers)

1. `--reportlets-only` on S5 reruns the whole pipeline and rewrites corrected
   BOLD that S6–S9 consumed. Do not use it on the locked cohort; regenerate S5
   figures only by unlocking deliberately.
2. `dashboard/reportlets/S8_...pre_csffix/` is a pre-fix backup served as a live
   dashboard section, linked from the index.
3. Schema drift: S3's schema requires a `failure_class` the step no longer emits;
   S1 and S8 have no schema file.
4. `policy/S5_func_distortion_correction.yaml.heldout_bak` sits beside the active
   policy; it is not loaded, but it is not the locked config either.

## Unlocking

Locking is a discipline, not a file permission. To change a step: state why in a
`.claude/specs/` entry, make the change, re-run the affected steps, regenerate
`PREPROC_LOCK.json`, and bump `lock_version`. A cohort whose lock manifest does
not reproduce is not the locked cohort.
