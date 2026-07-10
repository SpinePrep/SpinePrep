# SpinePrep — Migration & Release Runbook

This is the ordered runbook for migrating the project from its old
**SpinalfMRIprep** identity to **SpinePrep** and publishing it end to end. Each
step is tagged **[AUTO]** (done by tooling / already committed) or **[HUMAN]**
(needs an account, OAuth, DNS, money, or a browser-only setting that no token can
perform). Do the steps in order.

## Locked decisions
- **License:** Apache-2.0 (code) — `LICENSE` + `NOTICE`.
- **Version:** 26.0.0, calendar versioning (CalVer, YY.MINOR.PATCH) going forward.
- **GitHub home:** org `SpinePrep`, repo `SpinePrep/SpinePrep` (rename of the
  existing `SpinalfMRIprep/SpinalfMRIprep`).
- **Public content:** code, docs, pipeline, and technical specs are public. The
  manuscript (`paper/`) and publication-strategy specs are kept OUT of the public
  repo (purged from history — see Phase 1).
- **Container:** build-recipe by default; an opt-in GHCR publish workflow exists.
- **Domain:** move to `spineprep.com`; retire `spinalfmriprep.com`.
- **Distribution channels:** PyPI, conda-forge, and (opt-in) GHCR container.

---

## Phase 0 — Backup  [AUTO, done]
A full `git bundle` of the repo is written to `../SpinePrep-backup-<date>.bundle`
before any history rewrite. Nothing below is destructive to your local files.

## Phase 1 — Publish the migrated code  [AUTO]
- The local repo is ~2 months ahead of the stale public remote and already
  renamed internally to SpinePrep.
- `paper/` and the strategy specs are purged from all pushed history (they were
  only ever in commits *after* the current public tip, so this stays a
  fast-forward — no force-push, no broken clones). The files remain on your disk,
  gitignored.
- `git remote add origin https://github.com/SpinalfMRIprep/SpinalfMRIprep.git`
  then `git push origin main`.

## Phase 2 — Rename org and repo
1. **[HUMAN] Rename the organization.** GitHub has no API for this.
   `github.com/organizations/SpinalfMRIprep/settings/profile` → **Rename
   organization** → `SpinePrep`. GitHub sets up redirects from the old org URLs.
   (Your leftover `SpinePrep-old` org is unrelated and can stay or be deleted.)
2. **[AUTO] Rename the repo** to `SpinePrep` via API once the org rename is done
   (`gh api -X PATCH /repos/SpinePrep/SpinalfMRIprep -f name=SpinePrep`).
3. **[AUTO] Set repo metadata:** description, homepage `https://spineprep.com`,
   topics (`spinal-cord`, `fmri`, `bids-app`, `neuroimaging`, `preprocessing`),
   and enable Issues. Enable Discussions if you want a Q&A space.

## Phase 3 — Domain `spineprep.com`
1. **[HUMAN] Buy `spineprep.com`** at any registrar (Cloudflare/Namecheap/etc.).
2. **[HUMAN] Add DNS records** pointing the domain at GitHub Pages:

   | Type  | Name  | Value            |
   | ----- | ----- | ---------------- |
   | A     | `@`   | `185.199.108.153`|
   | A     | `@`   | `185.199.109.153`|
   | A     | `@`   | `185.199.110.153`|
   | A     | `@`   | `185.199.111.153`|
   | AAAA  | `@`   | `2606:50c0:8000::153` |
   | AAAA  | `@`   | `2606:50c0:8001::153` |
   | AAAA  | `@`   | `2606:50c0:8002::153` |
   | AAAA  | `@`   | `2606:50c0:8003::153` |
   | CNAME | `www` | `SpinePrep.github.io.` |

   (`docs/CNAME` already contains `spineprep.com`; the docs workflow keeps a
   `CNAME` at the `gh-pages` root.)
3. **[HUMAN] Retire `spinalfmriprep.com`** when ready (let it lapse, or add a
   registrar/Cloudflare redirect to `spineprep.com`).

