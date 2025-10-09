# /private/02_prompts/TICKET_TEMPLATE.md

> **Rule:** One active ticket **per architect**. Keep impact **≤ ~200 LOC** unless labeled `big-change`.

---

## Title

`[T-YYYYMMDD-ARCH-SLUG] [area] imperative`
*Area:* one of `preproc | norm | confounds | qc | bidsapp | docs | ci | eval | infra`

---

## Summary (value & acceptance)

* **Value:** *What improves for users/researchers (1–2 lines).*
* **Acceptance:** *Plain-language pass criteria (bullets, 2–4 items).*

---

## Scope boundaries

* **In:** *Exact behaviors/files to change.*
* **Out:** *Explicitly excluded work (avoid scope creep).*

---

## Deliverables

* **Code/paths:**

  * `path/to/file1.py`
  * `path/to/file2.py`
* **Artifacts:** *QC/report/figures logs as applicable.*
* **Docs:** *Pages or sections to update (if user-facing).*

---

## Checks (copy-paste runnable)

```bash
# Lint/format/spell/types
ruff check .
snakefmt --check .
codespell
mypy path/to/changed/core

# Tests & tiny E2E
pytest -q
spineprep doctor
spineprep run --bids /path/tiny --out /tmp/spineprep_out
mkdocs build --strict   # if docs touched

# Verify outputs/artifacts (examples)
test -f /tmp/spineprep_out/sub-01/qc/index.html
```

* **CI:** must be green on main; link CI job URL in return package.

---

## Risk / rollback

* **Risk:** *Biggest likely failure (one line).*
* **Rollback:** *How to revert safely (one line).*

---

## References

* **Blueprint sections:** *e.g., “Minimal default stages”, “CI/CD”.*
* **Roadmap gate:** *Phase A/B/C target this enables.*
* **ADR (if any):** *ADR-XXXX link (only for significant architecture changes).*

---

## Owner & metadata

* **Owner:** CEO
* **Architect:** *name/id*
* **Developer:** *name/id*
* **Estimated LOC:** *≤200*
* **Start:** *YYYY-MM-DD*
* **Due:** *YYYY-MM-DD (align with Release Schedule)*

---

## Return package (Dev → Arch)

* Changed paths & **commit SHAs**
* Terminal logs of **Checks** (paste)
* **CI URL** and artifact/QC paths
* One-line **risk/rollback** confirmation

