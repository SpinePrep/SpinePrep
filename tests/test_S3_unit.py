
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
import sys
import numpy as np
import nibabel as nib
import json
import shutil
import csv

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from spineprep.S3_func_init_and_crop import (
    _process_s3_2_outlier_gating,
    _process_s3_3_crop_and_qc,
    _extract_subject_session_from_work_dir
)

# Helper to create dummy nifti
def create_nifti(path, shape, affine=np.eye(4)):
    data = np.zeros(shape, dtype=np.float32)
    img = nib.Nifti1Image(data, affine)
    path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(img, path)
    return img

@pytest.fixture
def mock_work_dir(tmp_path):
    d = tmp_path / "work" / "runs" / "S3_func_init_and_crop" / "sub-TEST" / "ses-01"
    d.mkdir(parents=True, exist_ok=True)
    return d

def test_extract_subject_session(tmp_path):
    # Test Case 1: Flat run ID with session (actual production format)
    p1 = tmp_path / "work" / "runs" / "S3_func_init_and_crop" / "sub-01_ses-02_task-rest"
    p1.mkdir(parents=True)
    sub, ses, root = _extract_subject_session_from_work_dir(p1)
    assert sub == "01"
    assert ses == "02"
    assert root == tmp_path / "work" 

    # Test Case 2: Flat run ID without session
    p2 = tmp_path / "work" / "runs" / "S3_func_init_and_crop" / "sub-03_task-motor"
    p2.mkdir(parents=True)
    sub, ses, root = _extract_subject_session_from_work_dir(p2)
    assert sub == "03"
    assert ses is None
    assert root == tmp_path / "work"
    
    # Test Case 3: ses-none explicit (should return None for session)
    p3 = tmp_path / "work" / "runs" / "S3_func_init_and_crop" / "sub-04_ses-none_task-test"
    p3.mkdir(parents=True)
    sub, ses, root = _extract_subject_session_from_work_dir(p3)
    assert sub == "04"
    assert ses is None



def test_s3_2_outlier_gating_logic(mock_work_dir):
    # Create 4D BOLD with known outlier
    # 10 frames. Frame 5 is outlier.
    shape = (5, 5, 2, 10)
    data = np.random.normal(100, 5, shape) # Signal
    # Make frame 5 outlier (spike)
    data[..., 5] += 50
    
    bold_path = mock_work_dir / "func_bold_coarse.nii.gz"
    img = nib.Nifti1Image(data, np.eye(4))
    nib.save(img, bold_path)
    
    # Ref0
    ref0_path = mock_work_dir / "func_ref0.nii.gz"
    # Ref0 is median of data (approx)
    ref0_data = np.median(data, axis=3)
    nib.save(nib.Nifti1Image(ref0_data, np.eye(4)), ref0_path)
    
    # Mask (Full mask for logic test)
    mask_path = mock_work_dir / "init" / "cordmask_space_func.nii.gz"
    mask_path.parent.mkdir(parents=True, exist_ok=True)
    mask_data = np.ones(shape[:3], dtype=np.uint8)
    nib.save(nib.Nifti1Image(mask_data, np.eye(4)), mask_path)
    
    policy = {"dummy": {"drop_count": 2}}

    # func_bold_coarse is ALREADY dummy-dropped by S3.1 — S3.2 must NOT drop
    # again (that was the double-drop bug). So all 10 frames are preserved and
    # the outlier injected at frame 5 stays at index 5 (no shift).
    res = _process_s3_2_outlier_gating(bold_path, ref0_path, mask_path, mock_work_dir, policy)

    # Verify outputs
    outlier_json = res["outlier_mask_path"]
    with open(outlier_json) as f:
        info = json.load(f)

    assert info["total_frames"] == 10  # no re-drop in S3.2
    assert 5 in info["outlier_indices"]  # outlier stays at its original frame
    assert info["outlier_count"] >= 1


