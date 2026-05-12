from pathlib import Path

import nibabel as nib
import numpy as np

from spinalfmriprep.S1_input_verify import check_S1_input_verify, run_S1_input_verify


def _write_mapping(path: Path, dataset_key: str, bids_root: Path) -> Path:
    content = f"{dataset_key}: {bids_root}\n"
    path.write_text(content, encoding="utf-8")
    return path


def _make_nifti(path: Path, shape: tuple[int, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = np.zeros(shape, dtype=np.float32)
    img = nib.Nifti1Image(data, affine=np.eye(4))
    img.set_qform(np.eye(4), code=1)
    img.set_sform(np.eye(4), code=1)
    nib.save(img, path)


def test_run_fails_on_missing_dataset_key(tmp_path):
    mapping = tmp_path / "datasets_local.yaml"
    mapping.write_text("", encoding="utf-8")
    out = tmp_path / "out"

    result = run_S1_input_verify(
        dataset_key="nonexistent_dataset",
        datasets_local=mapping,
        bids_root=None,
        out=out,
    )

    assert result.status == "FAIL"
    assert "not found" in (result.failure_message or "")


def test_run_fails_when_local_mapping_missing(tmp_path):
    dataset_key = "openneuro_ds005884_cospine_motor"
    mapping = tmp_path / "datasets_local.yaml"
    mapping.write_text("", encoding="utf-8")
    out = tmp_path / "out"

    result = run_S1_input_verify(
        dataset_key=dataset_key,
        datasets_local=mapping,
        bids_root=None,
        out=out,
    )

    assert result.status == "FAIL"
    assert "not found" in (result.failure_message or "")


def test_run_builds_artifacts_and_check_passes(tmp_path):
    dataset_key = "openneuro_ds004386_spinalcord_rest_testretest"
    bids_root = tmp_path / "bids"
    _make_nifti(bids_root / "sub-01" / "func" / "sub-01_task-test_bold.nii.gz", (2, 2, 2, 3))
    _make_nifti(bids_root / "sub-01" / "anat" / "sub-01_T2w.nii.gz", (2, 2, 2))
    mapping = _write_mapping(tmp_path / "datasets_local.yaml", dataset_key, bids_root)
    out = tmp_path / "out"

    result = run_S1_input_verify(
        dataset_key=dataset_key,
        datasets_local=mapping,
        bids_root=None,
        out=out,
    )
    assert result.status in {"PASS", "WARN"}
    assert result.inventory_path.exists()
    assert result.qc_path.exists()
    assert result.runs_path.exists()
    assert result.fix_plan_path.exists()

    check_res = check_S1_input_verify(
        dataset_key=dataset_key,
        datasets_local=mapping,
        bids_root=None,
        out=out,
    )
    assert check_res.status == "PASS"


def test_missing_expected_physio_sets_warn(tmp_path):
    dataset_key = "openneuro_ds005884_cospine_motor"
    bids_root = tmp_path / "bids"
    _make_nifti(bids_root / "sub-01" / "func" / "sub-01_task-motor_bold.nii.gz", (2, 2, 2, 4))
    _make_nifti(bids_root / "sub-01" / "anat" / "sub-01_T1w.nii.gz", (2, 2, 2))
    mapping = _write_mapping(tmp_path / "datasets_local.yaml", dataset_key, bids_root)
    out = tmp_path / "out"

    result = run_S1_input_verify(
        dataset_key=dataset_key,
        datasets_local=mapping,
        bids_root=None,
        out=out,
    )
    assert result.status == "WARN"
    qc = result.qc_path.read_text(encoding="utf-8")
    assert "physio" in qc


def test_inventory_is_deterministic(tmp_path):
    dataset_key = "openneuro_ds004386_spinalcord_rest_testretest"
    bids_root = tmp_path / "bids"
    _make_nifti(bids_root / "sub-02" / "func" / "file2_bold.nii.gz", (2, 2, 2, 2))
    _make_nifti(bids_root / "sub-01" / "func" / "file1_bold.nii.gz", (2, 2, 2, 2))
    _make_nifti(bids_root / "sub-01" / "anat" / "sub-01_T2w.nii.gz", (2, 2, 2))
    _make_nifti(bids_root / "sub-02" / "anat" / "sub-02_T2w.nii.gz", (2, 2, 2))
    mapping = _write_mapping(tmp_path / "datasets_local.yaml", dataset_key, bids_root)
    out = tmp_path / "out"

    result1 = run_S1_input_verify(
        dataset_key=dataset_key,
        datasets_local=mapping,
        bids_root=None,
        out=out,
    )
    assert result1.status in {"PASS", "WARN"}
    inventory_text1 = result1.inventory_path.read_text(encoding="utf-8")

    result2 = run_S1_input_verify(
        dataset_key=dataset_key,
        datasets_local=mapping,
        bids_root=None,
        out=out,
    )
    assert result2.status in {"PASS", "WARN"}
    inventory_text2 = result2.inventory_path.read_text(encoding="utf-8")
    assert inventory_text1 == inventory_text2

    check_res = check_S1_input_verify(
        dataset_key=dataset_key,
        datasets_local=mapping,
        bids_root=None,
        out=out,
    )
    assert check_res.status == "PASS"


def test_inventory_records_func_acquisition_metadata(tmp_path):
    """S1 must extract BIDS sidecar timing fields for cord_likely func runs
    so a future opt-in slice-timing correction has data ready."""
    import json
    from spinalfmriprep.steps.s1.inventory import _build_inventory

    bids = tmp_path / "ds_X"
    func = bids / "sub-01" / "func"
    func.mkdir(parents=True)
    _make_nifti(func / "sub-01_task-rest_bold.nii.gz", (4, 4, 3, 5))
    (func / "sub-01_task-rest_bold.json").write_text(json.dumps({
        "RepetitionTime": 1.0,
        "SliceTiming": [0.0, 0.5, 0.25],
        "SliceEncodingDirection": "k",
        "PhaseEncodingDirection": "j-",
        "EchoTime": 0.030,
        "RandomKeyWeShouldIgnore": "foo",
    }), encoding="utf-8")
    # Dataset-level inheritance: S1 should fold this in alongside the run sidecar
    (bids / "task-rest_bold.json").write_text(json.dumps({
        "EffectiveEchoSpacing": 0.0005,
    }), encoding="utf-8")

    inv = _build_inventory(bids, "ds_X", policy_entry=None)
    func_runs = [r for r in inv["runs"] if r["modality"] == "func"]
    assert len(func_runs) == 1
    acq = func_runs[0].get("acquisition")
    assert acq is not None
    assert acq.get("RepetitionTime") == 1.0
    assert acq.get("SliceTiming") == [0.0, 0.5, 0.25]
    assert acq.get("SliceEncodingDirection") == "k"
    assert acq.get("PhaseEncodingDirection") == "j-"
    assert acq.get("EchoTime") == 0.030
    assert acq.get("EffectiveEchoSpacing") == 0.0005
    assert "RandomKeyWeShouldIgnore" not in acq


def test_inventory_records_fmap_acquisition_metadata(tmp_path):
    """S1 must read fmap sidecars too so S5 (distortion correction) can
    pull PE direction + TRT without re-parsing BIDS."""
    import json
    from spinalfmriprep.steps.s1.inventory import _build_inventory

    bids = tmp_path / "ds_Y"
    fmap = bids / "sub-01" / "fmap"
    fmap.mkdir(parents=True)
    # Reversed-phase EPI pair (the topup-eligible case)
    for d, pe in [("AP", "j-"), ("PA", "j")]:
        _make_nifti(fmap / f"sub-01_dir-{d}_epi.nii.gz", (4, 4, 3))
        (fmap / f"sub-01_dir-{d}_epi.json").write_text(json.dumps({
            "PhaseEncodingDirection": pe,
            "TotalReadoutTime": 0.0406,
            "EffectiveEchoSpacing": 0.00032,
            "ParallelReductionFactorInPlane": 2,
            "PartialFourier": 0.875,
        }), encoding="utf-8")
    # Need a func too so the inventory is non-empty (and to exercise the
    # both-modalities-tagged branch)
    func = bids / "sub-01" / "func"
    func.mkdir()
    _make_nifti(func / "sub-01_task-rest_bold.nii.gz", (4, 4, 3, 5))

    inv = _build_inventory(bids, "ds_Y", policy_entry=None)
    fmap_runs = [r for r in inv["runs"] if r["modality"] == "fmap"]
    assert len(fmap_runs) == 2
    pe_dirs = {r["acquisition"]["PhaseEncodingDirection"] for r in fmap_runs}
    assert pe_dirs == {"j", "j-"}, "S5 topup eligibility check needs both PE dirs"
    for r in fmap_runs:
        acq = r["acquisition"]
        assert acq["TotalReadoutTime"] == 0.0406
        assert acq["ParallelReductionFactorInPlane"] == 2

def test_inventory_records_trt_for_func(tmp_path):
    """A5 follow-up: TotalReadoutTime is in the func-sidecar allowlist."""
    import json
    from spinalfmriprep.steps.s1.inventory import _build_inventory

    bids = tmp_path / "ds_Z"
    func = bids / "sub-01" / "func"
    func.mkdir(parents=True)
    _make_nifti(func / "sub-01_task-rest_bold.nii.gz", (4, 4, 3, 5))
    (func / "sub-01_task-rest_bold.json").write_text(json.dumps({
        "RepetitionTime": 2.68,
        "TotalReadoutTime": 0.0406401,
        "EffectiveEchoSpacing": 0.000320001,
        "PhaseEncodingDirection": "j",
        "ReconMatrixPE": 128,
        "ParallelReductionFactorInPlane": 2,
    }), encoding="utf-8")
    inv = _build_inventory(bids, "ds_Z", policy_entry=None)
    func_runs = [r for r in inv["runs"] if r["modality"] == "func"]
    assert len(func_runs) == 1
    acq = func_runs[0]["acquisition"]
    assert acq.get("TotalReadoutTime") == 0.0406401
    assert acq.get("ReconMatrixPE") == 128
    assert acq.get("ParallelReductionFactorInPlane") == 2
    # Sanity: BIDS convention - TRT = (matrix_PE - 1) x EES (no GRAPPA division)
    import math
    assert math.isclose(acq["TotalReadoutTime"],
                        (acq["ReconMatrixPE"] - 1) * acq["EffectiveEchoSpacing"],
                        rel_tol=1e-4),         "TRT must follow BIDS convention: unaccelerated-equivalent readout time"
