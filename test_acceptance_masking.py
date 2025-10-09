#!/usr/bin/env python
"""Acceptance test for masking module on fixture data."""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import nibabel as nib
import numpy as np

# Add repo to path
sys.path.insert(0, str(Path(__file__).parent))

from spineprep.preproc.masking import run_masks


def mock_sct_deepseg_fn(t2w_path, out_mask, contrast):
    """Mock SCT deepseg to create a reasonable cord mask."""
    # Load the T2w to get shape and affine
    t2w_img = nib.load(t2w_path)
    shape = t2w_img.shape
    affine = t2w_img.affine

    # Create a simple cord mask (cylinder in center)
    cord_data = np.zeros(shape, dtype=np.uint8)

    # Find center
    cx, cy = shape[0] // 2, shape[1] // 2

    # Create a small cylinder
    for z in range(shape[2]):
        for x in range(max(0, cx - 3), min(shape[0], cx + 4)):
            for y in range(max(0, cy - 3), min(shape[1], cy + 4)):
                # Simple circle
                if (x - cx) ** 2 + (y - cy) ** 2 <= 9:
                    cord_data[x, y, z] = 1

    # Save the mock mask
    cord_img = nib.Nifti1Image(cord_data, affine)
    nib.save(cord_img, out_mask)

    return {
        "success": True,
        "return_code": 0,
        "stdout": "Mock segmentation completed",
        "stderr": "",
        "sct_version": "6.0.0",
        "cmd": f"sct_deepseg_sc -i {t2w_path} -c {contrast} -o {out_mask}",
    }


def test_acceptance():
    """Run acceptance test on fixture data."""
    fixture_t2w = Path("tests/fixtures/bids_tiny/sub-01/anat/sub-01_T2w.nii.gz")

    if not fixture_t2w.exists():
        print(f"ERROR: Fixture not found: {fixture_t2w}")
        return False

    out_root = Path("test_work_masking")
    out_root.mkdir(exist_ok=True)

    print(f"Running masking on {fixture_t2w}")

    # Mock the SCT call
    with patch(
        "spineprep.preproc.masking.run_sct_deepseg", side_effect=mock_sct_deepseg_fn
    ):
        outputs = run_masks(
            t2w_path=str(fixture_t2w),
            subject="sub-01",
            out_root=str(out_root),
            make_csf=True,
            qc=True,
        )

    print("\nOutputs:")
    for key, path in outputs.items():
        print(f"  {key}: {path}")

    # Check 1: Cord mask exists
    cord_mask = Path(outputs["cord_mask"])
    if not cord_mask.exists():
        print(f"ERROR: Cord mask not found: {cord_mask}")
        return False
    print(f"✓ Cord mask exists: {cord_mask}")

    # Check 2: CSF mask exists
    csf_mask = Path(outputs["csf_mask"])
    if not csf_mask.exists():
        print(f"ERROR: CSF mask not found: {csf_mask}")
        return False
    print(f"✓ CSF mask exists: {csf_mask}")

    # Check 3: QC PNG exists
    qc_png = Path(outputs["qc_png"])
    if not qc_png.exists():
        print(f"ERROR: QC PNG not found: {qc_png}")
        return False
    if qc_png.stat().st_size == 0:
        print(f"ERROR: QC PNG is empty: {qc_png}")
        return False
    print(f"✓ QC PNG exists and is readable: {qc_png} ({qc_png.stat().st_size} bytes)")

    # Check 4: Provenance JSON exists and has required fields
    prov_json = Path(outputs["cord_json"])
    if not prov_json.exists():
        print(f"ERROR: Provenance JSON not found: {prov_json}")
        return False

    with open(prov_json) as f:
        prov_data = json.load(f)

    required_fields = ["cmd", "sct_version", "time_utc", "inputs"]
    for field in required_fields:
        if field not in prov_data:
            print(f"ERROR: Missing field in provenance: {field}")
            return False

    print(f"✓ Provenance JSON exists with all fields: {prov_json}")
    print(f"  - cmd: {prov_data['cmd']}")
    print(f"  - sct_version: {prov_data['sct_version']}")
    print(f"  - inputs: {prov_data['inputs']}")

    print("\n✅ All acceptance tests passed!")
    return True


if __name__ == "__main__":
    success = test_acceptance()
    sys.exit(0 if success else 1)
