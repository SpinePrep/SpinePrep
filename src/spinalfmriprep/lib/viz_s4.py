
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import nibabel as nib
from pathlib import Path
from PIL import Image, ImageDraw
import imageio.v3 as imageio
from typing import Optional, List, Tuple

def render_motion_traces(
    params_df, 
    fd_threshold: float,
    output_path: Path,
    figsize: Tuple[float, float] = (10, 4),
    dpi: int = 100,
    colors: dict = None
):
    """
    Render motion traces plot (S4_motion_traces.png).
    """
    if colors is None:
        colors = {'tx': '#1f77b4', 'ty': '#ff7f0e', 'tz': '#2ca02c', 'threshold': 'red'}
        
    frames = np.arange(len(params_df))
    tx = params_df['tx'] if 'tx' in params_df else np.zeros(len(params_df))
    ty = params_df['ty'] if 'ty' in params_df else np.zeros(len(params_df))
    
    fig, ax = plt.subplots(figsize=figsize)
    ax.plot(frames, tx, color=colors['tx'], label='TX', linewidth=1)
    ax.plot(frames, ty, color=colors['ty'], label='TY', linewidth=1)
    
    # FD Threshold lines
    ax.axhline(y=fd_threshold, color=colors['threshold'], linestyle='--', alpha=0.7, label='FD threshold')
    ax.axhline(y=-fd_threshold, color=colors['threshold'], linestyle='--', alpha=0.7)
    
    ax.set_xlabel('Frame')
    ax.set_ylabel('Displacement (mm)')
    ax.legend(loc='upper right')
    ax.grid(alpha=0.3)
    ax.set_title('Motion Parameters (XY Translation)')
    
    fig.savefig(output_path, dpi=dpi, bbox_inches='tight')
    plt.close(fig)

