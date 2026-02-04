# Validation

SpinalfMRIprep is validated on multiple public and internal datasets spanning diverse acquisition protocols and clinical populations.

## Validation Strategy

SpinalfMRIprep uses a two-tier validation approach:

| Tier | Description | Purpose |
|------|-------------|---------|
| **Benchmark** | 1 subject × all sessions per dataset | Fast cross-dataset coverage for continuous testing |
| **Full** | All subjects × all sessions | Complete validation (in progress) |

## Benchmark Datasets

Benchmark validation runs 1 representative subject from each dataset with all available sessions.

| Dataset | Source | Subjects | Sessions | Task | Status |
|---------|--------|----------|----------|------|--------|
| ds005884 | OpenNeuro | 1 | 1 | Motor | ✅ Benchmark |
| ds005883 | OpenNeuro | 1 | 1 | Pain | ✅ Benchmark |
| ds004386 | OpenNeuro | 1 | 2 | Rest | ✅ Benchmark |
| ds004616 | OpenNeuro | 1 | 2 | Hand Grasp | ✅ Benchmark |
| Balgrist Motor | Internal | 1 | 4 | Motor | ✅ Benchmark |

**Benchmark totals**: 5 subjects, 10 subject-sessions

## Full Validation Datasets

Full validation will process all selected subjects across all sessions.

| Dataset | Source | Subjects | Sessions | Task | Status |
|---------|--------|----------|----------|------|--------|
| ds005884 | OpenNeuro | 38 | 1 | Motor | 🔄 In Progress |
| ds005883 | OpenNeuro | 38 | 1 | Pain | 🔄 In Progress |
| ds004386 | OpenNeuro | 48 | 2 | Rest | 🔄 In Progress |
| ds004616 | OpenNeuro | 24 | 2 | Hand Grasp | 🔄 In Progress |
| Balgrist Motor | Internal | 11 | 4 | Motor | 🔄 In Progress |

**Full validation totals**: 159 subjects, 264 subject-sessions

## Aggregate Metrics

!!! info "Validation In Progress"
    - **5 datasets** under benchmark testing
    - **5 subjects** (10 subject-sessions) in benchmark suite
    - **159 subjects** (264 subject-sessions) planned for full validation
    - Full validation metrics will be reported upon completion

## Quality Control Outputs

Every preprocessing step generates:

1. **`qc_status.json`** - Machine-readable status (PASS/WARN/FAIL) with failure classification
2. **Reportlets** - Visual PNG figures for human inspection

### Example QC Reportlet

*QC reportlet examples will be added after initial validation runs.*

## Reproducibility

SpinalfMRIprep guarantees deterministic outputs:

- Containerized execution (Docker/Apptainer)
- Pinned dependency versions
- Seed-controlled randomization where applicable

---

*For detailed QC specifications, see [Reference → Schemas](../reference/schemas.md).*
