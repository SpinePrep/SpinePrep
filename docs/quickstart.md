# Try It

Run SpinalfMRIprep on sample data in under 5 minutes.

## Prerequisites

- Docker Desktop (or Apptainer/Singularity)
- 10 GB free disk space

## One-Command Install

```bash
# Clone and install
git clone https://github.com/SpinalfMRIprep/SpinalfMRIprep.git
cd SpinalfMRIprep
pip install poetry && poetry install
```

## Download Sample Data

SpinalfMRIprep provides a script to download a minimal test dataset from OpenNeuro:

```bash
# Download 1 subject from ds005884 (Motor task)
poetry run spinalfmriprep download-sample --dataset ds005884 --subjects 1
```

This downloads ~500 MB of data to `data/ds005884/`.

## Pull Container Images

```bash
docker pull vnmd/spinalcordtoolbox_7.2:20251215
```

## Run Preprocessing (BIDS-App)

SpinalfMRIprep is a standard BIDS-App: `<bids_dir> <output_dir> <analysis_level>`.

```bash
# participant level: per-subject preprocessing (S1..S9)
poetry run spinalfmriprep data/ds005884 work/tryit participant

# group level: cross-subject QC aggregation + release reports (S10)
poetry run spinalfmriprep data/ds005884 work/tryit group
```

The same interface works from the container or via `python -m spinalfmriprep`.
`--participant-label` is accepted for convention (v1 processes all subjects in
`bids_dir`).

## View Results

Open the release report in your browser:

```bash
open work/tryit/release/release_report.html        # group-level overview
# per-subject reports:
open work/tryit/release/*/sub-*/sub-*_qc_report.html
```

Each subject report shows an Include/Review/Exclude recommendation, per-run
functional cards with the step reportlets embedded, and the confound model;
the group report adds the inclusion table, QC-metric distributions, the
attrition waterfall, and per-vertebral-level views.

---

## Next Steps

| Goal | Page |
|------|------|
| Process your own data | [Install & Use](tutorial.md) |
| Understand the algorithms | [Methods](methods/overview.md) |
| Contribute to development | [Contribute](contributing.md) |
