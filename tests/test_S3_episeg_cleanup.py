"""Regression tests for S3 EPISeg (sct_deepseg sc_epi) cord-mask cleanup.

Freezes the AS002 failure mode: EPISeg finds the full cord but splits it into
an upper and a lower on-axis component across the anterior-curve gap, plus a
few off-axis brain specks. The cleanup must UNION the two cord fragments and
DROP the specks — a naive largest-connected-component keep would keep only the
bigger fragment and re-truncate the cord (the bug this fix removes).
"""
import sys
from pathlib import Path

import nibabel as nib
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from spineprep.steps.s3.localize import _cleanup_epi_cordseg

# ~1.6 mm iso, matching the GVS cord-EPI acquisition
AFF = np.diag([1.6, 1.6, 1.6, 1.0])


def _save(tmp_path, data):
    p = tmp_path / "seg.nii.gz"
    nib.save(nib.Nifti1Image(data.astype(np.uint8), AFF), p)
    return p


def _policy(bridge_z=2):
    return {"func_localization": {"cleanup": {"bridge_z_slices": bridge_z}}}


def test_cleanup_unions_fragmented_cord_and_drops_speck(tmp_path):
    """Upper cord + lower cord (1-slice gap) + off-axis speck → cord kept whole."""
    d = np.zeros((40, 40, 40), dtype=np.uint8)
    # Upper cord fragment, on-axis column, Z 20..30
    d[19:22, 19:22, 20:31] = 1
    # Lower cord fragment, one empty slice below the upper one (gap at Z19),
    # shifted anteriorly (y drops) to mimic the anterior cervical curve.
    d[19:22, 16:19, 8:19] = 1
    # Off-axis brain speck, superior and lateral (well away from the cord axis)
    d[30:33, 5:8, 37:40] = 1

    before = int(d.sum())
    seg = _save(tmp_path, d)
    stats = _cleanup_epi_cordseg(seg, _policy(bridge_z=2))
    out = np.asarray(nib.load(seg).get_fdata()) > 0

    # The speck is gone, both cord fragments survive.
    assert d[30:33, 5:8, 37:40].astype(bool).sum() > 0  # speck existed
    assert out[30:33, 5:8, 37:40].sum() == 0            # speck dropped
    assert out[19:22, 19:22, 20:31].all()               # upper cord kept
    assert out[19:22, 16:19, 8:19].all()                # lower cord kept
    # Full cord Z-extent preserved (8..30), not truncated to one fragment.
    zc = np.where(out.any(axis=(0, 1)))[0]
    assert zc.min() == 8 and zc.max() == 30
    assert stats["components_dropped"] >= 1
    assert stats["voxels_dropped"] == before - int(out.sum())


def test_cleanup_noop_on_single_clean_component(tmp_path):
    """A single contiguous cord blob is returned unchanged (no erosion)."""
    d = np.zeros((40, 40, 40), dtype=np.uint8)
    d[18:22, 18:22, 6:34] = 1
    seg = _save(tmp_path, d)
    stats = _cleanup_epi_cordseg(seg, _policy())
    out = np.asarray(nib.load(seg).get_fdata()) > 0
    assert out.sum() == int(d.sum())          # nothing removed
    assert stats["components_dropped"] == 0


def test_cleanup_noop_on_empty_mask(tmp_path):
    """Degenerate empty mask must not raise."""
    d = np.zeros((20, 20, 20), dtype=np.uint8)
    seg = _save(tmp_path, d)
    stats = _cleanup_epi_cordseg(seg, _policy())
    assert stats["n_components"] == 0
    assert np.asarray(nib.load(seg).get_fdata()).sum() == 0
