
import numpy as np
import pandas as pd
import nibabel as nib
from scipy.ndimage import shift
from skimage.registration import phase_cross_correlation
from pathlib import Path
from typing import Tuple, List, Optional, Union
from spineprep.lib.timing import timed_subprocess_run

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

    # Locate the FLIRT schedule file. In a source checkout it sits at
    # <repo>/config/; in the installed container it is COPYed to the working dir
    # (WORKDIR /app) alongside policy/ and schemas/ — the same CWD-relative
    # convention the policy loader uses. Try both so dev and container both work.
    _sched_name = "flirt_XY_only.sch"
    _candidates = [
        Path(__file__).resolve().parents[3] / "config" / _sched_name,  # source checkout
        Path.cwd() / "config" / _sched_name,                           # installed (container WORKDIR)
    ]
    schedule_path = next((p for p in _candidates if p.exists()), None)
    if schedule_path is None:
        raise FileNotFoundError(
            f"FLIRT schedule file '{_sched_name}' not found in any of: "
            f"{[str(c) for c in _candidates]}"
        )

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
        res = timed_subprocess_run(cmd, capture_output=True, text=True)
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


def compute_framewise_displacement(
    params_df: pd.DataFrame,
    radius_mm: float = 50.0,
) -> np.ndarray:
    """
    Compute cord framewise displacement (FD) from motion parameters.

    For cord fMRI, FD is the sum of the absolute derivatives of the IN-PLANE
    translations only. Ricchi, Kinany & Van De Ville (2024, Imaging Neuroscience,
    doi:10.1162/imag_a_00286; PMC12290568) state it verbatim: "framewise
    displacement (FD) was computed by summing the absolute values of the
    derivatives of the motion parameters in x and y". Note they use mean FD for
    SUBJECT-level exclusion ("average FD > 0.4 mm"), NOT for frame censoring --
    no cord paper found publishes a frame-censoring FD threshold.
    This is a deliberate cord adaptation of Power et al. (2012, NeuroImage
    59(3):2142-2154, doi:10.1016/j.neuroimage.2011.10.018), whose brain FD sums
    6 rigid parameters (3 translations + 3 rotations as arc length on a 50 mm
    sphere): `sct_fmri_moco` estimates only in-plane slice-wise translations, and
    rotation is ill-defined on a cord-cropped small FOV, so tz and the rotations
    are not part of cord FD.

    CITATION HAZARDS (both were live in this docstring; fixed 2026-07-16):
    - Do NOT attribute this x/y FD form to Kaptan et al. 2023 (NeuroImage,
      doi:10.1016/j.neuroimage.2023.120152). That paper never uses FD at all; it
      censors on dVARS/refRMS at 2 SD and uses the slice-wise translations as
      REGRESSORS. CLAUDE.md's old "FD threshold (Kaptan 2023)" invariant carried
      the same error.
    - PMC12290568 is Ricchi/Kinany/Van De Ville (EPFL), NOT an Eippert-lab paper.
      An earlier fix of the first hazard introduced this second one.

    THRESHOLD WARNING: this function returns FD; it does not choose a threshold.
    The 0.5 mm default elsewhere is Power's BRAIN value and does not transfer
    here -- this FD sums TWO in-plane translation terms, Power's sums SIX
    (3 translations + 3 rotations as arc length). Per Jones et al. 2022, "different
    calculations of FD provide different values ... any absolute threshold would
    necessarily be metric specific". Power chose 0.5 as "well above the norm found
    in still subjects"; on this cord cohort 0.5 mm IS the norm (median), so the
    number inverts Power's own criterion. See .claude/specs/s4-fd-threshold.md.

    Power's published difference is BACKWARD (Delta d_i = d_(i-1) - d_i); pandas
    .diff() gives d_i - d_(i-1). The absolute value makes the two identical, so
    the sign order below is not a defect.

    The rotation branch below is retained only so a caller that passes a full
    6-column frame still gets a defined result; for the shipped cord engine the
    frame carries tx/ty only and the rotation columns are absent, so
    `radius_mm` has no effect.

    Args:
        params_df: DataFrame with motion columns; the cord engine supplies tx, ty.
        radius_mm: Sphere radius (mm) for converting any rotation columns to
                   arc length (unused for the tx/ty-only cord frame).

    Returns:
        fd: Array of FD values (mm). First value is 0.
    """
    trans_cols = [c for c in ['tx', 'ty', 'tz'] if c in params_df.columns]
    rot_cols = [c for c in ['rx', 'ry', 'rz'] if c in params_df.columns]

    diffs = params_df[trans_cols + rot_cols].diff().fillna(0)

    # Any rotation columns (absent for the cord engine) are converted from
    # radians to arc-length displacement on a radius_mm sphere, per Power 2012.
    for rc in rot_cols:
        diffs[rc] = diffs[rc] * radius_mm

    fd = diffs.abs().sum(axis=1).values

    return fd


