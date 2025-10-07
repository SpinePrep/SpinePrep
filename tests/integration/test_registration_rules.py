import os
import shutil
import subprocess
from pathlib import Path


def test_registration_all_fixture(tmp_path):
    # Prepare working dir
    work = tmp_path / "work"
    bids = work / "bids"
    deriv = work / "derivatives" / "spineprep"
    (bids / "sub-01/func").mkdir(parents=True, exist_ok=True)
    (bids / "sub-01/anat").mkdir(parents=True, exist_ok=True)
    # Create minimal valid NIfTI files (just copy a small file)
    # Create a minimal NIfTI file by copying a small file and renaming it
    (bids / "sub-01/func/sub-01_task-rest_run-01_bold.nii.gz").write_bytes(
        b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\x00\x03\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    )
    (bids / "sub-01/anat/sub-01_T2w.nii.gz").write_bytes(
        b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\x00\x03\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    )
    # Create all required files
    (deriv / "sub-01/func").mkdir(parents=True, exist_ok=True)
    (
        deriv / "sub-01/func/sub-01_task-rest_run-01_desc-confounds_timeseries.tsv"
    ).touch()
    (
        deriv / "sub-01/func/sub-01_task-rest_run-01_desc-confounds_timeseries.json"
    ).touch()
    (deriv / "sub-01/func/sub-01_task-rest_run-01_desc-mppca_bold.nii.gz").touch()
    (deriv / "sub-01/func/sub-01_task-rest_run-01_desc-motion_bold.nii.gz").touch()
    # Minimal manifest_deriv.tsv
    logs = deriv / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    bold_path = str(
        (bids / "sub-01/func/sub-01_task-rest_run-01_bold.nii.gz").resolve()
    )
    confounds_tsv = str(
        (
            deriv / "sub-01/func/sub-01_task-rest_run-01_desc-confounds_timeseries.tsv"
        ).resolve()
    )
    confounds_json = str(
        (
            deriv / "sub-01/func/sub-01_task-rest_run-01_desc-confounds_timeseries.json"
        ).resolve()
    )
    mppca_path = str(
        (deriv / "sub-01/func/sub-01_task-rest_run-01_desc-mppca_bold.nii.gz").resolve()
    )
    motion_path = str(
        (
            deriv / "sub-01/func/sub-01_task-rest_run-01_desc-motion_bold.nii.gz"
        ).resolve()
    )
    (logs / "manifest_deriv.tsv").write_text(
        f"sub\tses\trun\ttask\tbold_path\tderiv_motion\tderiv_motion_params_tsv\tderiv_motion_params_json\tderiv_confounds_tsv\tderiv_confounds_json\tderiv_mppca\nsub-01\t\t01\trest\t{bold_path}\t{motion_path}\t{(deriv / 'sub-01/func/sub-01_task-rest_run-01_desc-motion_params.tsv').resolve()}\t{(deriv / 'sub-01/func/sub-01_task-rest_run-01_desc-motion_params.json').resolve()}\t{confounds_tsv}\t{confounds_json}\t{mppca_path}\n"
    )
    (logs / "samples.tsv").write_text(
        f"sub\tses\trun\ttask\tbold_path\nsub-01\t\t01\trest\t{bold_path}\n"
    )
    cfg = tmp_path / "cfg.yaml"
    cfg.write_text(
        (
            Path("tests/fixtures/config_fixture.yaml")
            .read_text()
            .replace("tests/fixtures/work", str(work.resolve()))
        )
    )
    # Copy step scripts to working directory
    steps_dir = work / "steps"
    steps_dir.mkdir(exist_ok=True)
    for script in [
        "spi10_seg_cord.sh",
        "spi11_label_levels.sh",
        "spi12_reg_epi2t2.sh",
        "spi13_reg_t22pam50.sh",
        "spi14_warp_masks.sh",
    ]:
        shutil.copy(f"steps/{script}", steps_dir / script)
    # Run snakemake (dry-run)
    env = os.environ.copy()
    env["SPINEPREP_CONFIG"] = str(cfg)
    subprocess.run(
        [
            "snakemake",
            "-n",
            "-p",
            "registration_all",
            "--snakefile",
            "workflow/Snakefile",
            "--configfile",
            str(cfg),
            "--directory",
            str(work),
            "--cores",
            "2",
        ],
        check=True,
        env=env,
    )
    # Execute one id
    subprocess.run(
        [
            "snakemake",
            "-p",
            "-j",
            "2",
            "warp_masks",
            "--snakefile",
            "workflow/Snakefile",
            "--configfile",
            str(cfg),
            "--directory",
            str(work),
        ],
        check=True,
        env=env,
    )
    # Check products (ok or skip markers)
    xfm = deriv / "sub-01/xfm/from-epi_to-t2.h5"
    native_mask = (
        deriv / "sub-01/func/sub-01_task-rest_run-01_space-native_desc-cordmask.nii.gz"
    )
    pam50_mask = (
        deriv / "sub-01/func/sub-01_task-rest_run-01_space-PAM50_desc-cordmask.nii.gz"
    )
    assert xfm.exists() or (deriv / "sub-01/xfm/from-epi_to-t2.skip").exists()
    assert native_mask.exists() or (native_mask.with_suffix(".nii.gz.skip")).exists()
    assert pam50_mask.exists() or (pam50_mask.with_suffix(".nii.gz.skip")).exists()
