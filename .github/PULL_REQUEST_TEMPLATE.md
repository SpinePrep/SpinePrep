<!-- Thanks for contributing to SpinePrep. Keep PRs focused on one change. -->

## Summary

<!-- What does this PR do, and *why*? Link the issue it closes: "Closes #123". -->

## Type of change

- [ ] Bug fix (non-breaking change that fixes an issue)
- [ ] New feature (non-breaking change that adds capability)
- [ ] Breaking change (existing behaviour changes)
- [ ] Docs / tests / tooling only

## Which pipeline step(s)?

<!-- e.g. S6 registration, or "n/a — docs". If a step's behaviour changes, note
     how its step-local metric and reportlet still make sense. -->

## Checklist

- [ ] `poetry run pytest -q` passes locally
- [ ] Added or updated tests for the change
- [ ] Updated the relevant docs page
- [ ] Updated `CHANGELOG.md` (if user-facing)
- [ ] For a new algorithm/knob: cited the literature and documented it in the
      relevant `policy/<step>.yaml`
- [ ] Commit messages follow Conventional Commits
