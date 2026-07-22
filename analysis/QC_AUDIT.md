# SpinePrep cohort QC audit — end to end

Full-cohort verification of the crop-fix cohort at `/mnt/ssd1/spineprep_cohort_s2`
(9 datasets, 469 runs entering S3, 450 completing S9). Every number below was
read from the cohort's own qc.json / derivatives in this session. Recorded
2026-07-22.

Verdict: the preprocessed output is reliable and honest. The audit found three
real bugs in the QC/reporting layer (not the derivatives), fixed all three, and
confirmed every other axis is clean.

## Bugs found and fixed during the audit

1. **S1 branded 46 complete files as truncated (false corruption claim).** The
   truncation probe expected header+voxels and flagged any gzip-trailer
   mismatch, but a NIfTI header extension makes a COMPLETE file legitimately
   larger. It failed the whole internal_balgrist_motor_11 dataset with a false
   "incomplete download" claim, even though every file loads with all volumes.
   Fixed: an ISIZE mismatch now falls back to streaming the decompression, which
   a truncated gzip cannot survive but a complete one (extension or not) does.
   Verified: motor_11 now PASS (409/409 files); genuinely-truncated ds005883
   sub-22 still FAIL. (commits cb0115e, 2dfec0d)

2. **S1 reported FAIL with a null reason.** A dataset failing solely on a
   per-run truncation carried no failure_message, because the summariser only
   scanned dataset-level checks. It now surfaces the failing run's own issue --
   an unexplained FAIL is itself a QC-honesty failure. (commit cb0115e)

3. **S10 crashed the release on a null inclusion threshold.** The policy disables
   the FD gate with a null value; `float(dict.get(key, default))` returns None
   for a present-but-null key, so the whole group release failed even though all
   450 runs passed. Fixed: null means disabled, missing means default. (commit
   149d193)

## Axes verified clean

| axis | result |
|---|---|
| Attrition | 469 -> 468 -> 467 -> 464 -> 458 -> 450, monotone; every drop equals a prior-step FAIL (1+1+3+6+8=19). Fully reconciled. |
| Status integrity | After fix 1, all S1 statuses honest: 6 PASS, 2 WARN (subject-selection advisories, reasons given), 1 FAIL (ds005883 sub-22, genuinely truncated, reason given). |
| tSNR | 450 runs, median 18.4, range 7.0-29.8. All physical for 3T cord fMRI; no zeros, no placeholders. |
| Motion (FD) | mean_fd median 0.54 mm; 3 MotionPain runs peak >40 mm max_fd but PASS -- consistent with the design decision that FD is descriptive, not a gate (frames censored downstream). |
| FWHM | measured = None for all 450 (smoothing off by default); requested kernel recorded. The recent "stop reporting unmeasured FWHM as zero" fix is working -- honest None, not a fabricated 0. |
| CSF confounds | 12 runs have CSF columns = slices x 5 minus 1: on one thin-CSF slice each, S8 extracted 4 components instead of fabricating a 5th. The "stop fabricating CSF on unacquired slices" fix is working. |
| Confound rank | design_rank_deficit reported for 35/450 (7.8%, matches the documented ~8.7%); emitted, not silently regressed. |
| Registration | cord Dice median 0.92; the 2 runs with Dice 0.0 are correctly FAIL, not silent PASS. |
| Distortion | 81 topup (measured-field) runs, 386 `none` passthrough correctly WARN'd ("measured, not corrected"), 3 genuine quality flags. Honest. |
| Sidecar TR | all 450 carry the real TR (1.55-3.26 s, 8 distinct); zero at the 1.0 s header placeholder; none missing. |
| Derivative integrity | all 450 PASS runs have preproc BOLD + confounds + cord mask present and non-empty. |
| Reproducibility receipt | present and current: git SHA = HEAD, SCT 7.1, FSL 6.0.7.15, ANTs, MRtrix 3.0.4, per-step policy SHA-256. |

## Open item (tooling, not data)

Schema drift, `schemas/qc_*.schema.json` vs the emitted qc.json:
- S3 schema requires `failure_class`, which the step no longer emits (9/9 fail
  validation on a field that is absent by design).
- S4: one ds005883 run record missing `step_code`.
- S1 and S8 have no schema file at all.

These are validation-tooling gaps -- the contract asks schemas to track each
step's output. They do not affect the correctness or honesty of the derivatives.
Recommend regenerating the S3 schema and adding S1/S8 schemas before the paper's
methods claim schema-validated QC.
