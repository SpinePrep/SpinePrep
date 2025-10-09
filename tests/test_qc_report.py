"""Tests for per-subject QC HTML report generation (A7)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def mock_subject_dir():
    """Create a mock subject directory with required files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        subj_dir = Path(tmpdir) / "sub-01"
        subj_dir.mkdir(parents=True)

        # Create QC directory
        qc_dir = subj_dir / "qc"
        qc_dir.mkdir()

        # Create mock confounds TSV
        confounds_tsv = (
            subj_dir / "sub-01_task-rest_run-01_desc-confounds_timeseries.tsv"
        )
        confounds_tsv.write_text(
            "fd\tdvars\tacompcor01\tacompcor02\tacompcor03\tacompcor04\tacompcor05\tacompcor06\tcensor\n"
            "0.1\t1.0\t0.5\t0.3\t0.2\t0.1\t0.05\t0.02\t0\n"
            "0.2\t1.2\t0.4\t0.3\t0.2\t0.1\t0.05\t0.02\t0\n"
            "0.8\t2.5\t0.6\t0.4\t0.3\t0.2\t0.1\t0.05\t1\n"
        )

        # Create mock doctor.json
        doctor_json = Path(tmpdir) / "provenance" / "doctor-latest.json"
        doctor_json.parent.mkdir(parents=True, exist_ok=True)
        doctor_json.write_text(
            json.dumps(
                {
                    "status": "pass",
                    "platform": {"os": "Linux", "python": "3.11.0", "cpu_count": 8},
                    "deps": {
                        "sct": {"found": True, "version": "6.0"},
                        "pam50": {"found": True, "path": "/opt/sct/data/PAM50"},
                    },
                }
            )
        )

        # Create mock PNG assets
        (qc_dir / "overlay_epi_t2w.png").write_bytes(b"fake_png")
        (qc_dir / "overlay_t2w_template.png").write_bytes(b"fake_png")
        (qc_dir / "motion_fd_dvars.png").write_bytes(b"fake_png")

        yield {
            "subj_dir": subj_dir,
            "qc_dir": qc_dir,
            "confounds_tsv": confounds_tsv,
            "doctor_json": doctor_json,
        }


def test_write_qc_creates_index_html(mock_subject_dir):
    """Test that write_qc creates index.html in subject QC directory."""
    from spineprep.qc.report import write_qc

    assets = {
        "confounds_tsv": mock_subject_dir["confounds_tsv"],
        "doctor_json": mock_subject_dir["doctor_json"],
    }

    html_path = write_qc(
        subject_dir=mock_subject_dir["subj_dir"],
        assets=assets,
    )

    assert html_path.exists()
    assert html_path.name == "index.html"
    assert html_path.parent == mock_subject_dir["qc_dir"]


def test_qc_html_has_required_elements(mock_subject_dir):
    """Test that QC HTML contains img, table, and Environment text."""
    from spineprep.qc.report import write_qc

    assets = {
        "confounds_tsv": mock_subject_dir["confounds_tsv"],
        "doctor_json": mock_subject_dir["doctor_json"],
    }

    html_path = write_qc(
        subject_dir=mock_subject_dir["subj_dir"],
        assets=assets,
    )

    html = html_path.read_text()

    # Check for images
    assert "<img" in html, "HTML must contain at least one <img> tag"

    # Check for tables
    assert "<table" in html, "HTML must contain at least one <table> tag"

    # Check for Environment section
    assert "Environment" in html or "environment" in html.lower(), (
        "HTML must contain Environment section"
    )


def test_qc_html_contains_motion_metrics(mock_subject_dir):
    """Test that motion metrics (FD, DVARS) are displayed."""
    from spineprep.qc.report import write_qc

    assets = {
        "confounds_tsv": mock_subject_dir["confounds_tsv"],
        "doctor_json": mock_subject_dir["doctor_json"],
    }

    html_path = write_qc(
        subject_dir=mock_subject_dir["subj_dir"],
        assets=assets,
    )

    html = html_path.read_text()

    # Check for motion-related content
    assert "FD" in html or "framewise" in html.lower()
    assert "DVARS" in html or "dvars" in html.lower()
    assert "motion" in html.lower() or "Motion" in html


