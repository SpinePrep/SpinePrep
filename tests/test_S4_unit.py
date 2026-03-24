
import pytest
import numpy as np
import pandas as pd
from spinalfmriprep.lib import moco

def generate_synthetic_data(shape=(20, 20, 10, 5), offset=(0, 0)):
    """Generate 4D data with a moving 'cord'"""
    # Create coordinate grid
    xx, yy = np.meshgrid(np.arange(shape[0]), np.arange(shape[1]), indexing='ij')
    
    # Cord: Gaussian blob centered at (10, 10)
    data = np.zeros(shape)
    
    for t in range(shape[3]):
        # Apply offset to even volumes
        if t % 2 == 1:
            dx, dy = offset
        else:
            dx, dy = 0, 0
            
        # Center with offset
        cx, cy = 10 + dx, 10 + dy
        blob = np.exp(-((xx - cx)**2 + (yy - cy)**2) / (2 * 2.0**2))
        
        # Replicate along Z
        for z in range(shape[2]):
            data[:, :, z, t] = blob
            
    return data

def test_coarse_bulk_xy_correction_no_motion():
    # No motion -> tx, ty near 0
    ref = np.zeros((20, 20, 5))
    ref[8:12, 8:12, :] = 1.0 # Simple block
    bold = np.repeat(ref[..., np.newaxis], 4, axis=3) # 4 identical volumes
    
    corrected, params = moco.coarse_bulk_xy_correction(bold, ref, upsample_factor=100)
    
    assert params.shape == (4, 3) # volume, tx, ty
    assert np.allclose(params['tx_coarse'], 0, atol=0.05)
    assert np.allclose(params['ty_coarse'], 0, atol=0.05)
    assert np.allclose(corrected, bold)

def test_coarse_bulk_xy_correction_with_motion():
    # Volume 1 shifted by +1 pixel in X
    data = np.zeros((20, 20, 5, 2))
    
    # Ref (frame 0) centered at 10, 10
    xx, yy = np.meshgrid(np.arange(20), np.arange(20), indexing='ij')
    blob = np.exp(-((xx - 10)**2 + (yy - 10)**2) / 2)
    data[..., 0] = np.repeat(blob[..., np.newaxis], 5, axis=2)
    
    # Moving (frame 1) shifted by +1 X (center at 11, 10)
    blob_moved = np.exp(-((xx - 11)**2 + (yy - 10)**2) / 2)
    data[..., 1] = np.repeat(blob_moved[..., np.newaxis], 5, axis=2)
    
    ref = data[..., 0].copy()
    
    # Correction should detect shift needed to align Moving TO Ref
    # Moving (11) needs shift -1 to match Ref (10).
    # phase_cross_correlation returns "shift vector (dy, dx) required to register moving_image to reference_image."
    # If moving is at 11, ref at 10. Shift needed is -1?
    # Let's verify what moco.py does. It applies the returned shift.
    
    corrected, params = moco.coarse_bulk_xy_correction(data, ref, upsample_factor=100)
    
    # Check Frame 1 params
    tx = params.loc[1, 'tx_coarse']
    ty = params.loc[1, 'ty_coarse']
    
    # Expect tx approx -1.0
    print(f"Detected shift: tx={tx}, ty={ty}")
    assert np.isclose(tx, -1.0, atol=0.1)
    assert np.isclose(ty, 0.0, atol=0.1)
    
    # Check corrected data similarity to ref
    # Corrected frame 1 should match frame 0 better than original frame 1
    mse_orig = np.mean((data[..., 1] - ref)**2)
    mse_corr = np.mean((corrected[..., 1] - ref)**2)
    
    assert mse_corr < mse_orig
    print(f"MSE Reduced: {mse_orig} -> {mse_corr}")

def test_apply_z_shift_correction():
    # 4D data: (x, y, z, t) = (1, 1, 5, 1)
    # Z slices: [0, 1, 2, 3, 4]
    data = np.arange(5).reshape(1, 1, 5, 1).astype(float)
    
    # Shift +1 (move UP, z=0 -> z=1)
    # New Volume: [0, 0, 1, 2, 3] (slice 4 is lost, slice 0 is padded 0)
    # Wait, moco logic:
    # moco.py: 
    # if shift > 0: corrected[:,:,shift:,:] = bold[:,:,:-shift,:]
    # data[..., :-1, :] is [0, 1, 2, 3]
    # corrected[..., 1:, :] becomes [0, 1, 2, 3]
    # corrected[..., 0, :] stays 0? Yes (initialized to zeros)
    # result: [0, 0, 1, 2, 3]
    
    shifted_plus1 = moco.apply_z_shift_correction(data, 1)
    assert shifted_plus1[0, 0, 0, 0] == 0 # Padded
    assert shifted_plus1[0, 0, 1, 0] == 0 # Moved from z=0
    assert shifted_plus1[0, 0, 2, 0] == 1 # Moved from z=1
    
    # Shift -1 (move DOWN, z=1 -> z=0)
    # New Volume: [1, 2, 3, 4, 0]
    # moco.py:
    # if shift < 0 (abs=1): corrected[:,:,:-1,:] = bold[:,:,1:,:]
    # data[..., 1:, :] is [1, 2, 3, 4]
    # corrected[..., :-1, :] becomes [1, 2, 3, 4]
    # corrected[..., -1, :] stays 0
    
    shifted_minus1 = moco.apply_z_shift_correction(data, -1)
    assert shifted_minus1[0, 0, 0, 0] == 1
    assert shifted_minus1[0, 0, 4, 0] == 0 # Padded
    
def test_metrics_fd():
    # Test FD calculation
    # Frame 0: 0
    # Frame 1: tx=1.0
    # Frame 2: tx=1.0, ty=1.0
    
    params = pd.DataFrame({
        'tx': [0, 1, 1, 0],
        'ty': [0, 0, 1, 0],
        'tz': [0, 0, 0, 0],
        'rx': [0, 0, 0, 0],
        'ry': [0, 0, 0, 0],
        'rz': [0, 0, 0, 0]
    })
    
    fd = moco.compute_framewise_displacement(params)
    
    # Frame 0: 0 (diff with prev is assumed 0 or nan->0)
    assert fd[0] == 0.0
    
    # Frame 1: diff tx=1, ty=0 -> abs sum = 1
    assert fd[1] == 1.0
    
    # Frame 2: diff tx=0, ty=1 -> abs sum = 1
    assert fd[2] == 1.0
    
    # Frame 3: diff tx=-1, ty=-1 -> abs sum = 2
    assert fd[3] == 2.0
