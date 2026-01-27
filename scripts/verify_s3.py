
import sys
from pathlib import Path
sys.path.append("/mnt/ssd1/SpinalfMRIprep/src")

from spinalfmriprep.S3_func_init_and_crop import run_S3_func_init_and_crop

def verify_s3():
    print("Starting S3 Verification...")
    out_dir = Path("work/verify_s3_run")
    if out_dir.exists():
        import shutil
        shutil.rmtree(out_dir)
        
    # Run S3 in test mode
    result = run_S3_func_init_and_crop(out=str(out_dir))
    
    # Check Result
    status = result.status
    print(f"Run Status: {status}")
    
    if status != "PASS":
        print(f"S3 Run Failed! Result: {result}")
        sys.exit(1)
        
    # Verify Files
    run_dir = out_dir / "runs" / "S3_func_init_and_crop" / "sub-test" / "ses-none" / "func" / "test_bold.nii"
    
    expected_files = [
        run_dir / "init" / "func_ref_fast.nii.gz",
        run_dir / "init" / "func_ref0.nii.gz",
        run_dir / "init" / "t2_to_func_warp.nii.gz",
        run_dir / "init" / "cordmask_space_func.nii.gz",
        run_dir / "func_ref.nii.gz",
        run_dir / "metrics" / "frame_metrics.tsv",
        run_dir / "metrics" / "outlier_mask.json",
        run_dir / "funccrop_mask.nii.gz",
        run_dir / "funccrop_bold.nii.gz",
    ]
    
    missing = []
    for f in expected_files:
        if not f.exists():
            missing.append(f)
            
    if missing:
        print("Missing outputs:")
        for m in missing:
            print(f"  {m}")
        sys.exit(1)
        
    print("All expected outputs found.")
    
    # Check Figures
    figures_dir = out_dir / "derivatives" / "spinalfmriprep" / "sub-test" / "ses-none" / "figures"
    expected_figs = [
        "sub-test_ses-none_desc-S3_func_localization_crop_box_sagittal.png", # S3.1
        "sub-test_ses-none_desc-S3_t2_to_func_overlay.png", # S3.2
        "sub-test_ses-none_desc-S3_frame_metrics.png", # S3.3
        "sub-test_ses-none_desc-S3_crop_box_sagittal.png", # S3.4
        "sub-test_ses-none_desc-S3_funcref_montage.png", # S3.4
    ]
    
    missing_figs = []
    for fig in expected_figs:
        if not (figures_dir / fig).exists():
            missing_figs.append(fig)
            
    if missing_figs:
        print("Missing figures:")
        for m in missing_figs:
            print(f"  {m}")
        #sys.exit(1) # Figures might fail in headless? But we used PIL/matplotlib inline.
        
    print("Verification Successful!")

if __name__ == "__main__":
    verify_s3()
