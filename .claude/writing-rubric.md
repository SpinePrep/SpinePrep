# SpinePrep public-writing rubric

Binding for any text SpinePrep publishes: method/reference docs, README, tutorials,
release notes, paper prose, and dashboard/report copy. Goal: prose that reads as
written by a careful cord-fMRI methodologist, not by an LLM. Grounded in (a) the
corpus-derived field paper register at `/mnt/ssd1/qai/knowledge/style/rubric_academic.md`
(35 spinal-cord-fMRI papers), (b) the documentation register of fMRIPrep / MRIQC /
SCT / nipreps, and (c) a structural + lexical AI-tell audit.

The tell is **density and uniformity**, not any single item. One em-dash is fine;
one per sentence is a signature. One triad is rhetoric; a triad per paragraph is a
mold. Read every draft aloud before publishing.

## What belongs on the public site (audience and scope)

The site serves two readers: someone preprocessing their own BIDS dataset, and a
scientist who needs the methods record whether or not they run the tool. Nothing
else earns a place.

1. **Document the user's real entrypoint**: `spineprep <bids_dir> <out_dir>
   participant|group`. The per-step dev CLI, `--dataset-key`, `policy/datasets.yaml`,
   `config/datasets_local.yaml`, and workfolders/scopes are internal plumbing and do
   not appear. (The BIDS-App synthesizes its own dataset key; users never set one.)
2. **Publish what the reader supplies, tunes, or reads**: their BIDS data; the step
   knobs in `policy/Sn_*.yaml` (shipped and genuinely tunable); the derivatives; the
   QC reports; the limitations.
3. **Serve the scientist who never runs it**: algorithm, parameters, rationale with
   citations, QC metric, limitations.
4. **Keep maintainer scaffolding off the site**: the validation-cohort registry,
   local path maps, dev scopes, `.claude/specs/` audit trails, and any step users
   never run. Internal reasoning stays in `.claude/specs/`; the site carries the
   conclusion and the citation.
5. **Never present an internal-only path as the user path.** This is a truthfulness
   rule, not a style preference.

Tests to run before publishing a page:
- Is the step in `PARTICIPANT_STEPS` (S1–S9) or `GROUP_STEP` (S10)? If not, it is
  not a method page. S0 is a developer utility and is documented as such.
- For every file or flag named: does the user create, edit, or read it? If it is
  synthesized or maintainer-only, do not name it.
- Could a reader with only their own BIDS dataset follow every sentence? If a
  sentence assumes the repo checkout or the maintainers' cohort, cut it.

## Register by genre

| Artifact | Person | Tense | Notes |
|---|---|---|---|
| Method / reference doc page | third person, tool-as-subject (no "we"/"you") | present | fMRIPrep/SCT docs register |
| Paper / manuscript prose | passive Methods; "we observed/found" in Results/Discussion | past | defer to `rubric_academic.md` + `exemplars_academic.md` |
| Auto-generated methods boilerplate | tool-as-subject | past | fMRIPrep-boilerplate style; CC0; meant to be copied verbatim |
| Tutorial / quickstart | second person + imperative | present | the one genre where "you" and light "we provide…" are fine |
| README / overview | third person, mostly declarative | present | state what it is + does; no marketing adjectives |

## Method-page structure (replaces the old "At a glance"-card template)

Head each section by the **processing stage**, not a slogan. Terse prose paragraphs
(2–5 sentences). No summary card, no hero box.

1. **`# Sn: <Step name>`** (colon, not em-dash) + one plain sentence stating
   what the step produces.
2. **What it does** — 1–2 short paragraphs, prose, tool-as-subject.
3. **Algorithm and parameters** — prose for the method; a **definition list** (SCT
   style: knob → what it does → default → allowed values) for the tunable knobs,
   sourced from `policy/Sn.yaml`. Name each tool inline where it acts, as
   `` `tool` vX.Y (Expanded Name; Author YYYY) ``. State rationale in one flat
   clause tied to a citation or a physical reason — no build-up.
4. **Inputs and outputs** — BIDS-Derivatives paths. A table only if it is genuine
   2-D data.
5. **Quality control** — describe the step-local metric by *what it measures* and
   its reference, neutrally (not good/bad); name the reportlet the human inspects.
6. **Limitations** — the honest, specific caveats (partial volume, draining-vein
   contamination, single-site, etc.).
7. **References** — inline `(Author et al., YYYY)`; full list at page end.
- CLI usage lives in the Reference/CLI page, not per step.
- Provenance footer pinning the page to `policy/Sn.yaml` + the audit spec + a
  verified-against-code date.

