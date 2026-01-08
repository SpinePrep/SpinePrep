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

from spineprep.S3_func_init_and_crop import run_S3_func_init_and_crop


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
            print(f"  Status: {result['status']}")
            print(f"  Subtask: {result['subtask']}")
            print(f"  Results: {len(result['results'])} subtask(s) executed")
            print()

            # Verify S3.1 results
            if result["subtask"] != "S3.1":
                print(f"✗ ERROR: Expected subtask 'S3.1', got '{result['subtask']}'")
                return 1

            if len(result["results"]) != 1:
                print(f"✗ ERROR: Expected 1 result, got {len(result['results'])}")
                return 1

            s3_1_data = result["results"][0][1]
            print("S3.1 Outputs:")
            outputs_to_check = [
                ("func_ref_fast", "func_ref_fast_path"),
                ("func_ref0", "func_ref0_path"),
                ("discovery_seg", "discovery_seg_path"),
                ("roi_mask", "roi_mask_path"),
                ("func_ref_fast_crop", "func_ref_fast_crop_path"),
                ("figure", "figure_path"),
            ]

            all_exist = True
            for name, key in outputs_to_check:
                path = s3_1_data[key]
                exists = path.exists()
                status = "✓" if exists else "✗"
                print(f"  {status} {name}: {path}")
                if not exists:
                    all_exist = False

            print()

            if not all_exist:
                print("✗ ERROR: Some S3.1 outputs are missing")
                return 1

            if s3_1_data.get("localization_status") != "PASS":
                print(f"✗ ERROR: Localization status is not PASS: {s3_1_data.get('localization_status')}")
                return 1

            print("✓ All S3.1 outputs created successfully")
            print("✓ Localization status: PASS")
            print()

            # Verify that only S3.1 ran (no S3.2, S3.3, S3.4)
            executed_subtasks = [r[0] for r in result["results"]]
            if "S3.2" in executed_subtasks or "S3.3" in executed_subtasks or "S3.4" in executed_subtasks:
                print(f"✗ ERROR: Later subtasks were executed: {executed_subtasks}")
                return 1

            print("✓ Only S3.1 was executed (later subtasks correctly skipped)")
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

