from pathlib import Path

from spineprep.config import load_config


# Will import after Cursor adds workflow/lib/registration.py
def test_outputs_paths_shape(tmp_path: Path):
    # prepare fixture config
    # cfg = yaml.safe_load(Path("tests/fixtures/config_fixture.yaml").read_text())
    out = load_config("tests/fixtures/config_fixture.yaml")
    # pretend one manifest row
    row = {
        "sub": "sub-01",
        "ses": "",
        "run": "01",
        "task": "rest",
        "bold_path": str(
            (
                tmp_path / "bids/sub-01/func/sub-01_task-rest_run-01_bold.nii.gz"
            ).absolute()
        ),
    }
    (tmp_path / "bids/sub-01/func").mkdir(parents=True, exist_ok=True)
    Path(row["bold_path"]).touch()
    from workflow.lib.registration import derive_outputs  # type: ignore

    outs = derive_outputs(row, out["paths"]["deriv_dir"])
    assert "warp_epi2t2" in outs and outs["warp_epi2t2"].endswith("from-epi_to-t2.h5")
    for k in ("mask_native_cord", "mask_pam50_cord"):
        assert k in outs and outs[k].endswith(".nii.gz")


def test_inputs_resolution_without_t2_fallback(tmp_path: Path):
    from workflow.lib.registration import derive_inputs  # type: ignore

    row = {
        "sub": "sub-01",
        "ses": "",
        "run": "01",
        "task": "rest",
        "bold_path": str(
            (
                tmp_path / "bids/sub-01/func/sub-01_task-rest_run-01_bold.nii.gz"
            ).absolute()
        ),
    }
    (tmp_path / "bids/sub-01/func").mkdir(parents=True, exist_ok=True)
    Path(row["bold_path"]).touch()
    epi, t2 = derive_inputs(row, bids_root=str(tmp_path / "bids"))
    assert Path(epi).exists()
    # T2 may not exist in fixture; allow None
    assert t2 is None or isinstance(t2, str)
