"""Smoke tests for QC HTML generation."""

from __future__ import annotations

import tempfile
from pathlib import Path


def test_qc_index_html_exists():
    """Test that QC index page can be generated."""
    from spineprep.qc import build_qc_index

    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = Path(tmpdir)

        # Build minimal index
        html_path = build_qc_index(
            out_dir=out_dir,
            subjects=["sub-01"],
            pipeline_version="0.1.0-dev",
            doctor_status="pass",
        )

        assert html_path.exists()
        assert html_path.name == "index.html"

        # Check HTML content
        content = html_path.read_text()
        assert "<html" in content or "<!DOCTYPE" in content
        assert "SpinePrep" in content
        assert "0.1.0-dev" in content


def test_qc_subject_page():
    """Test that subject QC page can be generated."""
    from spineprep.qc import build_subject_qc

    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = Path(tmpdir)

        html_path = build_subject_qc(
            out_dir=out_dir,
            subject="sub-01",
            runs=[{"task": "rest", "run": "01", "nvols": 200}],
            motion_summary={"max_fd": 0.5, "mean_fd": 0.2},
        )

        assert html_path.exists()
        assert "sub-01" in html_path.name

        content = html_path.read_text()
        assert "sub-01" in content
        assert "motion" in content.lower()


def test_qc_no_external_cdn():
    """Test that QC HTML doesn't reference external CDNs."""
    from spineprep.qc import build_qc_index

    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = Path(tmpdir)

        html_path = build_qc_index(
            out_dir=out_dir,
            subjects=["sub-01"],
            pipeline_version="0.1.0-dev",
            doctor_status="pass",
        )

        content = html_path.read_text()

        # Should not reference external resources
        assert "cdn.jsdelivr.net" not in content
        assert "googleapis.com" not in content
        assert "cloudflare.com" not in content
        assert (
            "http://" not in content or "localhost" in content
        )  # Allow localhost for dev
        assert (
            "https://" not in content or "https://github.com" in content
        )  # Only repo link allowed


def test_qc_inline_css():
    """Test that QC HTML includes inline CSS."""
    from spineprep.qc import build_qc_index

    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = Path(tmpdir)

        html_path = build_qc_index(
            out_dir=out_dir,
            subjects=["sub-01"],
            pipeline_version="0.1.0-dev",
            doctor_status="pass",
        )

        content = html_path.read_text()

        # Should have inline CSS
        assert "<style>" in content and "</style>" in content


def test_qc_doctor_matrix():
    """Test that doctor matrix is included in QC."""
    from spineprep.qc import build_qc_index

    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = Path(tmpdir)

        # Create dummy doctor JSON
        doctor_json = out_dir / "provenance" / "doctor.json"
        doctor_json.parent.mkdir(parents=True, exist_ok=True)
        doctor_json.write_text('{"status": "pass", "platform": {"os": "Linux"}}')

        html_path = build_qc_index(
            out_dir=out_dir,
            subjects=["sub-01"],
            pipeline_version="0.1.0-dev",
            doctor_status="pass",
            doctor_json_path=doctor_json,
        )

        content = html_path.read_text()

        # Should include doctor info
        assert "doctor" in content.lower() or "environment" in content.lower()
        assert "pass" in content.lower() or "✓" in content or "green" in content


def test_qc_dag_svg_embed():
    """Test that DAG SVG can be embedded in QC."""
    from spineprep.qc import build_qc_index

    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = Path(tmpdir)

        # Create dummy DAG SVG
        dag_svg = out_dir / "provenance" / "dag.svg"
        dag_svg.parent.mkdir(parents=True, exist_ok=True)
        dag_svg.write_text('<svg><circle cx="50" cy="50" r="40"/></svg>')

        html_path = build_qc_index(
            out_dir=out_dir,
            subjects=["sub-01"],
            pipeline_version="0.1.0-dev",
            doctor_status="pass",
            dag_svg_path=dag_svg,
        )

        content = html_path.read_text()

        # Should embed or link to DAG
        assert "dag" in content.lower() or "workflow" in content.lower()