def create_axial_montage(
    data_3d: np.ndarray, 
    mask_3d: np.ndarray, 
    zooms: Tuple[float, float, float],
    n_slices: int = 9,
    tile_size: int = 128
) -> np.ndarray:
    """
    Create a 2D montage of axial slices with adaptive zoom (Match S3.3).
    - Per-slice centering on cord mask.
    - FOV = 2.0 * cord diameters.
    - Resized to fixed tile_size.
    """
    # 1. Find Z-extent of mask
    z_indices = np.where(mask_3d.any(axis=(0, 1)))[0]
    if len(z_indices) < n_slices:
        if len(data_3d.shape) > 2:
             # Fallback
             selected_z = np.linspace(0, data_3d.shape[2]-1, n_slices, dtype=int)
        else:
             return np.zeros((3*tile_size, 3*tile_size))
    else:
        # Uniformly distributed slices within mask
        # Match S3: np.linspace(min, max, 11)[1:-1] -> 9 inner slices if n_slices=9? 
        # S3 does: slices = np.linspace(z_min, z_max, 11)[1:-1] for 9 slices.
        # Let's match typical linspace behavior for robustness
        selected_z = np.linspace(z_indices.min(), z_indices.max(), n_slices, dtype=int)
    
    # Grid dims
    grid_cols = int(np.ceil(np.sqrt(n_slices)))
    grid_rows = int(np.ceil(n_slices / grid_cols))
    
    montage_rows = []
    
    current_z_idx = 0
    for r in range(grid_rows):
        row_strips = []
        for c in range(grid_cols):
            if current_z_idx < len(selected_z):
                z = selected_z[current_z_idx]
                current_z_idx += 1
                
                # S3 Logic: Per-slice centering
                mask_sl = mask_3d[:, :, z]
                coords = np.argwhere(mask_sl > 0)
                
                # Defaults if mask empty on this slice
                center_x, center_y = data_3d.shape[0]//2, data_3d.shape[1]//2
                diameter_mm = 10.0
                
                if coords.size > 0:
                    # Median is robust
                    center_x, center_y = np.median(coords, axis=0).astype(int)
                    
                    # Diameter
                    x_min, x_max = coords[:,0].min(), coords[:,0].max()
                    y_min, y_max = coords[:,1].min(), coords[:,1].max()
                    dx_mm = (x_max - x_min + 1) * zooms[0]
                    dy_mm = (y_max - y_min + 1) * zooms[1]
                    diameter_mm = max(dx_mm, dy_mm)
                    diameter_mm = max(diameter_mm, 5.0) # Floor
                
                target_fov_mm = 2.0 * diameter_mm
                
                # Crop extent in pixels
                # x is dim0 (dx), y is dim1 (dy)
                half_fov_x = (target_fov_mm / 2.0) / zooms[0]
                half_fov_y = (target_fov_mm / 2.0) / zooms[1]
                
                x_start = int(max(0, center_x - half_fov_x))
                x_end = int(min(data_3d.shape[0], center_x + half_fov_x))
                y_start = int(max(0, center_y - half_fov_y))
                y_end = int(min(data_3d.shape[1], center_y + half_fov_y))
                
                crop = data_3d[x_start:x_end, y_start:y_end, z]
                
                # Resize to tile_size using PIL
                # Rotate 90 to match medical anatomical view (Anterior up, Left right)
                # Raw: X=L-R, Y=P-A. 
                # Display: we usually want Y vertical.
                # rot90 does (y, x).
                crop_rot = np.rot90(crop)
                
                # Normalize for display to 0-255 range just for resizing? 
                # No, we want to preserve values for imshow colormap!
                # But resizing float array with PIL requires mode 'F' or conversion.
                # PIL resizing of float might interpret as 0-1 or raw?
                # Safer: Use scipy.ndimage.zoom, OR use matplotlib to plot?
                # S3 constructs a PIL image grid.
                # Here we return a numpy montage for imshow.
                # Converting to fixed pixel size implies resampling.
                # interpolation implies values might change slightly.
                # Let's use skimage.transform.resize if avaialble, or just scipy zoom.
                # Or simplistic: use PIL.Image.fromarray(..., mode='F')
                
                im_pil = Image.fromarray(crop_rot)
                im_resized = im_pil.resize((tile_size, tile_size), resample=Image.Resampling.BILINEAR)
                final_tile = np.array(im_resized)
                
                row_strips.append(final_tile)
            else:
                row_strips.append(np.zeros((tile_size, tile_size)))
        
        montage_rows.append(np.concatenate(row_strips, axis=1))
        
    if not montage_rows:
        return np.zeros((100, 100))
        
    montage = np.concatenate(montage_rows, axis=0)
    return montage

def render_tsnr_comparison(
    tsnr_before: np.ndarray,
    tsnr_after: np.ndarray,
    mask: np.ndarray,
    zooms: Tuple[float, float, float],
    output_path: Path,
    figsize: Tuple[float, float] = (12, 6),
    dpi: int = 100,
    n_slices: int = 9,
    colormap: str = 'viridis',
    vmax_percentile: float = 99.0
):
    """Render tSNR comparison montage."""
    
    # Compute robust max
    if mask.sum() > 0:
        vals = np.concatenate([tsnr_before[mask], tsnr_after[mask]])
        vmax = np.percentile(vals, vmax_percentile)
    else:
        vmax = np.percentile(np.concatenate([tsnr_before, tsnr_after]), 99) if tsnr_before.size > 0 else 1.0
        
    fig, axes = plt.subplots(1, 2, figsize=figsize)
    
    titles = ['Before MoCo', 'After MoCo']
    datasets = [tsnr_before, tsnr_after]
    
    for ax, data, title in zip(axes, datasets, titles):
        # Use new adaptive montage
        # Note: We use the SAME mask for both to ensure identical cropping
        montage = create_axial_montage(data, mask, zooms, n_slices=n_slices)
        
        im = ax.imshow(montage, cmap=colormap, vmin=0, vmax=vmax)
        ax.set_title(title, fontsize=14, color='white')
        ax.axis('off')
        
    # Shared Colorbar
    cbar = fig.colorbar(im, ax=axes, shrink=0.8, label='tSNR')
    cbar.ax.yaxis.set_tick_params(color='white', labelcolor='white')
    cbar.ax.yaxis.label.set_color('white')
    
    fig.savefig(output_path, dpi=dpi, bbox_inches='tight', facecolor='black') 
    plt.close(fig)

