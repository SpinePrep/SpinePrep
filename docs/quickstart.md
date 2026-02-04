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

## Run Preprocessing

```bash
# Run all steps on the sample data
poetry run spinalfmriprep run all \
  --bids-root data/ds005884 \
  --out work/tryit
```

## View Results

Open the QC dashboard in your browser:

```bash
open work/tryit/derivatives/spinalfmriprep/qc_dashboard.html
```

You should see:
- ✅ S0 Setup: PASS
- ✅ S1 Input Verify: PASS  
- ✅ S2 Anat Cord Ref: PASS
- ✅ S3 Func Init: PASS

---

## Next Steps

| Goal | Page |
|------|------|
| Process your own data | [Install & Use](tutorial.md) |
| Understand the algorithms | [Methods](methods/overview.md) |
| Contribute to development | [Contribute](contributing.md) |
