# Quality Control (QC)

SpinePrep generates self-contained HTML quality control reports for visual inspection of preprocessing results.

## Overview

QC reports are static HTML pages with:
- **No external dependencies** (inline CSS, embedded images)
- **No JavaScript** (pure HTML/CSS)
- **Self-contained** (can be opened offline)
- **Portable** (can be zipped and shared)

## Output Location

QC files are written to:

```
derivatives/spineprep/
├── qc/
│   ├── index.html              # Main QC landing page
│   ├── sub-01_qc.html          # Per-subject pages
│   ├── sub-02_qc.html
│   └── ...
└── logs/
    └── provenance/
        ├── dag.svg             # Workflow graph
        └── doctor-*.json       # Environment snapshot
```

## How to View

### Locally

Open in any web browser:

```bash
# Linux/macOS
xdg-open derivatives/spineprep/qc/index.html
open derivatives/spineprep/qc/index.html

# Windows
start derivatives/spineprep/qc/index.html
```

### From CI Artifacts

When running on CI, QC pages are bundled into `qc-bundle.zip`:

1. Download artifact from GitHub Actions
2. Unzip
3. Open `qc/index.html` in browser

## QC Index Page

The main index page includes:

### Environment Check
- **Doctor status**: pass/warn/fail with color coding
- **Platform**: OS, Python version
- **Dependencies**: SCT, Python packages

### Subject List
- Links to per-subject QC pages
- Total subject count

### Workflow DAG
- Link to workflow graph (SVG)
- Shows rule dependencies

## Per-Subject QC Pages

Each subject page includes:

### Motion Summary
- **Max FD**: Maximum framewise displacement across all runs
- **Mean FD**: Average framewise displacement
- Table of per-run statistics

### Run Details
- Task, run number, volume count
- Links to individual run reports (if generated)

### Warnings
- Registration quality issues
- High motion volumes
- Censored frame counts

## What's Included

**Current MVP:**
- Environment diagnostics
- Subject/run manifest
- Motion summaries
- Workflow DAG link

**Future Enhancements:**
- Motion plots (FD/DVARS timeseries)
- Registration before/after overlays
- aCompCor explained variance plots
- SNR maps
- Interactive slice viewers

## Design Principles

### Self-Contained
- All CSS inline (no external stylesheets)
- Images base64-encoded or relative paths within bundle
- No CDN dependencies
- Works without internet connection

### Accessible
- Semantic HTML
- High contrast for readability
- Mobile-responsive (viewport meta tag)
- Keyboard navigable

### Fast Loading
- Minimal JavaScript (none in MVP)
- Small file sizes
- Lazy loading for images (future)

## CI Integration

GitHub Actions automatically:
1. Runs E2E smoke test
2. Generates QC pages
3. Creates `qc-bundle.zip` with:
   - QC HTML pages
   - DAG SVG
   - Doctor JSON
   - Provenance files
4. Uploads as artifact (30-day retention)

### Downloading from CI

```bash
# Via GitHub CLI
gh run download <run-id> -n qc-bundle

# Or from web UI
# Actions → Workflow run → Artifacts → qc-bundle.zip
```

## Troubleshooting

- **Blank pages**: Check browser console for errors (shouldn't happen with static HTML)
- **Missing images**: Ensure relative paths are correct when zipping
- **Broken links**: Subject pages must be in same directory as index
- **Styling issues**: All CSS is inline; check for special characters in data

## Example QC Workflow

```bash
# 1. Run pipeline
spineprep run --bids /data/bids --out /data/out

# 2. QC pages generated automatically in:
ls /data/out/derivatives/spineprep/qc/

# 3. Open main page
xdg-open /data/out/derivatives/spineprep/qc/index.html

# 4. Review each subject
# 5. Download and archive for records:
cd /data/out/derivatives/spineprep
zip -r qc-archive.zip qc/ logs/provenance/
```

## QC Checklist

When reviewing QC, check for:

- [ ] Doctor status is **pass** (green)
- [ ] All expected subjects present
- [ ] Motion FD < 0.5mm for most volumes
- [ ] No excessive censored frames (> 50%)
- [ ] DAG matches expected workflow
- [ ] No error messages in logs

## Color Coding

- **Green** (✓): Pass - acceptable quality
- **Yellow** (⚠): Warning - review recommended
- **Red** (✗): Fail - attention required
