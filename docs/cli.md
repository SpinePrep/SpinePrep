# Command Line Interface

SpinePrep provides a command-line interface with the following commands:

## Commands

### `spineprep version`

Display the version of SpinePrep.

```bash
spineprep version
```

**Output:**
```
spineprep 0.2.0
```

---

### `spineprep doctor`

Check the environment and dependencies. Validates that required tools (SCT, PAM50) are available and writes a diagnostic report.

```bash
spineprep doctor [OPTIONS]
```

**Options:**

- `--out PATH` — Output directory for provenance files (default: `./out`)
- `--pam50 PATH` — Explicit path to PAM50 template directory
- `--json PATH` — Write additional copy of report to custom JSON path
- `--strict` — Treat warnings as failures

**Example:**
```bash
spineprep doctor --out /data/derivatives/spineprep
```

**Output:**
Prints a table of environment diagnostics and writes a timestamped JSON report to `{out}/provenance/doctor-YYYYMMDD_HHMMSS.json`.

---

### `spineprep run`

Run the preprocessing pipeline with configuration validation.

```bash
spineprep run --bids BIDS_ROOT --out OUTPUT_DIR [OPTIONS]
```

**Options:**

- `--bids PATH` — Path to BIDS dataset root directory (required)
- `--out PATH` — Path to output directory for derivatives (required)
- `--config PATH` — Path to YAML configuration file (optional)
- `--print-config` — Print the fully resolved configuration and exit
- `-n`, `--dry-run` — Dry-run mode: export DAG without running pipeline

**Example:**
```bash
# Print resolved config
spineprep run --bids /data/bids --out /data/derivatives/spineprep \
  --config my_config.yaml --print-config

# Run pipeline
spineprep run --bids /data/bids --out /data/derivatives/spineprep
```

**Config Precedence:**
Configuration values are merged in the following order (later overrides earlier):
1. Built-in defaults (`configs/base.yaml`)
2. User YAML file (`--config`)
3. CLI arguments (`--bids`, `--out`)

---

## Configuration

See [Configuration Guide](user-guide/config.md) for details on YAML structure, precedence rules, and available options.

For schema reference, see [Config Reference](reference/config.md).
