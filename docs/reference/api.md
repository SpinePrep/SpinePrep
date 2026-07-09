# Python API

!!! warning "SpinePrep is a CLI / BIDS-App, not a library"
    The supported way to use SpinePrep is the command line — see the
    [CLI Reference](cli.md). The Python modules under `src/spineprep/` are an
    **internal library** that implements the pipeline. They are not a committed,
    stable public API: names, signatures, and structure can change between
    versions without notice. If you import them, pin the version. For anything
    reproducible, drive the CLI instead.

This page documents the package layout and the real entry points, for readers
who need to understand or extend the code.

## Package layout

The installed package is `spineprep` (`src/spineprep/`):

| Location | Contents |
|----------|----------|
| `spineprep.cli` | The command-line interface; `main()` is the packaged entry point (`pyproject.toml` maps `spineprep` to it). |
| `spineprep.bids_app` | The BIDS-App wrapper (`main_bids_app`, `run_bids_app`). |
| `spineprep.S0_setup` … `spineprep.S10_qc_aggregation_and_release` | One module per pipeline step. Each exposes the step's `run_*` and `check_*` functions. |
| `spineprep.steps` | Per-step subpackages (`s1` … `s10`) holding the processing and reporting internals each step module calls. |
| `spineprep.lib` | Shared helpers: `image`, `moco`, `denoise`, `run`, `chain_scope`, `viz_s4`. |
| `spineprep.policy` | `datasets` — loads and validates `policy/datasets.yaml`. |
| `spineprep.__version__` | The installed version string. |

## Main entry points

### The CLI

```python
from spineprep import cli

# Same as running `spineprep …` on the command line; returns an exit code.
exit_code = cli.main(["/data/bids", "/data/out", "participant"])
```

`cli.main(argv)` routes a standard BIDS-App invocation (first token is a path)
to the BIDS-App wrapper, and a `run`/`check` invocation to the per-step
interface. It returns an integer exit code.

### The BIDS-App wrapper

```python
from spineprep.bids_app import run_bids_app

exit_code = run_bids_app(
    bids_dir="/data/bids",
    output_dir="/data/out",
    analysis_level="participant",   # or "group"
    participant_label=["01", "07"], # optional; default all subjects
    batch_workers=1,
)
```

### Per-step functions

Each step module exposes a `run_<STEP>` function that executes the step and a
`check_<STEP>` function that re-evaluates its QC without reprocessing. They
return a small `StepResult` object with `status` (`"PASS"` / `"WARN"` / `"FAIL"`)
and a `failure_message`. For example:

```python
from spineprep.S2_anat_cordref import run_S2_anat_cordref, StepResult

result = run_S2_anat_cordref(
    dataset_key="my_dataset",
    bids_root="/data/bids",
    out="/data/out",
)
print(result.status, result.failure_message)
```

The exact signatures vary by step (batch variants, `reportlets_only` variants,
etc.); read the module or the dispatch in `spineprep.cli` for the current shape.
These are internal and may change — again, prefer the CLI for stable use.

## Related references

- [CLI Reference](cli.md) — the supported interface.
- [Configuration](config.md) — the policy YAML that drives each step.
- [Schemas Reference](schemas.md) — the QC JSON each step emits.
