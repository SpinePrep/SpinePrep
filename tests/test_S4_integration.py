
import pytest
import shutil
import json
import numpy as np
import nibabel as nib
from pathlib import Path
from unittest.mock import patch, MagicMock

# Import the orchestrator
from spinalfmriprep.S4_func_motion_correction import run_S4_func_motion_correction

@pytest.fixture
def s4_test_env(tmp_path):
    # Setup directories
    out_dir = tmp_path / "out"
    work_dir = out_dir / "work"
    
    # Create S3-style run directory
    # S3 stores outputs in: runs/S3_func_init_and_crop/<run_name>/
    s3_run_dir = out_dir / "runs" / "S3_func_init_and_crop" / "sub-01_ses-01_task-rest_run-01"
    s3_run_dir.mkdir(parents=True)
    
    # Create dummy S3 outputs (generic filenames)
    affine = np.eye(4)
    data = np.zeros((10, 10, 5, 20)) # Small
    data[4:6, 4:6, 2:4, :] = 100 # Signal
    img = nib.Nifti1Image(data, affine)
    
    # 1. funccrop_bold.nii.gz (4D)
    bold_path = s3_run_dir / "funccrop_bold.nii.gz"
    nib.save(img, bold_path)
    
    # 2. func_ref.nii.gz (3D)
    ref_data = data[..., 0]
    ref_img = nib.Nifti1Image(ref_data, affine)
    nib.save(ref_img, s3_run_dir / "func_ref.nii.gz")
    
    # 3. funccrop_mask.nii.gz (3D)
    mask_data = np.zeros((10, 10, 5))
    mask_data[3:7, 3:7, :] = 1
    mask_img = nib.Nifti1Image(mask_data, affine)
    nib.save(mask_img, s3_run_dir / "funccrop_mask.nii.gz")
    
    return {
        "out_dir": out_dir,
        "work_dir": work_dir,
        "s3_run_dir": s3_run_dir,
        "bold_path": bold_path
    }

def test_S4_integration_flow(s4_test_env):
    out_dir = s4_test_env["out_dir"]
    work_dir = s4_test_env["work_dir"]
    s3_run_dir = s4_test_env["s3_run_dir"]
    
    # Policy
    policy = {
        "motion_correction": {
            "mode": "3d+2d",
            "stage1_coarse": {"upsample_factor": 1}, # Fast
            "stage2_slicereg": {"iterations": 1},
            "z_shift_correction": {"enabled": False}
        },
        "qc_thresholds": {
            "max_fd_mm": 5.0, # High pass
            "min_tsnr": 0.0,
            "max_high_motion_fraction": 1.0,
            "warn_fd_mm": 2.0,
            "warn_tsnr": 5.0,
            "warn_high_motion_fraction": 0.30
        },
        "qc": {
            "motion_traces": {"figsize": [10, 4], "dpi": 50, "colors": {"tx": "b", "ty": "r", "threshold": "k"}},
            "tsnr_comparison": {"figsize": [10, 4], "dpi": 50, "colormap": "gray"},
        }
    }
    
    # Mock subprocess.run for SCT
    with patch("subprocess.run") as mock_run:
        # Configure mock to create expected output file
        def side_effect(*args, **kwargs):
            cwd = kwargs.get("cwd")
            if cwd:
                # Create sct_fmri_moco outputs
                nib.save(nib.load(s4_test_env["bold_path"]), cwd / "sct_input_moco.nii.gz")
                
                # Create params tsv
                with open(cwd / "moco_params.tsv", "w") as f:
                    f.write("X\tY\n")
                    for _ in range(20):
                        f.write("0\t0\n")
                    
            return MagicMock(returncode=0)
            
        mock_run.side_effect = side_effect
        
        # Run S4 with new signature
        result = run_S4_func_motion_correction(
            s3_run_dir=s3_run_dir,
            policy=policy,
            out_dir=out_dir,
            work_dir=work_dir,
            dataset_key="test_ds",
        )
        
        # Verify result
        assert result["status"] == "PASS"
        assert result["status"] == "PASS"
        assert result["dataset_key"] == "test_ds"
        
        # Verify derivatives output
        deriv_func = out_dir / "derivatives" / "spinalfmriprep" / "sub-01" / "ses-01" / "func"
        # run_name = "sub-01_ses-01_task-rest_run-01", used as prefix
        assert (deriv_func / "sub-01_ses-01_task-rest_run-01_desc-mocoref_bold.nii.gz").exists()
        
        # Verify Figures
        figs_dir = out_dir / "derivatives" / "spinalfmriprep" / "sub-01" / "ses-01" / "figures"
        assert (figs_dir / "sub-01_ses-01_task-rest_run-01_desc-S4_motion_traces.png").exists()
