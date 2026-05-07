"""Per-voxel constant + centered-linear detrend of a 4D BOLD NIfTI.

Reproduces the per-voxel detrend that TAPAS PhysIO applies internally
before aCompCor PCA. Run before `fslmeants --eig` to make its PCs match
PhysIO's noise-ROI components.

Usage:
    python detrend_lstsq.py bold.nii bold_detrended.nii
"""

import sys

import nibabel as nib
import numpy as np


def detrend(bold_path: str, out_path: str) -> None:
    img = nib.load(bold_path)
    bold = img.get_fdata().astype(np.float64)
    X, Y, Z, T = bold.shape

    t = np.arange(T)
    DM = np.column_stack([np.ones(T), t - t.mean()])

    flat = bold.reshape(-1, T)
    beta = np.linalg.lstsq(DM, flat.T, rcond=None)[0]
    fit = (DM @ beta).T
    resid = flat - fit

    detrended = resid.reshape(X, Y, Z, T)
    nib.save(
        nib.Nifti1Image(detrended.astype(np.float32), img.affine, img.header),
        out_path,
    )
    print(f"detrended {bold.shape} -> {out_path}")


if __name__ == "__main__":
    detrend(sys.argv[1], sys.argv[2])
