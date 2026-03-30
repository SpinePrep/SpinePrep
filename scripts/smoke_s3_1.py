#!/usr/bin/env python3
"""
Smoke test for S3.1 subtask execution.

Tests that S3.1 can be run independently and produces expected outputs.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from spinalfmriprep.S3_func_init_and_crop import run_S3_func_init_and_crop


def main() -> int:
    """Run S3.1 smoke test."""
    print("=" * 60)
    print("S3.1 Smoke Test")
    print("=" * 60)
    print()

    # Create a temporary output directory
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = Path(tmpdir) / "smoke_test_s3_1"
        out_dir.mkdir(parents=True, exist_ok=True)

        print(f"Output directory: {out_dir}")
        print()

        # Run S3.1 with subtask flag
        print("Running S3.1 with --subtask S3.1...")
        try:
            result = run_S3_func_init_and_crop(
                subtask_id="S3.1",
                out=str(out_dir),
            )

            print(f"✓ Execution completed")
            print(f"  Status: {result.status}")
            
            if result.status != "PASS":
                print(f"✗ ERROR: Step failed: {result.failure_message}")
                return 1
            
            # Check that outputs exist
            if result.runs_path and result.runs_path.exists():
                print(f"  Runs: {result.runs_path}")
            if result.qc_path and result.qc_path.exists():
                print(f"  QC: {result.qc_path}")
            
            print()
            print("=" * 60)
            print("✓ S3.1 Smoke Test PASSED")
            print("=" * 60)
            return 0

        except Exception as e:
            print(f"✗ ERROR: Exception during execution: {e}")
            import traceback

            traceback.print_exc()
            return 1


if __name__ == "__main__":
    sys.exit(main())
