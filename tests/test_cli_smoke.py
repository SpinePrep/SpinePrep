"""Smoke tests for CLI scaffold."""

from __future__ import annotations

import subprocess
from pathlib import Path


def test_version_command():
    """spineprep version should print semver."""
    result = subprocess.run(
        ["spineprep", "version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"version command failed: {result.stderr}"
    output = result.stdout.strip()
    # Check it's a valid version string
    assert len(output) > 0, f"Expected version output, got empty: {output}"
    assert "dev" in output or "." in output, f"Expected version format, got: {output}"


def test_print_config(tmp_path):
    """spineprep run --print-config should emit resolved config."""
    # Create minimal config
    config_file = tmp_path / "test.yaml"
    config_file.write_text(
        """
project_name: Test
paths:
  bids_dir: /tmp/test/bids
  deriv_dir: /tmp/test/derivatives
  logs_dir: "{deriv_dir}/logs"
study:
  name: TestStudy
"""
    )

    out_dir = tmp_path / "out"

    result = subprocess.run(
        [
            "spineprep",
            "run",
            "--config",
            str(config_file),
            "--out",
            str(out_dir),
            "--print-config",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"print-config failed: {result.stderr}"

    # Output should be valid YAML
    output = result.stdout
    assert "paths" in output
    assert "project_name" in output or "Test" in output


def test_dag_export_dry_run(tmp_path):
    """spineprep run -n should materialize DAG and save dag.svg."""
    # Create minimal config with output directory
    out_dir = tmp_path / "out"

    config_file = tmp_path / "test.yaml"
    config_file.write_text(
        f"""
project_name: Test
paths:
  bids_dir: /tmp/test/bids
  deriv_dir: {out_dir}
  logs_dir: "{{deriv_dir}}/logs"
study:
  name: TestStudy
"""
    )

    result = subprocess.run(
        ["spineprep", "run", "--config", str(config_file), "--out", str(out_dir), "-n"],
        capture_output=True,
        text=True,
        check=False,
        cwd=Path(__file__).parent.parent,  # Run from repo root
    )

    # Command should succeed (dry run)
    assert result.returncode == 0, f"dry run failed: {result.stderr}\n{result.stdout}"

    # DAG should be exported
    dag_svg = out_dir / "provenance" / "dag.svg"
    assert dag_svg.exists(), f"DAG not exported to {dag_svg}"

    # DAG should contain SVG content
    content = dag_svg.read_text()
    assert "<svg" in content or "digraph" in content, (
        "DAG file doesn't contain expected content"
    )


def test_doctor_command():
    """spineprep doctor should run and report dependencies."""
    result = subprocess.run(
        ["spineprep", "doctor"],
        capture_output=True,
        text=True,
        check=False,
    )
    # Doctor should complete (may pass/warn/fail depending on environment)
    # Exit codes: 0=pass, 1=fail, 2=warn
    assert result.returncode in [
        0,
        1,
        2,
    ], f"doctor command had unexpected exit code: {result.returncode}"
    # Should print something
    output = result.stdout + result.stderr
    assert len(output) > 0, "doctor command produced no output"
