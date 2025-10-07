"""Integration tests for motion correction engines."""

import os
import subprocess
from pathlib import Path


def _prep_fixture(tmp_path):
    """Prepare test fixture with minimal BIDS structure."""
    work = tmp_path / "work"
    bids = work / "bids"
    deriv = work / "derivatives" / "spineprep"
    logs = deriv / "logs"
    (bids / "sub-01/func").mkdir(parents=True, exist_ok=True)
    (bids / "sub-01/func/sub-01_task-rest_run-01_bold.nii.gz").write_bytes(b"\x00")
    logs.mkdir(parents=True, exist_ok=True)
    # minimal manifests
    (logs / "samples.tsv").write_text(
        "sub\tses\trun\ttask\tbold_path\nsub-01\t\t01\trest\t"
        + str((bids / "sub-01/func/sub-01_task-rest_run-01_bold.nii.gz").resolve())
        + "\n"
    )
    (logs / "manifest_deriv.tsv").write_text(
        "sub\tses\trun\ttask\tbold_path\tderiv_motion\tderiv_motion_params_tsv\tderiv_motion_params_json\tderiv_confounds_tsv\tderiv_confounds_json\n"
        f"sub-01\t\t01\trest\t{(bids / 'sub-01/func/sub-01_task-rest_run-01_bold.nii.gz').resolve()}\t"
        f"{(deriv / 'sub-01/func/sub-01_task-rest_run-01_desc-motioncorr_bold.nii.gz').resolve()}\t"
        f"{(deriv / 'sub-01/func/sub-01_task-rest_run-01_desc-motion_params.tsv').resolve()}\t"
        f"{(deriv / 'sub-01/func/sub-01_task-rest_run-01_desc-motion_params.json').resolve()}\t"
        f"{(deriv / 'sub-01/func/sub-01_task-rest_run-01_desc-confounds_timeseries.tsv').resolve()}\t"
        f"{(deriv / 'sub-01/func/sub-01_task-rest_run-01_desc-confounds_timeseries.json').resolve()}\n"
    )
    cfg = tmp_path / "cfg.yaml"
    cfg.write_text(
        Path("tests/fixtures/config_fixture.yaml")
        .read_text()
        .replace("tests/fixtures/work", str(work.resolve()))
    )
    return work, cfg, deriv


def test_motion_rigid3d(tmp_path):
    """Test rigid3d motion correction engine."""
    work, cfg, deriv = _prep_fixture(tmp_path)
    env = os.environ.copy()
    env["SPINEPREP_CONFIG"] = str(cfg)
    subprocess.run(
        [
            "snakemake",
            "-n",
            "-p",
            "motion_0",
            "--snakefile",
            "workflow/Snakefile",
            "--directory",
            str(work),
        ],
        check=True,
        env=env,
    )
    subprocess.run(
        [
            "snakemake",
            "-p",
            "-j",
            "2",
            "motion_0",
            "--snakefile",
            "workflow/Snakefile",
            "--directory",
            str(work),
        ],
        check=True,
        env=env,
    )
    assert (
        deriv / "sub-01/func/sub-01_task-rest_run-01_desc-motioncorr_bold.nii.gz"
    ).exists()
    assert (
        deriv / "sub-01/func/sub-01_task-rest_run-01_desc-motion_params.tsv"
    ).exists()


def test_motion_sct_graceful_skip(tmp_path):
    """Test SCT motion correction with graceful degradation when tools missing."""
    work, cfg, deriv = _prep_fixture(tmp_path)
    env = os.environ.copy()
    env["SPINEPREP_CONFIG"] = str(cfg)
    subprocess.run(
        [
            "snakemake",
            "-p",
            "-j",
            "2",
            "motion_0",
            "--snakefile",
            "workflow/Snakefile",
            "--directory",
            str(work),
            "--config",
            "options.motion.engine=sct",
        ],
        check=True,
        env=env,
    )
    # either real outputs or skip markers
    ok = (
        deriv / "sub-01/func/sub-01_task-rest_run-01_desc-motioncorr_bold.nii.gz"
    ).exists()
    skip = (
        deriv / "sub-01/func/sub-01_task-rest_run-01_desc-motioncorr_bold.nii.gz.skip"
    ).exists()
    assert ok or skip
