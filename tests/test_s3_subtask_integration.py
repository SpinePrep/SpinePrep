"""
Integration tests for S3 subtask execution.

Tests that S3.1 can be run independently using --subtask flag.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

from spineprep.S3_func_init_and_crop import (
    _process_s3_1_dummy_drop_and_localization,
    run_S3_func_init_and_crop,
)
from spineprep.subtask import ExecutionContext, set_execution_context, should_exit_after_subtask


def test_s3_1_subtask_execution(tmp_path):
    """Test that S3.1 executes correctly when targeted."""
    # Set up execution context for S3.1
    set_execution_context(ExecutionContext(target_subtask="S3.1"))

    try:
        # Create test BOLD file
        # Use proper layout: {out_root}/runs/S3...
        out_root = tmp_path
        work_dir = out_root / "runs" / "S3_func_init_and_crop" / "sub-test" / "ses-none" / "func" / "test_bold.nii"
        work_dir.mkdir(parents=True, exist_ok=True)

        import nibabel as nib
        import numpy as np

        test_bold_path = work_dir / "test_bold.nii.gz"
        test_data = np.random.rand(64, 64, 24, 100).astype(np.float32)
        test_affine = np.eye(4)
        test_img = nib.Nifti1Image(test_data, test_affine)
        nib.save(test_img, test_bold_path)

        # Create S2.1 cordref_std output (required for S3.1 layered figure)
        s2_work_dir = out_root / "work" / "S2_anat_cordref" / "sub-test_ses-none"
        s2_work_dir.mkdir(parents=True, exist_ok=True)
        cordref_std_path = s2_work_dir / "cordref_std.nii.gz"
        # Create a simple 3D anatomical reference matching func dimensions
        cordref_data = np.random.rand(64, 64, 24).astype(np.float32)
        cordref_img = nib.Nifti1Image(cordref_data, test_affine)
        nib.save(cordref_img, cordref_std_path)

        policy = {
            "dummy_volumes": {"count": 4},
            "func_localization": {
                "enabled": True,
                "method": "deepseg",
                "task": "spinalcord",
            },
            "qc": {
                "overlay_contour_width": 2,
            },
        }

        # Execute S3.1
        result = _process_s3_1_dummy_drop_and_localization(
            test_bold_path, work_dir, policy
        )

        # Verify S3.1 outputs exist
        assert result["localization_status"] == "PASS", f"Status: {result.get('localization_status')}, Message: {result.get('failure_message')}"
        assert result["func_ref_fast_path"].exists()
        assert result["func_ref0_path"].exists()
        assert result["discovery_seg_path"].exists()
        assert result["roi_mask_path"].exists()
        assert result["func_ref_fast_crop_path"].exists()
        # Verify figure was created (if rendering succeeded)
        if result.get("figure_path"):
            assert result["figure_path"].exists()

        # Verify that we should exit after S3.1
        assert should_exit_after_subtask("S3.1") is True

    finally:
        set_execution_context(None)


def test_s3_1_only_via_run_function(tmp_path):
    """Test running S3.1 only via run_S3_func_init_and_crop with subtask_id."""
    # Create output directory
    out_dir = tmp_path / "test_output"

    # Run with subtask_id="S3.1"
    result = run_S3_func_init_and_crop(
        subtask_id="S3.1",
        out=str(out_dir),
    )

    # Verify result
    # Verify result
    assert result.status == "PASS"
    
    # Check outputs for S3.1
    # StepResult doesn't return the detailed dict now. We check files.
    # But wait, run_S3... in subtask mode might still return the dict?
    # No, USER changed it to return StepResult always.
    # We must check files.
    
    run_work_dir = out_dir / "runs" / "S3_func_init_and_crop" / "sub-test" / "ses-none" / "func" / "test_bold.nii"
    assert (run_work_dir / "init" / "func_ref0.nii.gz").exists()
    assert (run_work_dir / "init" / "localize" / "func_ref_fast_seg.nii.gz").exists()




def test_s3_1_skips_later_subtasks(tmp_path):
    """Test that S3.2, S3.3, S3.4 are skipped when only S3.1 is targeted."""
    # Set up execution context for S3.1
    set_execution_context(ExecutionContext(target_subtask="S3.1"))

    try:
        from spineprep.S3_func_init_and_crop import (
            _process_s3_2_registration,
            _process_s3_3_outlier_gating,
            _process_s3_4_crop_and_qc,
        )

        work_dir = tmp_path / "work"
        work_dir.mkdir(parents=True, exist_ok=True)

        policy = {}

        # S3.2 should return None (skipped)
        result_s3_2 = _process_s3_2_registration(
            Path("/dummy/ref0.nii.gz"),
            Path("/dummy/cordref.nii.gz"),
            work_dir,
            policy,
        )
        assert result_s3_2 is None

        # S3.3 should return None (skipped)
        result_s3_3 = _process_s3_3_outlier_gating(
            Path("/dummy/bold.nii.gz"),
            Path("/dummy/ref0.nii.gz"),
            Path("/dummy/mask.nii.gz"),
            work_dir,
            policy,
        )
        assert result_s3_3 is None

        # S3.4 should return None (skipped)
        result_s3_4 = _process_s3_4_crop_and_qc(
            Path("/dummy/bold.nii.gz"),
            Path("/dummy/mask.nii.gz"),
            work_dir,
            policy,
        )
        assert result_s3_4 is None

    finally:
        set_execution_context(None)


def test_s3_all_subtasks_without_target(tmp_path):
    """Test that all subtasks execute when no target is specified."""
    # No execution context (all subtasks should run)
    set_execution_context(None)

    try:
        out_dir = tmp_path / "test_output_all"

        # Run without subtask_id
        result = run_S3_func_init_and_crop(
            subtask_id=None,
            out=str(out_dir),
        )

        # Verify all subtasks executed
        assert result.status == "PASS"
        # StepResult does not expose subtask breakdown. 
        # Check byproducts.
        run_work_dir = out_dir / "runs" / "S3_func_init_and_crop" / "sub-test" / "ses-none" / "func" / "test_bold.nii"
        assert (run_work_dir / "init" / "func_ref0.nii.gz").exists() # S3.1
        assert (run_work_dir / "init" / "t2_to_func_warp.nii.gz").exists() # S3.2
        assert (run_work_dir / "metrics" / "frame_metrics.tsv").exists() # S3.3
        assert (run_work_dir / "funccrop_bold.nii.gz").exists() # S3.4

    finally:
        set_execution_context(None)