def test_qc_html_contains_acompcor_summary(mock_subject_dir):
    """Test that aCompCor summary table is present."""
    from spineprep.qc.report import write_qc

    assets = {
        "confounds_tsv": mock_subject_dir["confounds_tsv"],
        "doctor_json": mock_subject_dir["doctor_json"],
    }

    html_path = write_qc(
        subject_dir=mock_subject_dir["subj_dir"],
        assets=assets,
    )

    html = html_path.read_text()

    # Check for aCompCor content
    assert "acompcor" in html.lower() or "CompCor" in html or "compcor" in html.lower()
    # Should show component columns
    assert "acompcor01" in html or "PC" in html or "Component" in html


def test_qc_html_contains_environment_info(mock_subject_dir):
    """Test that environment info from doctor.json is displayed."""
    from spineprep.qc.report import write_qc

    assets = {
        "confounds_tsv": mock_subject_dir["confounds_tsv"],
        "doctor_json": mock_subject_dir["doctor_json"],
    }

    html_path = write_qc(
        subject_dir=mock_subject_dir["subj_dir"],
        assets=assets,
    )

    html = html_path.read_text()

    # Check for environment details
    assert "Linux" in html or "Python" in html or "SCT" in html
    assert "Environment" in html or "environment" in html.lower()


def test_qc_html_is_self_contained(mock_subject_dir):
    """Test that QC HTML has inline CSS and no external CDN dependencies."""
    from spineprep.qc.report import write_qc

    assets = {
        "confounds_tsv": mock_subject_dir["confounds_tsv"],
        "doctor_json": mock_subject_dir["doctor_json"],
    }

    html_path = write_qc(
        subject_dir=mock_subject_dir["subj_dir"],
        assets=assets,
    )

    html = html_path.read_text()

    # Should have inline CSS
    assert "<style>" in html and "</style>" in html

    # Should not reference external CDNs
    assert "cdn.jsdelivr.net" not in html
    assert "googleapis.com" not in html
    assert "cloudflare.com" not in html


def test_qc_html_parses_with_beautifulsoup(mock_subject_dir):
    """Test that generated HTML can be parsed with BeautifulSoup."""
    from spineprep.qc.report import write_qc

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        pytest.skip("BeautifulSoup not installed")

    assets = {
        "confounds_tsv": mock_subject_dir["confounds_tsv"],
        "doctor_json": mock_subject_dir["doctor_json"],
    }

    html_path = write_qc(
        subject_dir=mock_subject_dir["subj_dir"],
        assets=assets,
    )

    html = html_path.read_text()
    soup = BeautifulSoup(html, "html.parser")

    # Validate structure
    assert soup.find("img"), "Must have at least one img tag"
    assert soup.find("table"), "Must have at least one table"
    assert soup.find(string=lambda t: t and "Environment" in t), (
        "Must have Environment text"
    )


def test_qc_handles_missing_assets_gracefully(mock_subject_dir):
    """Test that QC generation works even with missing optional assets."""
    from spineprep.qc.report import write_qc

    # Remove optional assets
    (mock_subject_dir["qc_dir"] / "overlay_epi_t2w.png").unlink()

    assets = {
        "confounds_tsv": mock_subject_dir["confounds_tsv"],
        "doctor_json": mock_subject_dir["doctor_json"],
    }

    # Should not raise
    html_path = write_qc(
        subject_dir=mock_subject_dir["subj_dir"],
        assets=assets,
    )

    assert html_path.exists()
    html = html_path.read_text()
    assert "<html" in html or "<!DOCTYPE" in html


def test_qc_tabs_for_overlays(mock_subject_dir):
    """Test that overlay images are organized in tabs or sections."""
    from spineprep.qc.report import write_qc

    assets = {
        "confounds_tsv": mock_subject_dir["confounds_tsv"],
        "doctor_json": mock_subject_dir["doctor_json"],
    }

    html_path = write_qc(
        subject_dir=mock_subject_dir["subj_dir"],
        assets=assets,
    )

    html = html_path.read_text()

    # Should have overlay-related content
    assert "overlay" in html.lower() or "registration" in html.lower() or "EPI" in html


def test_qc_censoring_summary(mock_subject_dir):
    """Test that censoring summary is displayed."""
    from spineprep.qc.report import write_qc

    assets = {
        "confounds_tsv": mock_subject_dir["confounds_tsv"],
        "doctor_json": mock_subject_dir["doctor_json"],
    }

    html_path = write_qc(
        subject_dir=mock_subject_dir["subj_dir"],
        assets=assets,
    )

    html = html_path.read_text()

    # Should mention censoring
    assert (
        "censor" in html.lower()
        or "excluded" in html.lower()
        or "flagged" in html.lower()
    )
