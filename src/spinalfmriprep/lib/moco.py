
import numpy as np
import pandas as pd
import nibabel as nib
from scipy.ndimage import shift
from skimage.registration import phase_cross_correlation
from pathlib import Path
from typing import Tuple, List, Optional, Union

def coarse_bulk_xy_correction(
    bold_4d: np.ndarray,
    ref_3d: np.ndarray,
    work_dir: Path,
    upsample_factor: int = 10,
    interpolation_order: int = 1
) -> Tuple[np.ndarray, pd.DataFrame]:
    """
    Perform coarse bulk 2D (XY) motion correction on a 4D BOLD series.
    
    Corrects for bulk translation in X and Y by aligning the Z-projection (mean)
    of each volume to the Z-projection of the reference volume using FSL FLIRT.
    Applies the estimated 2D shift to every slice in the volume identically.
    Does NOT perform any interpolation or resampling along the Z-axis.

    Args:
        bold_4d: 4D numpy array (x, y, z, t) containing BOLD timeseries.
        ref_3d: 3D numpy array (x, y, z) containing reference volume.
        work_dir: Directory to store temporary NIfTI files for FSL.
        upsample_factor: Ignored for FLIRT, kept for signature backwards compatibility.
        interpolation_order: Order of spline interpolation for shift (0-5, default 1=linear).

    Returns:
        corrected_4d: Motion-corrected 4D numpy array.
        params_df: DataFrame containing 'tx', 'ty' motion parameters per volume.
    """
    import os
    import subprocess
    import shutil
    import concurrent.futures
    import logging

    logger = logging.getLogger(__name__)

    if bold_4d.ndim != 4:
        raise ValueError(f"Input bold_4d must be 4D, got {bold_4d.ndim}D")
    if ref_3d.ndim != 3:
        raise ValueError(f"Input ref_3d must be 3D, got {ref_3d.ndim}D")

    nx, ny, nz, nt = bold_4d.shape
    
    # Needs a 2D NIfTI encoding (nx, ny, 1) for flirt
    # Create the reference 2D projection
    ref_proj = np.mean(ref_3d, axis=2)[..., np.newaxis]
    ref_nii = nib.Nifti1Image(ref_proj, np.eye(4))
    
    flirt_dir = work_dir / "flirt_stage1"
    flirt_dir.mkdir(parents=True, exist_ok=True)
    
    ref_path = flirt_dir / "ref_2d.nii.gz"
    nib.save(ref_nii, ref_path)

    # We need the schedule file location. It should be tracked in the repo config.
    # We find it relative to this file's position `src/spinalfmriprep/lib/moco.py` -> `../../../config/...`
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    schedule_path = repo_root / "config" / "flirt_XY_only.sch"
    
    if not schedule_path.exists():
        raise FileNotFoundError(f"FLIRT schedule file not found at {schedule_path}")

    def register_volume(t: int) -> dict:
        vol = bold_4d[..., t]
        vol_proj = np.mean(vol, axis=2)[..., np.newaxis]
        
        mov_path = flirt_dir / f"mov_2d_t{t:04d}.nii.gz"
        nib.save(nib.Nifti1Image(vol_proj, np.eye(4)), mov_path)
        
        out_mat = flirt_dir / f"flirt_t{t:04d}.mat"
        
        cmd = [
            "flirt",
            "-in", str(mov_path),
            "-ref", str(ref_path),
            "-omat", str(out_mat),
            "-2D", # optimize in 2D
            "-schedule", str(schedule_path)
        ]
        
        # Run FLIRT
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            logger.error(f"FLIRT failed at volume {t}:\n{res.stderr}")
            return {'volume': t, 'tx_coarse': 0.0, 'ty_coarse': 0.0}
            
        # Parse affine matrix for translations
        # The translation mm values are at row 0, col 3 (tx) and row 1, col 3 (ty)
        # FLIRT matches moving -> reference, so (x', y', z', 1)^T = M * (x, y, z, 1)^T
        try:
            mat = np.loadtxt(str(out_mat))
            tx = mat[0, 3]
            ty = mat[1, 3]
        except Exception as e:
            logger.error(f"Failed to parse FLIRT mat file at volume {t}: {e}")
            tx, ty = 0.0, 0.0
            
        # Clean up files for this timepoint to save space
        mov_path.unlink(missing_ok=True)
        out_mat.unlink(missing_ok=True)
        
        return {'volume': t, 'tx_coarse': tx, 'ty_coarse': ty}

    # Parallelize FLIRT calls
    motion_records = []
    # Use max_workers=8 to not overwhelm disk IO creating thousands of niftis simultaneously
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(register_volume, t): t for t in range(nt)}
        for future in concurrent.futures.as_completed(futures):
            motion_records.append(future.result())
            
    # Sort motion records to ensure chronological order regardless of thread completion order
    motion_records = sorted(motion_records, key=lambda x: x['volume'])
    
    # 3. Apply the shift to each slice
    corrected_4d = np.zeros_like(bold_4d)
    
    for record in motion_records:
        t = record['volume']
        tx = record['tx_coarse']
        ty = record['ty_coarse']
        vol = bold_4d[..., t]
        
        for z in range(nz):
            # Apply shift to 2D slice. The FLIRT temp images above are written
            # with np.eye(4) (positive determinant → FSL treats them as
            # neurological and internally flips the first axis), so the reported
            # tx has the SAME sign as the axis-0 displacement and ty the OPPOSITE
            # sign on axis-1. To pull the moving slice back onto the reference we
            # therefore shift by [-tx, +ty] (negate x only). Verified empirically:
            # a known (+dx,+dy) displacement is recovered to ~0 MSE only by
            # [-tx,+ty]; [+tx,+ty] (old) and [-tx,-ty] both increase MSE above the
            # uncorrected baseline. (BUG-1c)
            corrected_4d[:, :, z, t] = shift(
                vol[:, :, z],
                shift=[-tx, ty],
                order=interpolation_order,
                mode='constant',
                cval=0.0
            )

    # Clean up the whole flirt directory
    shutil.rmtree(flirt_dir, ignore_errors=True)

    return corrected_4d, pd.DataFrame(motion_records)


