---
status: implemented
---

# S1 input verify — algorithm audit (all axes)

Date: 2026-07-14. Audit of S1 against standard / generalized / truthful /
correct / rigorous / reliable / complete, cross-checked against the code and the
real behaviour on the 9-dataset cohort. Companion to the principles audit
`s1-input-verify.md`.

## Verdict

Structure is sound (correct BIDS sidecar-inheritance walk, NIfTI header sanity,
worst-of severity aggregation, no bogus tuning knobs). Four findings; F1–F3
fixed this pass, F4 documented.

## What is solid (keep)
- **BIDS sidecar inheritance** (`_read_bold_sidecar`) — walks parent dirs and
  strips `sub-`/`ses-` entities so a root-level `task-rest_bold.json` applies to
  all runs. General and correct.
- **NIfTI header sanity** — exists, 4D with >1 volume for BOLD, finite affine,
  finite pixdim, qform/sform set. Correct.
- **Severity aggregation** (worst of all checks) and **no `policy/S1.yaml`**
  (BIDS checks aren't tuning knobs) — right.
- **Not shelling to bids-validator** — defensible (real derivatives-support gap).

## Findings

### F1 — "cord-specific classification" was overstated (truthfulness) — FIXED
`_classify_path` labels EVERY `func/` `_bold.nii(.gz)` as `cord_likely`; there is
no cord-vs-brain logic. Brain-shim runs get the same label; cord-vs-not is really
decided at S3 (localization fails on brain-only runs). The spec's claim that S1
does "cord-specific classification bids-validator doesn't compute" was the stated
reason for rolling its own checks — reworded honestly in `s1-input-verify.md`.

### F2 — S1 silently dropped T2*/MEGRE/PSIR/MP2RAGE anat (correctness) — FIXED
`_classify_path` recognised only `t1w`/`t2w` anat. Verified: on balgrist_painmotor
(MEGRE) **336 T2star files were invisible** — S1 counted 21 anat when there are
357. It PASSed only because T1w coexisted; a T2*-only dataset would get a false
"no anat" WARN, and the inventory/reportlet undercount anat on a pipeline whose
S2 explicitly uses T2*/MEGRE. Fix: any NIfTI under `anat/` is anatomical (the
BIDS rule). Re-verified: n_anat_runs 21 → 357.

### F3 — missing pre-flight checks broke downstream silently (completeness) — FIXED
S1 read `RepetitionTime`, `PhaseEncodingDirection`, `TotalReadoutTime` into the
inventory but never checked they exist. A BOLD with no TR, or an fmap with no
PE-direction/readout, passed S1 clean then failed at S5/topup or later. Added
`_apply_acquisition_metadata_checks`: WARN when a cord fMRI run lacks
RepetitionTime, or a fieldmap lacks PhaseEncodingDirection/TotalReadoutTime
(needed for FSL topup acqparams). WARN not FAIL — a fallback path (S5 SyN) may
still apply. (1-volume "4D" BOLD was already a FAIL in `_validate_nifti`.)

### F4 — a hard-coded dataset hack (generalization) — DOCUMENTED, not changed
`_is_selected` normalises subject IDs with `f"ZS{raw.zfill(3)}"` — the cospine
datasets' specific prefix baked into general code (their policy lists `ZS001`
for a subject the disk names `01`). Removing it now would break cospine subset
selection; it needs the policy subject IDs normalised to the on-disk IDs first.
Clean up when cospine subject naming is normalised; until then it is a known,
localized wart.

## Real-data grounding (cohort, current build)
- 9/9 datasets inventoried and PASS.
- painmotor anat inventory corrected 21 → 357 (T2*/MEGRE now visible).
- New `bold_repetition_time_present` check present in qc.json.

## Deferred (acceptable)
- A genuine cord-likelihood heuristic (FOV/coverage from header) instead of
  "any func BOLD" — only worth it if a dataset mixes brain-only and cord BOLD in
  one `func/`; today S3 catches that. Defer.
- bids-validator pre-flight once its derivatives support lands.
