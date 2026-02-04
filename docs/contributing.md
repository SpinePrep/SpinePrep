# Contribute

Guidelines for contributing to SpinalfMRIprep development.

## Getting Started

### Development Setup

```bash
# Clone the repository
git clone https://github.com/SpinalfMRIprep/SpinalfMRIprep.git
cd SpinalfMRIprep

# Install in development mode
pip install poetry
poetry install

# Install pre-commit hooks
poetry run pre-commit install
```

### Run Tests

```bash
# Run all tests
poetry run pytest

# Run specific test file
poetry run pytest tests/test_S1_input_verify.py

# Run with coverage
poetry run pytest --cov=spinalfmriprep
```

---

## Development Workflow

### Branch Naming

| Type | Format | Example |
|------|--------|---------|
| Feature | `feat/short-description` | `feat/add-motion-correction` |
| Bug fix | `fix/short-description` | `fix/segmentation-crash` |
| Docs | `docs/short-description` | `docs/update-tutorial` |

### Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add slice-timing correction to S4
fix: handle missing JSON sidecar gracefully
docs: expand S1 method specification
test: add integration test for multi-session
```

### Pull Request Process

1. Create a feature branch from `main`
2. Make your changes with tests
3. Run `poetry run pytest` to ensure tests pass
4. Run `poetry run pre-commit run --all-files`
5. Open a PR with clear description
6. Address review feedback
7. Squash and merge when approved

---

## Code Style

### Python

- Follow PEP 8
- Use type hints
- Docstrings in Google style
- Maximum line length: 100 characters

### Pre-commit Hooks

The repository uses pre-commit for automated checks:

- `ruff` - Linting and formatting
- `mypy` - Type checking
- `pytest` - Test execution

---

## Adding a New Step

To add a new processing step (e.g., S12):

1. **Create the module**: `src/spinalfmriprep/S12_new_step.py`

2. **Implement required functions**:
   ```python
   def run_S12_new_step(...) -> StepResult:
       """Run the step."""
       ...
   
   def check_S12_new_step(...) -> StepResult:
       """Validate step outputs."""
       ...
   ```

3. **Add CLI integration**: Update `src/spinalfmriprep/cli.py`

4. **Add tests**: Create `tests/test_S12_new_step.py`

5. **Add documentation**: Create `docs/methods/S12_new_step.md`

6. **Update navigation**: Add to `mkdocs.yml`

---

## Reporting Issues

### Bug Reports

Please include:

- SpinalfMRIprep version (`poetry run spinalfmriprep --version`)
- Operating system
- Container runtime and version
- Minimal reproducible example
- Full error traceback

### Feature Requests

Open a GitHub issue with:

- Use case description
- Proposed solution
- Alternatives considered

---

## Contact

- **GitHub Issues**: [SpinalfMRIprep/SpinalfMRIprep](https://github.com/SpinalfMRIprep/SpinalfMRIprep/issues)
- **Discussions**: Use GitHub Discussions for questions

---

*Thank you for contributing to SpinalfMRIprep!*
