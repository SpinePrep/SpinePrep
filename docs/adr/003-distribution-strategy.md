# ADR-003: Distribution and Containerization Strategy

**Status:** Accepted  
**Date:** 2025-10-08  
**Decision Makers:** CEO  

## Context

SpinePrep depends on SCT (complex install), FSL, Python packages, and requires reproducible execution across environments (local, HPC, cloud). Distribution must balance ease-of-use with version control rigor.

## Decision

Use **GHCR containers + pip install** for dual access patterns:

- **Container:** `ghcr.io/spineprep/spineprep:0.1.0` (pinned digest)
- **PyPI:** `pip install spineprep` (CLI + libraries)
- **Docs:** MkDocs with `mike` versioning (/ = latest, /stable = tagged)
- **Digests:** Lock all container bases and record in release notes

## Rationale

1. **GHCR:** Free, integrated with GitHub, supports OCI standards
2. **Multi-stage container:** Freeze SCT + dependencies, cache layers
3. **pip install:** Enables local development, CI, and Snakemake workflows
4. **mike docs:** Version-aware docs with stable/latest separation
5. **Digest pinning:** Reproducibility for papers (cite digest, not tag)

## Container Strategy

### Base Image
```dockerfile
FROM ubuntu:22.04 AS base
# Install SCT, FSL, Python 3.11, system deps
```

### Layers
1. System packages (SCT, FSL, graphviz)
2. Python deps (locked requirements.txt)
3. SpinePrep package

### Tags
- `v0.1.0` - immutable version tag
- `latest` - tracks main branch
- `stable` - alias to latest release

### Digest Tracking
```bash
docker pull ghcr.io/spineprep/spineprep:0.1.0
# Record sha256:abc123... in release notes
```

## Docs Deployment

### Mike Versioning
- `/` → dev (main branch, noindex)
- `/stable/` → v0.1.0 (indexed)
- `/v0.1.0/` → archived version

### Cross-Repo Pages
- Source: `SpinePrep/SpinePrep` (main repo)
- Publish: `spineprep/spineprep.github.io` (org pages)
- URL: `https://spineprep.github.io/`

### SEO Control
- `noindex` until v0.2.0 (banner visible in dev)
- Remove banner + enable indexing at v0.2.0

## Consequences

### Positive
- Reproducible via digest pinning
- Easy local install via pip
- Versioned docs with history
- Container isolation for SCT/FSL

### Negative
- GHCR requires GitHub auth for private images
- Container size (SCT + FSL ≈ 2GB)
- mike requires gh-pages branch management

## Reproducibility Guarantees

For papers, cite:
```
ghcr.io/spineprep/spineprep@sha256:abc123def456...
SpinePrep v0.1.0 (DOI: 10.5281/zenodo.xxxxxxx)
```

## CI Artifacts

- **E2E artifacts:** QC bundle, DAG, logs (30 days)
- **Coverage:** XML report (uploaded to Codecov)
- **Release assets:** Container digest, docs URL

## Future Evolution

- v0.2.0: Multi-arch builds (amd64, arm64)
- v0.3.0: Singularity/Apptainer images for HPC
- v1.0.0: Docker Hub mirror, Zenodo DOI

