"""S3.3: Cord-focused crop, QC reportlets.

Writes two artefacts named with the SCT batch_processing-derived
on-disk contract that S4-S10 read directly:

  - ``funccrop_bold.nii.gz``  — 4D BOLD cropped to the cord cylinder
    (i.e. ``bold_cropped`` in literature terminology; SCT and CoSpine
    keep the ``*_crop`` suffix convention so we follow it on disk).
  - ``funccrop_mask.nii.gz``  — the cylindrical crop / FOV mask in the
    same cropped geometry.

The "cord-in-BOLD" segmentation (~3% of voxels, distinct from this
FOV mask which is ~94%) is the discovery seg from S3.1 cropped to
the same geometry: ``init/localize/func_ref_fast_seg_crop.nii.gz``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import nibabel as nib
import numpy as np
from PIL import Image

from spinalfmriprep.lib.run import run_command as _run_command
from spinalfmriprep.subtask import (
    should_exit_after_subtask,
    subtask,
    subtask_context,
)

from .io import _extract_subject_session_from_work_dir
from .localize_viz import _render_s3_1_simple_func_with_mask
from .reportlets import _render_t2_to_func_overlay


@subtask("S3.3")
def _process_s3_3_crop_and_qc(
    bold_data_path: Path,
    cordmask_func_path: Path,      # Cord mask (mask-propagated or s3.1 seg if reg removed)
    functional_ref_path: Path,     # S3.2 Robust Ref (Coarse Crop)
    func_ref_fast_path: Path,      # S3.1 Full FOV Ref (Background)
    discovery_seg_path: Path,      # S3.1 Discovery Seg (Blue Overlay)
    work_dir: Path,
    policy: dict[str, Any],
    coarse_crop_bbox: list[int] | None = None,  # Offset for coordinate mapping back to full FOV
    cordref_std_path: Optional[Path] = None,    # S2 anatomical reference (for t2-to-func overlay)
) -> dict[str, Any]:
    """
    S3.3: Cord-focused crop + QC reportlets.

    This function:
    1. Creates cylindrical crop mask
    2. Crops 4D BOLD (and drops dummies from cropped)
    3. Renders S3.3 figures
    4. Generates QC artifacts

    Returns:
        Dictionary with crop and QC results.
    """
    crop_mask_path = work_dir / "funccrop_mask.nii.gz"
    bold_crop_path = work_dir / "funccrop_bold.nii.gz"

    # Policy params
    crop_dia = policy.get("crop", {}).get("mask_diameter_mm", 40)
    dilate_xyz = policy.get("crop", {}).get("dilate_xyz", [2, 2, 0])

    # 1. Create Cylindrical Crop Mask
    cmd_mask = [
        "sct_create_mask",
        "-i", str(functional_ref_path),
        "-p", f"centerline,{cordmask_func_path}",
        "-size", f"{crop_dia}mm",
        "-o", str(crop_mask_path)
    ]
    ok, out = _run_command(cmd_mask)
    if not ok:
        return {"qc_status": "FAIL", "failure_message": f"Failed to create crop mask: {out}"}

    # 2. Crop 4D BOLD
    bold_crop_temp = work_dir / "temp_crop_bold.nii.gz"
    cmd_crop = [
        "sct_crop_image",
        "-i", str(bold_data_path),
        "-m", str(crop_mask_path),
        "-o", str(bold_crop_temp)
    ]
    ok, out = _run_command(cmd_crop)
    if not ok:
        return {"qc_status": "FAIL", "failure_message": f"Failed to crop BOLD: {out}"}

    # Data-integrity guard: sct_crop_image is a SPATIAL crop, so the timepoint
    # count must be preserved. Dummies were already dropped once in S3.1; if the
    # output frame count differs from the input, frames were silently dropped/
    # added (this is exactly the failure mode of the S3 double-dummy-drop bug,
    # which shipped undetected because nothing reconciled frame counts). Fail
    # loudly. Guards every dataset.
    try:
        n_in = nib.load(str(bold_data_path)).shape
        n_out = nib.load(str(bold_crop_temp)).shape
        in_t = n_in[3] if len(n_in) == 4 else 1
        out_t = n_out[3] if len(n_out) == 4 else 1
        if in_t != out_t:
            return {"qc_status": "FAIL",
                    "failure_message": (f"Frame-count integrity check failed: cropped BOLD "
                                        f"has {out_t} frames but input had {in_t} "
                                        f"(spatial crop must preserve timepoints).")}
    except Exception as e:
        return {"qc_status": "FAIL", "failure_message": f"Frame-count integrity check error: {e}"}

    # Dummies were ALREADY dropped in S3.1 (input is the cropped post-drop
    # series). Do NOT drop again — just finalize the cropped 4D BOLD.
    try:
        bold_crop_temp.rename(bold_crop_path)

        # Cleanup temp
        if bold_crop_temp.exists():
            bold_crop_temp.unlink()

    except Exception as e:
         return {"qc_status": "FAIL", "failure_message": f"Failed to post-process cropped BOLD: {e}"}

    # 3. Render Figures
    subject, session, out_root = _extract_subject_session_from_work_dir(work_dir)
    run_id = work_dir.name if work_dir.name.startswith("sub-") else None
    if subject and out_root:
        if session:
            figures_dir = out_root / "derivatives" / "spinalfmriprep" / f"sub-{subject}" / f"ses-{session}" / "figures"
        else:
            figures_dir = out_root / "derivatives" / "spinalfmriprep" / f"sub-{subject}" / "figures"
        prefix = run_id if run_id else (f"sub-{subject}_ses-{session}" if session else f"sub-{subject}")
    else:
        figures_dir = work_dir.parent.parent / "derivatives" / "spinalfmriprep" / "sub-test" / "ses-none" / "figures"
        prefix = "test"

    figures_dir.mkdir(parents=True, exist_ok=True)

    # Figure 1: Crop Box Sagittal
    try:
         fig1_path = figures_dir / f"{prefix}_desc-S3_crop_box_sagittal.png"

         # Render using S3.1 logic with robust box calculation
         _render_s3_1_simple_func_with_mask(
             func_path=func_ref_fast_path,  # Full FOV background
             mask_path=discovery_seg_path,   # Blue overlay (S3.1 discovery)
             output_path=fig1_path,
             policy=policy,
             crop_box=None,           # Let renderer compute from aligned mask
             padding_mm=10.0          # Explicit padding 10mm
         )

    except Exception as e:
         print(f"Fig1 (S3.3) render fail: {e}")

    # Figure 2: Funcref Montage (Axial)
    fig2_path = figures_dir / f"{prefix}_desc-S3_funcref_montage.png"
    try:
        import nibabel.processing
        ref_img = nib.as_closest_canonical(nib.load(functional_ref_path))
        ref_data = ref_img.get_fdata()
        zooms = ref_img.header.get_zooms()

        # Load discovery mask and RESAMPLE to ref to ensure pixel alignment
        mask_raw = nib.as_closest_canonical(nib.load(discovery_seg_path))
        mask_img = nib.processing.resample_from_to(mask_raw, ref_img, order=0)
        mask_data = mask_img.get_fdata()

        # Find Z range of cord mask
        z_indices = np.unique(np.where(mask_data > 0)[2])
        if len(z_indices) > 0:
            z_min, z_max = z_indices.min(), z_indices.max()
        else:
            z_min, z_max = 0, ref_data.shape[2] - 1

        z_min = max(0, z_min)
        z_max = min(ref_data.shape[2]-1, z_max)

        slices = np.linspace(z_min, z_max, 11)[1:-1].astype(int)  # 9 inner slices

        dataset_h, dataset_w = ref_data.shape[:2]
        tile_size = 128

        grid_img = Image.new('RGB', (tile_size * 3, tile_size * 3))

        for i, z in enumerate(slices):
            if i >= 9: break
            row = i // 3
            col = i % 3

            sl = ref_data[:, :, z]
            mask_sl = mask_data[:, :, z]

            coords = np.argwhere(mask_sl > 0)
            if coords.size > 0:
                center_x, center_y = np.median(coords, axis=0).astype(int)

                x_min_c, y_min_c = coords.min(axis=0)
                x_max_c, y_max_c = coords.max(axis=0)
                dx_mm = (x_max_c - x_min_c + 1) * zooms[0]
                dy_mm = (y_max_c - y_min_c + 1) * zooms[1]
                diameter_mm = max(dx_mm, dy_mm)
                diameter_mm = max(diameter_mm, 5.0)

                target_fov_mm = 2.0 * diameter_mm

                fov_x = int(target_fov_mm / zooms[0])
                fov_y = int(target_fov_mm / zooms[1])

            else:
                center_x, center_y = dataset_h // 2, dataset_w // 2
                fov_x, fov_y = dataset_h // 2, dataset_w // 2

            crop_size = max(fov_x, fov_y)

            x_start = max(0, center_x - crop_size // 2)
            x_end = min(dataset_h, x_start + crop_size)
            if x_end - x_start < crop_size:
                 if x_start == 0:
                     x_end = min(dataset_h, x_start + crop_size)
                 elif x_end == dataset_h:
                     x_start = max(0, x_end - crop_size)

            y_start = max(0, center_y - crop_size // 2)
            y_end = min(dataset_w, y_start + crop_size)
            if y_end - y_start < crop_size:
                 if y_start == 0:
                     y_end = min(dataset_w, y_start + crop_size)
                 elif y_end == dataset_w:
                     y_start = max(0, y_end - crop_size)

            sl_crop = sl[x_start:x_end, y_start:y_end]
            sl_disp = np.rot90(sl_crop)

            vmin, vmax = np.percentile(sl_disp, [1, 99])
            if vmax > vmin:
                sl_norm = np.clip((sl_disp - vmin) / (vmax - vmin), 0, 1)
            else:
                sl_norm = sl_disp

            rgb_sl = np.repeat((sl_norm * 255).astype(np.uint8)[..., np.newaxis], 3, axis=2)
            pil_sl = Image.fromarray(rgb_sl)

            pil_sl = pil_sl.resize((tile_size, tile_size), resample=Image.Resampling.NEAREST)

            grid_img.paste(pil_sl, (col * tile_size, row * tile_size))

        grid_img.save(fig2_path)

    except Exception as e:
        print(f"Fig2 render fail: {e}")

    # Figure 3: T2-to-Func Overlay (anat vs func spatial coherence)
    fig3_path = figures_dir / f"{prefix}_desc-S3_t2_to_func_overlay.png"
    try:
        _render_t2_to_func_overlay(
            func_ref_path=functional_ref_path,
            cordref_std_path=cordref_std_path,
            cordmask_func_path=cordmask_func_path,
            output_path=fig3_path,
        )
    except Exception as e:
        print(f"Fig3 (t2_to_func_overlay) render fail: {e}")

    result = {
        "bold_crop_path": bold_crop_path,
        "crop_mask_path": crop_mask_path,
        "qc_status": "PASS",
        "figures": [fig1_path, fig2_path, fig3_path]
    }

    return result
