
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
