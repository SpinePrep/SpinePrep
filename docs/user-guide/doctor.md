# `spineprep doctor`

Check your environment and emit a JSON report.

## Usage
```bash
spineprep doctor --out ./out [--pam50 /path/to/PAM50] [--json ./doctor.json] [--strict]
```

* **Status codes**: 0 pass, 2 warnings, 1 failure (or warnings with `--strict`).
* **Artifacts**: `<out>/provenance/doctor-YYYYmmdd_HHMMSS.json`.

## What is checked

* **SCT**: `sct_version` on PATH and version.
* **PAM50**: directory contains `PAM50_t1.nii.gz` and `PAM50_spinal_levels.nii.gz`.
* **Python deps**: presence and versions of common libraries.

If SCT or PAM50 are missing, status is **fail** with guidance in `notes`.
