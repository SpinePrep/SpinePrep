"""S2B_func_denoise step: passthrough when disabled, enabled run with QC
reportlets + provenance, and the S3 consumption resolver. dwidenoise is real
(installed); the test is skipped if it is absent."""

import json
import shutil
from pathlib import Path

import numpy as np
import nibabel as nib
import yaml
import pytest

import spinalfmriprep.steps.s2b.orchestrate as s2b
import spinalfmriprep.steps.s3.io as s3io

_HAVE_DWI = shutil.which("dwidenoise") is not None


def _setup(tmp_path):
    wf = tmp_path / "wf_test_001"
    inv_dir = wf / "work" / "S1_input_verify" / "ds"
    inv_dir.mkdir(parents=True)
    bids = tmp_path / "bids" / "sub-01" / "func"
    bids.mkdir(parents=True)
    bold = bids / "sub-01_task-x_bold.nii.gz"
    rng = np.random.default_rng(0)
    nib.save(nib.Nifti1Image(
        (100 + rng.standard_normal((10, 10, 6, 40)).astype(np.float32) * 12),
        np.eye(4)), str(bold))
    inv = {"bids_root": str(tmp_path / "bids"),
           "files": [{"path": "sub-01/func/sub-01_task-x_bold.nii.gz",
                      "subject": "01", "session": None}]}
    (inv_dir / "bids_inventory.json").write_text(json.dumps(inv))
    return wf


def test_disabled_is_clean_passthrough(tmp_path, monkeypatch):
    wf = _setup(tmp_path)
    monkeypatch.setattr(s2b, "POLICY_PATH", tmp_path / "absent.yaml")
    r = s2b.run_S2B_func_denoise(dataset_key="ds", out=str(wf))
    assert r.status == "PASS"
    qc = json.loads((wf / "logs" / "S2B_func_denoise" / "ds" / "qc.json").read_text())
    assert qc["enabled"] is False and qc["runs"] == []
    # S3 resolver finds nothing -> falls back to raw
    assert s3io._find_denoised_bold(wf, "sub-01_task-x") is None


@pytest.mark.skipif(not _HAVE_DWI, reason="dwidenoise not installed")
def test_enabled_run_denoises_with_qc_and_provenance(tmp_path, monkeypatch):
    wf = _setup(tmp_path)
    pol = tmp_path / "s2b.yaml"
    pol.write_text(yaml.safe_dump({"enabled": True, "nthreads": 1, "qc_thresholds": {
        "warn_residual_corr": 0.4, "fail_residual_corr": 0.6, "warn_min_tsnr_gain_pct": 0.0}}))
    monkeypatch.setattr(s2b, "POLICY_PATH", pol)

    r = s2b.run_S2B_func_denoise(dataset_key="ds", out=str(wf))
    assert r.status in ("PASS", "WARN")
    run0 = json.loads((wf / "logs" / "S2B_func_denoise" / "ds" / "qc.json").read_text())["runs"][0]
    # provenance recorded
    assert run0["denoise"]["tool"] == "dwidenoise" and run0["denoise"]["version"]
    # metrics: tSNR improved + residual structure measured
    assert run0["metrics"]["tsnr_post"] > run0["metrics"]["tsnr_pre"]
    assert run0["metrics"]["residual_structure_corr"] is not None
    # 3 QC reportlets
    assert set(run0["reportlets"]) == {"noise_sigma", "tsnr_before_after", "residual_structure"}
    assert len(list(wf.rglob("*desc-S2B_*.png"))) == 3
    # S3 resolver now finds the denoised series
    found = s3io._find_denoised_bold(wf, "sub-01_task-x")
    assert found is not None and found.exists()
