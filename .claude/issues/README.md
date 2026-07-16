# Candidate issues

Drafted GitHub issues that are **not yet submitted**. Each file is a complete
issue body, ready to post to `SpinePrep/SpinePrep` once the operator approves it.

Frontmatter:

```yaml
---
status: candidate | submitted | dropped
title: <the issue title, verbatim>
repo: SpinePrep/SpinePrep
url: <filled in after submission>
---
```

Rules:

- **Nothing here is submitted without the operator saying so.** These are drafts
  held for review, not a queue that gets flushed.
- Body text follows `.claude/writing-rubric.md` (field register): the repo is
  public, so an issue is public writing.
- Keep the "to verify" section honest. If a claim in the issue rests on our own
  reasoning rather than a citation, say so there rather than letting it read as
  established.
- After submitting, set `status: submitted` and paste the `url` back in, so the
  draft and the live issue stay linked.

To post one:

```bash
gh issue create --repo SpinePrep/SpinePrep \
  --title "<title from frontmatter>" \
  --body-file .claude/issues/<file>.md   # strip the frontmatter first
```
