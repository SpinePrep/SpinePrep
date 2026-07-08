"""Unit tests for S9 primary functional derivatives: pure helpers.

Covers the deterministic, numpy/IO-pure helpers in s9/process.py and
s9/orchestrate.py: the cord-FOV bounding box, TR reading (header + raw
BIDS sidecar), per-vertebral-level tSNR, tSNR maps, status classification,
sidecar writing, and small parsing/resolution helpers. No SCT calls --
synthetic numpy arrays, tmp_path, and JSON on disk.
"""
from __future__ import annotations

import json

import nibabel as nib
import numpy as np
import pytest


def _save(arr, path, affine=None):
    """Write a numpy array to a NIfTI at `path` and return the path."""
    if affine is None:
        affine = np.eye(4)
    nib.save(nib.Nifti1Image(np.asarray(arr), affine), path)
    return path


# ---------------------------------------------------------------------------
# _cord_fov_bbox -- cord cross-section (x,y) x functional z-coverage
# ---------------------------------------------------------------------------


def test_cord_fov_bbox_tightly_bounds_blob_plus_margin(tmp_path):
    """A known cord blob must produce a bbox that, in x/y, equals the cord
    extent expanded by xy_margin on each side; in z it tracks the funcref
    nonzero extent clamped to the cord z-range."""
    from spineprep.steps.s9.process import _cord_fov_bbox

    shape = (40, 40, 30)
    # Cord blob occupies x in [18,21], y in [19,22], z in [10,19].
    cord = np.zeros(shape, dtype=np.float32)
    cord[18:22, 19:23, 10:20] = 1.0
    # Funcref covers z in [8,24] (wider in z than the cord); broad in x/y.
    func = np.zeros(shape, dtype=np.float32)
    func[5:35, 5:35, 8:25] = 1.0

    cord_p = _save(cord, tmp_path / "cord.nii.gz")
    func_p = _save(func, tmp_path / "func.nii.gz")

    xy_margin, z_pad = 8, 4
    bbox = _cord_fov_bbox(func_p, cord_p, xy_margin=xy_margin, z_pad=z_pad)
    assert bbox is not None
    sx, sy, sz = bbox

    # x: cord min=18, max=21 -> [18-8, 21+1+8] = [10, 30]
    assert (sx.start, sx.stop) == (max(18 - xy_margin, 0), min(21 + 1 + xy_margin, 40))
    # y: cord min=19, max=22 -> [19-8, 22+1+8] = [11, 31]
    assert (sy.start, sy.stop) == (max(19 - xy_margin, 0), min(22 + 1 + xy_margin, 40))
    # z lower: max(func_min - pad, cord_min, 0) = max(8-4, 10, 0) = 10
    assert sz.start == max(8 - z_pad, 10, 0)
    # z upper: min(func_max+1+pad, cord_max+1, shape) = min(24+1+4, 19+1, 30) = 20
    assert sz.stop == min(24 + 1 + z_pad, 19 + 1, 30)

    # The cropped region must fully contain every nonzero cord voxel.
    cnz = np.argwhere(cord > 0)
    for i, s in enumerate((sx, sy, sz)):
        assert s.start <= cnz[:, i].min()
        assert s.stop > cnz[:, i].max()


def test_cord_fov_bbox_xy_margin_clamps_at_volume_edge(tmp_path):
    """A cord touching the x=0 face must clamp the lower bound to 0 rather
    than going negative."""
    from spineprep.steps.s9.process import _cord_fov_bbox

    shape = (20, 20, 20)
    cord = np.zeros(shape, dtype=np.float32)
    cord[0:3, 9:12, 5:15] = 1.0  # cord hugs x=0
    func = np.zeros(shape, dtype=np.float32)
    func[:, :, 4:16] = 1.0

    bbox = _cord_fov_bbox(_save(func, tmp_path / "f.nii.gz"),
                          _save(cord, tmp_path / "c.nii.gz"),
                          xy_margin=8, z_pad=4)
    assert bbox is not None
    assert bbox[0].start == 0  # clamped, not -6
    # upper x: min(2+1+8, 20) = 11
    assert bbox[0].stop == min(2 + 1 + 8, 20)


