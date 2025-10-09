# TODO.md — Phase A (MVP)

**Mode:** Single CEO; multiple arch/dev pairs; **one active ticket per architect**.
**Goal (Phase A exit):** Minimal pipeline runs end-to-end with QC and containers; ≥95% success on internal datasets; CI green; docs build strict; tiny E2E run.

---

## How this file is used

* **ARCH** claims ONE `Open` item → moves it to `Active` (append `CLAIMED:<arch-id> <UTC-ISO>`).
* ARCH creates a ticket from the item using `TICKET_TEMPLATE.md`.
* **DEV** implements, returns package; **ARCH** verifies Checks.
* ARCH moves item to `Done` (append `SHA:<commit> <UTC-ISO>`).
* Keep items **independent**; split if >~200 LOC.

---

## Open

### A1 — CLI skeleton & doctor (area: `bidsapp`)

**Value:** Single entry point and environment/data preflight.
**Acceptance:** `spineprep run|doctor|version` exist; `doctor` checks Python, SCT (or offers **tested** auto-install), templates, disk, write perms; prints JSON snapshot.
**Checks (summary):**

```
spineprep version
spineprep doctor --json > doctor.json && test -s doctor.json
```

**Deliverables:** `spineprep/cli.py`, `spineprep/doctor.py`, packaging, help text.
**Est LOC:** ≤200

---

### A2 — BIDS ingest & manifest (area: `preproc`)

**Value:** Reliable dataset intake and early failure.
**Acceptance:** BIDS validation run; manifest (subjects/sessions/runs, PE/TR/TE/FOV/coverage) written; hard errors stop run.
**Checks:**

```
spineprep run --bids <tiny> --out <out> --dry-run
test -f <out>/manifest.csv
```

**Deliverables:** `ingest/reader.py`, `ingest/manifest.py`.
**Est LOC:** ≤200

---

### A3 — Motion reference & metrics (FD/DVARS) (area: `preproc`)

**Value:** Stable reference and motion/noise metrics.
**Acceptance:** Robust BOLD reference saved; FD & DVARS TSV columns emitted per run; schema validated.
**Checks:**

```
test -f <out>/sub-01/func/sub-01_task-*_boldref.nii.gz
grep -q "fd,dvars" <out>/sub-01/func/*confounds.tsv
```

**Deliverables:** `preproc/motion_ref.py`, `confounds/fd_dvars.py`.
**Est LOC:** ≤200

---

### A4 — Segmentation & masks (cord ± CSF) (area: `preproc`)

**Value:** Masks required for normalization and confounds.
**Acceptance:** SCT-based cord (± CSF) masks generated; stored with provenance; basic overlay PNGs for QC.
**Checks:**

```
test -f <out>/sub-01/anat/sub-01_desc-cord_mask.nii.gz
test -f <out>/sub-01/qc/sub-01_anat_mask_overlay.png
```

**Deliverables:** `preproc/masking.py`, SCT invocations, logging.
**Est LOC:** ≤200

---

### A5 — Coregistration & template normalization (area: `norm`)

**Value:** Consistent group space.
**Acceptance:** EPI→T2w coreg + T2w→template (SCT); transforms saved; **single write** achieved by composing transforms.
**Checks:**

```
test -f <out>/sub-01/xfm/*(epi2t2|t2totemplate).txt
test -f <out>/sub-01/func/*_space-PAM50_bold.nii.gz
```

**Deliverables:** `norm/register.py`, `norm/apply_compose.py`.
**Est LOC:** ≤200

---

### A6 — Basic confounds (motion + aCompCor + scrubbing) (area: `confounds`)

**Value:** Analysis-agnostic noise regressors.
**Acceptance:** Confounds TSV adds motion (6/12), aCompCor (CSF/WM masks), and scrubbing column; schema documented.
**Checks:**

```
grep -q "trans_x,rot_x" <out>/sub-01/func/*confounds.tsv
grep -q "acompcor" <out>/sub-01/func/*confounds.tsv
```

**Deliverables:** `confounds/acompcor.py`, `confounds/schema.json`.
**Est LOC:** ≤200

---

### A7 — QC HTML scaffold (area: `qc`)

**Value:** Transparent, navigable quality control.
**Acceptance:** Per-subject HTML with: overlays (EPI↔T2w↔template), motion plots, confounds summary, environment (`doctor.json`).
**Checks:**

```
test -f <out>/sub-01/qc/index.html
```

**Deliverables:** `qc/report.py`, assets, minimal CSS.
**Est LOC:** ≤200

---

### A8 — Containers with pinned SCT (Docker/Apptainer) (area: `infra`)

**Value:** Reproducible runtime.
**Acceptance:** Docker + Apptainer images build in CI; SCT pinned (tested release); labels include app version, git SHA, SCT, template digests.
**Checks:**

```
docker run spineprep:<tag> spineprep doctor
apptainer exec spineprep.sif spineprep version
```

**Deliverables:** `Dockerfile`, `apptainer.def`, GH Actions job.
**Est LOC:** ≤200

---

### A9 — Tiny E2E dataset & CI wiring (area: `ci`)

**Value:** Fast regression guard.
**Acceptance:** GitHub Actions runs: lint/format/spell/types/tests, **tiny E2E** `spineprep run`, `mkdocs --strict`; wall-time <30 min.
**Checks:** CI green on main; artifact retention 30 days.
**Deliverables:** `.github/workflows/ci.yml`, tiny dataset pointer, caching.
**Est LOC:** ≤200

---

### A10 — Docs scaffold (MkDocs, noindex) (area: `docs`)

**Value:** Public user docs without private leakage.
**Acceptance:** MkDocs site builds (`--strict`), `noindex` on; pages: Install (containers first), Quickstart, Outputs, FAQ.
**Checks:**

```
mkdocs build --strict
grep -q "noindex" site/index.html
```

**Deliverables:** `mkdocs.yml`, `docs/*.md`, `docs/.noindex`.
**Est LOC:** ≤200

---

## Active

*(ARCH moves items here when claimed; append `CLAIMED:<arch-id> <UTC-ISO>` and later `SHA:<commit> <UTC-ISO>` on completion.)*

* *(empty)*

---

## Done

*(ARCH appends completed items here with final SHA and date.)*

* *(empty)*

---

## Notes

* SDC remains **conditional** and can be gated later; Phase A focuses on the minimal backbone above.
* If any item exceeds ~200 LOC, **split** and land the smallest independent slice first.

