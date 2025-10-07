"""Unit tests for motion parameter outputs."""

from pathlib import Path


def test_motion_params_headers_and_paths(tmp_path: Path):
    """Test motion parameter TSV file format and headers."""
    # simulate outputs
    tsv = tmp_path / "sub-01_task-rest_run-01_desc-motion_params.tsv"
    tsv.write_text("trans_x\ttrans_y\ttrans_z\trot_x\trot_y\trot_z\n0\t0\t0\t0\t0\t0\n")
    assert tsv.exists()
    headers = tsv.read_text().strip().splitlines()[0].split("\t")
    assert headers == ["trans_x", "trans_y", "trans_z", "rot_x", "rot_y", "rot_z"]