def compose_cord_fd(
    stage1_tx: np.ndarray,
    stage1_ty: np.ndarray,
    slicewise_x: Optional[np.ndarray],
    slicewise_y: Optional[np.ndarray],
    voxsize_x: float,
    voxsize_y: float,
    axcodes: Optional[tuple] = None,
) -> tuple[np.ndarray, dict]:
    """Compose the two motion-correction stages into a per-volume cord FD (mm).

    Replaces the earlier reduction, which had two defects (audit 2026-07-16):

    1. MIXED UNITS. Stage 1 estimates with FSL FLIRT on a projection written with
       an identity affine (`coarse_bulk_xy_correction`), so FLIRT's world-mm are
       the fake 1 mm grid -- i.e. its `tx/ty` are in VOXELS of the real image.
       Verified by synthetic test: a 2-voxel shift on a 1.5 mm grid returns 2.000,
       not 3.0. Stage 2's `moco_params_x/y` are ANTs warp components in MM
       (verified in SCT's `moco.py`, which splits the warp into X/Y and saves the
       components). The old code summed the two and thresholded the result in mm,
       so Stage-1 motion was under-counted by the in-plane voxel size on every
       dataset that is not 1.0 mm (here: 1.5 mm CoSpine x2, 1.6 mm ds005075).
       FD was therefore NOT comparable across datasets. Stage 1 is now scaled to
       mm before composing.

    2. CANCELLATION. The old code took `mean(axis=(0,1,2))` of the SIGNED
       slice-wise field, so opposing rostral/caudal slice shifts cancelled -- the
       exact motion the slice-wise stage exists to measure. SCT's own convention
       takes the per-slice MAGNITUDE first (`mean(sqrt(X^2+Y^2))`), which cannot
       cancel. Here the composition is done PER SLICE and the absolute temporal
       difference is taken per slice, then averaged over slices, so cancellation
       is impossible while the per-axis Power form is preserved.

    SIGNS. On the cohort's uniform LAS geometry both stages report the same sign
    convention per axis (verified by synthetic test at the real orientation), so
    they compose by addition. This is orientation-dependent: Stage 1 is fixed by
    its identity-affine temporaries, while Stage 2 follows the image affine, so
    under RAS the X components would carry opposite signs and adding them would
    subtract. `axcodes` is checked and a non-LAS input is reported, since the
    composition has only been verified for LAS.

    FD[0] = 0, per Power et al. (2014): "FD for the first volume of a run is 0 by
    convention."

    Args:
        stage1_tx, stage1_ty: (n_vol,) bulk estimates in VOXELS.
        slicewise_x, slicewise_y: (1,1,n_slices,n_vol) ANTs warp components in mm,
            or None when the slice-wise stage did not run.
        voxsize_x, voxsize_y: in-plane voxel sizes in mm.
        axcodes: nibabel orientation codes of the BOLD, for the LAS check.

    Returns:
        (fd, info) -- fd is (n_vol,) in mm; info carries provenance for qc.json.
    """
    info: dict = {
        "fd_units": "mm",
        "stage1_scaled_to_mm_by": [float(voxsize_x), float(voxsize_y)],
        "slicewise_included": slicewise_x is not None,
        "reduction": "per-slice |dt| then mean over slices (no cancellation)",
    }
    if axcodes is not None:
        ax = "".join(axcodes)
        info["axcodes"] = ax
        if ax != "LAS":
            info["orientation_warning"] = (
                f"stage composition verified for LAS only; got {ax}. Stage-2 sign "
                f"follows the affine, so a non-LAS input may compose incorrectly."
            )

    # Stage 1 -> mm, broadcast across slices (it applied one shift to every slice).
    tx_mm = np.asarray(stage1_tx, dtype=float) * float(voxsize_x)
    ty_mm = np.asarray(stage1_ty, dtype=float) * float(voxsize_y)

    if slicewise_x is None or slicewise_y is None:
        total_x = tx_mm[None, :]
        total_y = ty_mm[None, :]
    else:
        sx = np.asarray(slicewise_x, dtype=float)
        sy = np.asarray(slicewise_y, dtype=float)
        # (1,1,nz,nt) -> (nz,nt)
        sx = sx.reshape(-1, sx.shape[-1])
        sy = sy.reshape(-1, sy.shape[-1])
        total_x = tx_mm[None, :] + sx
        total_y = ty_mm[None, :] + sy
        info["n_slices"] = int(sx.shape[0])

    # Per-slice absolute temporal difference; FD[0] = 0 (Power 2014 convention).
    dx = np.abs(np.diff(total_x, axis=1, prepend=total_x[:, :1]))
    dy = np.abs(np.diff(total_y, axis=1, prepend=total_y[:, :1]))
    fd_per_slice = dx + dy                 # Power's per-axis |delta| sum
    fd = fd_per_slice.mean(axis=0)         # magnitudes -> cannot cancel
    return fd, info


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

