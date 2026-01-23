# SpinePrep Documentation Cache

This directory contains cached vendor documentation for offline access by agents.

## SCT Documentation

Spinal Cord Toolbox (SCT) documentation is cached here for the pinned SCT version used by SpinePrep.

### Fetching SCT Docs

To download the published SCT documentation for the pinned version:

```bash
./scripts/fetch_sct_docs.sh
```

The script will:
- Infer the SCT version from the pinned image tag in `S0_setup.py` (currently `vnmd/spinalcordtoolbox_7.2:20251215` → version `7.2`)
- Download the published HTML documentation zip from ReadTheDocs
- Extract it to `docs/vendor/sct/<VERSION>/site/`
- Write provenance metadata to `docs/vendor/sct/<VERSION>/PROVENANCE.txt`

You can override the version explicitly:

```bash
SCT_VERSION=7.2 ./scripts/fetch_sct_docs.sh
```

### Viewing Offline

After fetching, view the documentation locally:

```bash
cd docs/vendor/sct/7.2/site
python -m http.server 8000
```

Then open `http://localhost:8000` in your browser.

If the archive extracts to a subdirectory (e.g., `spinalcordtoolbox-7.2/`), adjust the path:

```bash
cd docs/vendor/sct/7.2/site/spinalcordtoolbox-7.2
python -m http.server 8000
```

### Notes

- The cached docs are **gitignored** (`docs/vendor/` is in `.gitignore`)
- This is an **opt-in** script; it does not run as part of any SpinePrep pipeline step
- The script tries htmlzip first, then falls back to wget mirroring if htmlzip is unavailable
- If version-specific docs (e.g., `7.2`) aren't published, you can try `SCT_VERSION=latest` to fetch the latest published docs
- Provenance (URL, SHA256, SCT image digest) is recorded in `PROVENANCE.txt` for auditability