def render_dvars_plot(
    dvars_timeseries: np.ndarray,
    threshold: float,
    output_path: Path,
    figsize: Tuple[float, float] = (10, 4),
    dpi: int = 100,
    colors: dict = None
):
    """Render DVARS time series plot."""
    if colors is None:
        colors = dict(line='#1f77b4', threshold='red')
        
    fig, ax = plt.subplots(figsize=figsize)
    frames = np.arange(len(dvars_timeseries))
    
    ax.plot(frames, dvars_timeseries, color=colors['line'], label='DVARS', linewidth=1)
    ax.axhline(y=threshold, color=colors['threshold'], linestyle='--', alpha=0.7, label='Threshold')
    
    # Outliers
    outlier_idx = np.where(dvars_timeseries > threshold)[0]
    if len(outlier_idx) > 0:
        ax.scatter(outlier_idx, dvars_timeseries[outlier_idx], color='red', s=20, zorder=5, label='Outliers')
        
    ax.set_xlabel('Frame')
    ax.set_ylabel('DVARS (a.u.)')
    ax.legend(loc='upper right')
    ax.grid(alpha=0.3)
    ax.set_title('DVARS Time Series')
    
    fig.savefig(output_path, dpi=dpi, bbox_inches='tight')
    plt.close(fig)

def extract_sagittal(data_3d, x_idx):
    """Extract sagittal slice at given X index."""
    if x_idx < 0 or x_idx >= data_3d.shape[0]:
        return np.zeros((data_3d.shape[1], data_3d.shape[2]))
    slice_data = data_3d[int(x_idx), :, :]
    # Rotate for display (SI vertical, AP horizontal)
    return np.rot90(slice_data)

