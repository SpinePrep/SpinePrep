"""Tests for spineprep version command."""

from __future__ import annotations

import subprocess


def test_cli_version_command():
    """Test that 'spineprep version' prints version in semver format."""
    result = subprocess.run(
        ["spineprep", "version"],
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.returncode == 0
    output = result.stdout.strip()

    # Should print "spineprep X.Y.Z"
    assert output.startswith("spineprep ")

    # Extract version part
    version_str = output.split()[-1]

    # Validate semver format (X.Y.Z)
    parts = version_str.split(".")
    assert len(parts) == 3, f"Version should be X.Y.Z format, got {version_str}"

    # Each part should be a number
    for part in parts:
        assert (
            part.isdigit()
        ), f"Version part '{part}' should be numeric in {version_str}"


def test_version_import():
    """Test that __version__ is importable from package."""
    from spineprep import __version__

    assert __version__ is not None
    assert isinstance(__version__, str)
    assert len(__version__) > 0

    # Should be semver format
    parts = __version__.split(".")
    assert len(parts) == 3, f"Version should be X.Y.Z format, got {__version__}"
