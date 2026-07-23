# Postprocessing plan — against `preproc-v1`

Preprocessing is locked at git `961a779` (`PREPROC_LOCK.md`). Everything below
reads that cohort and must not modify it.

## Status: what is already computed

The analysis in `analysis/RESULTS.md` was run at 13:09 on 2026-07-22 against
derivatives whose newest input is 13:00 the same day. Every change since then was
reportlets/dashboard only, which the analysis does not read. **These results are
already the locked-cohort results and do not need recomputing.**

| candidate | status | where |
|---|---|---|
| Q1 reliability vs spatial scale | DONE — monotone decline, replicated | `RESULTS.md` |
| Q2 tSNR envelope | DONE — 16.4 to 25.4 across datasets | `RESULTS.md` |
| C3 biological validity | DONE — laterality strong, dorsal/ventral NULL | `RESULTS.md` |
| C5 confound importance | PARTIAL — 28 of 324 task runs | `confound_benchmark.csv` |
| C4 distortion falsification | **NOT RUN** — needs a second correction mode | empty |

## The work that remains

### 1. C4 distortion falsification — the only missing result

Correct the CoSpine reversed-PE runs a second way (SyN, pretending no fieldmap)
and compare against the measured TopUp field. The statistic is implemented and
unit-tested (`analysis/distortion.py`); only the data is missing.

**Isolation is mandatory.** S5's `--reportlets-only` reruns the pipeline and
rewrites corrected BOLD; running SyN inside the locked cohort would overwrite
outputs S6-S9 already consumed. So:

    OUT=/mnt/ssd1/spineprep_c4_syn      # a SEPARATE output root
    # force distortion_correction.mode = syn via a policy overlay
    spineprep run S5_func_distortion_correction \
        --dataset-key openneuro_ds005883_cospine_pain --out $OUT ...
    # then: analysis/distortion.py compare_cohort(locked_topup_qc, syn_qc)

Scope: 82 runs (38 pain + 44 motor). Cost: SyN is ANTs registration per run,
roughly 2-5 min each, so **3-7 hours**. This is the expensive item.
Output: `distortion.csv` + the F7 fidelity figure.

### 2. C5 confound benchmark at full scale

Currently 4 runs per dataset (28 total) because it refits 7 designs per run. The
Pareto result is already clear and consistent, but a headline claim wants the
full task cohort.

Scope: 7 designs x 324 task runs = 2268 GLM fits. Cost: **2-3 hours** under
`batch`. Cheap relative to C4 because it reads existing confounds, no re-runs.

### 3. Regenerate figures + results tables

`python3 -m analysis.run_all <locked cohort>` then `python3 -m analysis.figures`.
Only needed after 1 and 2 land, to fold their outputs into F7/F8.

## Order

1. Launch C5 full-scale (cheap, no risk, runs unattended)
2. Launch C4 SyN in an isolated output root (expensive, the long pole)
3. Re-run `run_all` + `figures` once both land
4. Update `RESULTS.md`, then the manuscript numbers

1 and 2 are independent and can run concurrently.

## What will NOT be done

- No re-running of S1-S10 on the locked cohort.
- No optimisation of preprocessing against these endpoints. Choosing a config by
  a metric and then reporting that metric on the same cohort is double dipping
  (Kriegeskorte 2009). The design space is CHARACTERISED, never tuned.
