# Releasing SpinePrep

The software is functionally ready and the in-repo release artifacts are prepared
(LICENSE, NOTICE, CITATION.cff, version 1.0.0, docs). The steps below are the
**operator-only** actions to make a public release — each needs an account,
credential, or sign-off the automation cannot perform.

## Decisions already locked (2026-07-08)
- License: **Apache-2.0** (code) — see `LICENSE` + `NOTICE`.
- Version: **1.0.0**.
- Container: **build-recipe only** (FSL is not freely redistributable — do NOT
  push a prebuilt image that bundles FSL).
- Author (CITATION.cff): **Kiomars Sharifi** (add co-authors before submission).

## Checklist

### 1. Repository
- [ ] Create/settle the public repo at `github.com/SpinePrep/SpinePrep`
      (matches `mkdocs.yml` + README/CITATION links).
- [ ] `git remote add origin …` and push `main`.
- [ ] Cut a signed tag: `git tag -a v1.0.0 -m "SpinePrep 1.0.0" && git push --tags`.
      (The tag makes `git describe` return `v1.0.0`, which the reproducibility
      receipt records as the pipeline version.)

### 2. Container distribution (recipe-only)
- [ ] Confirm the FSL licence terms permit your intended use; keep distribution as
      the **build recipe** (`Dockerfile.spineprep`) — users build locally.
- [ ] Do NOT publish a prebuilt FSL-bundled image to a public registry.
- [ ] (Optional) If a pullable image is desired later, produce an FSL-free base +
      documented FSL-install step, or host on infra where the FSL licence allows it.

### 3. Archival + citability
- [ ] Enable the Zenodo–GitHub integration on the repo; the `v1.0.0` release mints
      a DOI. Add the DOI badge to the README + `CITATION.cff` (`doi:` field).
- [ ] Update `CITATION.cff` `date-released` to the actual release date if it differs.

### 4. Documentation hosting
- [ ] Build + host the docs (`mkdocs build`) at `spineprep.com` or GitHub
      Pages; confirm the URLs in README/mkdocs resolve.
- [ ] The validation page carries a "methods validation in progress" banner — keep
      it until the reliability × validity study lands.

### 5. Data governance
- [ ] Balgrist **DUA sign-off** for referencing the internal cohorts; ensure only
      permitted data/derivatives are shown publicly. Public OpenNeuro datasets are
      cited by accession.

### 6. Authorship (before manuscript submission)
- [ ] Finalise the author list + affiliations in `CITATION.cff` and the paper.

## Verify a fresh build before announcing
```bash
docker build -f Dockerfile.spineprep \
  --build-arg GIT_SHA=$(git rev-parse HEAD) \
  --build-arg GIT_DESCRIBE=$(git describe --always --tags) \
  -t spineprep:1.0.0 .
scripts/container_smoke_test.sh spineprep:1.0.0 /path/to/bids <subject>
```

## Not required for the software release
- The **reliability × validity study** (manuscript centerpiece) is deferred; it
  gates the *paper*, not the tool. See `.claude/specs/v2-finalization-plan.md`.
- Optional engineering polish: B8 (decouple policy/config from CWD) and T3.3
  (cross-machine reproducibility) — see `.claude/specs/production-readiness.md`.
