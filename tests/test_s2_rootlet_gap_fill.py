import nibabel as nib
import numpy as np

from spineprep.steps.s2.register import _fill_interior_rootlet_gaps


def _write(tmp_path, levels):
    data = np.zeros((10, 10, 40), dtype=np.uint8)
    for lv in levels:
        z = 4 * lv
        data[4:6, 4:6, z:z + 2] = lv
    p = tmp_path / "rootlets.nii.gz"
    nib.save(nib.Nifti1Image(data, np.eye(4)), str(p))
    return p


def test_contiguous_levels_untouched(tmp_path):
    p = _write(tmp_path, [2, 3, 4, 5])
    out, info = _fill_interior_rootlet_gaps(p, tmp_path)
    assert out == p and info["rootlet_labels_interpolated"] == []


def test_interior_gap_filled_between_neighbours(tmp_path):
    p = _write(tmp_path, [2, 3, 6, 7])
    out, info = _fill_interior_rootlet_gaps(p, tmp_path)
    assert info["rootlet_labels_interpolated"] == [4, 5]
    data = np.asarray(nib.load(str(out)).dataobj)
    z4 = np.where(data == 4)[2].mean()
    z3, z6 = np.where(data == 3)[2].mean(), np.where(data == 6)[2].mean()
    assert z3 < z4 < z6


def test_wide_gap_not_filled(tmp_path):
    p = _write(tmp_path, [2, 6])
    out, info = _fill_interior_rootlet_gaps(p, tmp_path)
    assert out == p and info["rootlet_labels_interpolated"] == []
