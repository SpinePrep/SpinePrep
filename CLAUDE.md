# SpinalfMRIprep — Development Principles

> Distilled from fMRIPrep, BIDS-Apps, SCT, CoSpine, and the cord-fMRI
> literature. Each principle is a behaviour to check yourself against
> on any given day. When you deviate, document the reason in a
> `.claude/specs/` spec and cite the literature.

## The principles

### 1. ~~Small fixed dev cohort. Forever.~~ → Full data (retired 2026-06-16).
**Superseded.** The pipeline steps are locked; the project moved off the
small regression dev cohort and now runs **full datasets only**. The `reg`
(and `smoke`) cohorts, their `reg_*_subset` keys, and their workfolders were
removed. Production = the full per-dataset scopes (one per `intended_use:
v1_validation` dataset) + the balgrist `exp` scope.

*Historical rationale (kept for context):* during step development we used a
~10-run fixed cohort spanning the failure modes (vendor, FOV, shim, motion)
and never grew it for engineering decisions — the standard fMRIPrep/MRIQC
practice. That phase is done; principles #8 and #10 below now apply at full
scale rather than to a dev subset.

### 2. Literature-grounded defaults. Tune knobs, don't reinvent algorithms.
- Distortion correction: topup > fugue > SyN-fallback (FSL / fMRIPrep brain / CoSpine).
- Cord seg: `sct_deepseg_sc`.
- Func→anat: `sct_register_multimodal` cord-seg-driven rigid (S6 recipe).
- Template: PAM50 (De Leener 2018).
- Bandpass: Eippert 2017 (0.01–0.1 Hz).
- FD threshold: Kaptan 2023.

If you can't cite a paper for a choice, find the choice the field already made.

### 3. Each step has one step-local truth metric.
Measures the step in isolation, independent of downstream. Examples:
- S5: CoSpine cord-Dice + A–P cord-centerline displacement (Wei 2025).
- S6: per-slice cord-Dice in anat space.
- S7: PAM50 vertebral-level alignment.

"Downstream looks bad" is **never** a step-local metric.

### 4. Each step has one diagnostic reportlet.
Looking at one run's PNG should answer *what failed and why* — not just
good/bad. If you can't tell from one report, the reportlet is wrong; fix
it before adding subjects.

### 5. Visual QC is the validator. Metrics are supporting evidence.
The human eyeballs the HTML. Numbers quantify the call but don't replace
it (fMRIPrep, MRIQC, SCT, CoSpine all work this way). Don't build pure-
metric gates that the human can't sanity-check.

### 6. Lock the step. Move on.
Once metric + reportlet say OK on ≥80% of the dev cohort, the step ships
to `policy/<step>.yaml` and you stop touching it. Perpetual re-tuning is
a research-anti-pattern. Decisions need to **land**.

### 7. Don't backtrack the chain to attribute failures.
If S6 looks bad, open S6's reportlet. Don't blame S5 unless S5's own
metric is bad. Chain conflation is the #1 source of wasted weeks.

### 8. Full cohort (~250) is a release deliverable, not an engineering tool.
Run it 1–2 times in the whole project: once mid-pipeline sanity check,
once for the methods table. **Never to decide between algorithms.**

### 9. Reproducible by default.
Policy YAML versioned in git. BIDS-Derivatives compliant outputs.
Reproducibility receipt (tool versions + policy SHA + git SHA) at S10.
Anyone re-runs and gets the same numbers — this is the baseline
scientific contract.

### 10. Heterogeneity is the test, not the noise.
The 11 runs span 5 cohorts deliberately. An algorithm that PASSes on
`balgrist_motor` but FAILs on `handgrasp` tells you something real —
*that is* the data-driven signal. Treat each dataset as a separate axis
of evidence, not as a sample size to pool away.

## Meta-principle

Mimic the field's working pipelines (fMRIPrep, MRIQC, SCT). Don't invent
process; the existing patterns are battle-tested over a decade of
community use. Where SpinalfMRIprep deviates, document why in
`.claude/specs/` and cite the literature reason.

## One-line summary

**10 subjects, literature defaults, step-local metrics, visual QC, lock
and ship.** The whole pipeline runs *in your head* on one subject; the
cohort is just to convince the reviewer.

## Working conventions

- **Commits**: atomic per-feature, with the rationale in the message (the
  "why", not the "what"). Auto-commit completed verified work.
- **Specs**: under `.claude/specs/<slug>.md` with frontmatter
  `status: approved | implemented | superseded | abandoned`.
- **Policy**: per-step in `policy/<S?>_<name>.yaml`, versioned. Knobs
  documented with their literature citation in a comment.
- **Schema**: per-step in `schemas/qc_<S?>_<name>.schema.json`, kept in
  sync with the qc.json structure the step emits.
- **Run convention**: `scripts/full_chain_reg.py --start S<N>` allocates
  a fresh `wf_reg_NNN` and links upstream chain.
- **Promotion**: `python scripts/mark_done.py reg S<N> work/wf_reg_NNN
  --force` after a chain step completes.
- **Dashboards**: every step contributes to per-workfolder
  `dashboard/index.html`; S10 emits the cross-dataset release report.
