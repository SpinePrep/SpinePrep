from __future__ import annotations

import json
from pathlib import Path

from spinalfmriprep.qc_dashboard import generate_dashboard


def test_generate_dashboard_writes_index_and_reportlet_pages(tmp_path: Path) -> None:
    out = tmp_path / "work" / "wf_test"

    # Minimal workflow layout:
    # out/logs/<step>/<dataset>/qc.json
    qc_dir = out / "logs" / "S2_anat_cordref" / "reg_test_ds"
    qc_dir.mkdir(parents=True, exist_ok=True)

    # Dummy reportlet file
    fig_rel = "derivatives/spinalfmriprep/sub-01/figures/sub-01_desc-S2_cordmask_montage.png"
    fig_path = out / fig_rel
    fig_path.parent.mkdir(parents=True, exist_ok=True)
    fig_path.write_bytes(b"not_a_real_png")

    qc = {
        "status": "PASS",
        "failure_message": None,
        "runs": [
            {
                "subject": "01",
                "session": None,
                "status": "PASS",
                "reportlets": {
                    "cordmask_montage": fig_rel,
                },
            }
        ],
    }
    (qc_dir / "qc.json").write_text(json.dumps(qc), encoding="utf-8")

    res = generate_dashboard(out)
    assert res.indexed_qc_files == 1
    assert (out / "dashboard" / "index.html").exists()

    reportlet_page = out / "dashboard" / "reportlets" / "S2_anat_cordref" / "cordmask_montage.html"
    assert reportlet_page.exists()

    html = reportlet_page.read_text(encoding="utf-8")
    # The gallery should link to the figure via a relative path.
    assert "sub-01_desc-S2_cordmask_montage.png" in html
    # The workfolder should be displayed
    assert "Workfolder: wf_test" in html


def test_generate_dashboard_without_workfolder(tmp_path: Path) -> None:
    """Test that dashboard works without wf_* pattern in path."""
    out = tmp_path / "work" / "other"

    # Minimal workflow layout:
    # out/logs/<step>/<dataset>/qc.json
    qc_dir = out / "logs" / "S2_anat_cordref" / "reg_test_ds"
    qc_dir.mkdir(parents=True, exist_ok=True)

    # Dummy reportlet file
    fig_rel = "derivatives/spinalfmriprep/sub-01/figures/sub-01_desc-S2_cordmask_montage.png"
    fig_path = out / fig_rel
    fig_path.parent.mkdir(parents=True, exist_ok=True)
    fig_path.write_bytes(b"not_a_real_png")

    qc = {
        "status": "PASS",
        "failure_message": None,
        "runs": [
            {
                "subject": "01",
                "session": None,
                "status": "PASS",
                "reportlets": {
                    "cordmask_montage": fig_rel,
                },
            }
        ],
    }
    (qc_dir / "qc.json").write_text(json.dumps(qc), encoding="utf-8")

    res = generate_dashboard(out)
    assert res.indexed_qc_files == 1
    assert (out / "dashboard" / "index.html").exists()

    index_html = (out / "dashboard" / "index.html").read_text(encoding="utf-8")
    # Workfolder NAME should NOT be displayed when path doesn't contain wf_*
    assert "Workfolder: other" not in index_html


def test_chain_workfolder_materialises_upstream_reportlets(tmp_path: Path) -> None:
    """A downstream workfolder that symlinks an upstream qc.json gets per-figure
    symlinks created automatically so the dashboard resolves all reportlets."""
    work = tmp_path / "work"
    upstream = work / "wf_reg_001"
    downstream = work / "wf_smoke_001"
    upstream.mkdir(parents=True)
    downstream.mkdir(parents=True)

    # Upstream: real S2 qc.json + figure
    up_qc_dir = upstream / "logs" / "S2_anat_cordref" / "ds_test"
    up_qc_dir.mkdir(parents=True)
    fig_rel = "derivatives/spinalfmriprep/sub-01/figures/sub-01_desc-S2_cordmask_montage.png"
    (upstream / fig_rel).parent.mkdir(parents=True)
    (upstream / fig_rel).write_bytes(b"upstream-png")
    (up_qc_dir / "qc.json").write_text(json.dumps({
        "status": "PASS",
        "runs": [{"subject": "01", "session": None, "status": "PASS",
                  "reportlets": {"cordmask_montage": fig_rel}}],
    }), encoding="utf-8")

    # Downstream: only a symlink to the upstream qc.json (no derivatives/)
    down_qc_step = downstream / "logs" / "S2_anat_cordref"
    down_qc_step.parent.mkdir(parents=True)
    down_qc_step.symlink_to(upstream / "logs" / "S2_anat_cordref")

    res = generate_dashboard(downstream)

    # Per-figure symlink should now exist in downstream
    materialised = downstream / fig_rel
    assert materialised.is_symlink(), "chain reportlet was not materialised"
    assert materialised.resolve() == (upstream / fig_rel).resolve()

    # Dashboard should count the figure (not report it as missing)
    assert res.indexed_qc_files == 1
    assert not any("Missing reportlet" in e for e in res.errors), res.errors




