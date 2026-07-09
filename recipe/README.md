# conda-forge recipe

`meta.yaml` here is the recipe for publishing the SpinePrep **Python
orchestration layer** to [conda-forge](https://conda-forge.org/). Like the PyPI
package, it does **not** bundle SCT, FSL or ANTs — use the container recipe for a
complete runtime.

Submitting to conda-forge is a manual, reviewed process that cannot be fully
automated:

1. Publish the PyPI release first (the recipe's `source.url` points at the PyPI
   sdist).
2. Get the sdist checksum and paste it into `meta.yaml`:
   ```bash
   pip download spineprep==1.0.0 --no-deps --no-binary :all: -d /tmp/sp
   sha256sum /tmp/sp/spineprep-1.0.0.tar.gz
   ```
3. Fork [`conda-forge/staged-recipes`](https://github.com/conda-forge/staged-recipes),
   copy this file to `recipes/spineprep/meta.yaml`, and open a pull request.
4. conda-forge's bot lints the recipe and a maintainer reviews it. Once merged, a
   `spineprep-feedstock` repo is created and future releases are updated by the
   autotick bot.

Docs: <https://conda-forge.org/docs/maintainer/adding_pkgs/>
