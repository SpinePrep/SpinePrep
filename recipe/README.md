# conda-forge recipe

`meta.yaml` here is the recipe for publishing the SpinePrep **Python
orchestration layer** to [conda-forge](https://conda-forge.org/). Like the PyPI
package, it does **not** bundle SCT, FSL or ANTs — use the container recipe for a
complete runtime.

Submitting to conda-forge is a manual, reviewed process that cannot be fully
automated:

1. ✅ **Done** — the PyPI release is published (`spineprep 26.0.0`; the recipe's
   `source.url` points at its sdist).
2. ✅ **Done + verified** — `meta.yaml`'s `sha256`
   (`04fecd0d…ea88`) matches the PyPI sdist, which bundles `LICENSE` + `NOTICE`
   (so `license_file: LICENSE` resolves). To re-verify:
   ```bash
   pip download spineprep==26.0.0 --no-deps --no-binary :all: -d /tmp/sp
   sha256sum /tmp/sp/spineprep-26.0.0.tar.gz
   ```
3. ⬜ **[HUMAN — the only remaining step]** Fork
   [`conda-forge/staged-recipes`](https://github.com/conda-forge/staged-recipes),
   copy `meta.yaml` to `recipes/spineprep/meta.yaml`, and open a pull request.
4. ⬜ conda-forge's bot lints the recipe and a maintainer reviews it. Once merged,
   a `spineprep-feedstock` repo is created and future releases are bumped by the
   autotick bot. **Then add the conda-forge badge to the README** —
   `img.shields.io/conda/vn/conda-forge/spineprep` (it 404s until the feedstock
   exists).

Docs: <https://conda-forge.org/docs/maintainer/adding_pkgs/>
