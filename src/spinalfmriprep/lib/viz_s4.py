
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
):
    """Render axial moco-comparison reportlet.

    For every cord-bearing axial slice (capped at `max_slices`), build a row:
    [mean BOLD before moco | mean BOLD after moco]. Stack the rows vertically
    into a single PNG. Per the Feb 13 design decision, motion is much easier
    to read off axial cross-sections side-by-side than off a sagittal animation.

    - Temporal mean is the canonical motion QC image: motion blurs the
      pre-moco mean, the post-moco mean sharpens.
    - Intensity normalization is shared across before/after so observed
      contrast differences reflect the data, not the display.
    - Optional thin blue cord-mask contour, matching the S2 cordmask
      reportlet convention.
    """
    img_before = nib.load(bold_before_path)
    img_after = nib.load(bold_after_path)
    data_before = img_before.get_fdata()
    data_after = img_after.get_fdata()

    # Temporal means - check each volume independently. Callers may pass a
    # 4D timeseries for one side and a pre-computed 3D mean for the other.
    mean_before = data_before.mean(axis=3) if data_before.ndim == 4 else data_before
    mean_after = data_after.mean(axis=3) if data_after.ndim == 4 else data_after

    # Mask resolution
    final_mask = None
    if mask_data is not None and mask_data.shape == mean_before.shape:
        final_mask = mask_data > 0
    elif mask_path and Path(mask_path).exists():
        m = nib.load(mask_path).get_fdata()
        if m.shape == mean_before.shape:
            final_mask = m > 0
    if final_mask is None:
        # Fallback: whole-volume bbox so we still render something useful
        final_mask = np.ones_like(mean_before, dtype=bool)

    zooms = img_before.header.get_zooms()[:3]
    dx_mm, dy_mm, _dz_mm = float(zooms[0]), float(zooms[1]), float(zooms[2])

    # Select cord-bearing Z slices (slices where the mask has any voxels)
    z_has_cord = np.where(final_mask.any(axis=(0, 1)))[0]
    if z_has_cord.size == 0:
        # No cord found - still render a minimal placeholder so the dashboard
        # has a file at the expected path and the user sees the failure mode.
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

    # Shared robust intensity range across both columns + all selected slices
    vals_b = mean_before[final_mask]
    vals_a = mean_after[final_mask]
    pool = np.concatenate([vals_b, vals_a])
    pool = pool[pool > 1e-5]
    if pool.size > 0:
        vmin, vmax = np.percentile(pool, list(percentile))
    else:
        vmin, vmax = 0.0, 1.0
    if vmax <= vmin:
        vmax = vmin + 1e-5

    # Crop bbox in plane (across all slices, fixed per run so rows align)
    if final_mask.any():
        plane_mask = final_mask.any(axis=2)
        coords = np.argwhere(plane_mask)
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

    # Tile size: scale to a stable display dimension (240 px wide tile)
    crop_w = c1 - c0
    crop_h = r1 - r0
    tile_w = 240
    # Preserve in-plane aspect (voxel sizes already equal-ish for axial)
    asp = (crop_h * dx_mm) / (crop_w * dy_mm) if crop_w > 0 else 1.0
    tile_h = max(32, int(round(tile_w * asp)))

    header_h = 28
    label_w = 56
    gutter = 4
    panel_w = label_w + 2 * tile_w + gutter
    panel_h = header_h + len(selected_z) * tile_h

    canvas = Image.new("RGB", (panel_w, panel_h), (10, 10, 10))
    draw = ImageDraw.Draw(canvas)

    # Column headers
    font = _load_compact_font()
    draw.text((label_w + tile_w // 2 - 36, 6), "Before moco", fill=(220, 220, 220), font=font)
    draw.text((label_w + tile_w + gutter + tile_w // 2 - 30, 6), "After moco", fill=(220, 220, 220), font=font)

    def _to_uint8(arr2d: np.ndarray) -> np.ndarray:
        norm = np.clip((arr2d - vmin) / (vmax - vmin), 0.0, 1.0)
        return (norm * 255).astype(np.uint8)

    def _tile_image(slab2d: np.ndarray) -> Image.Image:
        # Match the medical-anatomical convention used elsewhere: rot90 so
        # the displayed columns/rows feel like the radiologist view.
        rotated = np.rot90(slab2d)
        u8 = _to_uint8(rotated)
        im = Image.fromarray(u8).convert("RGB")
        return im.resize((tile_w, tile_h), resample=Image.Resampling.NEAREST)

    for row_idx, z in enumerate(selected_z):
        y0 = header_h + row_idx * tile_h
        # Slice label on the left
        draw.text((6, y0 + tile_h // 2 - 8), f"z={int(z)}", fill=(180, 180, 180), font=font)

        crop_before = mean_before[r0:r1, c0:c1, z]
        crop_after = mean_after[r0:r1, c0:c1, z]
        tile_before = _tile_image(crop_before)
        tile_after = _tile_image(crop_after)
        canvas.paste(tile_before, (label_w, y0))
        canvas.paste(tile_after, (label_w + tile_w + gutter, y0))

        if show_mask_contour and final_mask[r0:r1, c0:c1, z].any():
            contour_b = _make_contour_overlay(
                final_mask[r0:r1, c0:c1, z], tile_w, tile_h
            )
            contour_a = contour_b  # same mask both columns
            canvas.paste(contour_b, (label_w, y0), contour_b)
            canvas.paste(contour_a, (label_w + tile_w + gutter, y0), contour_a)

    canvas.save(output_path)


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