def mcflirt_bulk_correction(bold_path, ref_path, out_path, work_dir=None):
    """Stage-1 bulk motion correction via FSL MCFLIRT — 3D 6-DOF rigid-body
    realignment of each volume to ``ref_path``.

    Matches the CoSpi cord-fMRI recipe (spi06_2_motioncorrection.sh):
    `mcflirt -cost leastsquares -spline_final`, registering to a fixed
    reference. Unlike the old 2-DOF FLIRT-on-Z-mean, this captures all six
    rigid parameters (3 translations + 3 rotations), which also become the
    standard motion nuisance regressors.

    Returns ``(corrected_path, params_df)`` where params_df has columns
    ``volume, tx_coarse, ty_coarse, tz_coarse, rx_coarse, ry_coarse,
    rz_coarse``. FSL MCFLIRT writes its .par as rotations (rad) x/y/z then
    translations (mm) x/y/z.
    """
    import subprocess
    import logging
    logger = logging.getLogger(__name__)

    out_base = str(out_path)
    for ext in (".nii.gz", ".nii"):
        if out_base.endswith(ext):
            out_base = out_base[: -len(ext)]
            break

    cmd = [
        "mcflirt",
        "-in", str(bold_path),
        "-reffile", str(ref_path),
        "-cost", "leastsquares",
        "-spline_final",
        "-plots",
        "-o", out_base,
    ]
    logger.info(f"Executing: {' '.join(cmd)}")
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"mcflirt failed: {res.stderr or res.stdout}")

    # Locate the .par (mcflirt writes <out_base>.par, sometimes <out_base>.nii.gz.par)
    par_path = Path(out_base + ".par")
    if not par_path.exists():
        alt = Path(out_base + ".nii.gz.par")
        par_path = alt if alt.exists() else par_path
    par = np.loadtxt(str(par_path))
    if par.ndim == 1:
        par = par.reshape(1, -1)

    df = pd.DataFrame({
        "volume": np.arange(par.shape[0]),
        "rx_coarse": par[:, 0], "ry_coarse": par[:, 1], "rz_coarse": par[:, 2],
        "tx_coarse": par[:, 3], "ty_coarse": par[:, 4], "tz_coarse": par[:, 5],
    })

    # Ensure the corrected 4D ends up at out_path (mcflirt writes out_base.nii.gz)
    written = Path(out_base + ".nii.gz")
    if str(written) != str(out_path) and written.exists():
        shutil.move(str(written), str(out_path))

    return Path(out_path), df


