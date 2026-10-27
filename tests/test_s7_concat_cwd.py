"""S7 composes warps in the run's own folder (sct_concat_transfo writes warp_final.nii.gz into the current one).

Run 2 of the clean-room check (2026-10-26) ran the container as the user, with the read-only /app as working
directory, and S7 failed: "cannot open output file 'warp_final.nii.gz'". Two runs side by side in one working
directory would also share that file.
"""

from pathlib import Path

from spineprep.steps.s7 import process


def test_concat_transfo_runs_in_the_output_folder(tmp_path, monkeypatch):
    seen = {}

    def fake_run(cmd, timeout=None, cwd=None):
        seen["cwd"] = cwd
        Path(cmd[cmd.index("-o") + 1]).write_bytes(b"warp")
        return True, ""

    monkeypatch.setattr(process, "_run_command", fake_run)
    out = tmp_path / "run-01" / "warp.nii.gz"
    out.parent.mkdir()
    ok, err = process._concat_transfo([tmp_path / "a.nii.gz", tmp_path / "b.nii.gz"], tmp_path / "ref.nii.gz", out)
    assert ok and err is None
    assert Path(seen["cwd"]) == out.parent
