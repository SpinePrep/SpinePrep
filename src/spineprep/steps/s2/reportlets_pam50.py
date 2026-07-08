"""Reportlet: PAM50 registration overlay GIF renderer."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import nibabel as nib
import numpy as np
from PIL import Image, ImageDraw

from .io import _run_command, _write_json
from .register import (
    _resolve_pam50_dir,
    _find_pam50_cord_mask,
    _extract_centerline_csv,
    _compute_si_mismatch_from_centerlines,
)
from .validate import _largest_connected_component
from .reportlets_core import (
    _scale_to_rgb,
    _fit_resize_and_paste_rgb,
    _fit_resize_and_paste_mask,
    _mask_contour_2d,
    _draw_thick_contour,
)


def _render_pam50_reg_overlay_gif(
    qc_root: Path,
    subject_image: Optional[Path],
    pam50_in_s2: Optional[Path],
    subject_cordmask: Optional[Path],
    warp_template2anat: Optional[Path],
    subject_label: Optional[str],
    session_label: Optional[str],
    vertebral_labels_path: Optional[Path] = None,
    canvas_size: tuple[int, int] = (2400, 1200),
    mosaic_cols: int = 6,
    mosaic_rows: int = 4,
    frame_delay_ms: int = 900,
    crossfade_steps: int = 10,
) -> Optional[Path]:
    """Render flicker/crossfade GIF: subject underlay vs PAM50-in-S2 underlay, with identical cord contours."""
    if (
        subject_image is None
        or pam50_in_s2 is None
        or subject_cordmask is None
        or warp_template2anat is None
    ):
        return None
    qc_root.mkdir(parents=True, exist_ok=True)

    try:
        subj_img = nib.as_closest_canonical(nib.load(subject_image))
        pam_img = nib.as_closest_canonical(nib.load(pam50_in_s2))
        seg_img = nib.as_closest_canonical(nib.load(subject_cordmask))
    except Exception:
        return None

    subj = subj_img.get_fdata()
    pam = pam_img.get_fdata()
    seg = seg_img.get_fdata()
    if subj.ndim > 3:
        subj = subj[..., 0]
    if pam.ndim > 3:
        pam = pam[..., 0]
    if seg.ndim > 3:
        seg = seg[..., 0]

    if subj.shape != seg.shape or pam.shape != subj.shape:
        return None

    subj_mask = seg > 0
    if not subj_mask.any():
        return None

    # Filter out scattered cord mask fragments - keep only largest connected component
    subj_mask = _largest_connected_component(subj_mask)
    if not subj_mask.any():
        return None

    pam50_dir = _resolve_pam50_dir()
    if pam50_dir is None:
        return None
    pam50_cord = _find_pam50_cord_mask(pam50_dir)
    if pam50_cord is None:
        return None

    # Warp PAM50 cord mask to subject space using SCT-native method
    warp_qc_dir = qc_root / "warp_template"
    warp_qc_dir.mkdir(parents=True, exist_ok=True)

    ok, _ = _run_command(
        [
            "sct_warp_template",
            "-d", str(subject_image),
            "-w", str(warp_template2anat),
            "-a", "0",
            "-qc", str(warp_qc_dir),
        ]
    )
    if not ok:
        return None

    pam_cord_in_s2 = None
    for candidate_name in ("PAM50_cord.nii.gz", "PAM50_cordseg.nii.gz", "template_cord.nii.gz"):
        candidate = warp_qc_dir / candidate_name
        if candidate.exists():
            pam_cord_in_s2 = candidate
            break

    if pam_cord_in_s2 is None or not pam_cord_in_s2.exists():
        warp_dir = warp_template2anat.parent
        for candidate_name in ("PAM50_cord.nii.gz", "PAM50_cordseg.nii.gz", "template_cord.nii.gz"):
            candidate = warp_dir / candidate_name
            if candidate.exists():
                pam_cord_in_s2 = candidate
                break

    if pam_cord_in_s2 is None or not pam_cord_in_s2.exists():
        pam_cord_in_s2 = qc_root / "pam50_cord_in_s2.nii.gz"
        ok, _ = _run_command(
            [
                "sct_apply_transfo",
                "-i", str(pam50_cord),
                "-d", str(subject_image),
                "-w", str(warp_template2anat),
                "-o", str(pam_cord_in_s2),
                "-x", "nn",
            ]
        )
        if not ok or not pam_cord_in_s2.exists():
            return None
    try:
        pam_cord_img = nib.as_closest_canonical(nib.load(pam_cord_in_s2))
    except Exception:
        return None
    pam_cord = pam_cord_img.get_fdata()
    if pam_cord.ndim > 3:
        pam_cord = pam_cord[..., 0]
    if pam_cord.shape != subj.shape:
        return None
    pam_mask = pam_cord > 0

    # SI mismatch diagnostics (non-blocking)
    diagnostics_dir = qc_root / "si_diagnostics"
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    try:
        subj_centerline_csv = _extract_centerline_csv(subject_cordmask, diagnostics_dir / "subj_centerline")
        pam_centerline_csv = _extract_centerline_csv(pam_cord_in_s2, diagnostics_dir / "pam_centerline")
        if subj_centerline_csv and pam_centerline_csv:
            si_diagnostics = _compute_si_mismatch_from_centerlines(subj_centerline_csv, pam_centerline_csv)
            diagnostics_json = diagnostics_dir / "si_mismatch_diagnostics.json"
            try:
                _write_json(diagnostics_json, si_diagnostics)
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        pass

    affine = subj_img.affine
    z_mm = np.array([float((affine @ np.array([0.0, 0.0, float(k), 1.0]))[2]) for k in range(subj.shape[2])])

    z_slices = np.where(subj_mask.any(axis=(0, 1)))[0]
    if z_slices.size == 0:
        return None
    z_min_k = int(z_slices.min())
    z_max_k = int(z_slices.max())

    if vertebral_labels_path is not None and vertebral_labels_path.exists():
        try:
            vert_img = nib.as_closest_canonical(nib.load(vertebral_labels_path))
            vert_data = vert_img.get_fdata()
            if vert_data.ndim > 3:
                vert_data = vert_data[..., 0]
            if vert_data.shape == subj.shape:
                vert_int = np.round(vert_data).astype(int)
                c1_mask = vert_int == 1
                if c1_mask.any():
                    c1_z_indices = np.where(c1_mask.any(axis=(0, 1)))[0]
                    z_c1_top = int(c1_z_indices.min()) if c1_z_indices.size > 0 else z_min_k
                else:
                    z_c1_top = z_min_k
                non_zero = vert_int > 0
                if non_zero.any():
                    all_labeled_slices = np.where(non_zero.any(axis=(0, 1)))[0]
                    z_last_vertebral_bottom = int(all_labeled_slices.max()) if all_labeled_slices.size > 0 else z_max_k
                else:
                    z_last_vertebral_bottom = z_max_k
                pad = 10
                z_min_k = max(0, z_c1_top - pad)
                z_max_k = min(subj.shape[2] - 1, z_last_vertebral_bottom + pad)
        except Exception:
            pass

    z_min_mm = float(z_mm[z_min_k])
    z_max_mm = float(z_mm[z_max_k])
    if z_max_mm < z_min_mm:
        z_min_mm, z_max_mm = z_max_mm, z_min_mm

    n_tiles = int(mosaic_cols * mosaic_rows)
    targets_mm = np.linspace(z_min_mm, z_max_mm, num=n_tiles)
    z_indices_all = [int(np.argmin(np.abs(z_mm - t))) for t in targets_mm]

    z_indices = []
    for k in z_indices_all:
        if subj_mask[:, :, k].any() and pam_mask[:, :, k].any():
            z_indices.append(k)

    canvas_w, canvas_h = canvas_size
    left_w = int(canvas_w * 0.2)
    right_w = canvas_w - left_w
    tile_w = right_w // mosaic_cols
    tile_h = canvas_h // mosaic_rows

    coords = np.argwhere(subj_mask)
    x_index = int(np.median(coords[:, 0]))
    x_index = max(0, min(x_index, subj.shape[0] - 1))

    proj_yz = subj_mask.any(axis=0)
    proj_disp = np.flipud(proj_yz.T)
    disp_coords = np.argwhere(proj_disp)
    if disp_coords.size == 0:
        return None
    z0_cord, _ = disp_coords.min(axis=0)
    z1_cord, _ = disp_coords.max(axis=0)
    pad = 5
    z0_cord = max(0, int(z0_cord) - pad)
    z1_cord = min(proj_disp.shape[0] - 1, int(z1_cord) + pad)
    _, y0_cord = disp_coords.min(axis=0)
    _, y1_cord = disp_coords.max(axis=0)
    y_range = y1_cord - y0_cord
    y_pad_extra = int(y_range * 0.3)
    y0_cord = max(0, int(y0_cord) - pad - y_pad_extra)
    y1_cord = min(proj_disp.shape[1] - 1, int(y1_cord) + pad + y_pad_extra)

    def _render_underlay_canvas(underlay_3d: np.ndarray) -> Optional[Image.Image]:
        sag_slice = underlay_3d[x_index, :, :]
        sag_disp = np.flipud(sag_slice.T)
        sag_disp = sag_disp[z0_cord : z1_cord + 1, y0_cord : y1_cord + 1]
        sag_rgb = _scale_to_rgb(sag_disp)
        sag_fit = _fit_resize_and_paste_rgb(sag_rgb, left_w, canvas_h)
        sag_panel = Image.fromarray(sag_fit, mode="RGB")

        mosaic = Image.new("RGB", (right_w, canvas_h), (0, 0, 0))  # type: ignore[arg-type]
        for idx, k in enumerate(z_indices):
            if not (subj_mask[:, :, k].any() and pam_mask[:, :, k].any()):
                continue
            r = idx // mosaic_cols
            c = idx % mosaic_cols
            x0 = c * tile_w
            y0t = r * tile_h
            slice2d = underlay_3d[:, :, k]
            mask_slice = subj_mask[:, :, k]
            coords_ax = np.argwhere(mask_slice)
            if coords_ax.size > 0:
                x_min, y_min = coords_ax.min(axis=0)
                x_max, y_max = coords_ax.max(axis=0)
                bbox_w = x_max - x_min
                bbox_h = y_max - y_min
                ax_pad = max(10, int(max(bbox_w, bbox_h) * 0.25))
                x_min = max(0, int(x_min) - ax_pad)
                y_min = max(0, int(y_min) - ax_pad)
                x_max = min(slice2d.shape[0] - 1, int(x_max) + ax_pad)
                y_max = min(slice2d.shape[1] - 1, int(y_max) + ax_pad)
                slice_cropped = slice2d[x_min : x_max + 1, y_min : y_max + 1]
            else:
                slice_cropped = slice2d
            slice_rotated = np.rot90(slice_cropped, k=-1)
            rgb = _scale_to_rgb(slice_rotated)
            rgb_fit = _fit_resize_and_paste_rgb(rgb, tile_w, tile_h)
            tile_img = Image.fromarray(rgb_fit, mode="RGB")
            mosaic.paste(tile_img, (x0, y0t))

        canvas = Image.new("RGB", (canvas_w, canvas_h), (0, 0, 0))  # type: ignore[arg-type]
        canvas.paste(sag_panel, (0, 0))
        canvas.paste(mosaic, (left_w, 0))
        return canvas

    subj_base = _render_underlay_canvas(subj)
    pam_base = _render_underlay_canvas(pam)
    if subj_base is None or pam_base is None:
        return None

    overlay = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))  # type: ignore[arg-type]
    draw = ImageDraw.Draw(overlay)

    subj_sag = np.flipud(subj_mask[x_index, :, :].T)
    pam_sag = np.flipud(pam_mask[x_index, :, :].T)
    subj_sag = subj_sag[z0_cord : z1_cord + 1, y0_cord : y1_cord + 1]
    pam_sag = pam_sag[z0_cord : z1_cord + 1, y0_cord : y1_cord + 1]
    subj_sag_r = _fit_resize_and_paste_mask(subj_sag, left_w, canvas_h)
    pam_sag_r = _fit_resize_and_paste_mask(pam_sag, left_w, canvas_h)
    subj_edge = _mask_contour_2d(subj_sag_r)
    pam_edge = _mask_contour_2d(pam_sag_r)
    _draw_thick_contour(overlay, subj_edge, (255, 0, 0, 255), thickness=2, outline_color=(0, 0, 0, 255))
    _draw_thick_contour(overlay, pam_edge, (0, 100, 200, 255), thickness=2, outline_color=(0, 0, 0, 255))

    for idx, k in enumerate(z_indices):
        if not (subj_mask[:, :, k].any() and pam_mask[:, :, k].any()):
            continue
        r = idx // mosaic_cols
        c = idx % mosaic_cols
        x0 = left_w + c * tile_w
        y0t = r * tile_h
        subj_m_slice = subj_mask[:, :, k]
        pam_m_slice = pam_mask[:, :, k]
        coords_ax = np.argwhere(subj_m_slice)
        if coords_ax.size > 0:
            x_min, y_min = coords_ax.min(axis=0)
            x_max, y_max = coords_ax.max(axis=0)
            bbox_w = x_max - x_min
            bbox_h = y_max - y_min
            ax_pad = max(10, int(max(bbox_w, bbox_h) * 0.25))
            x_min = max(0, int(x_min) - ax_pad)
            y_min = max(0, int(y_min) - ax_pad)
            x_max = min(subj_m_slice.shape[0] - 1, int(x_max) + ax_pad)
            y_max = min(subj_m_slice.shape[1] - 1, int(y_max) + ax_pad)
            subj_m_cropped = subj_m_slice[x_min : x_max + 1, y_min : y_max + 1]
            pam_m_cropped = pam_m_slice[x_min : x_max + 1, y_min : y_max + 1]
        else:
            subj_m_cropped = subj_m_slice
            pam_m_cropped = pam_m_slice
        subj_m_rotated = np.rot90(subj_m_cropped, k=-1)
        pam_m_rotated = np.rot90(pam_m_cropped, k=-1)
        subj_m = _fit_resize_and_paste_mask(subj_m_rotated, tile_w, tile_h)
        pam_m = _fit_resize_and_paste_mask(pam_m_rotated, tile_w, tile_h)
        subj_edge_t = _mask_contour_2d(subj_m)
        pam_edge_t = _mask_contour_2d(pam_m)
        _draw_thick_contour(overlay, subj_edge_t, (255, 0, 0, 255), x_offset=x0, y_offset=y0t, thickness=2, outline_color=(0, 0, 0, 255))
        _draw_thick_contour(overlay, pam_edge_t, (0, 100, 200, 255), x_offset=x0, y_offset=y0t, thickness=2, outline_color=(0, 0, 0, 255))
        z_label = float(z_mm[k])
        draw.text((x0 + 5, y0t + 5), f"z={z_label:.0f}mm", fill=(230, 230, 230, 255))

    draw.text((10, 10), "S2 PAM50 registration QC", fill=(255, 255, 255, 255))
    legend_y = 40
    draw.text((10, legend_y), "subject cord", fill=(255, 0, 0, 255))
    draw.text((10, legend_y + 18), "PAM50 cord (warped to S2)", fill=(0, 100, 200, 255))
    meta = f"sub={subject_label or 'unknown'} ses={session_label or 'none'}  z=[{z_min_mm:.0f},{z_max_mm:.0f}]mm"
    draw.text((10, canvas_h - 20), meta, fill=(180, 180, 180, 255))

    steps = max(1, int(crossfade_steps))
    alphas_fwd = np.linspace(0.0, 1.0, num=steps + 1)
    alphas_bwd = np.linspace(1.0, 0.0, num=steps + 1)[1:]
    alphas = [float(a) for a in np.concatenate([alphas_fwd, alphas_bwd])]

    frames_dir = qc_root / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    frame_paths: list[Path] = []
    for i, a in enumerate(alphas):
        base = Image.blend(subj_base, pam_base, a).convert("RGBA")
        composed = Image.alpha_composite(base, overlay)
        p = frames_dir / f"frame_{i:03d}.png"
        composed.convert("RGB").save(p)
        frame_paths.append(p)

    if not frame_paths:
        return None

    total_ms = int(max(1, frame_delay_ms) * 2)
    delay_cs = max(1, int(round((total_ms / max(1, len(frame_paths))) / 10.0)))
    gif_path = qc_root / "S2_pam50_reg_overlay.gif"
    ok, _ = _run_command(
        ["convert", "-delay", str(delay_cs), "-loop", "0", *[str(p) for p in frame_paths], str(gif_path)]
    )
    return gif_path if ok else None
