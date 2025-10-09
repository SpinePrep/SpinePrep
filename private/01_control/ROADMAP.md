# SpinePrep — ROADMAP.md

**Owner:** CEO
**Mode:** Single CEO, multiple arch/dev pairs, **one active ticket per architect**
**Repository:** Public, under development, not searchable
**License:** Apache-2.0

---

## 0) Objectives

**Primary goal:** Ship a minimal, analysis-agnostic spinal cord fMRI preprocessing pipeline with transparent QC and reproducible containers, then validate across heterogeneous datasets and prepare a high-impact submission.

**Success criteria (global):**

* ≥95% subject-run completion across internal datasets.
* CI: green on lint/tests/docs and tiny E2E run; containers pinned by digest.
* QC: per-subject HTML with overlays, metrics, and environment snapshot.
* Validation: improved vertebral-level alignment metrics, higher task detection, and solid rest test–retest reliability on external data.
* One-command BIDS-App UX.

---

## 1) Phases and timelines

### Phase A — MVP pipeline (Weeks 1–4)

**Outcome:** Minimal pipeline runs end-to-end with QC and containers.

**Scope (minimal defaults):**

1. Ingest & validate BIDS (manifest, warnings).
2. Motion reference & metrics (FD, DVARS).
3. Segmentation & masks (cord ± CSF) via SCT; EPISeg when available.
4. Coregistration & template normalization via SCT templates.
5. Single spatial resampling (compose transforms).
6. Basic confounds (motion, aCompCor, scrubbing masks).
7. Derivatives & provenance (BIDS-Derivatives, logs, transforms, config snapshot).
8. QC HTML (overlays, metrics, env report).
   *Note:* SDC is **conditional** via explicit flags when prerequisites exist.

**Deliverables:**

* `spineprep` CLI (`run`, `doctor`, `version`)
* Docker/Singularity images with pinned environment and SCT
* MkDocs site (public), `noindex` until stable tag
* Tiny dataset for CI E2E smoke

**Acceptance (exit gates):**

* ≥95% success on internal datasets (11 squeeze, 18 hand, 30 tapping).
* CI: ruff, snakefmt, codespell, mypy (core), pytest, mkdocs strict, tiny E2E.
* QC HTML present for every subject; required tables/plots render.

**Risks & mitigations:**

* Env variance → container first, `doctor` preflight, optional auto-install of tested SCT.
* Registration brittleness → conservative defaults; numeric gates + overlays.

---

### Phase B — Validation & evidence (Weeks 5–10)

**Outcome:** Compelling, minimal evidence set across multiple datasets.

**Datasets:**

* **Internal:** 3 cervical task sets (total n=59).
* **External:** ≥3 open datasets (mix of rest test–retest, at least one with reverse-PE, one brain+cord). IDs recorded in public docs.

**Metrics & figures (script-generated):**

1. Geometry: per-level EPI→template alignment error (mm), dataset-wise and pooled.
2. Temporal: tSNR distributions in cervical ROIs; FD/DVARS summaries.
3. Task sensitivity: cluster overlap and peak Z in expected segments.
4. Reliability: rest test–retest ICC in cervical ROIs (where available).

**Ablations (max 2):**

* Registration strategy A vs B (as implemented).
* With vs without SDC on reverse-PE subsets.

**Deliverables:**

* Reproducible analysis scripts that emit tables/figures and a methods note.
* Public validation page summarizing datasets, metrics, and results.

**Acceptance (exit gates):**

* Evidence shows improved alignment and task sensitivity; reliability in acceptable range on rest.
* All figures/tables reproducible via one entry-point script.

**Risks & mitigations:**

* Heterogeneous protocols → parameterize inputs; fail fast on incompatibles.
* Limited physio logs → rely on aCompCor baseline; transparently report availability.

---

### Phase C — Hardening & release (Weeks 11–16)

**Outcome:** Stable tagged release suitable for high-impact submission.

**Scope:**

* Coverage ≥85%; performance profiling and caching improvements.
* Finalize containers with digests; provenance labels complete.
* Docs polish; remove `noindex` at stable tag; citation boilerplate available.
* Prepare submission package (figures, methods, data availability).

**Deliverables:**

* Stable tag (v0.9.x or v1.0.0 per readiness).
* GHCR images, versioned docs, release notes, sample datasets index.

**Acceptance (exit gates):**

* Byte-stable tiny E2E run; deterministic figure regeneration.
* Compatibility matrix published (Python, SCT, OS, container digests).

**Risks & mitigations:**

* CI runtime sprawl → tiny dataset + cache; matrix kept minimal.
* Regressions near tag → freeze window; ticket freeze except critical fixes.

---

## 2) Milestones (date placeholders)

* **M1 (End Week 2):** CLI skeleton + `doctor`; Snakemake DAG dry run; initial QC scaffold.
* **M2 (End Week 4):** Phase A acceptance met; containers published (pre-release).
* **M3 (End Week 8):** External datasets processed; draft figures for geometry/temporal/task/reliability.
* **M4 (End Week 10):** Phase B acceptance met; ablations complete.
* **M5 (End Week 14):** Coverage ≥85%, perf pass, docs polish.
* **M6 (End Week 16):** Stable tag + submission package.

*Publishing rhythm:* ISMRM abstract by **~Week 4–5**; Nature Methods submission by **~Week 16**.

---

## 3) Execution rules

* **Concurrency:** Max one active ticket **per architect**.
* **Ticket size:** ≲200 LOC unless labeled `big-change`.
* **Definition of Done:** CI green, tests/docs updated, tiny E2E reproducible.
* **Evidence discipline:** Figures/tables generated by scripts with pinned inputs.
* **Documentation discipline:** Public docs never reference `/private`.

---

## 4) Future work (off the critical path)

* Advanced motion strategies; extended SDC strategies; DL-based steps.
* Thoracic/lumbar extensions; richer physio modeling; anisotropic/centerline smoothing.
* Deeper brain+cord harmonization.

(Defer to post-submission milestones; each proposed item requires evidence and a dedicated ticket.)

---

## 5) Dependencies & compatibility

* **Runtime:** Python 3.11; Snakemake; Ubuntu 22.04/24.04 runners.
* **Core external:** Spinal Cord Toolbox (SCT) with standard templates (e.g., PAM50).
* **Containers:** Docker/Singularity/Apptainer; images pinned by digest.
* **CI:** GitHub Actions.

---

## 6) Acceptance checklist (per phase)

* **A:** 95%+ completion on internal, QC present, CI green, containers built.
* **B:** Multi-dataset metrics improved; ablations complete; reproducible figures.
* **C:** Coverage ≥85%; stable tag; docs versioned; submission assets built.

---

*This roadmap is locked. Changes require an architect decision recorded in public docs (non-private) and enforced via tickets.*

