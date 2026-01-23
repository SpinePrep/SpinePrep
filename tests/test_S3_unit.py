
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
    _process_s3_2_registration,
    _process_s3_3_outlier_gating,
    _process_s3_4_crop_and_qc,
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
    # Test Case 1: Standard run structure
    p1 = tmp_path / "work" / "runs" / "S3_func_init_and_crop" / "sub-01" / "ses-02"
    sub, ses, root = _extract_subject_session_from_work_dir(p1)
    # The function expects directory stricture to exist? No, acts on path parts.
    # But code uses .trace() or similar? No, uses parts.
    # Wait, code uses .resolve().
    # Test extraction
    # Since paths don't exist, resolve might fail or be weird?
    # Actually checking code: `current = work_dir.resolve()`
    # We should create them to be safe or mock resolve.
    p1.mkdir(parents=True)
    sub, ses, root = _extract_subject_session_from_work_dir(p1)
    assert sub == "01"
    assert ses == "02"
    assert root == tmp_path / "work" 

    # Test Case 2: ses-none
    p2 = tmp_path / "work" / "runs" / "S3_func_init_and_crop" / "sub-03_ses-none"
    p2.mkdir(parents=True)
    sub, ses, root = _extract_subject_session_from_work_dir(p2)
    assert sub == "03"
    assert ses is None

def test_s3_2_registration_command_generation(mock_work_dir):
    # Setup inputs
    func_ref0 = mock_work_dir / "init" / "func_ref0.nii.gz"
    create_nifti(func_ref0, (10, 10, 5))
    
    cordref_crop = mock_work_dir / "cordref_crop.nii.gz"
    create_nifti(cordref_crop, (10, 10, 5))
    
    # Mock helpers
    with patch("spineprep.S3_func_init_and_crop._run_command") as mock_run:
        with patch("spineprep.S3_func_init_and_crop._find_s2_cordmask_dseg") as mock_find_mask:
            with patch("spineprep.S3_func_init_and_crop.Image") as mock_PIL: # Skip image usage
                 # Mock successful run
                 mock_run.return_value = (True, "Success")
                 
                 # Mock finding S2 mask
                 mask_path = mock_work_dir / "s2_mask.nii.gz"
                 create_nifti(mask_path, (20, 20, 10))
                 mock_find_mask.return_value = mask_path
                 
                 # Create discovery seg which is required
                 localize_dir = mock_work_dir / "init" / "localize"
                 localize_dir.mkdir(parents=True)
                 create_nifti(localize_dir / "func_ref_fast_seg.nii.gz", (10, 10, 5))
                 
                 policy = {}
                 
                 res = _process_s3_2_registration(func_ref0, cordref_crop, mock_work_dir, policy)
                 
                 assert res["registration_status"] == "PASS"
                 assert (mock_work_dir / "init" / "t2_to_func_warp.nii.gz") == res["t2_to_func_xfm_path"]
                 
                 # Verify sct_register_multimodal was called
                 calls = [args[0] for args, _ in mock_run.call_args_list]
                 # We expect crop, then register, then apply
                 assert any("sct_register_multimodal" in cmd[0] for cmd in calls)
                 assert any("sct_apply_transfo" in cmd[0] for cmd in calls)

def test_s3_3_outlier_gating_logic(mock_work_dir):
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
    
    policy = {"dummy_volumes": {"count": 2}} # Drop first 2
    
    # We dropped 2. Correct indices:
    # Original Frame 5 becomes Frame 3 (5-2).
    # Expected outlier index: 3
    
    res = _process_s3_3_outlier_gating(bold_path, ref0_path, mask_path, mock_work_dir, policy)
    
    # Verify outputs
    outlier_json = res["outlier_mask_path"]
    with open(outlier_json) as f:
        info = json.load(f)
        
    assert info["total_frames"] == 8 # 10 - 2
    assert 3 in info["outlier_indices"] # Frame 3 IS the outlier
    assert info["outlier_count"] >= 1


def test_s3_4_crop_command_generation(mock_work_dir):
    bold_path = mock_work_dir / "bold.nii.gz"
    create_nifti(bold_path, (20, 20, 10, 5))
    
    mask_path = mock_work_dir / "mask.nii.gz"
    create_nifti(mask_path, (20, 20, 10))
    
    ref_path = mock_work_dir / "ref.nii.gz"
    create_nifti(ref_path, (20, 20, 10))
    
    policy = {"crop": {"mask_diameter_mm": 35}}
    
    with patch("spineprep.S3_func_init_and_crop._run_command") as mock_run:
        with patch("spineprep.S3_func_init_and_crop.Image") as mock_PIL:
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
            
            res = _process_s3_4_crop_and_qc(bold_path, mask_path, ref_path, mock_work_dir, policy)
            
            assert res["qc_status"] == "PASS"
            
            calls = [args[0] for args, _ in mock_run.call_args_list]
            # Check create_mask
            mask_calls = [c for c in calls if "sct_create_mask" in c[0]]
            assert len(mask_calls) == 1
            assert "-size" in mask_calls[0]
            assert "35mm" in mask_calls[0]
            
