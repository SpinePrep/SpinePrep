---
status: approved
created: 2026-07-01
locks: the task list to make SpinalfMRIprep runnable end-to-end on arbitrary new
  BIDS datasets by an external user (not our fixed cohort)
---

# SpinalfMRIprep — Production Readiness for New Datasets

Goal: a new user points the BIDS-App at *their* cervical cord-fMRI BIDS dataset and
gets GLM-ready BIDS-Derivatives + QC reports, reproducibly, without our per-dataset
hand-tuning. Audited against the code 2026-07-01.

## Already works (verified) — do NOT redo

- BIDS-App entrypoint `spinalfmriprep <bids> <out> {participant,group}`; `--participant-label`.
- S5 auto-selects TopUp vs SyN from PhaseEncodingDirection metadata — no per-dataset config.
- QC thresholds in policy/S*.yaml are literature-grounded GENERIC values, not cohort-tuned.
- S2 reorients arbitrary input to RPI (`sct_image -setorient`).
- No step branches on dataset name; contrast-agnostic cord seg (sct_deepseg).
- S1 tolerates unregistered datasets (policy_entry=None); RETROICOR/physio skips gracefully when absent.

---

## Tier 0 — BLOCKERS (without these it does not run portably on new data)

- **T0.1 — Build + verify the container end-to-end. ✅ DONE (2026-07-02, commit
  613f98c).** Image `spinalfmriprep:7.1` (15.4 GB) built and run through a full
  S1→S10 chain on a real subject via the BIDS-App interface (participant + group);
  produces complete BIDS-Derivatives + QC reports + reproducibility receipt.
  Fixed 8 real portability/packaging bugs the host suite could not catch
  (.dockerignore; gcc/g++/make; install_sct headless GUI self-check; ImageMagick
  + fonts; COPY config/; f-string SyntaxError on py<3.12; moco schedule path;
  S5 ANTs-via-docker → local isct_ binaries; S8 cord-mask BIDS-App runs/ layout).
  Container moco reproduced the host result exactly (no numerical drift).
  **Follow-ups discovered:**
  - *Receipt gap:* `pipeline_git_sha`/`git_describe` are null in the container
    (no repo, only installed package). Bake the git SHA into the image at build
    (ENV/version file) so the reproducibility receipt stamps the pipeline version.
  - *Publish the image* (registry push) — currently local only; ties to release.
  - *Pre-existing unrelated test failure* (NOT from this work):
    `test_activation_task_regressor_recovers_signal` — `reliability_activation.
    _task_regressor` returns None (nilearn design-matrix path). Affects the paper's
    task-activation validation (V2); fix separately.
- **T0.2 — Also ship an Apptainer/Singularity image.** HPC clusters (where most new
  users run) forbid Docker. Apptainer is present on this host; convert the working
  Docker image (`apptainer build spinalfmriprep.sif docker-daemon://spinalfmriprep:7.1`)
  and run the same one-subject chain to verify. **← next**
- **T0.3 — Real input validation with actionable errors.** `--skip-bids-validator`
  is currently a no-op. Wrap the BIDS validator (or a documented lightweight
  structural check) so a malformed dataset fails fast with a clear message, not a
  mid-chain crash.

## Tier 1 — CORRECTNESS on unseen data (runs, but may mislead)

- **T1.1 — Auto-derive the dataset spec from the data for ad-hoc runs.** With
  policy_entry=None, S1 skips fmap/physio expectation checks. Detect has_fmap,
  has_physio, domains, tasks, and modalities from the dataset itself so validation
  guardrails work without a registered policy entry.
- **T1.2 — Data-envelope detection + honest WARN.** Validated on CERVICAL (+one
  whole-CNS) FOV. Detect and warn (not silently mis-process) when input is
  thoracic/lumbar-only, brain-only, non-3T, non-EPI, or a FOV/vertebral range PAM50
  registration handles poorly. Document the supported envelope explicitly.
- **T1.3 — Verify the S2 reorientation path on non-RPI input.** register.py:163 uses
  a fragile substring/regex check (`"orientation.*RPI" in output`) to decide whether
  to reorient — likely always- or never-true. Test on a genuinely LAS/LPI dataset;
  fix so reorientation actually triggers when needed.
- **T1.4 — Per-subject failure isolation.** Confirm/ensure one subject's failure
  (missing anat, unusable cord, single-volume func, odd TR) is caught, logged, and
  SKIPPED — the batch must continue and report, never abort. Essential for
  unattended runs on messy real data.

## Tier 2 — ROBUSTNESS / USABILITY

- **T2.1 — Full-chain integration test on a SYNTHETIC new dataset (S1→S10).** Current
  test_bids_app covers only ad-hoc S1. Add a tiny synthetic BIDS tree that exercises
  the whole chain + group level, as a regression guard for portability.
- **T2.2 — Surface key parameters as documented CLI/config overrides.** Smoothing σ,
  QC thresholds, distortion mode override, cord-level range — tunable without editing
  policy YAML. Ship reliability-optimal defaults (from the §A study).
- **T2.3 — Machine-readable run summary + exit codes.** Emit a per-subject
  pass/fail/skip manifest (JSON) and meaningful exit codes so the app composes into
  other pipelines.
- **T2.4 — Output BIDS-Derivatives compliance check.** Confirm derivatives validate
  as BIDS-Derivatives (naming, dataset_description, spaces) for interoperability.
- **T2.5 — Resource + runtime guidance.** Document memory, disk, GPU flag
  (SCT_USE_GPU), and per-subject wall-clock; fail clearly on insufficient resources.

## Tier 3 — POLISH / TRUST

- **T3.1 — User docs for external runs.** Install (container pull), invocation,
  supported-data envelope, how to read the QC report, troubleshooting/FAQ. Extend the
  existing quickstart/tutorial from our-cohort framing to any-dataset framing.
- **T3.2 — Ship a tiny public reference dataset + expected QC.** Lets a user verify
  their install reproduces known-good outputs (install smoke test).
- **T3.3 — Cross-environment reproducibility check.** Confirm the receipt (tool
  versions, policy SHA, git SHA) + container yields identical results on a second
  machine.

## Definition of done

An external user, on their own cluster, can `apptainer run` the image on their BIDS
dataset, get validated BIDS-Derivatives + QC reports with correct PASS/WARN/FAIL
calls, have bad subjects skipped-and-reported rather than crashing the run, and
verify their install against a reference dataset. Tiers 0–1 are mandatory for that
claim; Tiers 2–3 make it trustworthy and pleasant.
