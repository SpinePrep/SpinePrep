# SpinePrep — RELEASE_SCHEDULE.md

**Owner:** CEO · **Mode:** one active ticket per architect · **Repo:** public (not searchable) · **License:** Apache-2.0

---

## Targets (ISO-8601)

* **ISMRM abstract submit:** **2025-10-29 23:59 UTC**
* **Phase B complete (validation):** 2025-12-19
* **RC tag:** 2026-01-12
* **Stable tag & docs indexed:** 2026-01-26
* **Nature Methods submit:** 2026-02-09

---

## Versioning

* Phase A: `v0.1.0-alpha.N` → `v0.5.0-beta.1` (A exit)
* Phase B: `v0.8.0-beta.N`
* RC: `v0.9.0-rc.1` (add `-rc.2` only if blocking)
* Stable: `v1.0.0` (containers/docs pinned by digest)
* SemVer: minor=features, patch=fixes; major for breaking (post-paper)

---

## Gates (must pass)

### Phase A exit → `v0.5.0-beta.1`

* ≥95% runs finish on internal data; QC HTML per subject
* CI green: lint/format/spell/types/tests/tiny-E2E/docs(strict)
* Containers (GHCR) with pinned SCT; `spineprep doctor` passes

### Phase B exit → `v0.8.0-beta.N`

* Repro scripts emit figures/tables for: per-level alignment, tSNR, FD/DVARS, task Z/overlap, rest ICC (if available)
* Two ablations max; results reproducible from one entry point

### RC → `v0.9.0-rc.1`

* Coverage ≥85%; byte-stable tiny-E2E on two Linux runners
* Container labels include app/SCT/template digests
* No P0/P1 open

### Stable → `v1.0.0`

* Deterministic regeneration of paper figures
* Compatibility matrix published (Python, SCT, OS, digests)
* Docs switched to indexed

---

## Freezes

* Feature freeze at RC cut (2026-01-12)
* String/docs freeze: 2026-01-21
* Release freeze: 2026-01-24
  Only P0 fixes allowed; each requires a ticket.

---

## Submission bundles

* **ISMRM:** abstract PDF, 1 panel (geometry+task), refs, link to validation page (anon if needed)
* **Nature Methods:** manuscript, full figure set (geometry, tSNR, task, ICC, ablations), methods, code availability, container digests, dataset manifest

---

## Checklists (condensed)

* **Containers:** build Docker/Apptainer; SCT pinned; smoke-test tiny data
* **CI/CD:** cache builds; job <30 min; retain artifacts 30 days
* **Docs:** MkDocs strict; versioned with `mike`; no `/private` references
* **Provenance:** store `doctor.json`, env/config snapshots; publish `--print-config` defaults

---

## Roles

* **CEO:** owns dates/tags/submissions
* **Architect(s):** tickets & review; enforce blueprint/roadmap
* **Developer(s):** implement; keep CI green; produce artifacts

