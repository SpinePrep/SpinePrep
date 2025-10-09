# Workflow Architecture

SpinePrep uses [Snakemake](https://snakemake.readthedocs.io/) to orchestrate the preprocessing pipeline. This page describes the workflow structure, DAG generation, and provenance tracking.

## Pipeline Overview

The SpinePrep workflow is defined in `workflow/Snakefile` and consists of modular rules that:

1. Create BIDS-Derivatives directory structure
2. Export DAG visualization for provenance
3. Process functional and anatomical images
4. Generate quality control reports

## Workflow Rules

### `rule all`

The main target rule that specifies all final outputs:
- DAG visualization (`provenance/dag.svg` or `provenance/dag.dot`)
- Derivatives scaffold sentinel (`.spineprep_scaffold`)

### `rule derivatives_scaffold`

Creates the BIDS-Derivatives directory structure:

```
{output_dir}/
└── derivatives/
    └── spineprep/
        ├── dataset_description.json
        ├── logs/
        ├── reports/
        └── .spineprep_scaffold
```

The `dataset_description.json` file includes:
- Pipeline name and version
- BIDS version compliance
- Generated-by metadata

### `rule dag_svg`

Exports the workflow DAG as a visual graph:

- **Format**: SVG if Graphviz (`dot`) is available, otherwise DOT (plain text)
- **Location**: `{output_dir}/provenance/dag.svg` or `.dot`
- **Content**: Shows all rules, dependencies, and output files

**Example DAG:**
The DAG shows the dependency graph of all workflow rules, making it easy to understand:
- Which steps run in which order
- Which outputs depend on which inputs
- Parallelization opportunities

## Provenance Tracking

All workflow metadata is stored in the provenance directory:

```
{output_dir}/provenance/
├── dag.svg          # Workflow visualization
└── doctor-*.json    # Environment diagnostics
```

### Provenance Directory

Location: `{output_dir}/provenance/`

Contains:
- **DAG visualization** (`dag.svg` or `dag.dot`) - Workflow graph
- **Doctor reports** (`doctor-YYYYMMDD_HHMMSS.json`) - Environment checks
- **Future**: Processing logs, parameter snapshots, software versions

### Derivatives Directory

Location: `{output_dir}/derivatives/spineprep/`

Structure follows BIDS-Derivatives specification:
- `dataset_description.json` - Dataset metadata
- `logs/` - Processing logs and manifests
- `reports/` - QC HTML reports
- Subject-level subdirectories (e.g., `sub-01/`)

## Running the Workflow

### Basic Execution

```bash
spineprep run --bids /data/bids --out /data/derivatives
```

### Dry Run (Validation)

```bash
spineprep run --bids /data/bids --out /data/derivatives --dry-run
```

Dry-run mode:
- Resolves the workflow DAG
- Shows which rules would execute
- Validates file dependencies
- Does NOT execute any processing

### Export DAG

```bash
spineprep run --bids /data/bids --out /data/derivatives --dry-run --save-dag
```

Creates `{out}/provenance/dag.svg` (or `.dot` if Graphviz unavailable).

### Parallel Execution

```bash
spineprep run --bids /data/bids --out /data/derivatives --cores 8
```

Snakemake will automatically parallelize independent jobs across 8 cores.

## Environment Variables

The workflow uses environment variables to pass configuration:

- `SPINEPREP_BIDS_ROOT` - Path to BIDS dataset
- `SPINEPREP_OUTPUT_DIR` - Path to output directory
- `PYTHONPATH` - Extended to include SpinePrep modules

These are set automatically by `spineprep run`.

## Snakemake Integration

SpinePrep invokes Snakemake with the following flags:

- `--snakefile workflow/Snakefile` - Workflow definition
- `--cores N` - Number of parallel jobs
- `--printshellcmds` - Show shell commands being executed
- `--reason` - Explain why each rule is executed
- `-n` - Dry-run mode (when `--dry-run` specified)

## Future Enhancements

Planned workflow features:

- **Checkpoints** for dynamic input discovery
- **Resource profiling** (memory, CPU time per rule)
- **Cluster integration** (SLURM, SGE, etc.)
- **Container support** (Singularity/Docker)
- **Detailed provenance logs** for each processing step

## See Also

- [Configuration Guide](user-guide/config.md) - Config file format and options
- [Command Line Interface](cli.md) - CLI reference
- [Snakemake Documentation](https://snakemake.readthedocs.io/) - Workflow engine docs

