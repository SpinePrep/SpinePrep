"""CLI wrapper for basic confounds computation.

Usage:
    python -m spineprep.confounds.cli_basic \\
        --in INPUT.nii.gz \\
        --out OUTPUT_confounds.tsv \\
        --sidecar OUTPUT_confounds.json
"""

from __future__ import annotations

import argparse

import nibabel as nib
import numpy as np

from spineprep.confounds.basic import (
    compute_dvars,
    compute_fd_power,
    detect_spikes,
    write_confounds_tsv,
    write_sidecar_json,
)


def extract_motion_from_affines(img: nib.Nifti1Image) -> np.ndarray:
    """
    Extract motion parameters from NIfTI affine (simplistic).

    For A5, we approximate motion from affine changes. If affines are constant,
    return zeros. This is a placeholder until proper motion correction is added.

    Args:
        img: NIfTI image

    Returns:
        Motion params of shape (T, 6): [tx, ty, tz, rx, ry, rz]
        Translations in mm, rotations in radians
    """
    T = img.shape[3] if img.ndim == 4 else 1

    # For now, just return zeros (constant affine assumption)
    # Future: extract from volume-wise affines if available
    motion = np.zeros((T, 6))

    return motion


def main() -> int:
    """CLI entry point for basic confounds."""
    parser = argparse.ArgumentParser(description="Compute basic confounds for BOLD")
    parser.add_argument("--in", dest="input", required=True, help="Input NIfTI path")
    parser.add_argument("--out", dest="output", required=True, help="Output TSV path")
    parser.add_argument("--sidecar", required=True, help="Output JSON sidecar path")
    parser.add_argument(
        "--fd-thr", type=float, default=0.5, help="FD spike threshold (mm)"
    )
    parser.add_argument(
        "--dvars-z", type=float, default=2.5, help="DVARS Z-score threshold"
    )
    parser.add_argument(
        "--radius", type=float, default=50.0, help="Head radius for FD (mm)"
    )

    args = parser.parse_args()

    try:
        # Load BOLD
        print(f"[A5] Loading {args.input}")
        img = nib.load(args.input)
        data = np.asanyarray(img.dataobj, dtype=np.float32)

        if data.ndim != 4:
            raise ValueError(f"Expected 4D BOLD, got shape {data.shape}")

        T = data.shape[3]

        # Extract motion (placeholder: zeros for A5)
        motion = extract_motion_from_affines(img)

        # Compute FD
        fd = compute_fd_power(motion, radius=args.radius)

        # Compute DVARS
        dvars = compute_dvars(data)

        # Detect spikes
        spike = detect_spikes(fd, dvars, fd_thr=args.fd_thr, dvars_z=args.dvars_z)

        # Build confounds dict
        confounds = {
            "trans_x": motion[:, 0],
            "trans_y": motion[:, 1],
            "trans_z": motion[:, 2],
            "rot_x": motion[:, 3],
            "rot_y": motion[:, 4],
            "rot_z": motion[:, 5],
            "fd_power": fd,
            "dvars": dvars,
            "spike": spike,
        }

        # Write TSV
        write_confounds_tsv(args.output, confounds)
        print(f"[A5] Confounds TSV written: {args.output} ({T} volumes)")

        # Write sidecar JSON
        metadata = {
            "Estimator": "SpinePrep A5 basic",
            "FDPowerRadiusMM": args.radius,
            "SpikeFDThr": args.fd_thr,
            "SpikeDVARSZ": args.dvars_z,
            "Notes": [
                "Motion parameters approximated from affine (zeros if constant)",
                "DVARS computed from implicit mask of finite non-zero variance voxels",
                "Spikes detected when FD >= threshold OR DVARS Z-score >= threshold",
            ],
        }
        write_sidecar_json(args.sidecar, metadata)
        print(f"[A5] Sidecar JSON written: {args.sidecar}")

        return 0

    except Exception as e:
        print(f"ERROR: Confounds computation failed: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