def test_s3_3_crop_command_generation(mock_work_dir):
    bold_path = mock_work_dir / "bold.nii.gz"
    create_nifti(bold_path, (20, 20, 10, 5))
    
    mask_path = mock_work_dir / "mask.nii.gz"
    create_nifti(mask_path, (20, 20, 10))
    
    ref_path = mock_work_dir / "ref.nii.gz"
    create_nifti(ref_path, (20, 20, 10))
    
    policy = {"crop": {"mask_diameter_mm": 35}}
    
    with patch("spineprep.steps.s3.crop._run_command") as mock_run:
        with patch("spineprep.steps.s3.crop.Image") as mock_PIL:
            # Mock success
            mock_run.return_value = (True, "Success")
            
            # Need to create the output of sct_crop_image because the code loads it to save final
            # Mocking _run_command just avoids execution. 
            # But the code does: 
            #   bold_crop_temp = ...
            #   _run(sct_crop_image ... -o bold_crop_temp)
            #   img = nib.load(bold_crop_temp)
            # So verification will fail if bold_crop_temp doesn't exist.
            # We must verify calls BEFORE expected crash or mock the nib.load part too.
            # Or simpler: create the expected temp file as a side effect.
            
            def side_effect(cmd):
                # If command involves sct_crop_image with -o output
                if "sct_crop_image" in cmd[0] or "sct_crop_image" in cmd:
                    # Find output path
                    try:
                        idx = cmd.index("-o")
                        out_p = Path(cmd[idx+1])
                        create_nifti(out_p, (10, 10, 10, 5)) # Cropped shape
                    except ValueError:
                        pass
                return (True, "Success")
                
            mock_run.side_effect = side_effect
            
            # Create dummy S3.1 outputs required by S3.3
            func_ref_fast = mock_work_dir / "func_ref_fast.nii.gz"
            create_nifti(func_ref_fast, (20, 20, 10))
            discovery_seg = mock_work_dir / "discovery_seg.nii.gz"
            create_nifti(discovery_seg, (20, 20, 10))
            
            res = _process_s3_3_crop_and_qc(bold_path, mask_path, ref_path, func_ref_fast, discovery_seg, mock_work_dir, policy)
            
            assert res["qc_status"] == "PASS"
            
            calls = [args[0] for args, _ in mock_run.call_args_list]
            # Check create_mask
            mask_calls = [c for c in calls if "sct_create_mask" in c[0]]
            assert len(mask_calls) == 1
            assert "-size" in mask_calls[0]
            assert "35mm" in mask_calls[0]


# ---------------------------------------------------------------------------
# S3.1 drift gate
# ---------------------------------------------------------------------------


def test_drift_gate_passes_cord_like_segmentation():
    """Cord-sized segmentation (~50 mm² per slice) passes the gate."""
    from spineprep.steps.s3.localize import _check_drift_gate

    # 1mm isotropic, axial; Z axis is superior. Build a thin cord (5x5 voxels = 25 mm²)
    # over 30 slices.
    data = np.zeros((40, 40, 40), dtype=np.float32)
    data[18:23, 18:23, 5:35] = 1
    affine = np.diag([1.0, 1.0, 1.0, 1.0])  # RAS

    policy = {"func_localization": {"discover": {"drift_gate": {
        "enabled": True,
        "superior_slices_check": 5,
        "area_spike_threshold": 4.0,
        "absolute_area_cap_mm2": 200.0,
    }}}}

    passed, msg, info = _check_drift_gate(data, affine, policy)
    assert passed, f"expected PASS, got {msg}"
    assert info["thresholds"]["absolute_area_cap_mm2"] == 200.0


def test_drift_gate_rejects_brain_blob():
    """A segmentation that opens up into a brain-sized cross-section is rejected."""
    from spineprep.steps.s3.localize import _check_drift_gate

    data = np.zeros((60, 60, 40), dtype=np.float32)
    # Cord-sized portion at slices 5-25 (~25 mm² per slice)
    data[18:23, 18:23, 5:25] = 1
    # Brain-sized blob at slices 30-35 (~625 mm² per slice >> 200 cap)
    data[10:35, 10:35, 30:36] = 1
    affine = np.diag([1.0, 1.0, 1.0, 1.0])

    policy = {"func_localization": {"discover": {"drift_gate": {
        "enabled": True,
        "superior_slices_check": 5,
        "area_spike_threshold": 4.0,
        "absolute_area_cap_mm2": 200.0,
    }}}}

    passed, msg, _ = _check_drift_gate(data, affine, policy)
    assert not passed
    assert "brain detected" in msg