def test_cord_fov_bbox_returns_none_for_empty_cord(tmp_path):
    """No cord voxels -> no bbox."""
    from spineprep.steps.s9.process import _cord_fov_bbox

    shape = (16, 16, 16)
    cord = np.zeros(shape, dtype=np.float32)  # empty
    func = np.zeros(shape, dtype=np.float32)
    func[4:12, 4:12, 4:12] = 1.0
    bbox = _cord_fov_bbox(_save(func, tmp_path / "f.nii.gz"),
                          _save(cord, tmp_path / "c.nii.gz"))
    assert bbox is None


def test_cord_fov_bbox_returns_none_when_z_ranges_disjoint(tmp_path):
    """If functional coverage and the cord share no z, hi[2] <= lo[2] -> None.
    Cord in z [2,5], funcref in z [15,18]: clamped z window collapses."""
    from spineprep.steps.s9.process import _cord_fov_bbox

    shape = (16, 16, 20)
    cord = np.zeros(shape, dtype=np.float32)
    cord[6:9, 6:9, 2:6] = 1.0
    func = np.zeros(shape, dtype=np.float32)
    func[:, :, 15:19] = 1.0
    bbox = _cord_fov_bbox(_save(func, tmp_path / "f.nii.gz"),
                          _save(cord, tmp_path / "c.nii.gz"), z_pad=0)
    assert bbox is None


# ---------------------------------------------------------------------------
# TR readers: header (_bold_tr) and raw BIDS sidecar (_run_repetition_time)
# ---------------------------------------------------------------------------


def test_bold_tr_reads_pixdim4_from_header(tmp_path):
    """_bold_tr returns the 4th zoom (pixdim[4]) when it is a positive TR."""
    from spineprep.steps.s9.process import _bold_tr

    data = np.zeros((4, 4, 4, 3), dtype=np.float32)
    img = nib.Nifti1Image(data, np.eye(4))
    img.header.set_zooms((2.0, 2.0, 3.0, 1.55))
    p = tmp_path / "bold.nii.gz"
    nib.save(img, p)
    assert _bold_tr(p) == pytest.approx(1.55)


def test_bold_tr_none_when_zooms_lack_time(tmp_path):
    """A 3D image has no pixdim[4]; _bold_tr returns None."""
    from spineprep.steps.s9.process import _bold_tr

    p = _save(np.zeros((4, 4, 4), dtype=np.float32), tmp_path / "bold3d.nii.gz")
    assert _bold_tr(p) is None


def test_run_repetition_time_reads_run_sidecar(tmp_path):
    """The authoritative TR comes from the run's own raw BIDS sidecar."""
    from spineprep.steps.s9.orchestrate import _run_repetition_time

    run_id = "sub-01_task-rest_run-01"
    sub = tmp_path / "sub-01" / "func"
    sub.mkdir(parents=True)
    (sub / f"{run_id}_bold.json").write_text(json.dumps({"RepetitionTime": 2.312}))
    assert _run_repetition_time(str(tmp_path), run_id) == pytest.approx(2.312)


def test_run_repetition_time_falls_back_to_task_sidecar(tmp_path):
    """With no run sidecar, BIDS inheritance reads the task-level sidecar at
    the dataset root."""
    from spineprep.steps.s9.orchestrate import _run_repetition_time

    run_id = "sub-07_task-motor_run-02"
    (tmp_path / "task-motor_bold.json").write_text(
        json.dumps({"RepetitionTime": 1.8}))
    assert _run_repetition_time(str(tmp_path), run_id) == pytest.approx(1.8)


def test_run_repetition_time_none_when_no_sidecar(tmp_path):
    """No sidecar anywhere -> None (caller then falls back to the header)."""
    from spineprep.steps.s9.orchestrate import _run_repetition_time

    assert _run_repetition_time(str(tmp_path), "sub-01_task-rest_run-01") is None


