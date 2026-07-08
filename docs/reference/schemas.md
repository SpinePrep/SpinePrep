# Schemas Reference

SpinePrep uses well-defined schemas for data exchange and quality control.

## QC Status Schema

Every step produces a `qc_status.json` file with the following structure:

```json
{
  "status": "PASS | WARN | FAIL",
  "failure_class": "INPUT | TOOL | QUALITY | INFRA | UNKNOWN",
  "failure_reason": "Human-readable explanation",
  "primary_evidence": ["path/to/reportlet.png"],
  "suspected_root_causes": ["Ordered list of hypotheses"],
  "next_actions": ["Ordered list of recommended actions"],
  "blocking": false
}
```

### Status Values

| Value | Meaning |
|-------|---------|
| `PASS` | Step completed successfully, outputs are valid |
| `WARN` | Step completed with minor issues, manual review recommended |
| `FAIL` | Step failed, outputs may be invalid or missing |

### Failure Classes

| Class | Meaning |
|-------|---------|
| `INPUT` | Problem with input data (missing files, bad format) |
| `TOOL` | External tool failure (SCT, FSL, etc.) |
| `QUALITY` | Output quality below threshold |
| `INFRA` | Infrastructure issue (disk, memory, container) |
| `UNKNOWN` | Unclassified failure |

## BIDS Derivatives

SpinePrep outputs follow [BIDS Derivatives](https://bids-specification.readthedocs.io/en/stable/derivatives/introduction.html) conventions:

```
derivatives/
└── spineprep/
    ├── dataset_description.json
    └── sub-XX/
        └── ses-YY/
            ├── anat/
            ├── func/
            └── figures/
```

## Configuration Schema

See [Config Reference](config.md) for the policy configuration schema.
