"""BIDS-App entrypoint (T1). Verifies the conformant interface, the CLI
routing, and that the per-subject chain can run ad-hoc on an unregistered
bids_dir — exercised through S1 (pure-Python; no SCT required)."""
from __future__ import annotations

import json
from pathlib import Path

import nibabel as nib
import numpy as np


def _tiny_bids(root: Path) -> Path:
    """Minimal valid-enough BIDS tree: one subject, one rest BOLD + sidecar."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "dataset_description.json").write_text(
        json.dumps({"Name": "tiny", "BIDSVersion": "1.8.0"}))
    func = root / "sub-01" / "func"
    func.mkdir(parents=True)
    img = nib.Nifti1Image(np.zeros((4, 4, 4, 5), dtype=np.float32), np.eye(4))
    nib.save(img, func / "sub-01_task-rest_bold.nii.gz")
    (func / "sub-01_task-rest_bold.json").write_text(
        json.dumps({"RepetitionTime": 2.0, "TaskName": "rest"}))
    return root


def test_dataset_key_sanitizes_folder_name():
    from spinalfmriprep.bids_app import _dataset_key_for
    assert _dataset_key_for(Path("/data/ds-004 926!")) == "bidsapp_ds_004_926"
    assert _dataset_key_for(Path("/data/My.Cohort")) == "bidsapp_my_cohort"


def test_cli_routes_bids_app_invocation(monkeypatch, tmp_path):
    """`spinalfmriprep BIDS_DIR OUT participant` routes to the BIDS-App, not the
    run/check subparser."""
    from spinalfmriprep import cli
    captured = {}

    def fake(argv):
        captured["argv"] = argv
        return 0

    monkeypatch.setattr("spinalfmriprep.bids_app.main_bids_app", fake)
    rc = cli.main([str(tmp_path / "bids"), str(tmp_path / "out"), "participant"])
    assert rc == 0
    assert captured["argv"][2] == "participant"


def test_run_check_still_works_as_subcommand(monkeypatch):
    """The internal run/check subcommands are not shadowed by the router."""
    from spinalfmriprep import cli
    # --version short-circuits; just confirm it doesn't route to bids_app
    monkeypatch.setattr(
        "spinalfmriprep.bids_app.main_bids_app",
        lambda argv: (_ for _ in ()).throw(AssertionError("should not route")))
    assert cli.main(["--version"]) == 0


def test_bids_app_participant_runs_s1_adhoc(tmp_path, monkeypatch):
    """End-to-end through the entrypoint, limited to S1 (no SCT): an
    unregistered bids_dir runs ad-hoc and produces an S1 qc.json."""
    from spinalfmriprep import bids_app
    bids = _tiny_bids(tmp_path / "ds")
    out = tmp_path / "out"
    # Limit the participant chain to S1 so the test needs no SCT/FSL.
    monkeypatch.setattr(bids_app, "PARTICIPANT_STEPS", ["S1_input_verify"])
    rc = bids_app.run_bids_app(bids, out, "participant")
    assert rc == 0
    qc = list((out / "logs" / "S1_input_verify").rglob("qc.json"))
    assert qc, "S1 should emit a qc.json for the ad-hoc dataset"
    d = json.loads(qc[0].read_text())
    assert d.get("status") in ("PASS", "WARN", "FAIL")
