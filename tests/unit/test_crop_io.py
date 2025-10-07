"""Unit tests for crop IO functionality."""

from workflow.lib.crop import read_crop_json, write_crop_json


def test_write_read_crop_json_roundtrip(tmp_path):
    """Test that crop JSON can be written and read correctly."""
    info = {"from": 2, "to": 97, "nvols": 100, "reason": "robust_z"}
    p = tmp_path / "crop.json"
    write_crop_json(str(p), info)
    got = read_crop_json(str(p))
    assert got == info