def test_drift_gate_disabled_returns_pass():
    """When the policy disables the gate it never fails, even on obvious brain."""
    from spineprep.steps.s3.localize import _check_drift_gate

    data = np.zeros((60, 60, 40), dtype=np.float32)
    data[5:55, 5:55, 30:36] = 1  # huge blob
    affine = np.diag([1.0, 1.0, 1.0, 1.0])

    policy = {"func_localization": {"discover": {"drift_gate": {"enabled": False}}}}
    passed, _, _ = _check_drift_gate(data, affine, policy)
    assert passed


def test_drift_gate_rejects_cord_too_short():
    """A few-slice ribbon of cord is dropped via the min_z_slices guard."""
    from spineprep.steps.s3.localize import _check_drift_gate

    data = np.zeros((40, 40, 40), dtype=np.float32)
    data[18:23, 18:23, 5:8] = 1  # only 3 slices, well below min
    affine = np.diag([1.0, 1.0, 1.0, 1.0])

    policy = {"func_localization": {"discover": {
        "min_z_slices": 20,
        "drift_gate": {
            "enabled": True,
            "superior_slices_check": 5,
            "area_spike_threshold": 4.0,
            "absolute_area_cap_mm2": 200.0,
        },
    }}}

    passed, msg, info = _check_drift_gate(data, affine, policy)
    assert not passed
    assert "cord too short" in msg
    assert info["n_cord_slices"] == 3


def test_drift_gate_min_extent_off_when_zero():
    """min_z_slices=0 disables only the min-extent guard, not the gate itself."""
    from spineprep.steps.s3.localize import _check_drift_gate

    data = np.zeros((40, 40, 40), dtype=np.float32)
    data[18:23, 18:23, 5:8] = 1  # 3 slices, cord-sized
    affine = np.diag([1.0, 1.0, 1.0, 1.0])

    policy = {"func_localization": {"discover": {
        "min_z_slices": 0,
        "drift_gate": {
            "enabled": True,
            "superior_slices_check": 5,
            "area_spike_threshold": 4.0,
            "absolute_area_cap_mm2": 200.0,
        },
    }}}

    passed, _, _ = _check_drift_gate(data, affine, policy)
    assert passed
            


# ---------------------------------------------------------------------------
# S3.1 caudal completion (deepseg under-segments the lower cord on low-SNR
# functional references; propseg's contiguous caudal cord is unioned on).
# ---------------------------------------------------------------------------

from spineprep.steps.s3.localize import _caudal_union


def _disc(cx, cy, z, r=2):
    """Small filled cord disc of radius r at (cx, cy) on slice z."""
    yy, xx = np.mgrid[0:40, 0:40]
    return (xx - cx) ** 2 + (yy - cy) ** 2 <= r ** 2, z


def _build(shape, slices):
    v = np.zeros(shape, dtype=np.float32)
    for mask2d, z in slices:
        v[:, :, z][mask2d] = 1
    return v


def test_caudal_union_extends_genuine_cord():
    """propseg cord contiguous below the deepseg caudal end is added."""
    shape = (40, 40, 30)
    aff = np.diag([1.6, 1.6, 4.4, 1.0])  # RAS: axis 2 = S+
    # deepseg present on z=20..25 (cord at x=20,y=20)
    deep = _build(shape, [_disc(20, 20, z) for z in range(20, 26)])
    # propseg tracks the same axis and continues to z=17..25
    prop = _build(shape, [_disc(20, 20, z) for z in range(17, 26)])
    out, added = _caudal_union(deep, prop, aff, lateral_tol_vox=5, max_gap=0,
                               area_mult=3.0, axis_tol_vox=3.1)
    assert sorted(added) == [17, 18, 19]
    assert (out[:, :, 17] > 0).any()


def test_caudal_union_rejects_offaxis_runaway():
    """propseg that curves progressively off the cord axis (vessel/airway) is cut."""
    shape = (40, 40, 30)
    aff = np.diag([1.6, 1.6, 4.4, 1.0])
    deep = _build(shape, [_disc(20, 20, z) for z in range(20, 26)])
    # propseg drifts +4 vox/slice in y after z=19 -> off-axis quickly
    prop_slices = [_disc(20, 20, 19)]
    for i, z in enumerate(range(18, 12, -1)):
        prop_slices.append(_disc(20, 20 + 4 * (i + 1), z))
    prop = _build(shape, prop_slices)
    out, added = _caudal_union(deep, prop, aff, lateral_tol_vox=5, max_gap=0,
                               area_mult=3.0, axis_tol_vox=3.1)
    # z=19 stays on-axis and is kept; the runaway below is rejected
    assert added == [19]


