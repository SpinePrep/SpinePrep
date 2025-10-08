# Contributing to SpinePrep

Thank you for your interest in contributing to SpinePrep! This guide will help you get started with development, understand our processes, and make your first contribution.

## Development Setup

### Prerequisites

- Python 3.8+
- Git
- FSL (version 6.0+)
- Spinal Cord Toolbox (SCT)
- Docker (optional, for containerized development)

### Installation

1. **Fork and clone the repository**:
   ```bash
   git clone https://github.com/your-username/spineprep.git
   cd spineprep
   ```

2. **Create a virtual environment**:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install in development mode**:
   ```bash
   pip install -e .
   pip install -r requirements-dev.txt
   ```

4. **Install pre-commit hooks**:
   ```bash
   pre-commit install
   ```

### Development Environment

```bash
# Install development dependencies
pip install -r requirements-dev.txt

# Install pre-commit hooks
pre-commit install

# Run tests
pytest

# Run linting
ruff check .
ruff format .

# Run type checking
mypy spineprep/
```

## Development Workflow

### Branch Naming

Use the following branch naming convention:

```
feat/spi-###-<kebab-slug>
fix/spi-###-<kebab-slug>
docs/spi-###-<kebab-slug>
```

Examples:
- `feat/spi-011-docs-site`
- `fix/spi-012-motion-bug`
- `docs/spi-013-api-docs`

### Commit Messages

Follow the Conventional Commits specification:

```
<type>(<scope>): <imperative summary>  [spi-###]
```

Examples:
- `feat(confounds): add motion regressors  [spi-042]`
- `fix(registration): correct template path  [spi-043]`
- `docs(api): add function documentation  [spi-044]`

### Pull Request Process

1. **Create a feature branch**:
   ```bash
   git checkout -b feat/spi-###-your-feature
   ```

2. **Make your changes**:
   - Write code following our style guidelines
   - Add tests for new functionality
   - Update documentation as needed

3. **Run tests and linting**:
   ```bash
   pytest
   ruff check .
   ruff format .
   mypy spineprep/
   ```

4. **Commit your changes**:
   ```bash
   git add .
   git commit -m "feat(scope): your change description  [spi-###]"
   ```

5. **Push and create a pull request**:
   ```bash
   git push origin feat/spi-###-your-feature
   ```

## Code Style Guidelines

### Python Code

- Follow PEP 8 style guidelines
- Use type hints for all functions
- Write docstrings for all public functions
- Use meaningful variable names
- Keep functions small and focused

### Example

```python
def calculate_framewise_displacement(
    motion_params: np.ndarray,
    radius: float = 50.0
) -> np.ndarray:
    """Calculate framewise displacement from motion parameters.

    Args:
        motion_params: Motion parameters (6 columns: 3 translation, 3 rotation)
        radius: Head radius for rotation to translation conversion

    Returns:
        Framewise displacement values
    """
    # Implementation here
    pass
```

### Configuration Files

- Use YAML for configuration files
- Follow consistent indentation (2 spaces)
- Use descriptive key names
- Include comments for complex options

### Documentation

- Use Markdown for documentation
- Follow the existing documentation structure
- Include code examples
- Use clear, concise language

## Testing

### Test Structure

```
tests/
├── unit/           # Unit tests
├── integration/    # Integration tests
└── fixtures/       # Test data and configurations
```

### Writing Tests

```python
def test_calculate_framewise_displacement():
    """Test framewise displacement calculation."""
    # Arrange
    motion_params = np.array([[0, 0, 0, 0, 0, 0],
                             [1, 1, 1, 0.1, 0.1, 0.1]])

    # Act
    fd = calculate_framewise_displacement(motion_params)

    # Assert
    assert len(fd) == 1
    assert fd[0] > 0
```

### Running Tests

```bash
# Run all tests
pytest

# Run specific test file
pytest tests/unit/test_motion.py

# Run with coverage
pytest --cov=spineprep

# Run integration tests
pytest tests/integration/
```

## CI/CD Pipeline

### GitHub Actions

Our CI pipeline includes:

1. **Code Quality**:
   - Linting with `ruff`
   - Formatting with `ruff format`
   - Type checking with `mypy`

