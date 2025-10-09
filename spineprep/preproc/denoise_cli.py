"""CLI wrapper for MP-PCA denoising.

Usage:
    python -m spineprep.preproc.denoise_cli --in INPUT --out OUTPUT [--patch 5] [--stride 3]
"""

from __future__ import annotations

import argparse

from spineprep.preproc.denoise import mppca_denoise


def main() -> int:
    """CLI entry point for denoising."""
    parser = argparse.ArgumentParser(description="MP-PCA denoising for BOLD data")
    parser.add_argument("--in", dest="input", required=True, help="Input NIfTI path")
    parser.add_argument("--out", dest="output", required=True, help="Output NIfTI path")
    parser.add_argument(
        "--patch", type=int, default=5, help="Patch radius (default: 5)"
    )
    parser.add_argument(
        "--stride", type=int, default=3, help="Stride for patches (default: 3)"
    )

    args = parser.parse_args()

    try:
        mppca_denoise(
            in_path=args.input,
            out_path=args.output,
            patch=args.patch,
            stride=args.stride,
        )
        return 0
    except Exception as e:
        print(f"ERROR: Denoising failed: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
