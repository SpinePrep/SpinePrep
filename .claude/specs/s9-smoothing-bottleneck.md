---
status: characterized
---

# Spec: S9 cord-smoothing bottleneck + restart stall

> **Resolution (2026-06-23): NOT an algorithm defect.** A single S9 run in
> isolation smooths in **14.9 s** (instrumented probe on a real ds004926 run,
> 34×33×15×176). The historical "0 runs in 112 min" was **stale-process cache
> contention** — leftover workers from an externally-killed chain holding the
> machine — plus, on a shared lab server, other users' jobs (antsRegistration,
> mri_segreg, svc-* services) competing for cores. On a clean machine S9
> parallelizes fine: ds004926 (66 runs, small PAM50 grid) finished in ~3 min
> (33 runs in the first 75 s). What remains is a *real, non-bug* cost on
> large-grid datasets — see "Genuine cost" below. Both datasets now complete
> S9→S11 (2026-06-23 run). Keep this spec as the reference for why S9 looks
> slow and what is/isn't worth optimizing.

## Genuine cost (not a bug): PAM50 4D emission on large grids

The expensive part of S9 is NOT the cord-aware *smoothing* (the straighten-once
batched path is ~15 s/run). It is the **PAM50-space 4D emission**: one
`sct_apply_transfo` (spline) per emitted 4D, warping every volume to the PAM50
cord-FOV grid. Cost scales with `n_volumes × n_PAM50_slices × 2`
(smoothed + unsmoothed, policy `emit_unsmoothed: true`):
- **ds004926** (dorsal-horn): 176 vol × 175-slice PAM50 grid → fast (~seconds).
- **ds005075** (brain+spine): 261 vol × **286**-slice grid → ~4-5 min of
  single-threaded CPU **per apply**, ×2 outputs ≈ ~10 min/run. Measured: one
  apply accumulated 100% CPU for 4+ min and was still going (working, not hung).
  27 runs at ~10 min/run, 6-wide ≈ ~40 min total. Slow but correct.

If this ever needs to be faster (it currently does not — it runs ~once per
release), the lever is the PAM50 emission, not the smoother: skip the
`desc-unsmoothed` PAM50 4D when not needed, or vectorize the per-volume warp
(load the displacement field once, apply to all T volumes via
`scipy.ndimage.map_coordinates`) instead of N sequential ANTs spawns.

---

# Original report (2026-06-22) — kept for context

Discovered while running the v1_validation chain on the two new datasets
(ds005075 brain+cord rest, ds004926 dorsal-horn pain) on 2026-06-22. S9
(`S9_primary_functional_derivatives`, cord-aware smoothing → PAM50 GLM-ready
outputs) is the one step that did NOT complete reliably at the time — now
explained above.

## Symptoms (evidence)

- **ds004926 (te40, 66 runs at S8, 160 vols/run):** S9 re-run via
  `full_chain_reg.py --start S9 --stop S11 --batch-workers {3,10}` produced
  **0 completed `desc-preproc_bold` in ~112 min** wall-clock, repeatedly. ANTs
  (`isct_antsApplyTransforms`) shows ~90% CPU intermittently (it IS computing),
  but runs never finish and worker parallelism collapses (10 workers → ~1 busy,
  load attributable to SCT ~0; machine otherwise idle).
- **ds005075 (rest, 30 runs):** S9 completed only **16/30** in the original
  continuous run (the rest FAIL/dropped), so this is not unique to ds004926.
- The ORIGINAL continuous chain (S1→…→S9 in one orchestrator invocation) DID
  produce ~32 runs' worth of S9 output for ds004926 before the whole chain was
  externally killed (a session/cgroup cleanup, ~10:27). Every subsequent
  `--start S9` restart stalled near zero. So there may be a difference between
  the continuous-chain S9 and the `--start S9` resumed S9 (chain-linking of S8
  inputs, or accumulated state).

## Likely causes (to investigate)

1. **Per-volume cord straightening is intrinsically expensive.** `sct_cord`
   (default) → `_run_sct_smooth_batched` straightens once then applies the warp
   to each of N volumes; the legacy `sct_cord_pervolume` straightens every
   volume. On 160-volume runs this is ~hundreds of ANTs applies/run. The policy
   comment estimates "200 vol ≈ 10 min", but observed throughput is far worse
   here. Confirm which path actually runs and time a single run in isolation.
2. **Worker contention / shared-state.** With batch-workers>1, S9 workers appear
   to serialize (10 workers, ~1 effectively busy). Suspect a shared temp/cache
   (e.g. `straightening.cache` / a shared `smooth_batched` work dir) or a lock.
   The cwd-isolation that `lib/run.run_command` provides for SCT may not cover
   the batched-smoothing temp dirs. A stale-process incident (leftover workers
   from the killed run holding the cache) made an earlier restart hang at 0% CPU
   until cleaned — points at shared straightening state.
3. **`--start S9` resume linking.** The resumed S9 may not see S8 inputs the way
   the continuous chain did; verify the linked `runs/`, `derivatives/`, and
   funccrop/moco inputs resolve for every run on resume.

## Suggested fixes (next task)

- Time ONE ds004926 run through `_run_sct_smooth_batched` in isolation
  (`sct_cord`), instrument the straighten-once vs per-volume-apply split, and
  confirm the ~10 min/run target — or find where it blows up.
- Make the batched smoothing fully per-run isolated (unique temp/cache dir per
  run, no shared `straightening.cache`); re-test batch-workers=8–10.
- Consider an alternative that avoids cord straightening entirely for the
  smoothed GLM-ready output: smooth in PAM50 space (already have the warps) or
  use `gaussian_inplane` (policy already supports it) as a fast fallback for
  long 4D series, gated by run length.
- Fix `--start S9` resume so a partial S9 can continue without redoing runs.

## Current cohort state (2026-06-23)

- ds005075: full S1→S11 ran once. The 14/30 attrition on this dataset was
  **root-caused to S5 distortion, not S6 registration** — whole-CNS (brain+cord)
  acquisition with no reverse-PE fieldmap → image-based SyN fallback can't reach
  TopUp quality, and the lung-adjacent lower cord (C6-T2) is uncorrectable. Fixed
  at S5 (commit 3a360d5): cervical-bounded cord ROI + mode-aware distortion-
  limited flag. **Re-ran S5 on ds005075 (wf_brainspine_014): 14 FAIL → 1 FAIL**
  (26 WARN distortion-limited, 3 PASS; the lone FAIL is sub-A034, cord Dice 0.28
  = genuine registration failure). `done/brainspine/S5` now points at the new
  workfolder.
  - **PENDING:** S6→S11 still point at workfolders built on the OLD S5, so the 13
    newly-rescued WARN runs have not yet flowed downstream (old S6 cohort was the
    ~16 surviving runs). Re-running S6→S11 to propagate them is gated on the S9
    defect below. Do it as part of the single full-cohort release run, not a
    standalone churn (principle #8).
- ds004926: S1→S8 complete, **RETROICOR validated** (te40 + integrated physio;
  16 regressors/run). S9 NOT complete — blocked by this defect. S11 not run.
- Related finding: S6 func→anat registration robustness on large/whole-CNS FOV
  is a separate weak point (per-step attrition 80→66 at S6 for ds004926); do not
  conflate it with the ds005075 S5 distortion issue now fixed above.