2. **Testing**:
   - Unit tests with `pytest`
   - Integration tests
   - Coverage reporting

3. **Documentation**:
   - Build documentation with `mkdocs`
   - Check links with `lychee`
   - Spell checking with `codespell`

4. **Deployment**:
   - Build and test Docker images
   - Deploy documentation to GitHub Pages

### Required Checks

All pull requests must pass:

- [ ] Code linting (`ruff check .`)
- [ ] Code formatting (`ruff format .`)
- [ ] Type checking (`mypy spineprep/`)
- [ ] Unit tests (`pytest tests/unit/`)
- [ ] Integration tests (`pytest tests/integration/`)
- [ ] Documentation build (`mkdocs build --strict`)
- [ ] Link checking (`lychee docs/`)

## Documentation

### Documentation Structure

```
docs/
├── index.md              # Landing page
├── getting-started.md     # Installation and quick start
├── user-guide/           # User documentation
├── reference/            # API and configuration reference
├── how-tos/              # Tutorials and guides
├── contributing.md       # This file
└── CHANGELOG.md          # Release notes
```

### Writing Documentation

1. **Use clear, concise language**
2. **Include code examples**
3. **Provide context and motivation**
4. **Use consistent formatting**
5. **Include screenshots for complex procedures**

### Documentation Build

```bash
# Build documentation locally
mkdocs serve

# Build for production
mkdocs build --strict

# Check links
lychee docs/
```

## Release Process

### Version Numbering

We use semantic versioning (MAJOR.MINOR.PATCH):

- **MAJOR**: Breaking changes
- **MINOR**: New features (backward compatible)
- **PATCH**: Bug fixes (backward compatible)

### Release Checklist

- [ ] Update version in `pyproject.toml`
- [ ] Update `CHANGELOG.md`
- [ ] Run full test suite
- [ ] Build documentation
- [ ] Create release tag
- [ ] Publish to PyPI
- [ ] Update documentation

## Getting Help

### Communication Channels

- **GitHub Issues**: Bug reports and feature requests
- **GitHub Discussions**: Questions and general discussion
- **Email**: Contact maintainers directly

### Asking Questions

When asking questions, please include:

1. **SpinePrep version**: `spineprep --version`
2. **Python version**: `python --version`
3. **Operating system**: `uname -a`
4. **Error messages**: Full error traceback
5. **Configuration**: Relevant configuration files
6. **Data information**: BIDS structure and data characteristics

### Reporting Bugs

When reporting bugs, please include:

1. **Clear description** of the problem
2. **Steps to reproduce** the issue
3. **Expected behavior** vs. actual behavior
4. **Environment information** (OS, Python, dependencies)
5. **Configuration files** (anonymized)
6. **Error logs** and tracebacks

## Code of Conduct

### Our Pledge

We are committed to providing a welcoming and inclusive environment for all contributors, regardless of:

- Age, body size, disability, ethnicity
- Gender identity and expression
- Level of experience, education
- Nationality, personal appearance
- Race, religion, sexual orientation

### Expected Behavior

- Use welcoming and inclusive language
- Be respectful of differing viewpoints
- Accept constructive criticism gracefully
- Focus on what's best for the community
- Show empathy towards other community members

### Unacceptable Behavior

- Harassment, trolling, or insulting comments
- Public or private harassment
- Publishing private information without permission
- Inappropriate sexual attention or advances
- Other unprofessional conduct

## Recognition

### Contributors

We recognize all contributors in our documentation and release notes. Contributors are listed in:

- `CONTRIBUTORS.md`
- Release notes
- Documentation acknowledgments

### Types of Contributions

We welcome many types of contributions:

- **Code**: Bug fixes, new features, performance improvements
- **Documentation**: User guides, API documentation, tutorials
- **Testing**: Test cases, test data, test infrastructure
- **Design**: User interface, user experience, accessibility
- **Community**: Helping others, answering questions, mentoring

## License

By contributing to SpinePrep, you agree that your contributions will be licensed under the same license as the project (see `LICENSE` file).

## Thank You

Thank you for contributing to SpinePrep! Your contributions help make spinal cord neuroimaging more accessible and reproducible for the entire community.