def test_run_repetition_time_none_when_root_missing():
    """A nonexistent / empty bids_root yields None rather than raising."""
    from spineprep.steps.s9.orchestrate import _run_repetition_time

    assert _run_repetition_time(None, "sub-01_task-rest") is None
    assert _run_repetition_time("/no/such/path/xyz", "sub-01_task-rest") is None


# ---------------------------------------------------------------------------
# Per-vertebral-level tSNR
# ---------------------------------------------------------------------------


def test_per_vertebral_level_tsnr_matches_mean_over_std(tmp_path):
    """For a synthetic 4D series, per-level mean tSNR must equal the mean of
    voxelwise mean/std over the voxels labelled with that level."""
    from spineprep.steps.s9.process import _per_vertebral_level_tsnr

    shape = (4, 4, 4)
    n_t = 6
    rng = np.random.default_rng(0)
    data = rng.normal(loc=100.0, scale=5.0, size=shape + (n_t,)).astype(np.float32)

    # Two levels: level 1 at z=0, level 2 at z=1; rest unlabeled.
    levels = np.zeros(shape, dtype=np.int32)
    levels[:, :, 0] = 1
    levels[:, :, 1] = 2

    bold_p = _save(data, tmp_path / "bold.nii.gz")
    lvl_p = _save(levels, tmp_path / "levels.nii.gz")
    out_tsv = tmp_path / "per_level.tsv"

    n = _per_vertebral_level_tsnr(bold_p, lvl_p, out_tsv)
    assert n == 2

    # Independently derive expected per-voxel tSNR (mean/std along time).
    m = data.mean(axis=3)
    s = data.std(axis=3)
    tsnr = np.where(s > 0, m / s, 0)

    lines = out_tsv.read_text().strip().splitlines()
    assert lines[0] == "level\tmean_tsnr\tstd_tsnr\tn_voxels"
    parsed = {int(r[0]): (float(r[1]), float(r[2]), int(r[3]))
              for r in (ln.split("\t") for ln in lines[1:])}

    for lvl in (1, 2):
        mask = (levels == lvl)
        vals = tsnr[mask]
        vals = vals[(vals > 0) & np.isfinite(vals)]
        exp_mean, exp_std, exp_n = float(vals.mean()), float(vals.std()), int(vals.size)
        got_mean, got_std, got_n = parsed[lvl]
        assert got_n == exp_n
        assert got_mean == pytest.approx(exp_mean, rel=1e-3)
        assert got_std == pytest.approx(exp_std, rel=1e-3)


def test_per_vertebral_level_tsnr_header_only_on_shape_mismatch(tmp_path):
    """Mismatched levels/bold geometry -> header-only TSV and zero levels."""
    from spineprep.steps.s9.process import _per_vertebral_level_tsnr

    data = np.ones((4, 4, 4, 3), dtype=np.float32)
    levels = np.ones((4, 4, 5), dtype=np.int32)  # wrong z-extent
    out_tsv = tmp_path / "pl.tsv"
    n = _per_vertebral_level_tsnr(_save(data, tmp_path / "b.nii.gz"),
                                  _save(levels, tmp_path / "l.nii.gz"),
                                  out_tsv)
    assert n == 0
    assert out_tsv.read_text() == "level\tmean_tsnr\tstd_tsnr\tn_voxels\n"


# ---------------------------------------------------------------------------
# tSNR map + in-mask median
# ---------------------------------------------------------------------------


def test_tsnr_map_median_equals_mean_over_std(tmp_path):
    """tSNR = mean/std along time; the returned scalar is the median of the
    positive finite voxels, and the saved map matches voxelwise mean/std."""
    from spineprep.steps.s9.process import _tsnr_map

    rng = np.random.default_rng(1)
    data = rng.normal(50.0, 4.0, size=(3, 3, 3, 8)).astype(np.float32)
    out_p = tmp_path / "tsnr.nii.gz"
    med = _tsnr_map(_save(data, tmp_path / "b.nii.gz"), out_p)

    m = data.mean(axis=3); s = data.std(axis=3)
    tsnr = np.where(s > 0, m / s, 0).astype(np.float32)
    finite = tsnr[(tsnr > 0) & np.isfinite(tsnr)]
    assert med == pytest.approx(float(np.median(finite)), rel=1e-4)

    saved = nib.load(out_p).get_fdata()
    assert np.allclose(saved, tsnr, atol=1e-4)


