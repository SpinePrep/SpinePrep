# SpinePrep — BLUEPRINT.md

**Owner:** CEO (single human)
**Architects:** ChatGPT (Architect Designer), multiple pairs allowed with devs
**Developers:** Cursor sessions (Senior Developers)
**Default runtime:** Python 3.11, Snakemake, Ubuntu 22.04/24.04 runners
**Repository:** Public, under development, not searchable
**License:** Apache-2.0

---

## 1) Product north star

SpinePrep is a spinal cord fMRI preprocessing pipeline that produces BIDS-Derivatives, transparent QC, and reproducible outputs. It is analysis-agnostic and minimal by default, with advanced options gated by evidence.

**Non-goals (MVP):** GUI, analytics/telemetry, bespoke distortion hacks without prerequisites, public search indexing before first stable tag.

---

## 2) Governance and workflow

* CEO controls scope, merges, releases.
* Multiple architect/developer pairs may exist, and **each pair runs exactly 1 ticket at a time**.
* Main-only until v1.0; after v1.0 use short-lived PRs with protections.
* **Definition of Done (per ticket):** CI green, tests updated, docs updated, reproducible tiny-dataset run, changelog if user-facing.

**RACI:** Responsible = Developer, Accountable = CEO, Consulted = Architect, Informed = Repo watchers.

---

## 3) Architecture (MVP scope)

### Minimal default stages

1. **Ingest & validate**: BIDS validation; emit manifest and warnings.
2. **Motion reference & metrics**: robust BOLD reference; compute FD and DVARS.
3. **Segmentation & masks**: cord (± CSF) via SCT; EPISeg may be used when available.
4. **Coregistration & template normalization**: to standard spinal templates via SCT.
5. **Single spatial resampling**: compose all transforms and write once.
6. **Basic confounds**: motion columns, aCompCor from masks, scrubbing masks.
7. **Derivatives & provenance**: BIDS-Derivatives, logs, transforms, config snapshot.
8. **QC HTML**: overlays, per-level/summary metrics, warnings, environment report.

> **Susceptibility distortion correction (SDC) is conditional**, not default: enabled only when prerequisites exist (e.g., reverse-PE/fieldmaps) and controlled by explicit flags.

### CLI

* `spineprep run --bids <DIR> --out <DIR> [--config <YAML>]`
* `spineprep doctor` (environment and data prerequisites)
* `spineprep version`
* **Config precedence:** CLI > YAML > defaults. `--print-config` supported.

### Dependencies

* Spinal Cord Toolbox (SCT) and standard spinal templates (e.g., PAM50).
* Python deps pinned; orchestration with Snakemake.

### Reproducibility

* Container images pinned by digest; lockfiles committed.
* Command-line and environment snapshots stored per run.

---

## 4) Operational flow (happy path)

```bash
# Environment check
spineprep doctor

# Minimal run
spineprep run --bids /data/bids --out /data/derivatives/spineprep

# Inspect QC
xdg-open /data/derivatives/spineprep/sub-*/qc/index.html
```

**Gates**

* Doctor green → proceed.
* BIDS errors → fail; warnings → surface in QC.
* Confounds TSV schema valid.
* Registration quality passes numeric gates; overlays render.
* QC HTML builds with no missing assets.

---

## 5) CI/CD

**CI on push to main**: ruff, snakefmt, codespell, mypy (core), unit tests, tiny-dataset E2E smoke, mkdocs strict, link check.
**CI on tag (semver)**: version check, container build/publish (GHCR), versioned docs publish, artifact retention.
**Artifacts**: QC HTML, doctor JSON, DAG SVG, logs, coverage (retain 30 days).

---

## 6) Testing policy

* Unit coverage target: ≥70% MVP, ≥85% after hardening.
* Golden-image tests for transforms and confounds schema.
* Fixed seeds where applicable.
* Tiny public dataset E2E run in CI.

---

## 7) Documentation

* MkDocs strict. Public docs describe user-facing behavior only.
* Private materials under `/private` are never referenced publicly.
* Versioned docs with `mike` (“latest” dev, “stable” for tags).
* `noindex` until stable tag.

---

## 8) Phases (end-to-end list)

**Phase A — MVP pipeline**: Minimal stages above; one-command run; tiny E2E CI; QC HTML; boilerplate scaffolding.
**Phase B — Validation & evidence**: Multi-dataset evaluation (internal + selected open). Metrics: per-level alignment error, tSNR, FD/DVARS, task sensitivity, rest ICC. Max two ablations.
**Phase C — Hardening & release**: Publish containers with digests; coverage ≥85%; performance/caching; docs polish; remove `noindex`; submission package.

> The blueprint does not track “done”. Only tickets do.

---

## 9) Ticket policy

**Title:** `[id] [area] imperative`
**Summary:** 2–3 lines of value plus acceptance criteria.
**Scope boundaries:** in/out.
**Deliverables:** code paths, tests, docs.
**Checks:** exact CLI/CI commands to verify.
**Risk/rollback:** one line.
**Owner:** CEO.

**Limits:** **one active ticket per architect** (i.e., per arch/dev pair). Keep each ticket ≲200 LOC unless flagged `big-change`.

---

## 10) ADRs and compatibility

**ADR (Architecture Decision Record):** a short, versioned note capturing a significant technical decision, context, alternatives, and consequences.

* Write an ADR for changes to the engine/orchestrator, registration approach, confound model, containerization, or compatibility.
* ADRs live under `docs/adr/`.
* Maintain a compatibility matrix for Python, SCT, OS, and container digests.

---

## 11) Guardrails

* Main-only until v1.0.
* CI must pass before a ticket is “done”.
* No private files committed.
* No analytics.
* Public docs never reference private materials.

---

## 12) SCT installation policy

* **Containers**: SpinePrep images ship with a **pinned, tested SCT version** preinstalled (preferred).
* **Local (non-container)**: `spineprep doctor` verifies SCT/version and can **auto-install the latest SpinePrep-tested SCT release** into an isolated prefix, record the path, and cache it.
* **Pinning**: SCT version recorded in container labels and `doctor` output.
* **Refusal**: If SCT is missing and auto-install is declined, SpinePrep exits with remediation instructions.

---

## 13) Risks (top)

1. SCT/template variance → container-pinned SCT; `doctor` verify/auto-install.
2. Header inconsistencies → header checks/fixes and tests.
3. BIDS metadata gaps → fail early on errors; warn and document fallbacks.
4. Registration brittleness → conservative defaults, overlays, numeric gates.
5. CI runtime sprawl → tiny dataset, caching, minimal matrix.
6. Premature visibility → keep `noindex` until stable tag.

---

## 14) Developer quick start

```bash
# Env
conda create -n spineprep python=3.11 -y && conda activate spineprep
pip install -e .[dev,docs]
spineprep doctor

# Local checks
ruff check . && snakefmt --check . && codespell
pytest -q
mkdocs build --strict
snakemake -n --cores 4 --printshellcmds --reason
```

---

## 15) Glossary

**ADR:** Architecture Decision Record (important technical decision log)
**BIDS:** Brain Imaging Data Structure
**BIDS-Derivatives:** Standardized outputs from BIDS inputs
**SCT:** Spinal Cord Toolbox
**PAM50:** Standard spinal cord template family
**FD/DVARS:** Motion and intensity-change metrics
**aCompCor:** Component-based physiological regressors

