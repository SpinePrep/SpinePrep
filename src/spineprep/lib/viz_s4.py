
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
    fd,
    dvars,
    fd_threshold: float,
    dvars_threshold: float,
    output_path: Path,
    figsize: Tuple[float, float] = (11, 8),
    dpi: int = 100,
    colors: dict = None
):
    """Stacked S4 trace panel sharing one volume (time) axis.

    Row 1: total in-plane translation X/Y (mm) — the corrected total motion
    (Stage-1 bulk + Stage-2 slicewise mean), both already in mm.
    Row 2: FD (framewise displacement, mm) with the scrubbing threshold drawn
    HERE only (FD is a frame-to-frame change, so a horizontal line is meaningful
    on this panel and meaningless on the position traces) + dots on flagged
    volumes.
    Row 3: DVARS (frame-to-frame intensity change) with its single-sourced
    threshold + dots. Catches signal disruption FD's rigid model cannot see.
    """
    if colors is None:
        colors = {'tx': '#1f77b4', 'ty': '#ff7f0e', 'fd': '#222222',
                  'dvars': '#6a3d9a', 'threshold': 'red'}
    fd = np.asarray(fd, dtype=float)
    dvars = np.asarray(dvars, dtype=float)
    n = len(params_df)
    frames = np.arange(n)
    tx = params_df['tx'].to_numpy() if 'tx' in params_df else np.zeros(n)
    ty = params_df['ty'].to_numpy() if 'ty' in params_df else np.zeros(n)

    fig, axes = plt.subplots(3, 1, figsize=figsize, sharex=True,
                             gridspec_kw={'height_ratios': [1.3, 1, 1], 'hspace': 0.12})

    axes[0].plot(frames, tx, color=colors['tx'], lw=1, label='X (R–L)')
    axes[0].plot(frames, ty, color=colors['ty'], lw=1, label='Y (A–P)')
    axes[0].set_ylabel('Translation\n(mm)')
    axes[0].legend(loc='upper right', fontsize=8, ncol=2)
    axes[0].set_title('Total in-plane motion (Stage-1 bulk + Stage-2 slicewise mean)')

    axes[1].plot(frames, fd, color=colors['fd'], lw=1, label='FD')
    axes[1].axhline(fd_threshold, color=colors['threshold'], ls='--', alpha=0.7,
                    label=f'thr {fd_threshold:g} mm')
    fo = np.where(fd > fd_threshold)[0]
    if fo.size:
        axes[1].scatter(fo, fd[fo], color='red', s=14, zorder=5, label=f'{fo.size} flagged')
    axes[1].set_ylabel('FD\n(mm)')
    axes[1].legend(loc='upper right', fontsize=8, ncol=3)

    axes[2].plot(frames, dvars, color=colors['dvars'], lw=1, label='DVARS')
    axes[2].axhline(dvars_threshold, color=colors['threshold'], ls='--', alpha=0.7,
                    label=f'thr {dvars_threshold:g}')
    do = np.where(dvars > dvars_threshold)[0]
    if do.size:
        axes[2].scatter(do, dvars[do], color='red', s=14, zorder=5, label=f'{do.size} flagged')
    axes[2].set_ylabel('DVARS\n(a.u.)')
    axes[2].set_xlabel('Volume (time)')
    axes[2].legend(loc='upper right', fontsize=8, ncol=3)

    for ax in axes:
        ax.grid(alpha=0.3)
    fig.savefig(output_path, dpi=dpi, bbox_inches='tight')
    plt.close(fig)