def test_tsnr_map_none_for_single_timepoint(tmp_path):
    """A 4D image with < 2 timepoints cannot define a temporal std -> None."""
    from spineprep.steps.s9.process import _tsnr_map

    data = np.ones((3, 3, 3, 1), dtype=np.float32)
    assert _tsnr_map(_save(data, tmp_path / "b.nii.gz"),
                     tmp_path / "o.nii.gz") is None


def test_median_tsnr_in_mask_restricts_to_mask(tmp_path):
    """The in-mask median must reflect only the masked voxels."""
    from spineprep.steps.s9.process import _median_tsnr_in_mask

    rng = np.random.default_rng(2)
    data = rng.normal(80.0, 6.0, size=(5, 5, 5, 10)).astype(np.float32)
    mask = np.zeros((5, 5, 5), dtype=np.float32)
    mask[1:4, 1:4, 1:4] = 1.0

    got = _median_tsnr_in_mask(_save(data, tmp_path / "b.nii.gz"),
                               _save(mask, tmp_path / "m.nii.gz"))

    m = data.mean(axis=3); s = data.std(axis=3)
    tsnr = np.where(s > 0, m / s, 0)
    vals = tsnr[mask > 0.5]
    vals = vals[(vals > 0) & np.isfinite(vals)]
    assert got == pytest.approx(float(np.median(vals)), rel=1e-4)


# ---------------------------------------------------------------------------
# Status classification (_classify)
# ---------------------------------------------------------------------------


_THR = {
    "pass_tsnr_ratio_min": 1.5, "warn_tsnr_ratio_min": 1.2,
    "fail_tsnr_ratio_below": 1.0,
    "pass_cord_dice": 0.95, "warn_cord_dice": 0.85,
    "pass_median_in_cord_tsnr": 5.0, "warn_median_in_cord_tsnr": 3.0,
}


def test_classify_all_gates_pass():
    from spineprep.steps.s9.process import _classify
    metrics = {"tsnr_ratio_median": 1.7, "cord_dice_pre_post": 0.97,
               "tsnr_post_median": 9.0}
    status, reasons = _classify(metrics, _THR)
    assert status == "PASS"
    assert reasons == []


def test_classify_tsnr_ratio_below_fail_floor_is_fail():
    from spineprep.steps.s9.process import _classify
    metrics = {"tsnr_ratio_median": 0.9, "cord_dice_pre_post": 0.97,
               "tsnr_post_median": 9.0}
    status, reasons = _classify(metrics, _THR)
    assert status == "FAIL"
    assert any("tsnr_ratio_median FAIL" in r for r in reasons)


def test_classify_low_cord_dice_fails():
    """cord_dice below the warn floor is a FAIL gate."""
    from spineprep.steps.s9.process import _classify
    metrics = {"tsnr_ratio_median": 1.7, "cord_dice_pre_post": 0.80,
               "tsnr_post_median": 9.0}
    status, reasons = _classify(metrics, _THR)
    assert status == "FAIL"
    assert any("cord_dice FAIL" in r for r in reasons)


def test_classify_missing_tsnr_ratio_warns():
    """Absent tsnr_ratio_median downgrades to WARN, not FAIL."""
    from spineprep.steps.s9.process import _classify
    status, reasons = _classify({"cord_dice_pre_post": 0.97,
                                 "tsnr_post_median": 9.0}, _THR)
    assert status == "WARN"
    assert any("not computed" in r for r in reasons)


