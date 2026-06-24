"""Unit tests for the reliability benchmark modules (validation/, T2)."""
from __future__ import annotations

import sys
from pathlib import Path

import nibabel as nib
import numpy as np

# validation/ modules import each other by bare name; put it on the path.
_VAL = str(Path(__file__).resolve().parents[1] / "validation")
if _VAL not in sys.path:
    sys.path.insert(0, _VAL)


def test_icc_perfect_agreement_is_one():
    from reliability_tsnr import icc_2_1
    M = np.array([[1.0, 1.0], [2.0, 2.0], [3.0, 3.0], [4.0, 4.0]])
    icc, n = icc_2_1(M)
    assert n == 4
    assert icc > 0.99


def test_icc_no_between_subject_variance_is_low():
    from reliability_tsnr import icc_2_1
    # all subjects identical → no rank reliability
    M = np.array([[2.0, 2.1], [2.0, 1.9], [2.0, 2.05], [2.0, 1.95]])
    icc, _ = icc_2_1(M)
    assert icc < 0.5


def test_edges_fisher_z_of_correlation():
    import reliability_connectivity as rc
    t = np.linspace(0, 10, 50)
    a = np.sin(t)
    ts = {1: (a - a.mean()) / a.std(),
          2: (a - a.mean()) / a.std(),          # identical → r≈1
          3: np.random.default_rng(0).normal(size=50)}
    edges = rc._edges(ts, [1, 2, 3])
    assert edges[(1, 2)] > 3.0          # Fisher-z of r≈1 is large
    assert abs(edges[(1, 3)]) < edges[(1, 2)]


def test_per_level_timeseries_extracts_means(tmp_path):
    import reliability_connectivity as rc
    # 3 levels in a 6x1x1 atlas; bold with a distinct signal per level
    atlas = np.zeros((6, 1, 1), dtype=np.int16)
    atlas[0:2, 0, 0] = 5      # C5 (2 voxels — below the <3 floor → dropped)
    atlas[2:6, 0, 0] = 6      # C6 (4 voxels — kept)
    bold = np.zeros((6, 1, 1, 20), dtype=np.float32)
    bold[2:6, 0, 0, :] = np.tile(np.sin(np.linspace(0, 6, 20)), (4, 1))
    ap = tmp_path / "atlas.nii.gz"; bp = tmp_path / "bold.nii.gz"
    nib.save(nib.Nifti1Image(atlas, np.eye(4)), ap)
    nib.save(nib.Nifti1Image(bold, np.eye(4)), bp)
    ts = rc._per_level_timeseries(bp, ap)
    assert 6 in ts and 5 not in ts      # C5 dropped (only 2 voxels)
    assert ts[6].shape == (20,)
    assert abs(ts[6].std() - 1.0) < 1e-5  # z-scored


def test_normative_summary_stats():
    import normative_qc_db as nq
    import numpy as np
    s = nq._summary(np.array([1.0, 2.0, 3.0, 4.0, 5.0]))
    assert s["n"] == 5 and s["median"] == 3.0
    assert s["mean"] == 3.0 and s["p5"] is not None and s["p95"] is not None