def render_slicewise_heatmap(
    moco_x: np.ndarray,
    moco_y: np.ndarray,
    output_path: Path,
    cord_z_extent: Optional[Tuple[int, int]] = None,
    figsize: Tuple[float, float] = (11, 6),
    dpi: int = 100,
):
    """Slice (Z) × volume (time) heatmap of the Stage-2 slicewise correction.

    The cord analogue of fMRIPrep's carpet plot, and the ONLY figure that shows
    the slice dimension — i.e. what the cord-specific Stage-2 actually did. Two
    signed panels (X = R–L, Y = A–P where cord pulsation lives), in mm (the
    SCT/ANTs warp components are already physical mm). A diverging map centred at
    0 shows direction, so opposite-direction slice motion — which cancels in the
    per-volume mean and is therefore invisible to FD — shows up here.
    Good run = uniform pale. Bad run = a bright horizontal band (one slice
    jitters) or a vertical stripe (a whole-volume burst). Volume 0 = all-zero
    reference (black first column).
    """
    X = np.squeeze(np.asarray(moco_x))
    Y = np.squeeze(np.asarray(moco_y))
    if X.ndim != 2:  # be defensive about singleton axes
        X = X.reshape(-1, X.shape[-1]); Y = Y.reshape(-1, Y.shape[-1])
    both = np.concatenate([np.abs(X).ravel(), np.abs(Y).ravel()])
    vmax = float(np.percentile(both, 99)) if both.size else 1.0
    if vmax <= 0:
        vmax = 1.0

    fig, axes = plt.subplots(2, 1, figsize=figsize, sharex=True,
                             gridspec_kw={'hspace': 0.20})
    im = None
    for ax, data, lab in zip(axes, [X, Y], ['X shift (R–L)', 'Y shift (A–P)']):
        im = ax.imshow(data, aspect='auto', origin='lower', cmap='RdBu_r',
                       vmin=-vmax, vmax=vmax, interpolation='nearest')
        ax.set_ylabel(f'Slice (Z)\n{lab}')
        if cord_z_extent is not None:
            ax.axhline(cord_z_extent[0] - 0.5, color='k', lw=0.7, ls=':')
            ax.axhline(cord_z_extent[1] + 0.5, color='k', lw=0.7, ls=':')
    axes[-1].set_xlabel('Volume (time)')
    axes[0].set_title('Stage-2 slicewise correction (signed, mm) — which slices moved, and when')
    fig.colorbar(im, ax=axes, shrink=0.85, label='shift (mm)')
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
    improvement_pct: Optional[float] = None,
    figsize: Tuple[float, float] = (12, 8),
    dpi: int = 100,
    n_slices: int = 6,
    colormap: str = 'viridis',
    vmax_percentile: float = 99.0
):
    """tSNR before/after — the step-local truth metric (did moco make each
    voxel's signal steadier). Top row: two cord-centred axial montages (same
    mask -> identical crops). Bottom: per-slice cord-tSNR vs Z for before and
    after — a slice where 'after' dips BELOW 'before' is a slice Stage-2 harmed,
    which the whole-cord average hides. Improvement % shown in the title.
    """
    if mask.sum() > 0:
        vals = np.concatenate([tsnr_before[mask], tsnr_after[mask]])
        vmax = np.percentile(vals, vmax_percentile)
    else:
        vmax = np.percentile(np.concatenate([tsnr_before, tsnr_after]), 99) if tsnr_before.size > 0 else 1.0

    fig = plt.figure(figsize=figsize, facecolor='black')
    gs = fig.add_gridspec(2, 2, height_ratios=[2.2, 1.0], hspace=0.18, wspace=0.04)
    ax_b = fig.add_subplot(gs[0, 0]); ax_a = fig.add_subplot(gs[0, 1])
    im = None
    for ax, data, title in [(ax_b, tsnr_before, 'Before MoCo'), (ax_a, tsnr_after, 'After MoCo')]:
        montage = create_axial_montage(data, mask, zooms, n_slices=n_slices)
        im = ax.imshow(montage, cmap=colormap, vmin=0, vmax=vmax)
        ax.set_title(title, fontsize=13, color='white'); ax.axis('off')
    cbar = fig.colorbar(im, ax=[ax_b, ax_a], shrink=0.85, label='tSNR')
    cbar.ax.yaxis.set_tick_params(color='white', labelcolor='white')
    cbar.ax.yaxis.label.set_color('white')

    # Per-slice cord-tSNR profile (after dipping below before = harmed slice)
    ax_p = fig.add_subplot(gs[1, :]); ax_p.set_facecolor('black')
    z_idx = np.where(mask.any(axis=(0, 1)))[0]
    if z_idx.size:
        prof_b = [float(tsnr_before[:, :, z][mask[:, :, z]].mean()) if mask[:, :, z].any() else np.nan for z in z_idx]
        prof_a = [float(tsnr_after[:, :, z][mask[:, :, z]].mean()) if mask[:, :, z].any() else np.nan for z in z_idx]
        ax_p.plot(z_idx, prof_b, color='#999999', marker='o', ms=3, lw=1, label='before')
        ax_p.plot(z_idx, prof_a, color='#0086e6', marker='o', ms=3, lw=1, label='after')
        ax_p.set_xlabel('Slice (Z, caudal→rostral by index)', color='white')
        ax_p.set_ylabel('cord tSNR', color='white')
        ax_p.legend(loc='best', fontsize=8, facecolor='black', labelcolor='white', framealpha=0.3)
        ax_p.tick_params(colors='white'); ax_p.grid(alpha=0.2)
        ax_p.set_title('Per-slice cord tSNR — after below before = slice harmed', color='white', fontsize=10)

    sup = 'tSNR before vs after MoCo'
    if improvement_pct is not None:
        sup += f'    Δ {improvement_pct:+.1f}%'
    fig.suptitle(sup, color='white', fontsize=13)
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
