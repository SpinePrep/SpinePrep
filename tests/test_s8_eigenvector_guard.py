import numpy as np

from spineprep.steps.s8.process import _load_eigenvectors


def test_full_file_loads(tmp_path):
    p = tmp_path / "e.txt"
    np.savetxt(p, np.random.default_rng(0).normal(size=(50, 3)))
    arr, reason = _load_eigenvectors(p, 50)
    assert reason is None and arr.shape == (50, 3)


def test_single_component_becomes_column(tmp_path):
    p = tmp_path / "e.txt"
    np.savetxt(p, np.arange(50.0))
    arr, _ = _load_eigenvectors(p, 50)
    assert arr.shape == (50, 1)


def test_empty_file_skipped(tmp_path):
    p = tmp_path / "e.txt"
    p.write_text("")
    arr, reason = _load_eigenvectors(p, 50)
    assert arr is None and reason == "empty_eigenvector_file"


def test_truncated_file_skipped(tmp_path):
    p = tmp_path / "e.txt"
    np.savetxt(p, np.zeros((30, 2)))
    arr, reason = _load_eigenvectors(p, 50)
    assert arr is None and "30 != 50" in reason