def render_moco_axial_comparison(
    bold_before_path: Path,
    bold_after_path: Path,
    output_path: Path,
    mask_path: Optional[Path] = None,
    mask_data: Optional[np.ndarray] = None,
    max_slices: int = 12,
    show_mask_contour: bool = True,
    margin_mm: float = 5.0,
    percentile: Tuple[float, float] = (2.0, 98.0),
    animate: bool = True,
    max_frames: int = 16,
    fps: int = 4,
):
    """Render axial moco-comparison reportlet.

    Per the Feb 13 design decision, motion correction quality is most legible
    on axial cross-sections shown side-by-side. Layout is constant across all
    frames: every cord-bearing axial slice (capped at `max_slices`) gets a
    row [BOLD before moco | BOLD after moco], stacked vertically.

    When `animate=True` (default), output is an animated GIF cycling through
    `max_frames` uniformly-sampled timepoints from the 4D BOLD - the eye sees
    cord wobble on the left column and stable cord on the right. If either
    input is already a 3D mean, that column stays static across frames.

    When `animate=False`, the temporal means are stacked into a single PNG;
    blur (before) vs sharpness (after) tells the same story without motion.

    Intensity normalisation is shared across columns AND across all frames
    so observed differences reflect the data, not display range drift. An
    optional thin blue cord-mask contour marks the cord on every tile.
    """
    img_before = nib.load(bold_before_path)
    img_after = nib.load(bold_after_path)
    data_before = img_before.get_fdata()
    data_after = img_after.get_fdata()

    is_4d_before = data_before.ndim == 4
    is_4d_after = data_after.ndim == 4
    mean_before = data_before.mean(axis=3) if is_4d_before else data_before
    mean_after = data_after.mean(axis=3) if is_4d_after else data_after

    final_mask = None
    if mask_data is not None and mask_data.shape == mean_before.shape:
        final_mask = mask_data > 0
    elif mask_path and Path(mask_path).exists():
        m = nib.load(mask_path).get_fdata()
        if m.shape == mean_before.shape:
            final_mask = m > 0
    if final_mask is None:
        final_mask = np.ones_like(mean_before, dtype=bool)

    zooms = img_before.header.get_zooms()[:3]
    dx_mm, dy_mm, _dz_mm = float(zooms[0]), float(zooms[1]), float(zooms[2])

    z_has_cord = np.where(final_mask.any(axis=(0, 1)))[0]
    if z_has_cord.size == 0:
        placeholder = Image.new("RGB", (400, 80), (40, 40, 40))
        d = ImageDraw.Draw(placeholder)
        d.text((10, 30), "no cord-bearing slices in mask", fill=(220, 220, 220))
        placeholder.save(output_path)
        return

    if z_has_cord.size > max_slices:
        idx = np.linspace(0, z_has_cord.size - 1, max_slices).round().astype(int)
        selected_z = z_has_cord[idx]
    else:
        selected_z = z_has_cord

    # Shared robust intensity range. Pool BOTH the temporal means AND a
    # subsample of raw volumes so the gif's per-frame brightness stays
    # consistent with the static means.
    pool_arrays = [mean_before[final_mask], mean_after[final_mask]]
    if animate and (is_4d_before or is_4d_after):
        nt = max(
            data_before.shape[3] if is_4d_before else 0,
            data_after.shape[3] if is_4d_after else 0,
        )
        sample_t = np.linspace(0, nt - 1, min(nt, max_frames), dtype=int)
        for t in sample_t[:: max(1, len(sample_t) // 4)]:  # 4 sample times for percentile
            if is_4d_before:
                pool_arrays.append(data_before[..., t][final_mask])
            if is_4d_after:
                pool_arrays.append(data_after[..., t][final_mask])
    pool = np.concatenate(pool_arrays)
    pool = pool[pool > 1e-5]
    vmin, vmax = (np.percentile(pool, list(percentile)) if pool.size > 0 else (0.0, 1.0))
    if vmax <= vmin:
        vmax = vmin + 1e-5

    plane_mask = final_mask.any(axis=2)
    coords = np.argwhere(plane_mask)
    if coords.size:
        r_min, c_min = coords.min(axis=0)
        r_max, c_max = coords.max(axis=0)
    else:
        r_min, c_min = 0, 0
        r_max, c_max = mean_before.shape[0] - 1, mean_before.shape[1] - 1
    pad_r = int(np.ceil(margin_mm / dx_mm))
    pad_c = int(np.ceil(margin_mm / dy_mm))
    r0 = max(0, r_min - pad_r)
    r1 = min(mean_before.shape[0], r_max + pad_r + 1)
    c0 = max(0, c_min - pad_c)
    c1 = min(mean_before.shape[1], c_max + pad_c + 1)

    crop_w = c1 - c0
    crop_h = r1 - r0
    tile_w = 200 if animate else 240  # slightly smaller tiles to keep GIF size sane
    asp = (crop_h * dx_mm) / (crop_w * dy_mm) if crop_w > 0 else 1.0
    tile_h = max(32, int(round(tile_w * asp)))

    header_h = 28
    label_w = 56
    gutter = 4
    panel_w = label_w + 2 * tile_w + gutter
    panel_h = header_h + len(selected_z) * tile_h

    font = _load_compact_font()

    # Pre-compute the mask contour per slice once (same overlay every frame)
    contour_overlays = {}
    if show_mask_contour:
        for z in selected_z:
            sl_mask = final_mask[r0:r1, c0:c1, int(z)]
            if sl_mask.any():
                contour_overlays[int(z)] = _make_contour_overlay(sl_mask, tile_w, tile_h)

    def _tile_image(slab2d: np.ndarray) -> Image.Image:
        rotated = np.rot90(slab2d)
        norm = np.clip((rotated - vmin) / (vmax - vmin), 0.0, 1.0)
        u8 = (norm * 255).astype(np.uint8)
        return Image.fromarray(u8).convert("RGB").resize(
            (tile_w, tile_h), resample=Image.Resampling.NEAREST
        )

    def _build_frame(vol_before: np.ndarray, vol_after: np.ndarray,
                     frame_label: Optional[str] = None) -> Image.Image:
        canvas = Image.new("RGB", (panel_w, panel_h), (10, 10, 10))
        draw = ImageDraw.Draw(canvas)
        draw.text((label_w + tile_w // 2 - 36, 6), "Before moco",
                  fill=(220, 220, 220), font=font)
        draw.text((label_w + tile_w + gutter + tile_w // 2 - 30, 6),
                  "After moco", fill=(220, 220, 220), font=font)
        if frame_label:
            draw.text((panel_w - 80, 6), frame_label, fill=(180, 180, 180), font=font)
        for row_idx, z in enumerate(selected_z):
            y0 = header_h + row_idx * tile_h
            draw.text((6, y0 + tile_h // 2 - 8), f"z={int(z)}",
                      fill=(180, 180, 180), font=font)
            tile_before = _tile_image(vol_before[r0:r1, c0:c1, int(z)])
            tile_after = _tile_image(vol_after[r0:r1, c0:c1, int(z)])
            canvas.paste(tile_before, (label_w, y0))
            canvas.paste(tile_after, (label_w + tile_w + gutter, y0))
            ov = contour_overlays.get(int(z))
            if ov is not None:
                canvas.paste(ov, (label_w, y0), ov)
                canvas.paste(ov, (label_w + tile_w + gutter, y0), ov)
        return canvas

    if not animate or not (is_4d_before or is_4d_after):
        # Static mean-vs-mean PNG fallback
        _build_frame(mean_before, mean_after).save(output_path)
        return

    # Animated GIF: sample timepoints uniformly across the longer 4D BOLD.
    nt = max(
        data_before.shape[3] if is_4d_before else 0,
        data_after.shape[3] if is_4d_after else 0,
    )
    sample_t = np.linspace(0, nt - 1, min(nt, max_frames), dtype=int)
    frames = []
    for t in sample_t:
        vb = data_before[..., t] if is_4d_before else mean_before
        va = data_after[..., t] if is_4d_after else mean_after
        frames.append(np.array(_build_frame(vb, va, frame_label=f"vol {int(t)}")))

    # Write as animated GIF. Use `duration` (ms) to dodge the imageio `fps`
    # deprecation warning we saw on the old renderer.
    duration_ms = max(50, int(round(1000.0 / max(1, fps))))
    imageio.imwrite(output_path, frames, duration=duration_ms, loop=0)


def _load_compact_font():
    """Small TTF if available, else PIL bitmap fallback."""
    try:
        from PIL import ImageFont
        for candidate in (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ):
            try:
                return ImageFont.truetype(candidate, 13)
            except Exception:
                continue
        return ImageFont.load_default()
    except Exception:
        return None


def _make_contour_overlay(mask_2d: np.ndarray, tile_w: int, tile_h: int) -> Image.Image:
    """Return an RGBA tile with a thin blue cord-mask contour, sized to tile."""
    # Rotate to match the tile orientation
    m = np.rot90(mask_2d).astype(bool)
    # Edge = mask XOR its 1-px erosion (no scipy dependency: shift each axis)
    pad = np.zeros((m.shape[0] + 2, m.shape[1] + 2), dtype=bool)
    pad[1:-1, 1:-1] = m
    eroded = pad[0:-2, 1:-1] & pad[2:, 1:-1] & pad[1:-1, 0:-2] & pad[1:-1, 2:] & m
    edge = m & ~eroded
    rgba = np.zeros((*edge.shape, 4), dtype=np.uint8)
    rgba[..., 0] = 0
    rgba[..., 1] = 130
    rgba[..., 2] = 230
    rgba[..., 3] = edge.astype(np.uint8) * 220
    overlay = Image.fromarray(rgba, mode="RGBA")
    return overlay.resize((tile_w, tile_h), resample=Image.Resampling.NEAREST)


def render_moco_gif(
    bold_before_path: Path,
    bold_after_path: Path,
    output_path: Path,
    mask_path: Optional[Path] = None,
    mask_data: Optional[np.ndarray] = None, # Allow passing numpy mask directly
    fps: int = 5,
    max_frames: int = 20
):
    """DEPRECATED sagittal GIF moco comparison.

    Kept as a thin shim only because external callers may import it. New
    code should call render_moco_axial_comparison(). The current pipeline
    no longer calls this function (Feb 13 design: switched to axial PNG).
    """
    
    # Load data
    img_before = nib.load(bold_before_path)
    data_before = img_before.get_fdata()
    img_after = nib.load(bold_after_path)
    data_after = img_after.get_fdata() 
    
    nt = data_before.shape[3]
    
    # Handle Mask for Centroid
    # Priority: mask_data > mask_path > derive from data
    final_mask = None
    
    if mask_data is not None:
        if mask_data.shape == data_before.shape[:3]:
            final_mask = mask_data
    
    if final_mask is None and mask_path and mask_path.exists():
        loaded_mask = nib.load(mask_path).get_fdata()
        # Verify shape
        if loaded_mask.shape == data_before.shape[:3]:
            final_mask = loaded_mask
        # If shape mismatch (e.g. uncropped mask vs cropped data), ignore file mask
    
    # Calculate Mid-Sagittal index
    if final_mask is not None and final_mask.sum() > 0:
        coords = np.argwhere(final_mask > 0)
        x_start, x_end = coords[:,0].min(), coords[:,0].max()
        x_mid = (x_start + x_end) // 2
    else:
        # Robust fallback: Center of Mass of temporal mean
        from scipy.ndimage import center_of_mass
        mean_vol = np.mean(data_before, axis=3)
        # Threshold to ignore background noise
        thr = np.percentile(mean_vol, 50)
        if thr > 0:
            com = center_of_mass(mean_vol > thr)
            x_mid = int(com[0])
        else:
            x_mid = data_before.shape[0] // 2
            
    # Frame selection
    frames_to_use = np.linspace(0, nt-1, min(nt, max_frames), dtype=int)
    
    # Global Normalization params (Robust 2%-98%)
    all_slices = []
    for t in frames_to_use:
        s1 = extract_sagittal(data_before[..., t], x_mid)
        s2 = extract_sagittal(data_after[..., t], x_mid)
        all_slices.append(s1)
        all_slices.append(s2)
        
    flat = np.concatenate([s.ravel() for s in all_slices])
    # Ignore pure zeros for percentile calc if possible
    valid_flat = flat[flat > 1e-5]
    if valid_flat.size > 0:
        vmin, vmax = np.percentile(valid_flat, [2, 98])
    else:
        vmin, vmax = 0, 1
        
    if vmax <= vmin: vmax = vmin + 1e-5
    
    # Generate frames
    gif_frames = []
    
    # Aspect ratio check
    zooms = img_before.header.get_zooms()
    dy, dz = zooms[1], zooms[2]
    aspect = dz / dy if dy > 0 else 1.0
    
    for t in frames_to_use:
        sl_before = extract_sagittal(data_before[..., t], x_mid)
        sl_after = extract_sagittal(data_after[..., t], x_mid)
        
        # Normalize
        norm_before = np.clip((sl_before - vmin) / (vmax - vmin), 0, 1)
        norm_after = np.clip((sl_after - vmin) / (vmax - vmin), 0, 1)
        
        uint8_before = (norm_before * 255).astype(np.uint8)
        uint8_after = (norm_after * 255).astype(np.uint8)
        
        # Create side-by-side
        im_b = Image.fromarray(uint8_before)
        im_a = Image.fromarray(uint8_after)
        
        # Resize
        target_w = 256
        w, h = im_b.size
        if w > 0:
            target_h = int(h * aspect * (target_w / w))
        else:
            target_h = 256 # Fallback
            
        if target_h < 1: target_h = 1
        
        im_b = im_b.resize((target_w, target_h), resample=Image.Resampling.NEAREST)
        im_a = im_a.resize((target_w, target_h), resample=Image.Resampling.NEAREST)
        
        combined = Image.new('RGB', (target_w * 2, target_h))
        combined.paste(im_b, (0, 0))
        combined.paste(im_a, (target_w, 0))
        
        # Add Text
        draw = ImageDraw.Draw(combined)
        draw.text((5, 5), "Before", fill=(255, 255, 255))
        draw.text((target_w + 5, 5), "After", fill=(255, 255, 255))
        draw.text((5, target_h - 15), f"Vol {t}", fill=(200, 200, 200))
        
        gif_frames.append(np.array(combined))
        
    imageio.imwrite(output_path, gif_frames, fps=fps, loop=0)