def compute_framewise_displacement(
    params_df: pd.DataFrame, 
    radius_mm: float = 50.0 # Standard, essentially ignored for pure Translation
) -> np.ndarray:
    """
    Compute Framewise Displacement (FD) from motion parameters.
    Based on Power et al. (2012) definition: sum of absolute derivatives.
    
    Args:
        params_df: DataFrame with motion columns (tx, ty, tz, rx, ry, rz).
                   Columns can be subset (e.g., just tx, ty).
        radius_mm: Head radius to convert rotation radians to mm (standard 50mm).
    
    Returns:
        fd: Array of FD values (mm). First value is 0.
    """
    # Identify present columns
    trans_cols = [c for c in ['tx', 'ty', 'tz'] if c in params_df.columns]
    rot_cols = [c for c in ['rx', 'ry', 'rz'] if c in params_df.columns]
    
    # Calculate differences (derivatives)
    diffs = params_df[trans_cols + rot_cols].diff().fillna(0)
    
    # Convert rotations to mm (if any)
    # Assume rotations are in degrees? Or radians?
    # SCT usually outputs radians? Need to verify input source.
    # Our coarse step outputs translation only (mm/pixels).
    # Let's assume input units match.
    # If rotations present, convert to arc length displacement
    for rc in rot_cols:
        # Assuming radians for now (standard in tools)
        diffs[rc] = diffs[rc] * radius_mm 
        
    # Sum of absolute differences
    fd = diffs.abs().sum(axis=1).values
    
    return fd


def compute_dvars(
    bold_4d: np.ndarray, 
    mask_3d: Optional[np.ndarray] = None
) -> np.ndarray:
    """
    Compute DVARS (RMS of frame-to-frame intensity difference).
    
    Args:
        bold_4d: 4D BOLD array (x, y, z, t).
        mask_3d: Optional boolean mask. If None, uses whole volume.
    
    Returns:
        dvars: Array of DVARS values. First value is 0.
    """
    # 1. Compute frame-to-frame difference
    diff_4d = np.diff(bold_4d, axis=3) # shape (x, y, z, t-1)
    
    # 2. Apply mask
    if mask_3d is not None:
        # Flatten spatial dims within mask
        # mask_3d > 0 ensures boolean
        diff_data = diff_4d[mask_3d > 0, :] # shape (n_voxels, t-1)
    else:
        diff_data = diff_4d.reshape(-1, diff_4d.shape[3])
        
    # 3. RMS over spatial dimension
    # DVARS[t] = sqrt( mean( (I_t - I_{t-1})^2 ) )
    dvars_t = np.sqrt(np.mean(diff_data**2, axis=0))
    
    # Pad first value with 0 to match length
    return np.concatenate(([0], dvars_t))


