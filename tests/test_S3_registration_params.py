from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from spineprep.S3_func_init_and_crop import _register_t2_to_func


class _FakeRun:
    def __init__(self) -> None:
        self.cmd = None

    def __call__(self, cmd, capture_output=True, text=True):  # noqa: D401 - test stub
        self.cmd = cmd
        return SimpleNamespace(
            returncode=0,
            stdout="Final metric value: 0.50\n",
            stderr="",
        )


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x", encoding="utf-8")
    return path


def test_register_t2_to_func_image_based_omits_seg_flags(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_run = _FakeRun()
    monkeypatch.setattr("subprocess.run", fake_run)

    t2_crop = _touch(tmp_path / "t2_crop.nii.gz")
    func_ref = _touch(tmp_path / "func_ref0.nii.gz")
    out_xfm = tmp_path / "xfm" / "t2_to_func_warp.nii.gz"
    out_warped = tmp_path / "xfm" / "t2_in_func.nii.gz"

    t2_seg = _touch(tmp_path / "t2_seg.nii.gz")
    func_roi = _touch(tmp_path / "func_roi.nii.gz")
    func_seg = _touch(tmp_path / "func_seg.nii.gz")

    res = _register_t2_to_func(
        t2_crop_path=t2_crop,
        func_ref_path=func_ref,
        output_xfm_path=out_xfm,
        output_warped_path=out_warped,
        policy={"registration": {"type": "rigid", "metric": "MI"}},
        t2_cord_mask_path=t2_seg,
        func_roi_mask_path=func_roi,
        func_seg_path=func_seg,
        initwarp_path=None,
        use_segmentation_based=False,
    )

    assert res["status"] == "PASS"
    assert fake_run.cmd is not None
    cmd_str = " ".join(fake_run.cmd)
    assert "algo=translation" in cmd_str
    assert "-iseg" not in fake_run.cmd
    assert "-dseg" not in fake_run.cmd
    assert "-m" in fake_run.cmd


def test_register_t2_to_func_seg_based_includes_seg_flags(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_run = _FakeRun()
    monkeypatch.setattr("subprocess.run", fake_run)

    t2_crop = _touch(tmp_path / "t2_crop.nii.gz")
    func_ref = _touch(tmp_path / "func_ref0.nii.gz")
    out_xfm = tmp_path / "xfm" / "t2_to_func_warp.nii.gz"
    out_warped = tmp_path / "xfm" / "t2_in_func.nii.gz"

    t2_seg = _touch(tmp_path / "t2_seg.nii.gz")
    func_roi = _touch(tmp_path / "func_roi.nii.gz")
    func_seg = _touch(tmp_path / "func_seg.nii.gz")

    res = _register_t2_to_func(
        t2_crop_path=t2_crop,
        func_ref_path=func_ref,
        output_xfm_path=out_xfm,
        output_warped_path=out_warped,
        policy={"registration": {"type": "rigid", "metric": "MI"}},
        t2_cord_mask_path=t2_seg,
        func_roi_mask_path=func_roi,
        func_seg_path=func_seg,
        initwarp_path=None,
        use_segmentation_based=True,
    )

    assert res["status"] == "PASS"
    assert fake_run.cmd is not None
    cmd_str = " ".join(fake_run.cmd)
    assert "algo=slicereg" in cmd_str
    assert "metric=MeanSquares" in cmd_str
    assert "-iseg" in fake_run.cmd
    assert "-dseg" in fake_run.cmd
    assert "-m" in fake_run.cmd


def test_register_t2_to_func_includes_initwarp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_run = _FakeRun()
    monkeypatch.setattr("subprocess.run", fake_run)

    t2_crop = _touch(tmp_path / "t2_crop.nii.gz")
    func_ref = _touch(tmp_path / "func_ref0.nii.gz")
    out_dir = tmp_path / "xfm"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_xfm = out_dir / "t2_to_func_warp.nii.gz"
    out_warped = out_dir / "t2_in_func.nii.gz"

    initwarp = _touch(tmp_path / "initwarp.nii.gz")

    res = _register_t2_to_func(
        t2_crop_path=t2_crop,
        func_ref_path=func_ref,
        output_xfm_path=out_xfm,
        output_warped_path=out_warped,
        policy={"registration": {"type": "rigid", "metric": "MI"}},
        t2_cord_mask_path=None,
        func_roi_mask_path=None,
        func_seg_path=None,
        initwarp_path=initwarp,
        use_segmentation_based=False,
    )

    assert res["status"] == "PASS"
    assert fake_run.cmd is not None
    assert "-initwarp" in fake_run.cmd


def test_register_t2_to_func_failure_writes_diagnostics(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_fail(cmd, capture_output=True, text=True):
        return SimpleNamespace(returncode=1, stdout="", stderr="boom")

    monkeypatch.setattr("subprocess.run", _fake_fail)

    t2_crop = _touch(tmp_path / "t2_crop.nii.gz")
    func_ref = _touch(tmp_path / "func_ref0.nii.gz")
    out_dir = tmp_path / "xfm"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_xfm = out_dir / "t2_to_func_warp.nii.gz"
    out_warped = out_dir / "t2_in_func.nii.gz"

    res = _register_t2_to_func(
        t2_crop_path=t2_crop,
        func_ref_path=func_ref,
        output_xfm_path=out_xfm,
        output_warped_path=out_warped,
        policy={"registration": {"type": "rigid", "metric": "MI"}},
        t2_cord_mask_path=None,
        func_roi_mask_path=None,
        func_seg_path=None,
        initwarp_path=None,
        use_segmentation_based=False,
    )

    assert res["status"] == "FAIL"
    diag_path = out_dir / "registration_diagnostics.txt"
    assert diag_path.exists()
    assert "Return code: 1" in diag_path.read_text(encoding="utf-8")


def test_binarize_mask_for_segmentation_threshold(tmp_path: Path) -> None:
    import numpy as np
    import nibabel as nib
    from spineprep.S3_func_init_and_crop import _binarize_mask_for_segmentation

    data = np.array([[[0.1, 0.6], [0.49, 0.51]]], dtype=np.float32)
    img = nib.Nifti1Image(data, np.eye(4))
    src = tmp_path / "roi_mask.nii.gz"
    nib.save(img, src)
    out = tmp_path / "seg.nii.gz"

    ok = _binarize_mask_for_segmentation(src, out, threshold=0.5)
    assert ok

    seg = nib.load(out).get_fdata()
    assert set(np.unique(seg)).issubset({0.0, 1.0})
    assert int(seg[0, 0, 1]) == 1
    assert int(seg[0, 1, 0]) == 0
