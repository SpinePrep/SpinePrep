"""MP-PCA denoising wrapper for BOLD data."""

from __future__ import annotations

import sys
from pathlib import Path

import nibabel as nib
import numpy as np


def mppca_denoise(
    in_path: str | Path,
    out_path: str | Path,
    patch: int = 5,
    stride: int = 3,
) -> None:
    """
    Apply MP-PCA denoising to 4D BOLD data.

    Uses DIPY if available, otherwise performs copy-through with warning.

    Args:
        in_path: Input NIfTI path
        out_path: Output NIfTI path
        patch: Patch radius for MP-PCA (default: 5)
        stride: Stride for overlapping patches (default: 3)
    """
    in_path = Path(in_path)
    out_path = Path(out_path)

    # Load input
    img = nib.load(str(in_path))
    data = np.asanyarray(img.dataobj)
    affine = img.affine
    header = img.header

    # Try to use DIPY
    try:
        from dipy.denoise.localpca import mppca

        print(
            f"[A4] Denoising {in_path.name} with MP-PCA (patch={patch}, stride={stride})"
        )

        # Apply MP-PCA
        denoised_data = mppca(data, patch_radius=patch, pca_method="eig")

        # Save denoised data
        out_path.parent.mkdir(parents=True, exist_ok=True)
        denoised_img = nib.Nifti1Image(denoised_data, affine, header)
        nib.save(denoised_img, str(out_path))

        print(f"[A4] Denoised data written to {out_path}")

    except ImportError:
        # DIPY not available - copy through with warning
        print(
            f"[A4][warn] DIPY not available, copying {in_path.name} without denoising",
            file=sys.stderr,
        )

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_img = nib.Nifti1Image(data, affine, header)
        nib.save(out_img, str(out_path))

        print(f"[A4] Copy-through complete: {out_path}")

    except Exception as e:
        # DIPY failed - copy through with error message
        print(
            f"[A4][warn] MP-PCA failed ({e}), copying without denoising",
            file=sys.stderr,
        )

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_img = nib.Nifti1Image(data, affine, header)
        nib.save(out_img, str(out_path))

        print(f"[A4] Copy-through after error: {out_path}")