def compute_tsnr(
    bold_4d: np.ndarray, 
    mask_3d: Optional[np.ndarray] = None
) -> Tuple[np.ndarray, float]:
    """
    Compute tSNR map and mean tSNR within mask.
    tSNR = mean(time) / std(time)
    
    Returns:
        tsnr_map: 3D array of tSNR values.
        mean_tsnr: Scalar mean tSNR inside mask.
    """
    mean_img = np.mean(bold_4d, axis=3)
    std_img = np.std(bold_4d, axis=3)
    
    # Avoid division by zero
    with np.errstate(divide='ignore', invalid='ignore'):
        tsnr_map = mean_img / std_img
        tsnr_map[std_img == 0] = 0
        
    mean_val = 0.0
    if mask_3d is not None:
        vals = tsnr_map[mask_3d > 0]
        # Filter NaNs just in case
        vals = vals[np.isfinite(vals)]
        if vals.size > 0:
            mean_val = float(np.mean(vals))
    else:
        mean_val = float(np.mean(tsnr_map))
        
    return tsnr_map, mean_val


def detect_z_shift(
    run_ref: np.ndarray, 
    target_ref: np.ndarray,
    search_range_mm: float = 10.0,
    slice_thickness_mm: float = 5.0  
) -> float:
    """
    Estimate Z-shift between two 3D volumes using cross-correlation of Z-profiles.
    
    Args:
        run_ref: 3D reference volume of current run.
        target_ref: 3D target volume (e.g. from run 1).
        search_range_mm: Max shift to search in mm.
        slice_thickness_mm: Slice thickness in mm.
        
    Returns:
        shift_mm: Estimated Z-shift in mm.
    """
    # Compute "Z-profile": mean intensity per slice
    # Sum over X and Y
    profile_run = np.mean(run_ref, axis=(0, 1))
    profile_target = np.mean(target_ref, axis=(0, 1))
    
    # Cross-correlation
    # "correlation" mode 'full'
    # Use scipy.signal.correlate? Or easier: simple search over integer slices?
    # Given typical EPI thickness (3-5mm), integer slice shift is usually enough for "Large Shift" detection.
    
    # Let's do simple search or phase correlation?
    # Phase correlation on 1D profiles is robust.
    
    shift_vector = phase_cross_correlation(
        profile_target[:, np.newaxis], 
        profile_run[:, np.newaxis],
        upsample_factor=10
    )[0]
    
    # shift_vector[0] is in pixels (slices)
    z_shift_slices = shift_vector[0]
    z_shift_mm = z_shift_slices * slice_thickness_mm
    
    return float(z_shift_mm), int(round(z_shift_slices))

def apply_z_shift_correction(
    bold_4d: np.ndarray,
    shift_slices: int
) -> np.ndarray:
    """
    Apply integer Z-shift correction to 4D BOLD data.
    Shifts the volume along Z-axis by `shift_slices`.
    Pads with zeros.
    
    Args:
        bold_4d: 4D numpy array (x, y, z, t).
        shift_slices: Integer number of slices to shift. 
                      Positive -> shift UP (towards higher Z index)? 
                      Depends on coordinate system.
                      If shift is +1, data at z=0 moves to z=1.
                      New z=0 is 0.
    
    Returns:
        Corrected 4D array.
    """
    if shift_slices == 0:
        return bold_4d.copy()
        
    corrected = np.zeros_like(bold_4d)
    nz = bold_4d.shape[2]
    
    # src_start, src_end -> dest_start, dest_end
    # If shift +k:
    # dest[k:] = src[:-k]
    # dest[0:k] = 0
    # If shift -k:
    # dest[:-k] = src[k:]
    # dest[-k:] = 0
    
    if shift_slices > 0:
        # Shift to higher Z indices
        if shift_slices < nz:
            corrected[:, :, shift_slices:, :] = bold_4d[:, :, :-shift_slices, :]
    else:
        # Shift to lower Z indices (shift is negative)
        abs_shift = abs(shift_slices)
        if abs_shift < nz:
            corrected[:, :, :-abs_shift, :] = bold_4d[:, :, abs_shift:, :]
            
    return corrected

