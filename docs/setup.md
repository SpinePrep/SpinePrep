# Getting Started

## Installation

SpinePrep is designed to run via **Docker** or **Apptainer** (Singularity) to ensure reproducibility.

### Prerequisites

- [Docker Engine](https://docs.docker.com/get-docker/) OR [Apptainer](https://apptainer.org/docs/user/main/quick_start.html)
- Python 3.11+
- Poetry (recommended)

### Installation

```bash
git clone https://github.com/spineprep/spineprep.git
cd spineprep
poetry install
```

## Project Structure

SpinePrep enforces a strict directory structure to ensure data integrity and workflow determinism.

### Workspace Naming
Work directories inside your project follow a canonical naming convention:

| Prefix | Description | Example |
|---|---|---|
| `wf_smoke_XXX` | **Smoke tests**: Quick validation on minimal test data. | `wf_smoke_001` |
| `wf_reg_XXX` | **Regression**: Validation runs on regression dataset keys. | `wf_reg_001` |
| `wf_full_XXX` | **Full runs**: v1 validation datasets, acceptance tests. | `wf_full_001` |

### Repo Hygiene
- **Data Safety**: Large datasets live in `datasets/` and are **ignored by git**.
- **Artifact Safety**: Runtime artifacts live in `work/` and `logs/` and are **ignored by git**.
