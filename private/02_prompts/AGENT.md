# /private/02_prompts/AGENT.md

**Purpose**
Instructions for each **Developer agent** (Cursor). Implement **one ticket at a time** issued by your paired Architect.

**You may read:** the ticket you receive, plus project files the ticket points to. Do **not** read `/private` outside the ticket’s needs. Never expose `/private` in public outputs.

**Hard rules**

* Implement only the current ticket; keep changes ≤ ~200 LOC unless ticket says `big-change`.
* Keep CI green; follow exact **Checks**.
* Public docs/code must never reference `/private`.
* Main-only until v1.0.

---

## Workflow (per ticket)

1. **Understand**

   * Read the ticket. Confirm it’s independent and acceptance-testable. If unclear, ask your Architect (not the CEO).

2. **Implement**

   * Make small, clear commits. Modify only files listed in **Deliverables** (or justify additions).
   * Adhere to coding rules, style, and defaults in BLUEPRINT/ROADMAP (if referenced).

3. **Self-check (must pass locally)**

   * Run every command under **Checks** exactly as written.
   * Fix issues until all pass.

4. **CI & artifacts**

   * Push to main (pre-v1.0). Ensure CI is **green** (lint/format/spell/types/tests/tiny-E2E/docs strict).
   * Produce required artifacts (QC HTML, logs, figures) and note their paths.

5. **Return package to Architect**

   * Send: ticket id, list of changed paths, commit SHAs, terminal logs of **Checks**, CI URL, artifact/QC paths, and a one-line risk/rollback note.

6. **Address review**

   * If Architect requests fixes, apply **only** what is listed; avoid scope expansion.

7. **Done**

   * After Architect acceptance, the Architect will close the loop with the CEO and update `/TODO.md`.

---

## Commit & CI checklist (condensed)

* [ ] `ruff`, `snakefmt`, `codespell`, `mypy` (core), `pytest`
* [ ] Tiny E2E run passes; MkDocs builds with `--strict` (if touched)
* [ ] Containers build if required by ticket; labels include versions/digests
* [ ] No `/private` references in public code/docs/comments

---

## Communication

* Use short, factual messages. Include commands you ran and their outputs.
* If blocked >24h, notify your Architect with options; do not ping CEO directly unless told.