def test_caudal_union_noop_when_nothing_below():
    """A mask already reaching the FOV / cord end gets no caudal addition."""
    shape = (40, 40, 30)
    aff = np.diag([1.6, 1.6, 4.4, 1.0])
    deep = _build(shape, [_disc(20, 20, z) for z in range(2, 26)])
    prop = _build(shape, [_disc(20, 20, z) for z in range(10, 26)])  # above deep caudal end
    out, added = _caudal_union(deep, prop, aff, lateral_tol_vox=5, max_gap=0,
                               area_mult=3.0, axis_tol_vox=3.1)
    assert added == []
    assert np.array_equal(out > 0, deep > 0)


# ---------------------------------------------------------------------------
# S3.1 caudal completion, second stage: intensity-guided trace on the reference
# for the lowest-SNR tails where neither deepseg nor propseg re-activate.
# ---------------------------------------------------------------------------

from spineprep.steps.s3.localize import _caudal_trace


def _ref_with_cord(shape, cord_slices, cord_val=300.0, bg=30.0, cx=20, cy=20, r=2):
    """Reference image: bright cord discs on the given slices over a dim bg."""
    img = np.full(shape, bg, dtype=np.float32)
    yy, xx = np.mgrid[0:shape[0], 0:shape[1]]
    for z in cord_slices:
        img[:, :, z][(xx - cx) ** 2 + (yy - cy) ** 2 <= r ** 2] = cord_val
    return img


def test_caudal_trace_extends_faint_cord():
    """A compact bright cord continuing below the mask is traced and added."""
    shape = (40, 40, 30)
    aff = np.diag([1.6, 1.6, 4.4, 1.0])  # axis 2 = S+, caudal = low z
    deep = _build(shape, [_disc(20, 20, z) for z in range(20, 26)])
    # reference has cord all the way down to z=15
    img = _ref_with_cord(shape, list(range(15, 26)))
    out, added = _caudal_trace(deep, img, aff)
    assert sorted(added) == [15, 16, 17, 18, 19]
    assert (out[:, :, 15] > 0).any()


def test_caudal_trace_noop_on_pure_noise():
    """No bright cord below the terminus -> nothing added (honest noise floor)."""
    shape = (40, 40, 30)
    aff = np.diag([1.6, 1.6, 4.4, 1.0])
    deep = _build(shape, [_disc(20, 20, z) for z in range(20, 26)])
    img = _ref_with_cord(shape, list(range(20, 26)))  # cord only where deepseg is
    out, added = _caudal_trace(deep, img, aff)
    assert added == []
    assert np.array_equal(out > 0, deep > 0)


def test_caudal_trace_rejects_bright_csf_band():
    """A wide, uniformly-bright CSF band below the terminus is rejected."""
    shape = (40, 40, 30)
    aff = np.diag([1.6, 1.6, 4.4, 1.0])
    deep = _build(shape, [_disc(20, 20, z) for z in range(20, 26)])
    img = _ref_with_cord(shape, list(range(20, 26)))
    # a wide bright band (cord-canal CSF) on z=17..19 spanning many voxels
    img[14:27, 18:23, 17:20] = 320.0
    out, added = _caudal_trace(deep, img, aff)
    assert added == []


def test_caudal_trace_stops_at_airway_lateral_jump():
    """A bright blob well off the cord axis (airway) is not followed."""
    shape = (40, 40, 30)
    aff = np.diag([1.6, 1.6, 4.4, 1.0])
    deep = _build(shape, [_disc(20, 20, z) for z in range(20, 26)])
    img = _ref_with_cord(shape, list(range(20, 26)))
    # bright compact blob 12 vox (~19 mm) off-axis below the terminus
    img_off = _ref_with_cord(shape, list(range(15, 20)), cx=20, cy=32)
    img = np.maximum(img, img_off)
    out, added = _caudal_trace(deep, img, aff)
    assert added == []
