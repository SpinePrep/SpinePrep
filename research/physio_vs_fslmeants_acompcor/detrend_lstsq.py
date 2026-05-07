# per-voxel constant + linear detrend, same design as PhysIO aCompCor.
# usage: python detrend_lstsq.py bold.nii bold_detrended.nii

import sys
import numpy as np
import nibabel as nib

bold_path, out_path = sys.argv[1], sys.argv[2]

img = nib.load(bold_path)
bold = img.get_fdata().astype(np.float64)
X, Y, Z, T = bold.shape

t = np.arange(T)
DM = np.column_stack([np.ones(T), t - t.mean()])

flat = bold.reshape(-1, T)
beta = np.linalg.lstsq(DM, flat.T, rcond=None)[0]
resid = flat - (DM @ beta).T

nib.save(nib.Nifti1Image(resid.reshape(X, Y, Z, T).astype(np.float32),
                         img.affine, img.header), out_path)

print(f"detrended {bold.shape} -> {out_path}")
