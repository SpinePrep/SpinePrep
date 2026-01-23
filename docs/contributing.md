# Contributing

## Development Workflow

We follow a structured workflow to ensure code quality and traceability.

### Branching & Commits
- **Branch per step**: Create branches like `step/S{N}-short-desc`.
- **Commit messages**: Use key prefix `S{N}: summary`. Include ticket IDs in the body if applicable.
- **Pull Requests**: Open early, push often.

### Environment Setup
```bash
poetry install
poetry run pre-commit install
```

### Running Tests
```bash
poetry run pytest -v
```