Model the prose on the field's real methods text, e.g. Kaptan (2023) motion
correction: *"a slice-wise motion correction procedure with regularization in
z-direction (as implemented in SCT, `sct_fmri_moco`) was employed in two steps.
First, the … volumes of each run were averaged to create a mean image … A
cylindrical mask (with a diameter of 41 mm) was generated …"* — passive, tool
named in code font, parameters inline, no emphasis formatting.

## Sentence and formatting rules

- Present tense, passive, tool-as-subject on doc pages: "The cord is segmented with
  `sct_deepseg` (contrast-agnostic model; Bédard 2025)."
- Cite the tool/method at the point where it does the work, with version, in the
  same sentence as the choice it justifies. Never footnote the citation away from
  the claim.
- Vary sentence length deliberately (field median ~20 words, IQR 11–32). A
  one-sentence paragraph is allowed.
- **Bold only for CLI flags / defined terms at definition.** Code identifiers go in
  `monospace`, never bold.
- Lists only for genuinely enumerable parallel items (the 9 datasets, the S1–S10
  steps, prerequisites). Convert bulleted verb-phrases back into sentences. No table
  for a single key–value.
- Hedge once per claim, never stacked. Strong verbs (`we observed`, `provides
  evidence`) only when the result is robust; hedge verbs (`may reflect`, `likely`)
  for inference beyond the data.

## AI-tell removal checklist (run over every draft)

Structure
- Delete "At a glance / TL;DR / In summary" boxes that restate the body. Keep only a
  genuine paper abstract.
- Cut paragraph-opening sentences that announce the paragraph instead of stating a
  fact ("There are several considerations when it comes to…").
- Remove rhetorical questions; state the answer.
- Remove "First/Second/Finally" and "In this section we will…" unless the steps are
  truly ordered.
- Break uniform rhythm: if every sentence is 15–25 words and every section is
  intro→three-points→recap, disrupt it.

Rhetoric
- Reduce em-dashes to ≤1 per few paragraphs; rewrite the rest as clauses.
- Kill rule-of-three triads padded by a filler third item.
- Kill "not just X, but Y" / "it's not A, it's B" frames.
- Remove "-ing" significance tails ("…, ensuring transparency across the field").
- Remove marketing metaphors (front door, workhorse, under the hood) — name the
  component.
- Remove signpost fillers: "Here's why", "The key insight", "Let's dive in", "In
  essence", "Simply put".

Words and claims
- Every "studies show / it is known" gets a specific citation or is deleted. No
  claim above its evidence (project invariant).
- "significantly / notably / importantly" as sentence-openers → cut, or attach a
  real statistic. "significant" only in the statistical sense, with test + p.
- Empty intensifiers and unsupported numbers ("up to 40%") → the measured value or
  cut.

## Lexical bans

**Tier A — do not use** (near-zero in the corpus; pure AI tells): delve, tapestry,
realm, landscape (figurative), seamless(ly), testament, boast, garner, underscore
(= emphasize), pivotal, intricate/intricacies, meticulous, elevate, foster,
showcase, navigate (figurative), resonate, cutting-edge, game-changer, paramount,
myriad, plethora, harness (figurative), synergy, holistic, "it's worth noting",
"plays a crucial/vital/key role", "a key/critical aspect", "when it comes to", "at
its core". Also em-dashes-in-prose are house-style-off (Kiomars preference).

**Tier B — only when literally true and measured:** robust (statistical sense
only), comprehensive (only if it covers the whole space), leverage → use, utilize →
use, crucial/vital/critical/essential/key (only when literally load-bearing),
enhance/optimize/streamline → the concrete verb, ensure → "so that" + mechanism.

Self-check grep (justify or kill every hit):
```
grep -inE 'delve|seamless|leverage|utilize|comprehensive|crucial|pivotal|underscore|testament|tapestry|realm|landscape|robust|notably|it is worth noting|plays a (crucial|vital|key) role|under the hood|front door|at a glance' <file>
```

## Calibration — the S1 page before/after

The first S1 method page failed this rubric; the tells and their fixes:

| Tell (before) | Fix (after) |
|---|---|
| "**At a glance**" card summarizing the page | deleted; page opens with what S1 produces |
| "S1 is the pipeline's front door." | "S1 verifies the input dataset before any processing." |
| bold on many terms per line | bold removed; tool names → `monospace` |
| em-dash asides in most sentences | rewritten as clauses/sentences |
| "Two points of honesty:", "Here's why" | deleted; state the fact directly |
| whole page as nested bullets | prose paragraphs; definition list only for the checks |

## How to use

1. Draft in the register for the genre (table above); for paper prose also read
   `rubric_academic.md` + pick 2 exemplars from `exemplars_academic.md`.
2. Run the AI-tell checklist and the grep top-to-bottom.
3. Read aloud; break any uniform rhythm.
4. Verify every parameter/claim against `policy/` + code (no claim above evidence).
