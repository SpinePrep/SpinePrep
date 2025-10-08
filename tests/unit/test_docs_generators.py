"""Tests for documentation generators."""

import json
import subprocess


def test_config_ref_builds(tmp_path):
    """Test that config reference generator builds successfully."""

    # Create a minimal schema for testing
    schema_path = tmp_path / "test_schema.json"
    test_schema = {
        "type": "object",
        "properties": {
            "test_option": {
                "type": "string",
                "default": "test_value",
                "description": "A test option",
            }
        },
    }
    with open(schema_path, "w") as f:
        json.dump(test_schema, f)

    # Run the generator
    output_path = tmp_path / "config.md"
    subprocess.check_call(
        [
            "python",
            "scripts/gen_docs_config_ref.py",
            "--schema",
            str(schema_path),
            "--out",
            str(output_path),
        ]
    )

    assert output_path.exists()
    content = output_path.read_text()
    assert "test_option" in content
    assert "test_value" in content


def test_api_ref_builds(tmp_path, monkeypatch):
    """Test that API reference generator builds successfully."""
    # Create a minimal test module
    test_module_path = tmp_path / "test_module.py"
    test_module_path.write_text(
        '''
"""Test module for API reference generation."""

def test_function(param1: str, param2: int = 42) -> str:
    """Test function with parameters.

    Args:
        param1: First parameter
        param2: Second parameter with default

    Returns:
        A test string
    """
    return f"{param1}_{param2}"


class TestClass:
    """Test class for API reference generation."""

    def __init__(self, value: str):
        """Initialize test class.

        Args:
            value: Initial value
        """
        self.value = value

    def method(self, x: int) -> str:
        """Test method.

        Args:
            x: Input value

        Returns:
            Processed value
        """
        return f"{self.value}_{x}"
'''
    )

    # Run the generator
    output_path = tmp_path / "api.md"
    subprocess.check_call(
        [
            "python",
            "scripts/gen_docs_api_ref.py",
            "--lib-dir",
            str(tmp_path),
            "--out",
            str(output_path),
        ]
    )

    assert output_path.exists()
    content = output_path.read_text()
    assert "test_function" in content
    assert "TestClass" in content
