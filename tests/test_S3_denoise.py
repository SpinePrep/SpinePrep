"""S3 MP-PCA denoise helper (lib/denoise.py): command construction, metadata,
extent override, and graceful fallback. dwidenoise is mocked so the test runs
without MRtrix installed."""

import shutil
from pathlib import Path

import numpy as np
import nibabel as nib
import pytest

from spineprep.lib import denoise


def _synthetic_bold(path: Path, n_t: int = 20):
    rng = np.random.default_rng(0)
    data = (rng.standard_normal((8, 8, 4, n_t)).astype(np.float32) + 100.0)
    nib.save(nib.Nifti1Image(data, np.eye(4)), str(path))


def _make_mock(out_should_exist=True):
    """side_effect for run_command: answer -version, and on the denoise call
    create the output + noise map by copying the input."""
    def _mock(cmd, *a, **k):
        if "dwidenoise" in cmd[0] and "-version" in cmd:
            return True, "== dwidenoise 3.0.4 =="
        # denoise call: dwidenoise <in> <out> -noise <noise> -force [-extent ...]
        inp, out = cmd[1], cmd[2]
        if out_should_exist:
            shutil.copy(inp, out)
            noise = cmd[cmd.index("-noise") + 1]
            shutil.copy(inp, noise)  # stand-in noise map
            return True, ""
        return False, "dwidenoise: simulated failure"
    return _mock


def test_denoise_builds_command_and_meta(tmp_path, monkeypatch):
    bold = tmp_path / "bold.nii.gz"; _synthetic_bold(bold)
    out = tmp_path / "dn.nii.gz"
    calls = []
    mock = _make_mock()
    def _spy(cmd, *a, **k):
        calls.append(cmd); return mock(cmd, *a, **k)
    monkeypatch.setattr(denoise, "_run_command", _spy)

    ok, noise_map, meta = denoise.mppca_denoise(bold, out, tmp_path / "w", {"enabled": True})

    assert ok and out.exists()
    dn_cmd = next(c for c in calls if "-noise" in c)
    assert dn_cmd[0] == "dwidenoise" and "-force" in dn_cmd
    assert "-extent" not in dn_cmd  # auto-size by default
    assert meta["tool"] == "dwidenoise" and meta["extent"] == "auto"
    assert meta["version"] == "== dwidenoise 3.0.4 =="
    assert meta["tsnr_pre"] is not None and meta["tsnr_post"] is not None


def test_denoise_extent_override(tmp_path, monkeypatch):
    bold = tmp_path / "bold.nii.gz"; _synthetic_bold(bold)
    calls = []
    mock = _make_mock()
    monkeypatch.setattr(denoise, "_run_command",
                        lambda c, *a, **k: (calls.append(c), mock(c, *a, **k))[1])
    ok, _, meta = denoise.mppca_denoise(
        bold, tmp_path / "dn.nii.gz", tmp_path / "w", {"enabled": True, "extent": "5,5,5"})
    dn_cmd = next(c for c in calls if "-noise" in c)
    assert "-extent" in dn_cmd and dn_cmd[dn_cmd.index("-extent") + 1] == "5,5,5"
    assert meta["extent"] == "5,5,5"


def test_denoise_fallback_on_failure(tmp_path, monkeypatch):
    bold = tmp_path / "bold.nii.gz"; _synthetic_bold(bold)
    monkeypatch.setattr(denoise, "_run_command", _make_mock(out_should_exist=False))
    ok, noise_map, meta = denoise.mppca_denoise(
        bold, tmp_path / "dn.nii.gz", tmp_path / "w", {"enabled": True})
    assert ok is False and noise_map is None and "error" in meta
