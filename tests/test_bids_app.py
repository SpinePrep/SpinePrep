"""BIDS-App entrypoint (T1). Verifies the conformant interface, the CLI
routing, and that the per-subject chain can run ad-hoc on an unregistered
bids_dir — exercised through S1 (pure-Python; no SCT required)."""
from __future__ import annotations

import json
from pathlib import Path

import nibabel as nib
import numpy as np


def _tiny_bids(root: Path) -> Path:
    """Minimal valid-enough BIDS tree: one subject with a rest BOLD (+ sidecar)
    and a T2w anat, so the front-door input validation passes."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "dataset_description.json").write_text(
        json.dumps({"Name": "tiny", "BIDSVersion": "1.8.0"}))
    func = root / "sub-01" / "func"
    func.mkdir(parents=True)
    img = nib.Nifti1Image(np.zeros((4, 4, 4, 5), dtype=np.float32), np.eye(4))
    nib.save(img, func / "sub-01_task-rest_bold.nii.gz")
    (func / "sub-01_task-rest_bold.json").write_text(
        json.dumps({"RepetitionTime": 2.0, "TaskName": "rest"}))
    anat = root / "sub-01" / "anat"
    anat.mkdir(parents=True)
    nib.save(nib.Nifti1Image(np.zeros((4, 4, 8), dtype=np.float32), np.eye(4)),
             anat / "sub-01_T2w.nii.gz")
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


def test_participant_label_builds_filtered_view(tmp_path, monkeypatch):
    """--participant-label restricts the chain to a symlinked BIDS view."""
    from spinalfmriprep import bids_app
    bids = _tiny_bids(tmp_path / "ds")
    # add a second subject so filtering is observable
    func2 = bids / "sub-02" / "func"; func2.mkdir(parents=True)
    import nibabel as nib, numpy as np, json
    nib.save(nib.Nifti1Image(np.zeros((4, 4, 4, 5), dtype=np.float32), np.eye(4)),
             func2 / "sub-02_task-rest_bold.nii.gz")
    (func2 / "sub-02_task-rest_bold.json").write_text(json.dumps({"RepetitionTime": 2.0}))
    out = tmp_path / "out"
    monkeypatch.setattr(bids_app, "PARTICIPANT_STEPS", ["S1_input_verify"])
    # sub-02 has no anat, but we only request sub-01, so validation passes.
    rc = bids_app.run_bids_app(bids, out, "participant", participant_label=["01"])
    assert rc == 0
    view = out / ".bids_view"
    assert (view / "sub-01").exists() and not (view / "sub-02").exists()


# --- T0.3: front-door input validation --------------------------------------

def test_validate_passes_on_valid_tree(tmp_path):
    from spinalfmriprep.bids_app import _validate_bids_input
    bids = _tiny_bids(tmp_path / "ds")
    errors, warnings = _validate_bids_input(bids)
    assert errors == []


def test_validate_errors_when_not_bids(tmp_path):
    from spinalfmriprep.bids_app import _validate_bids_input
    empty = tmp_path / "notbids"; empty.mkdir()
    errors, _ = _validate_bids_input(empty)
    assert any("sub-*" in e for e in errors)


def test_validate_errors_missing_anat(tmp_path):
    from spinalfmriprep.bids_app import _validate_bids_input
    bids = _tiny_bids(tmp_path / "ds")
    # remove the anat -> S2 would crash; validation must catch it
    for f in (bids / "sub-01" / "anat").glob("*"):
        f.unlink()
    errors, _ = _validate_bids_input(bids)
    assert any("anatomical" in e for e in errors)


def test_validate_errors_missing_bold(tmp_path):
    from spinalfmriprep.bids_app import _validate_bids_input
    bids = _tiny_bids(tmp_path / "ds")
    for f in (bids / "sub-01" / "func").glob("*_bold.nii*"):
        f.unlink()
    errors, _ = _validate_bids_input(bids)
    assert any("BOLD" in e for e in errors)


def test_validate_errors_unknown_participant(tmp_path):
    from spinalfmriprep.bids_app import _validate_bids_input
    bids = _tiny_bids(tmp_path / "ds")
    errors, _ = _validate_bids_input(bids, participant_label=["99"])
    assert any("not found" in e for e in errors)


def test_validate_errors_corrupt_nifti(tmp_path):
    from spinalfmriprep.bids_app import _validate_bids_input
    bids = _tiny_bids(tmp_path / "ds")
    # truncate the bold to a non-empty but unreadable file
    bold = next((bids / "sub-01" / "func").glob("*_bold.nii.gz"))
    bold.write_bytes(b"not a nifti")
    errors, _ = _validate_bids_input(bids)
    assert any("readable NIfTI" in e for e in errors)


def test_skip_bids_validator_bypasses(tmp_path, monkeypatch):
    """--skip-bids-validator runs the chain even on an invalid tree."""
    from spinalfmriprep import bids_app
    bids = _tiny_bids(tmp_path / "ds")
    for f in (bids / "sub-01" / "anat").glob("*"):
        f.unlink()  # invalid (no anat), but we skip validation
    out = tmp_path / "out"
    monkeypatch.setattr(bids_app, "PARTICIPANT_STEPS", ["S1_input_verify"])
    rc = bids_app.run_bids_app(bids, out, "participant", skip_bids_validator=True)
    assert rc == 0


def test_validation_blocks_bad_tree(tmp_path, monkeypatch):
    """Without the skip flag, an invalid tree returns non-zero before the chain."""
    from spinalfmriprep import bids_app
    bids = _tiny_bids(tmp_path / "ds")
    for f in (bids / "sub-01" / "anat").glob("*"):
        f.unlink()
    out = tmp_path / "out"
    called = {"ran": False}

    def fake_main(argv):
        called["ran"] = True
        return 0
    monkeypatch.setattr("spinalfmriprep.cli.main", fake_main)
    rc = bids_app.run_bids_app(bids, out, "participant")
    assert rc == 2 and called["ran"] is False
