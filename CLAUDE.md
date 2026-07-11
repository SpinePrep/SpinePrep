# SpinePrep — Agent Contract

- **Server:** balgrist  ·  **qsm session:** `p2-spineprep`  ·  **Path:** `/mnt/ssd1/SpinePrep`
- **Never mix with Ahura.** `/mnt/ssd1/Ahura*` is off-limits — don't read, reference, or touch it.

## What it is

SpinePrep is a reproducible, QC-first **preprocessing pipeline for human spinal-cord
fMRI**, packaged as a containerised BIDS-App (a BIDS dataset in, GLM-ready derivatives
+ per-step quality-control reports out). It automates the field's recommended cord-fMRI
recipe end to end and is deliberately **not** a source of new algorithms — the science
belongs to the tools it integrates (Spinal Cord Toolbox / SCT, FSL, ANTs, PAM50 template).
Its contribution is the integration, automation, reproducibility, and standardised QC.

**Current state:** released and public — PyPI package `spineprep`, **v26.0.0** (CalVer),
docs at [spineprep.com](https://spineprep.com), Zenodo DOI 10.5281/zenodo.21294696. The
pipeline (steps S1–S10) is **locked and validated on 8 datasets / 384 runs**; the work
that remains is the paper. The venue pivoted to **eLife** on 2026-07-06.

## Where things live

- **Pipeline code:** `src/spineprep/` — one module per step, `S1_input_verify.py` …
  `S10_qc_aggregation_and_release.py`, plus `S0_setup.py`, `S2B_func_denoise.py`.
  `bids_app.py` is the BIDS-App loop; `cli.py` is the entrypoint.
- **Per-step policy (the tunable knobs):** `policy/<Sn>_<name>.yaml`, versioned in git,
  each knob commented with its literature citation. `policy/datasets.yaml` registers inputs.
- **QC schemas:** `schemas/qc_<Sn>_<name>.schema.json`, kept in sync with each step's `qc.json`.
- **Specs / decisions:** `.claude/specs/<slug>.md` with frontmatter
  `status: approved | implemented | superseded | abandoned`.
- **Driving docs (read at the start of every cycle, trust over chat):** `GOAL.md`,
  `DONE.md` (completion log), and `.claude/specs/v2-finalization-plan.md` (the eLife plan)
  with `.claude/specs/v2-highest-venue-claims.md` (locked claims).

## Run / test / verify

One console script, `spineprep`, does both jobs:

- **BIDS-App (production):** `spineprep <BIDS_DIR> <OUT_DIR> {participant|group}`
  — `participant` runs the per-subject chain S1..S9; `group` runs S10 (cross-subject QC
  aggregation + release report). This is also the container ENTRYPOINT (`docker build -f
  Dockerfile.spineprep …`; Apptainer for HPC — see the quickstart).
- **Per-step dev CLI:** `spineprep run <STEP> …` / `spineprep check <STEP> …` (check = no writes).
- **Tests:** `poetry run pytest -q` (or `.venv/bin/pytest`). Suite is green (242 passed,
  1 skipped as of 2026-07-06). Every behavioural change ships with a test.
- Dev setup: `poetry install --with dev`. Don't run heavy pipelines to "verify" — read
  the step's reportlet and its `qc.json`.

## Design invariants (load-bearing — keep them true)

These are the rules the whole pipeline is built on. Preserve them.

1. **Literature-grounded defaults; tune knobs, don't reinvent algorithms.** If you can't
   cite a paper for a choice, use the choice the field already made. Current defaults:
   distortion topup > fugue > SyN-fallback; cord seg `sct_deepseg_sc`; func→anat
   `sct_register_multimodal` (cord-seg-driven rigid); template PAM50 (De Leener 2018);
   bandpass 0.01–0.1 Hz (Eippert 2017); FD threshold (Kaptan 2023).
2. **One step-local truth metric per step** — measures that step in isolation, independent
   of downstream. "Downstream looks bad" is never a step-local metric.
3. **One diagnostic reportlet per step.** One run's PNG must answer *what failed and why*.
   Fix a weak reportlet before adding subjects.
4. **Visual QC is the validator; metrics are supporting evidence.** The human eyeballs the
   HTML report. Don't build pure-metric gates a human can't sanity-check.
5. **Lock the step, then move on.** Once metric + reportlet pass, ship the config to
   `policy/<step>.yaml` and stop touching it. Perpetual re-tuning is an anti-pattern.
6. **Don't backtrack the chain to attribute failures.** If S6 looks bad, open S6's
   reportlet; don't blame S5 unless S5's own metric is bad. Chain conflation wastes weeks.
7. **Reproducible by default.** Policy YAML versioned in git; BIDS-Derivatives-compliant
   outputs; a reproducibility receipt (tool versions + policy SHA + git SHA) at S10.
8. **Heterogeneity is the signal, not noise.** Datasets span vendors/FOV/shim/motion
   deliberately — treat each as a separate axis of evidence, not a pool to average away.

Where SpinePrep deviates from the established brain pipelines (fMRIPrep, MRIQC, SCT),
document why in a `.claude/specs/` spec and cite the literature reason.

## Conventions

- **Commits:** atomic per feature, with the *why* in the message. Auto-commit verified work.
- **Claims discipline:** the paper's locked claims live in the v2 specs; **never ship a
  claim above its evidence** — reword the claim or do the work, never stretch the numbers.

> Note: the old small-cohort dev workflow (`reg`/`smoke` cohorts, `wf_reg_NNN` workfolders,
> `scripts/full_chain_reg.py`, `scripts/mark_done.py reg …`) was **retired 2026-06-16**.
> The project runs full per-dataset scopes only; those scripts are legacy, not the workflow.
