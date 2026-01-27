# Validation

SpinalfMRIprep is validated on multiple public and internal datasets spanning diverse acquisition protocols and clinical populations.

## Validation Datasets

| Dataset | Source | Subjects | Task | Status |
|---------|--------|----------|------|--------|
| ds005884 | OpenNeuro | 20 | Motor | ✅ Regression |
| ds005883 | OpenNeuro | 20 | Pain | ✅ Regression |
| ds004386 | OpenNeuro | 15 | Rest | ✅ Regression |
| ds004616 | OpenNeuro | 12 | Hand Grasp | ✅ Regression |
| Balgrist Motor | Internal | 11 | Motor | ✅ Regression |

## Aggregate Metrics

!!! success "Current Validation Status"
    - **5 datasets** under continuous regression testing
    - **78 subjects** processed end-to-end
    - **100%** automated QC pass rate on regression suite

## Quality Control Outputs

Every preprocessing step generates:

1. **`qc_status.json`** - Machine-readable status (PASS/WARN/FAIL) with failure classification
2. **Reportlets** - Visual PNG figures for human inspection

### Example QC Reportlet

*QC reportlet examples will be added after initial validation runs.*

## Reproducibility

SpinalfMRIprep guarantees deterministic outputs:

- Containerized execution (Docker/Singularity)
- Pinned dependency versions
- Seed-controlled randomization where applicable

---

*For detailed QC specifications, see [Reference → Schemas](../reference/schemas.md).*
