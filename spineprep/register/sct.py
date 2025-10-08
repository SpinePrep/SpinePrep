"""Minimal SCT registration wrapper with conservative defaults."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import numpy as np


def build_register_cmd(
    src: str,
    dest: str,
    out_warp: str,
    out_resampled: str | None = None,
    param: str = "step=1,type=seg,algo=rigid:step=2,type=seg,algo=affine",
) -> list[str]:
    """
    Build sct_register_multimodal command with conservative defaults.

    Args:
        src: Source image path (e.g., EPI reference)
        dest: Destination image path (e.g., PAM50_t2.nii.gz)
        out_warp: Output warp field path
        out_resampled: Output resampled image path (optional)
        param: Registration parameters (default: rigid + affine only)

    Returns:
        Command list ready for subprocess.run()
    """
    cmd = [
        "sct_register_multimodal",
        "-i",
        src,
        "-d",
        dest,
        "-owarp",
        out_warp,
    ]

    if out_resampled:
        cmd.extend(["-o", out_resampled])

    # Add registration parameters
    cmd.extend(["-param", param])

    return cmd


def run_register(
    src: str,
    dest: str,
    out_warp: str,
    out_resampled: str | None = None,
    param: str | None = None,
) -> dict[str, Any]:
    """
    Run SCT registration with safe defaults.

    Args:
        src: Source image path
        dest: Destination image path
        out_warp: Output warp path
        out_resampled: Output resampled image path (optional)
        param: Custom registration parameters (optional)

    Returns:
        Dictionary with:
        - success: bool
        - return_code: int
        - stdout: str
        - stderr: str
        - sct_version: str (if available)
    """
    # Get SCT version for provenance
    sct_version = "unknown"
    try:
        version_proc = subprocess.run(
            ["sct_version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if version_proc.returncode == 0:
            sct_version = version_proc.stdout.strip().splitlines()[0]
    except Exception:
        pass

    # Build command
    if param is None:
        # Conservative defaults: rigid + affine only (no deformable)
        param = "step=1,type=seg,algo=rigid:step=2,type=seg,algo=affine"

    cmd = build_register_cmd(src, dest, out_warp, out_resampled, param)

    # Ensure output directories exist
    Path(out_warp).parent.mkdir(parents=True, exist_ok=True)
    if out_resampled:
        Path(out_resampled).parent.mkdir(parents=True, exist_ok=True)

    # Run registration
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )

        return {
            "success": result.returncode == 0,
            "return_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "sct_version": sct_version,
            "command": " ".join(cmd),
        }

    except Exception as e:
        return {
            "success": False,
            "return_code": -1,
            "stdout": "",
            "stderr": str(e),
            "sct_version": sct_version,
            "command": " ".join(cmd),
        }


def compute_ssim(img1: np.ndarray, img2: np.ndarray) -> float:
    """
    Compute Structural Similarity Index (SSIM) between two images.

    Args:
        img1: First image array
        img2: Second image array

    Returns:
        SSIM value (0-1, higher is better)
    """
    from skimage.metrics import structural_similarity

    # Handle 3D data (compute mean SSIM across slices or use 3D)
    if img1.shape != img2.shape:
        raise ValueError(f"Image shapes must match: {img1.shape} vs {img2.shape}")

    # For 3D data, compute slice-wise and average
    if len(img1.shape) == 3:
        ssim_vals = []
        for z in range(img1.shape[2]):
            slice1 = img1[:, :, z]
            slice2 = img2[:, :, z]
            # Skip empty slices
            if slice1.max() > 0 and slice2.max() > 0:
                ssim = structural_similarity(
                    slice1, slice2, data_range=slice1.max() - slice1.min()
                )
                ssim_vals.append(ssim)
        return float(np.mean(ssim_vals)) if ssim_vals else 0.0

    # For 2D data
    return float(structural_similarity(img1, img2, data_range=img1.max() - img1.min()))


def compute_psnr(img1: np.ndarray, img2: np.ndarray) -> float:
    """
    Compute Peak Signal-to-Noise Ratio (PSNR) between two images.

    Args:
        img1: First image array
        img2: Second image array

    Returns:
        PSNR value in dB (higher is better, typically 20-50 dB)
    """
    from skimage.metrics import peak_signal_noise_ratio

    if img1.shape != img2.shape:
        raise ValueError(f"Image shapes must match: {img1.shape} vs {img2.shape}")

    return float(
        peak_signal_noise_ratio(img1, img2, data_range=img1.max() - img1.min())
    )
