# Contributing to SpinePrep

Thanks for your interest in improving SpinePrep. This page is the short version;
the full developer guide lives at
**[spineprep.com/contributing](https://spineprep.com/contributing/)**.

## Where to go first

- **Questions / "how do I…"** → ask on the
  [NeuroStars `spineprep` tag](https://neurostars.org/tag/spineprep), not the
  issue tracker. This keeps answers searchable for the next person.
- **Bug reports** → open a
  [Bug report issue](https://github.com/SpinePrep/SpinePrep/issues/new/choose).
  Include the exact command, `spineprep --version`, the failing step's QC JSON,
  and the reportlet PNG if relevant.
- **Feature ideas** → open a Feature request issue and describe the scientific
  motivation (ideally with a citation).

## Development setup

```bash
git clone https://github.com/SpinePrep/SpinePrep.git
cd SpinePrep
pip install poetry
poetry install --with dev
poetry run pytest -q
```

The full pipeline additionally needs **SCT, FSL, and ANTs** on your `PATH`. The
easiest way to get a complete environment is to build the container recipe
(`Dockerfile.spineprep`) — see the [quickstart](https://spineprep.com/quickstart/).

## Ground rules

- **Branches:** `feat/…`, `fix/…`, `docs/…` off `main`.
- **Commits:** [Conventional Commits](https://www.conventionalcommits.org/).
  Put the *why* in the message, not just the *what*.
- **Tests:** every behavioural change ships with a test; `poetry run pytest`
  must be green before you open a PR.
- **Scope:** SpinePrep tracks the field's working pipelines (fMRIPrep, MRIQC,
  SCT). New algorithms need a literature citation; new knobs are documented with
  their citation in the relevant `policy/<step>.yaml`. See
  [`CLAUDE.md`](CLAUDE.md) for the development principles.
- **One step, one metric, one reportlet.** Changes to a pipeline step keep its
  step-local truth metric and its diagnostic reportlet intact.

## Pull request checklist

1. Branch from `main`; keep the PR focused on one change.
2. `poetry run pytest -q` passes; add/adjust tests.
3. Update the relevant docs page and, if user-facing, `CHANGELOG.md`.
4. Fill in the PR template; link the issue it closes.

By contributing you agree that your contributions are licensed under the
project's [Apache-2.0 license](LICENSE), and you abide by the
[Code of Conduct](CODE_OF_CONDUCT.md).
