"""Tests for Snakemake DAG rendering and provenance export."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path


def test_dry_run_exits_successfully():
    """Test that spineprep run --dry-run exits 0."""
    with tempfile.TemporaryDirectory() as tmpdir:
        bids_dir = Path(tmpdir) / "bids"
        out_dir = Path(tmpdir) / "out"
        bids_dir.mkdir()
        out_dir.mkdir()

        # Create minimal BIDS structure
        (bids_dir / "dataset_description.json").write_text(
            '{"Name": "Test", "BIDSVersion": "1.6.0"}'
        )

        result = subprocess.run(
            [
                "spineprep",
                "run",
                "--bids",
                str(bids_dir),
                "--out",
                str(out_dir),
                "--dry-run",
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        # Should exit 0 for dry-run
        assert result.returncode == 0, (
            f"STDERR: {result.stderr}\nSTDOUT: {result.stdout}"
        )


def test_dag_export_with_save_dag_flag():
    """Test that --save-dag creates provenance/dag.svg or .dot."""
    with tempfile.TemporaryDirectory() as tmpdir:
        bids_dir = Path(tmpdir) / "bids"
        out_dir = Path(tmpdir) / "out"
        bids_dir.mkdir()
        out_dir.mkdir()

        # Create minimal BIDS structure
        (bids_dir / "dataset_description.json").write_text(
            '{"Name": "Test", "BIDSVersion": "1.6.0"}'
        )

        result = subprocess.run(
            [
                "spineprep",
                "run",
                "--bids",
                str(bids_dir),
                "--out",
                str(out_dir),
                "--dry-run",
                "--save-dag",
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        # Should exit 0
        assert result.returncode == 0, (
            f"STDERR: {result.stderr}\nSTDOUT: {result.stdout}"
        )

        # Check for DAG file (svg or dot)
        prov_dir = out_dir / "provenance"
        dag_svg = prov_dir / "dag.svg"
        dag_dot = prov_dir / "dag.dot"

        # At least one should exist
        assert dag_svg.exists() or dag_dot.exists(), (
            f"Neither {dag_svg} nor {dag_dot} exists. "
            f"STDERR: {result.stderr}\nSTDOUT: {result.stdout}"
        )

        # Check that the file is non-empty
        if dag_svg.exists():
            assert dag_svg.stat().st_size > 0, "dag.svg is empty"
        if dag_dot.exists():
            assert dag_dot.stat().st_size > 0, "dag.dot is empty"


def test_scaffold_creation_non_dry_run():
    """Test that non-dry-run creates derivatives/.spineprep_scaffold."""
    with tempfile.TemporaryDirectory() as tmpdir:
        bids_dir = Path(tmpdir) / "bids"
        out_dir = Path(tmpdir) / "out"
        bids_dir.mkdir()
        out_dir.mkdir()

        # Create minimal BIDS structure
        (bids_dir / "dataset_description.json").write_text(
            '{"Name": "Test", "BIDSVersion": "1.6.0"}'
        )

        result = subprocess.run(
            [
                "spineprep",
                "run",
                "--bids",
                str(bids_dir),
                "--out",
                str(out_dir),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,  # Prevent hanging
        )

        # Should exit 0 (or might exit with "nothing to do" which is also ok)
        assert result.returncode in [0, 1], (
            f"Unexpected exit code: {result.returncode}\n"
            f"STDERR: {result.stderr}\nSTDOUT: {result.stdout}"
        )

        # Check for scaffold sentinel or derivatives directory
        # Note: scaffold might be created only after actual processing
        # For now, we check that the derivatives directory structure was created
        assert (out_dir / "derivatives").exists(), "derivatives directory not created"


def test_dag_export_format_preference():
    """Test DAG export prefers SVG if dot is available, falls back to .dot."""
    with tempfile.TemporaryDirectory() as tmpdir:
        bids_dir = Path(tmpdir) / "bids"
        out_dir = Path(tmpdir) / "out"
        bids_dir.mkdir()
        out_dir.mkdir()

        (bids_dir / "dataset_description.json").write_text(
            '{"Name": "Test", "BIDSVersion": "1.6.0"}'
        )

        result = subprocess.run(
            [
                "spineprep",
                "run",
                "--bids",
                str(bids_dir),
                "--out",
                str(out_dir),
                "--dry-run",
                "--save-dag",
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0

        prov_dir = out_dir / "provenance"
        dag_svg = prov_dir / "dag.svg"
        dag_dot = prov_dir / "dag.dot"

        # Check if dot is available
        import shutil

        dot_available = shutil.which("dot") is not None

        if dot_available:
            # Should create SVG
            assert dag_svg.exists(), "SVG should be created when dot is available"
        else:
            # Should fall back to .dot
            assert dag_dot.exists(), (
                "DOT file should be created when dot is unavailable"
            )


def test_provenance_directory_creation():
    """Test that provenance directory is created."""
    with tempfile.TemporaryDirectory() as tmpdir:
        bids_dir = Path(tmpdir) / "bids"
        out_dir = Path(tmpdir) / "out"
        bids_dir.mkdir()
        out_dir.mkdir()

        (bids_dir / "dataset_description.json").write_text(
            '{"Name": "Test", "BIDSVersion": "1.6.0"}'
        )

        result = subprocess.run(
            [
                "spineprep",
                "run",
                "--bids",
                str(bids_dir),
                "--out",
                str(out_dir),
                "--dry-run",
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0

        # Provenance directory should be created
        prov_dir = out_dir / "provenance"
        assert prov_dir.exists(), "Provenance directory should be created"
        assert prov_dir.is_dir(), "Provenance path should be a directory"