def test_classify_low_median_cord_tsnr_warn_then_fail():
    """Median in-cord tSNR between warn and pass floors -> WARN; below the
    warn floor -> FAIL."""
    from spineprep.steps.s9.process import _classify
    base = {"tsnr_ratio_median": 1.7, "cord_dice_pre_post": 0.97}
    warn_status, _ = _classify({**base, "tsnr_post_median": 4.0}, _THR)
    assert warn_status == "WARN"
    fail_status, _ = _classify({**base, "tsnr_post_median": 2.0}, _THR)
    assert fail_status == "FAIL"


# ---------------------------------------------------------------------------
# Small parsing / sidecar / dataset-description helpers
# ---------------------------------------------------------------------------


def test_task_from_run_id():
    from spineprep.steps.s9.process import _task_from_run_id
    assert _task_from_run_id("sub-01_task-rest_run-01") == "rest"
    assert _task_from_run_id("sub-02_task-handgrasp_acq-foo") == "handgrasp"
    assert _task_from_run_id("sub-03_run-01") is None


def test_write_bold_sidecar_contains_glm_fields(tmp_path):
    from spineprep.steps.s9.process import _write_bold_sidecar
    bold = tmp_path / "sub-01_task-rest_desc-preproc_bold.nii.gz"
    bold.write_bytes(b"stub")
    _write_bold_sidecar(bold, tr=2.0, task="rest", space="PAM50",
                        smoothing_fwhm=[2.3548, 2.3548, 11.774])
    side = bold.with_name("sub-01_task-rest_desc-preproc_bold.json")
    meta = json.loads(side.read_text())
    assert meta["RepetitionTime"] == 2.0
    assert meta["TaskName"] == "rest"
    assert meta["SpatialReference"] == "PAM50"
    assert meta["SkullStripped"] is False
    assert meta["SmoothingFWHM"] == [2.3548, 2.3548, 11.774]
    assert meta["GeneratedBy"][0]["Step"] == "S9_primary_functional_derivatives"


def test_write_bold_sidecar_omits_absent_optionals(tmp_path):
    from spineprep.steps.s9.process import _write_bold_sidecar
    bold = tmp_path / "sub-01_task-rest_bold.nii.gz"
    bold.write_bytes(b"stub")
    _write_bold_sidecar(bold, tr=None, task=None)
    meta = json.loads((tmp_path / "sub-01_task-rest_bold.json").read_text())
    assert "RepetitionTime" not in meta
    assert "TaskName" not in meta
    assert "SpatialReference" not in meta
    assert "SmoothingFWHM" not in meta


def test_ensure_dataset_description_idempotent(tmp_path):
    """Writes a derivative manifest once and does not overwrite an existing one."""
    from spineprep.steps.s9.process import _ensure_dataset_description
    root = tmp_path / "derivatives" / "spineprep"
    _ensure_dataset_description(root)
    dd = root / "dataset_description.json"
    assert dd.exists()
    first = json.loads(dd.read_text())
    assert first["DatasetType"] == "derivative"
    # A second call must not clobber a (here, hand-edited) existing file.
    dd.write_text(json.dumps({"Name": "edited"}))
    _ensure_dataset_description(root)
    assert json.loads(dd.read_text())["Name"] == "edited"


def test_resolve_bids_root_from_datasets_yaml(tmp_path):
    """_resolve_bids_root maps a dataset_key to its local BIDS path, accepting
    both the bare-string and the {path: ...} dict forms."""
    from spineprep.steps.s9.orchestrate import _resolve_bids_root
    y = tmp_path / "datasets_local.yaml"
    y.write_text(
        "datasets:\n"
        "  ds_str: /data/ds_str\n"
        "  ds_dict:\n"
        "    path: /data/ds_dict\n"
    )
    assert _resolve_bids_root(str(y), "ds_str") == "/data/ds_str"
    assert _resolve_bids_root(str(y), "ds_dict") == "/data/ds_dict"
    assert _resolve_bids_root(str(y), "missing") is None
    assert _resolve_bids_root(None, "ds_str") is None
