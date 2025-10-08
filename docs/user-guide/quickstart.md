# Quickstart

Get SpinePrep running in 5 minutes on the tiny test dataset.

## Prerequisites

- Python 3.9+
- Spinal Cord Toolbox (SCT) 5.8+ with PAM50 data
- Git

## 1. Install

```bash
# Clone repository
git clone https://github.com/SpinePrep/SpinePrep.git
cd SpinePrep

# Create virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install SpinePrep
pip install -e .

# Install Snakemake
pip install snakemake

# Verify installation
spineprep version
# Expected: 0.1.0
```

## 2. Check Environment

```bash
spineprep doctor

# Expected output:
#   Overall Status: [✓] PASS  (or [⚠] WARN if optional deps missing)
#   [✓] SCT: ...
#   [✓] PAM50: ...
#   [✓] Python Packages: ...
```

**If doctor fails:**
- SCT not found: Install from [https://github.com/spinalcordtoolbox/spinalcordtoolbox](https://github.com/spinalcordtoolbox/spinalcordtoolbox)
- PAM50 missing: Run `sct_download_data -d PAM50`

## 3. Test Run (Tiny Fixture)

```bash
# Use included tiny test dataset
spineprep run \
  --bids tests/fixtures/bids_tiny \
  --out /tmp/spineprep-test \
  -n

# Expected output:
#   [dry-run] DAG exported to /tmp/spineprep-test/derivatives/spineprep/logs/provenance/dag.svg
#   [dry-run] Pipeline check complete

# Verify DAG was created
ls -lh /tmp/spineprep-test/derivatives/spineprep/logs/provenance/dag.svg
```

## 4. View QC Report (After Real Run)

For a real run (remove `-n`):

```bash
# Run on tiny fixture (skips heavy processing)
spineprep run \
  --bids tests/fixtures/bids_tiny \
  --out /tmp/spineprep-test

# Open QC report
xdg-open /tmp/spineprep-test/derivatives/spineprep/qc/index.html  # Linux
open /tmp/spineprep-test/derivatives/spineprep/qc/index.html      # macOS
```

## 5. Your Own Data

Create a minimal config:

```bash
cat > my_config.yaml << 'EOF'
pipeline_version: "0.1.0"
project_name: "MyStudy"

study:
  name: "MyStudyName"

paths:
  root: "/data/my-study"
  bids_dir: "{root}/bids"
  deriv_dir: "{root}/derivatives/spineprep"
  work_dir: "{root}/work"
  logs_dir: "{deriv_dir}/logs"

dataset:
  sessions: null
  runs_per_subject: null

acq:
  tr: 2.0
  slice_timing: "ascending"
  pe_dir: "AP"
  echo_spacing_s: null

options:
  denoise_mppca: true
  motion:
    engine: "sct+rigid3d"
    slice_axis: "IS"
    concat:
      mode: "session+task"
      require_same: ["tr", "pe_dir"]
  temporal_crop:
    enable: true
  censor:
    enable: true
    fd_thresh_mm: 0.5
    dvars_thresh: 1.5
  acompcor:
    enable: true
    tissues: ["cord", "wm", "csf"]
    n_components_per_tissue: 6

registration:
  enable: true
  template: PAM50

# See configs/base.yaml for all options
EOF

# Dry run to validate
spineprep run --config my_config.yaml -n

# Real run
spineprep run --config my_config.yaml
```

## Common Issues

### "PAM50 not found"

```bash
# Check SCT installation
echo $SCT_DIR

# Download PAM50 if missing
sct_download_data -d PAM50

# Verify
ls $SCT_DIR/data/PAM50/PAM50_t2.nii.gz
```

### "snakemake not found"

```bash
pip install snakemake
```

### "ModuleNotFoundError: No module named 'workflow'"

```bash
# Ensure running from repo root
cd /path/to/SpinePrep
spineprep run --config my_config.yaml
```

## Next Steps

- Read [Configuration Guide](../reference/config.md) for all options
- Review [Outputs](./outputs.md) to understand derivatives
- Check [QC Guide](./qc.md) for quality assessment
- See [Registration](./registration.md) for PAM50 details

## Getting Help

- **Documentation**: [https://spineprep.github.io](https://spineprep.github.io)
- **Issues**: [https://github.com/SpinePrep/SpinePrep/issues](https://github.com/SpinePrep/SpinePrep/issues)
- **Discussions**: [https://github.com/SpinePrep/SpinePrep/discussions](https://github.com/SpinePrep/SpinePrep/discussions)

## Example Dataset

Coming in v0.2.0: Public sample dataset with downloadable script.

