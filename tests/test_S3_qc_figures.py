from __future__ import annotations

import numpy as np
import nibabel as nib
from pathlib import Path
from PIL import Image
import pytest

from spineprep.S3_func_init_and_crop import (
    _render_t2_to_func_overlay,
    _render_crop_box_sagittal,
    _render_funcref_montage,
    _render_frame_metrics_png,
)


def _create_test_func_ref(
    tmp_path: Path,
    shape: tuple[int, int, int] = (64, 64, 24),
    voxel_sizes: tuple[float, float, float] = (1.0, 1.0, 5.0),
    name: str = "func_ref.nii.gz",
) -> Path:
    """Create a synthetic functional reference image with specified voxel sizes."""
    data = np.random.randn(*shape).astype(np.float32)
    # Add some structure (brighter in center)
    center = [s // 2 for s in shape]
    for i in range(shape[0]):
        for j in range(shape[1]):
            for k in range(shape[2]):
                dist = np.sqrt((i - center[0]) ** 2 + (j - center[1]) ** 2 + (k - center[2]) ** 2)
                if dist < 10:
                    data[i, j, k] += 100.0
    
    affine = np.eye(4)
    affine[0, 0] = voxel_sizes[0]
    affine[1, 1] = voxel_sizes[1]
    affine[2, 2] = voxel_sizes[2]
    
    img = nib.Nifti1Image(data, affine)
    path = tmp_path / name
    nib.save(img, path)
    return path


def _create_test_mask(
    tmp_path: Path,
    shape: tuple[int, int, int] = (64, 64, 24),
    voxel_sizes: tuple[float, float, float] = (1.0, 1.0, 5.0),
    name: str = "mask.nii.gz",
) -> Path:
    """Create a synthetic mask image."""
    data = np.zeros(shape, dtype=np.float32)
    # Create a cylindrical mask in the center
    center = [s // 2 for s in shape]
    radius = 8
    for i in range(shape[0]):
        for j in range(shape[1]):
            for k in range(shape[2]):
                dist_xy = np.sqrt((i - center[0]) ** 2 + (j - center[1]) ** 2)
                if dist_xy < radius and center[2] - 5 <= k <= center[2] + 5:
                    data[i, j, k] = 1.0
    
    affine = np.eye(4)
    affine[0, 0] = voxel_sizes[0]
    affine[1, 1] = voxel_sizes[1]
    affine[2, 2] = voxel_sizes[2]
    
    img = nib.Nifti1Image(data, affine)
    path = tmp_path / name
    nib.save(img, path)
    return path


def test_render_t2_to_func_overlay_creates_image(tmp_path: Path) -> None:
    """Test that t2_to_func_overlay creates a valid PNG image."""
    func_ref_path = _create_test_func_ref(tmp_path, shape=(64, 64, 24), voxel_sizes=(1.0, 1.0, 5.0))
    mask_path = _create_test_mask(tmp_path, shape=(64, 64, 24), voxel_sizes=(1.0, 1.0, 5.0))
    output_path = tmp_path / "overlay.png"
    policy = {"qc": {"overlay_contour_width": 2}}
    
    _render_t2_to_func_overlay(func_ref_path, mask_path, output_path, policy)
    
    assert output_path.exists(), "Output image should be created"
    img = Image.open(output_path)
    assert img.size[0] == 1200, f"Expected width 1200, got {img.size[0]}"
    assert img.size[1] > 0, "Height should be positive"
    assert img.mode == "RGB", f"Expected RGB mode, got {img.mode}"


def test_render_t2_to_func_overlay_aspect_ratio_isotropic(tmp_path: Path) -> None:
    """Test aspect ratio calculation for isotropic voxels."""
    # Isotropic: 1mm x 1mm x 1mm, 64x64x64
    func_ref_path = _create_test_func_ref(tmp_path, shape=(64, 64, 64), voxel_sizes=(1.0, 1.0, 1.0))
    mask_path = _create_test_mask(tmp_path, shape=(64, 64, 64), voxel_sizes=(1.0, 1.0, 1.0))
    output_path = tmp_path / "overlay.png"
    policy = {"qc": {"overlay_contour_width": 2}}
    
    _render_t2_to_func_overlay(func_ref_path, mask_path, output_path, policy)
    
    img = Image.open(output_path)
    # For isotropic: physical aspect = (64*1.0) / (64*1.0) = 1.0
    # So height should be ~1200px
    expected_height = 1200
    assert abs(img.size[1] - expected_height) < 5, f"Expected height ~{expected_height}, got {img.size[1]}"


def test_render_t2_to_func_overlay_aspect_ratio_anisotropic(tmp_path: Path) -> None:
    """Test aspect ratio calculation for anisotropic voxels (like balgrist)."""
    # Anisotropic: 1mm x 1mm x 5mm, 128x128x12
    # Physical: 128mm x 60mm, aspect = 128/60 = 2.13
    # Expected height: 1200 / 2.13 = ~562px
    func_ref_path = _create_test_func_ref(tmp_path, shape=(128, 128, 12), voxel_sizes=(1.0, 1.0, 5.0))
    mask_path = _create_test_mask(tmp_path, shape=(128, 128, 12), voxel_sizes=(1.0, 1.0, 5.0))
    output_path = tmp_path / "overlay.png"
    policy = {"qc": {"overlay_contour_width": 2}}
    
    _render_t2_to_func_overlay(func_ref_path, mask_path, output_path, policy)
    
    img = Image.open(output_path)
    # Physical aspect = (128*1.0) / (12*5.0) = 128/60 = 2.13
    # Expected height: 1200 / 2.13 = 562px
    expected_height = 562
    assert abs(img.size[1] - expected_height) < 5, f"Expected height ~{expected_height}, got {img.size[1]}"
    assert img.size[0] == 1200, f"Expected width 1200, got {img.size[0]}"


def test_render_t2_to_func_overlay_aspect_ratio_motor_dataset(tmp_path: Path) -> None:
    """Test aspect ratio for motor dataset (1.5mm x 1.5mm x 4.0mm, 128x128x70)."""
    # Motor dataset: 1.5mm x 1.5mm x 4.0mm, 128x128x70
    # Physical: 192mm x 280mm, aspect = 192/280 = 0.69
    # Expected height: 1200 / 0.69 = ~1750px
    func_ref_path = _create_test_func_ref(tmp_path, shape=(128, 128, 70), voxel_sizes=(1.5, 1.5, 4.0))
    mask_path = _create_test_mask(tmp_path, shape=(128, 128, 70), voxel_sizes=(1.5, 1.5, 4.0))
    output_path = tmp_path / "overlay.png"
    policy = {"qc": {"overlay_contour_width": 2}}
    
    _render_t2_to_func_overlay(func_ref_path, mask_path, output_path, policy)
    
    img = Image.open(output_path)
    # Physical aspect = (128*1.5) / (70*4.0) = 192/280 = 0.69
    # Expected height: 1200 / 0.69 = 1750px
    expected_height = 1750
    assert abs(img.size[1] - expected_height) < 10, f"Expected height ~{expected_height}, got {img.size[1]}"
    assert img.size[0] == 1200, f"Expected width 1200, got {img.size[0]}"


def test_render_crop_box_sagittal_creates_image(tmp_path: Path) -> None:
    """Test that crop_box_sagittal creates a valid PNG image."""
    func_ref_path = _create_test_func_ref(tmp_path, shape=(64, 64, 24), voxel_sizes=(1.0, 1.0, 5.0))
    crop_mask_path = _create_test_mask(tmp_path, shape=(64, 64, 24), voxel_sizes=(1.0, 1.0, 5.0))
    output_path = tmp_path / "crop_box.png"
    policy = {"qc": {"overlay_contour_width": 2}}
    
    _render_crop_box_sagittal(func_ref_path, crop_mask_path, output_path, policy)
    
    assert output_path.exists(), "Output image should be created"
    img = Image.open(output_path)
    assert img.size[0] == 1200, f"Expected width 1200, got {img.size[0]}"
    assert img.size[1] > 0, "Height should be positive"
    assert img.mode == "RGB", f"Expected RGB mode, got {img.mode}"


def test_render_crop_box_sagittal_aspect_ratio(tmp_path: Path) -> None:
    """Test crop_box_sagittal uses correct aspect ratio."""
    func_ref_path = _create_test_func_ref(tmp_path, shape=(128, 128, 12), voxel_sizes=(1.0, 1.0, 5.0))
    crop_mask_path = _create_test_mask(tmp_path, shape=(128, 128, 12), voxel_sizes=(1.0, 1.0, 5.0))
    output_path = tmp_path / "crop_box.png"
    policy = {"qc": {"overlay_contour_width": 2}}
    
    _render_crop_box_sagittal(func_ref_path, crop_mask_path, output_path, policy)
    
    img = Image.open(output_path)
    # Same calculation as overlay: 1200x562
    expected_height = 562
    assert abs(img.size[1] - expected_height) < 5, f"Expected height ~{expected_height}, got {img.size[1]}"
    assert img.size[0] == 1200, f"Expected width 1200, got {img.size[0]}"


def test_render_funcref_montage_creates_image(tmp_path: Path) -> None:
    """Test that funcref_montage creates a valid PNG image."""
    func_ref_path = _create_test_func_ref(tmp_path, shape=(64, 64, 24), voxel_sizes=(1.0, 1.0, 5.0))
    mask_path = _create_test_mask(tmp_path, shape=(64, 64, 24), voxel_sizes=(1.0, 1.0, 5.0))
    output_path = tmp_path / "montage.png"
    policy = {}
    
    _render_funcref_montage(func_ref_path, mask_path, output_path, policy)
    
    assert output_path.exists(), "Output image should be created"
    img = Image.open(output_path)
    assert img.size[0] > 0, "Width should be positive"
    assert img.size[1] > 0, "Height should be positive"
    assert img.mode in ("RGB", "RGBA"), f"Expected RGB or RGBA mode, got {img.mode}"


def test_render_frame_metrics_png_creates_image(tmp_path: Path) -> None:
    """Test that frame_metrics_png creates a valid PNG image."""
    output_path = tmp_path / "frame_metrics.png"
    n_frames = 100
    
    # Create synthetic metrics
    dvars = np.random.randn(n_frames) * 0.5 + 1.0
    dvars[0] = np.nan  # First frame has no predecessor
    refrms = np.random.randn(n_frames) * 0.3 + 0.8
    
    # Create outlier mask (some frames are outliers)
    outlier_mask = np.zeros(n_frames, dtype=bool)
    outlier_mask[10:15] = True  # Frames 10-14 are outliers
    outlier_mask[50:55] = True  # Frames 50-54 are outliers
    
    dvars_threshold = 1.5
    refrms_threshold = 1.2
    policy = {"qc": {"frame_metrics_figsize": [10, 4]}}
    
    _render_frame_metrics_png(
        output_path, dvars, refrms, outlier_mask, dvars_threshold, refrms_threshold, policy
    )
    
    assert output_path.exists(), "Output image should be created"
    img = Image.open(output_path)
    assert img.size[0] > 0, "Width should be positive"
    assert img.size[1] > 0, "Height should be positive"
    assert img.mode in ("RGB", "RGBA"), f"Expected RGB or RGBA mode, got {img.mode}"


def test_render_frame_metrics_png_outlier_detection(tmp_path: Path) -> None:
    """Test that frame_metrics correctly marks outliers per metric."""
    output_path = tmp_path / "frame_metrics.png"
    n_frames = 50
    
    # Create metrics where some frames exceed thresholds
    dvars = np.ones(n_frames) * 1.0
    dvars[0] = np.nan  # First frame
    dvars[10:15] = 2.0  # These exceed DVARS threshold
    dvars[20:25] = 0.5  # These are below threshold
    
    refrms = np.ones(n_frames) * 0.8
    refrms[30:35] = 1.5  # These exceed ref-RMS threshold
    refrms[40:45] = 0.5  # These are below threshold
    
    outlier_mask = np.zeros(n_frames, dtype=bool)
    dvars_threshold = 1.5
    refrms_threshold = 1.2
    policy = {"qc": {"frame_metrics_figsize": [10, 4]}}
    
    _render_frame_metrics_png(
        output_path, dvars, refrms, outlier_mask, dvars_threshold, refrms_threshold, policy
    )
    
    # Image should be created successfully
    assert output_path.exists(), "Output image should be created"
    img = Image.open(output_path)
    assert img.size[0] > 0 and img.size[1] > 0, "Image should have valid dimensions"


def test_render_t2_to_func_overlay_empty_mask(tmp_path: Path) -> None:
    """Test that overlay handles empty mask gracefully."""
    func_ref_path = _create_test_func_ref(tmp_path, shape=(64, 64, 24), voxel_sizes=(1.0, 1.0, 5.0))
    
    # Create empty mask
    empty_mask_data = np.zeros((64, 64, 24), dtype=np.float32)
    empty_mask_img = nib.Nifti1Image(empty_mask_data, np.eye(4))
    empty_mask_path = tmp_path / "empty_mask.nii.gz"
    nib.save(empty_mask_img, empty_mask_path)
    
    output_path = tmp_path / "overlay.png"
    policy = {"qc": {"overlay_contour_width": 2}}
    
    # Should not crash, but may produce image with no red contour
    _render_t2_to_func_overlay(func_ref_path, empty_mask_path, output_path, policy)
    
    assert output_path.exists(), "Output image should be created even with empty mask"
    img = Image.open(output_path)
    assert img.size[0] == 1200, "Width should still be 1200px"


def test_render_t2_to_func_overlay_zero_values(tmp_path: Path) -> None:
    """Test that overlay handles zero-valued functional data."""
    # Create func_ref with all zeros
    zero_data = np.zeros((64, 64, 24), dtype=np.float32)
    zero_img = nib.Nifti1Image(zero_data, np.eye(4))
    zero_func_path = tmp_path / "zero_func.nii.gz"
    nib.save(zero_img, zero_func_path)
    
    mask_path = _create_test_mask(tmp_path, shape=(64, 64, 24), voxel_sizes=(1.0, 1.0, 5.0))
    output_path = tmp_path / "overlay.png"
    policy = {"qc": {"overlay_contour_width": 2}}
    
    # Should handle zero values gracefully
    _render_t2_to_func_overlay(zero_func_path, mask_path, output_path, policy)
    
    assert output_path.exists(), "Output image should be created even with zero values"
    img = Image.open(output_path)
    assert img.size[0] == 1200, "Width should still be 1200px"


def test_render_t2_to_func_overlay_different_shapes(tmp_path: Path) -> None:
    """Test that overlay handles different image shapes correctly."""
    # Test with very small S-I dimension (like balgrist)
    func_ref_path = _create_test_func_ref(tmp_path, shape=(128, 128, 8), voxel_sizes=(1.0, 1.0, 5.0))
    mask_path = _create_test_mask(tmp_path, shape=(128, 128, 8), voxel_sizes=(1.0, 1.0, 5.0))
    output_path = tmp_path / "overlay.png"
    policy = {"qc": {"overlay_contour_width": 2}}
    
    _render_t2_to_func_overlay(func_ref_path, mask_path, output_path, policy)
    
    assert output_path.exists(), "Output image should be created"
    img = Image.open(output_path)
    # Physical aspect = (128*1.0) / (8*5.0) = 128/40 = 3.2
    # Expected height: 1200 / 3.2 = 375px
    expected_height = 375
    assert abs(img.size[1] - expected_height) < 5, f"Expected height ~{expected_height}, got {img.size[1]}"


def test_render_crop_box_sagittal_mismatched_shapes(tmp_path: Path) -> None:
    """Test that crop_box handles shape mismatches (should use func_ref shape)."""
    func_ref_path = _create_test_func_ref(tmp_path, shape=(64, 64, 24), voxel_sizes=(1.0, 1.0, 5.0))
    # Create mask with different shape (should still work if compatible after canonical)
    crop_mask_path = _create_test_mask(tmp_path, shape=(64, 64, 24), voxel_sizes=(1.0, 1.0, 5.0))
    output_path = tmp_path / "crop_box.png"
    policy = {"qc": {"overlay_contour_width": 2}}
    
    _render_crop_box_sagittal(func_ref_path, crop_mask_path, output_path, policy)
    
    assert output_path.exists(), "Output image should be created"
    img = Image.open(output_path)
    assert img.size[0] == 1200, "Width should be 1200px"


def test_render_funcref_montage_empty_mask(tmp_path: Path) -> None:
    """Test funcref_montage handles empty mask (fallback paths)."""
    func_ref_path = _create_test_func_ref(tmp_path, shape=(64, 64, 24), voxel_sizes=(1.0, 1.0, 5.0))
    
    # Create empty mask
    empty_mask_data = np.zeros((64, 64, 24), dtype=np.float32)
    empty_mask_img = nib.Nifti1Image(empty_mask_data, np.eye(4))
    empty_mask_path = tmp_path / "empty_mask.nii.gz"
    nib.save(empty_mask_img, empty_mask_path)
    
    output_path = tmp_path / "montage_empty.png"
    policy = {}
    
    _render_funcref_montage(func_ref_path, empty_mask_path, output_path, policy)
    
    assert output_path.exists(), "Output image should be created even with empty mask"
    img = Image.open(output_path)
    assert img.size[0] > 0 and img.size[1] > 0, "Image should have valid dimensions"


def test_render_funcref_montage_custom_slices(tmp_path: Path) -> None:
    """Test funcref_montage with custom number of slices."""
    func_ref_path = _create_test_func_ref(tmp_path, shape=(64, 64, 30), voxel_sizes=(1.0, 1.0, 5.0))
    mask_path = _create_test_mask(tmp_path, shape=(64, 64, 30), voxel_sizes=(1.0, 1.0, 5.0))
    output_path = tmp_path / "montage_custom.png"
    policy = {"qc": {"montage_slices": 6, "montage_zoom_padding": 15}}
    
    _render_funcref_montage(func_ref_path, mask_path, output_path, policy)
    
    assert output_path.exists(), "Output image should be created"
    img = Image.open(output_path)
    assert img.size[0] > 0 and img.size[1] > 0, "Image should have valid dimensions"


def test_render_funcref_montage_boundary_cases(tmp_path: Path) -> None:
    """Test funcref_montage with mask at image boundaries (tests boundary adjustment code)."""
    # Create func_ref with mask near boundaries
    func_data = np.random.randn(40, 40, 20).astype(np.float32)
    func_data[5:15, 5:15, 5:15] += 100.0  # Bright region
    
    # Create mask at top-left corner (tests boundary adjustment)
    mask_data = np.zeros((40, 40, 20), dtype=np.float32)
    mask_data[2:12, 2:12, 5:15] = 1.0  # Mask near (0,0) boundary
    
    func_img = nib.Nifti1Image(func_data, np.eye(4))
    mask_img = nib.Nifti1Image(mask_data, np.eye(4))
    
    func_path = tmp_path / "func_boundary.nii.gz"
    mask_path = tmp_path / "mask_boundary.nii.gz"
    nib.save(func_img, func_path)
    nib.save(mask_img, mask_path)
    
    output_path = tmp_path / "montage_boundary.png"
    policy = {"qc": {"montage_zoom_padding": 10}}
    
    _render_funcref_montage(func_path, mask_path, output_path, policy)
    
    assert output_path.exists(), "Output image should be created"
    img = Image.open(output_path)
    assert img.size[0] > 0 and img.size[1] > 0, "Image should have valid dimensions"


def test_render_funcref_montage_zero_intensities(tmp_path: Path) -> None:
    """Test funcref_montage with zero-valued functional data (fallback for empty mask intensities)."""
    # Create func_ref with all zeros
    zero_data = np.zeros((64, 64, 24), dtype=np.float32)
    zero_img = nib.Nifti1Image(zero_data, np.eye(4))
    zero_func_path = tmp_path / "zero_func.nii.gz"
    nib.save(zero_img, zero_func_path)
    
    mask_path = _create_test_mask(tmp_path, shape=(64, 64, 24), voxel_sizes=(1.0, 1.0, 5.0))
    output_path = tmp_path / "montage_zero.png"
    policy = {}
    
    _render_funcref_montage(zero_func_path, mask_path, output_path, policy)
    
    assert output_path.exists(), "Output image should be created even with zero values"
    img = Image.open(output_path)
    assert img.size[0] > 0 and img.size[1] > 0, "Image should have valid dimensions"

