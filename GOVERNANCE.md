# SpinePrep Governance

SpinePrep is currently a small, maintainer-led project. This document states how
decisions are made so contributors know what to expect. It will grow as the
community does.

## Roles

- **Maintainer(s).** Responsible for the technical direction, reviewing and
  merging pull requests, cutting releases, and upholding the
  [Code of Conduct](CODE_OF_CONDUCT.md). The current lead maintainer is
  **Kiomars Sharifi** (ETH Zurich / University of Zurich / Balgrist University
  Hospital).
- **Contributors.** Anyone who opens an issue or pull request. Contributors do
  not need commit access to have influence — a well-argued issue changes the
  roadmap.

## How decisions are made

- **Everyday changes** (bug fixes, docs, tests) are decided by maintainer review
  on the pull request.
- **Pipeline / algorithm changes** must be justified against the field's working
  pipelines and the literature (see the development principles in
  [`CLAUDE.md`](CLAUDE.md)). A change that alters a step's behaviour needs its
  step-local truth metric and diagnostic reportlet to still make sense.
- **Larger or contested changes** are discussed in a GitHub issue until rough
  consensus is reached; the maintainer makes the final call and records the
  rationale in the issue or a spec under `.claude/specs/`.

## Releases

Releases follow [Semantic Versioning](https://semver.org/). Each release is a
git tag + GitHub Release with hand-curated notes (`CHANGELOG.md`) and, once the
Zenodo integration is enabled, an archival DOI.

## Adding maintainers

Sustained, high-quality contribution is the path to commit access. The lead
maintainer invites new maintainers and updates this document accordingly.
