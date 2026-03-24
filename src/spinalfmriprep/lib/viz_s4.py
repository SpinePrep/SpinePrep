
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

def render_moco_gif(
    bold_before_path: Path,
    bold_after_path: Path,
    output_path: Path,
    mask_path: Optional[Path] = None,
    mask_data: Optional[np.ndarray] = None, # Allow passing numpy mask directly
    fps: int = 5,
    max_frames: int = 20
):
    """Generate Before/After GIF comparison."""
    
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

