"""Unit tests for motion grouping functionality."""

import pytest

from workflow.lib.samples import assign_motion_groups


def test_group_key_and_guards(tmp_path):
    """Test motion group key assignment and requirement guards."""
    rows = [
        {
            "sub": "sub-01",
            "ses": "01",
            "task": "motor",
            "pe_dir": "AP",
            "slice_axis": "IS",
            "tr": 1.2,
            "voxel_size": "1.0x1.0x3.0",
            "bold_path": "/x/a.nii.gz",
        },
        {
            "sub": "sub-01",
            "ses": "01",
            "task": "motor",
            "pe_dir": "AP",
            "slice_axis": "IS",
            "tr": 1.2,
            "voxel_size": "1.0x1.0x3.0",
            "bold_path": "/x/b.nii.gz",
        },
        {
            "sub": "sub-01",
            "ses": "01",
            "task": "motor",
            "pe_dir": "AP",
            "slice_axis": "IS",
            "tr": 1.2,
            "voxel_size": "1.0x1.0x3.0",
            "bold_path": "/x/c.nii.gz",
        },
    ]
    out = assign_motion_groups(
        rows,
        mode="session+task",
        require_same=["pe_dir", "slice_axis", "tr", "voxel_size"],
    )
    keys = {r["motion_group"] for r in out}
    assert len(keys) == 1 and next(iter(keys)).startswith("sub-01_ses-01_task-motor")

    # Test requirement violation
    rows[1]["pe_dir"] = "PA"
    with pytest.raises(ValueError):
        assign_motion_groups(
            rows,
            mode="session+task",
            require_same=["pe_dir", "slice_axis", "tr", "voxel_size"],
        )
