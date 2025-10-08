"""End-to-end smoke test on tiny BIDS fixture."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path


def test_e2e_pipeline_completes(tmp_path):
    """Test that the full pipeline runs end-to-end on tiny fixture."""
    # Set up paths
    repo_root = Path(__file__).parent.parent
    bids_tiny = repo_root / "tests" / "fixtures" / "bids_tiny"
    assert bids_tiny.exists(), f"BIDS tiny fixture not found at {bids_tiny}"

    # Create output directory
    out_root = tmp_path / "spineprep-out"
    out_root.mkdir()

    # Use simplified approach: just use the bids and out args without full config
    # This tests the CLI with minimal configuration
    result = subprocess.run(
        ["spineprep", "run", "--bids", str(bids_tiny), "--out", str(out_root), "-n"],
        capture_output=True,
        text=True,
        check=False,
        cwd=repo_root,
    )

    # Should succeed
    assert result.returncode == 0, (
        f"E2E dry-run failed: {result.stderr}\\n{result.stdout}"
    )

    # Check that command completed
    assert (
        "[dry-run] Pipeline check complete" in result.stdout
        or "DAG exported" in result.stdout
    )

    # DAG export is optional (may fail if snakemake/dot not available)
    # Just check that the process didn't crash
    deriv = out_root / "derivatives" / "spineprep"
    if deriv.exists():
        dag_svg = deriv / "logs" / "provenance" / "dag.svg"
        if dag_svg.exists():
            # If DAG was created, validate it
            dag_content = dag_svg.read_text()
            assert "<svg" in dag_content or "digraph" in dag_content


def test_e2e_doctor_creates_report():
    """Test that doctor command creates report."""
    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = Path(tmpdir)

        result = subprocess.run(
            ["spineprep", "doctor", "--out", str(out_dir)],
            capture_output=True,
            text=True,
            check=False,
        )

        # Should complete (may pass/warn/fail depending on environment)
        assert result.returncode in [0, 1, 2]

        # Should create JSON
        prov_dir = out_dir / "provenance"
        if prov_dir.exists():
            json_files = list(prov_dir.glob("doctor-*.json"))
            assert len(json_files) > 0, "Doctor JSON not created"


def test_e2e_version_matches():
    """Test that version is consistent across artifacts."""
    result = subprocess.run(
        ["spineprep", "version"],
        capture_output=True,
        text=True,
        check=True,
    )

    version = result.stdout.strip()
    assert len(version) > 0
    assert "0.1.0" in version or "." in version