## Phase 4 — Documentation hosting  [HUMAN, one-time]
The docs workflow uses **`mike`** (versioned docs) and pushes to the `gh-pages`
branch. In repo **Settings → Pages**:
- Source = **Deploy from a branch** → branch `gh-pages` → `/ (root)`.
- Custom domain = `spineprep.com`; wait for the cert, then enable **Enforce
  HTTPS**.
After the first push to `main`, the `docs` workflow publishes the `dev` version;
publishing a release publishes the versioned docs and moves `latest`.

## Phase 5 — PyPI
1. **[HUMAN] Register the Trusted Publisher** (OIDC, no stored token). At
   `https://pypi.org/manage/account/publishing/` add a *pending publisher*:
   PyPI project `spineprep`, owner `SpinePrep`, repo `SpinePrep`, workflow
   `release.yml`, environment `pypi`. (First verify the name `spineprep` is free
   on PyPI; if taken, pick a new name and update `pyproject.toml`.) Optionally add
   a `testpypi` publisher on test.pypi.org for dry runs.
2. **[AUTO] Publish** by creating a GitHub Release for the tag `v26.0.0`
   (`gh release create v26.0.0 --generate-notes`). The `release` workflow builds
   and uploads to PyPI automatically. Dry-run first via the workflow's manual
   `workflow_dispatch` (TestPyPI).

## Phase 6 — Zenodo DOI  [HUMAN, one-time]
1. `https://zenodo.org/login` → **Log in with GitHub** → **Authorize**.
2. `https://zenodo.org/account/settings/github/` → toggle **SpinePrep/SpinePrep
   ON**.
3. Create the GitHub Release (Phase 5) *after* the toggle — Zenodo mints a DOI.
4. **[AUTO after]** Add the DOI badge to `README.md` and the `doi:` field to
   `CITATION.cff` (a commented-out placeholder badge is already in the README).

## Phase 7 — conda-forge  [HUMAN PR]
After the PyPI release exists, follow `recipe/README.md`: fill the sdist
`sha256` in `recipe/meta.yaml`, then open a PR to `conda-forge/staged-recipes`.

## Phase 8 — BIDS-Apps listing  [AUTO PR, after public]
Register on the BIDS Apps list by opening a PR to `bids-standard/bids-website`
adding this entry to `data/tools/apps.yml`:

```yaml
- gh: SpinePrep/SpinePrep
  status: active
  ds_type: raw
  datatype:
    - func
    - anat
  description: Reproducible BIDS-App preprocessing for human spinal-cord fMRI with per-vertebral-level QC.
  ci: gh
  branch: main
```

## Phase 9 — Seed NeuroStars  [HUMAN]
The `spineprep` tag exists as a URL but is empty until first use. Create a
neurostars.org account and make one introductory post tagged `spineprep` so the
support links in the docs and issue templates resolve to real content.

## Phase 10 — Local folder rename  [HUMAN]
Rename `/mnt/ssd1/SpinalfMRIprep` → `/mnt/ssd1/SpinePrep` and update references
(`.mcp.json`, the `qsm`/tmux session, the Claude memory dir key). Do this from
*outside* an active session in the old path, or the running shell's CWD breaks.

## Phase 11 — Announce  [HUMAN]
bioRxiv preprint → journal submission; announce on the docs site, the seeded
NeuroStars post, the GitHub Release, and OHBM/BrainHack if attending.

---

## Data governance (before going fully public / submitting)
- Balgrist **DUA sign-off** for referencing internal cohorts; only permitted
  data/derivatives shown publicly. Public OpenNeuro datasets cited by accession.
- Finalise author list + affiliations in `CITATION.cff` and the paper.

## Verify a fresh container build before announcing
```bash
docker build -f Dockerfile.spineprep \
  --build-arg GIT_SHA=$(git rev-parse HEAD) \
  --build-arg GIT_DESCRIBE=$(git describe --always --tags) \
  -t spineprep:26.0.0 .
scripts/container_smoke_test.sh spineprep:26.0.0 /path/to/bids <subject>
```

## Not required for the software release
- The **reliability × validity study** (manuscript centerpiece) is deferred; it
  gates the *paper*, not the tool. See the local (non-public) finalization spec.
