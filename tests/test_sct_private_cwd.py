"""SCT tools that drop files into the current directory run in the run's own folder.

Clean-room run 2 (2026-10-26) ran the container as the user with the read-only /app as working directory:
S2's rootlet registration failed ("Permission denied: '/app/rootlets_mid.nii.gz'"), so the template registration
fell back to discs, and S7 failed on warp_final.nii.gz. Subjects run side by side in one working directory would
also share those files.
"""

from pathlib import Path

from spineprep.steps.s2 import register


def test_register_to_template_runs_in_its_output_folder(tmp_path, monkeypatch):
    seen = {}

    def fake_run(cmd, timeout=None, cwd=None):
        seen["cwd"] = cwd
        return False, "stop here"

    monkeypatch.setattr(register, "_run_command", fake_run)
    work = tmp_path / "reg_rootlet"
    register._run_register_to_template(tmp_path / "t1.nii.gz", tmp_path / "seg.nii.gz", None, None, "t1", work)
    assert Path(seen["cwd"]) == work
