"""Unit tests for confounds computation functionality."""

import numpy as np

from workflow.lib.confounds import compute_dvars, compute_fd_from_params


def test_fd_from_params_power():
    """Test FD computation from motion parameters."""
    # 3 frames, small translations (mm) and rotations (rad)
    params = np.array(
        [[0, 0, 0, 0, 0, 0], [0.5, 0, 0, 0, 0, 0], [0.5, 0.2, 0, 0.001, 0, 0]],
        dtype=float,
    )

    fd = compute_fd_from_params(params, tr_s=2.0)
    assert fd.shape == (3,)
    # FD[0] = 0; FD[1] ~0.5; FD[2] should be different
    assert fd[0] == 0
    assert 0.49 <= fd[1] <= 0.51
    assert fd[2] > 0  # Should be positive


def test_dvars_basic(tmp_path):
    """Test DVARS computation from synthetic BOLD data."""
    # synthetic BOLD: 5x5x2, T=5, single jump to trigger DVARS>0
    import nibabel as nib

    data = np.zeros((5, 5, 2, 5), dtype=np.float32)
    data[..., 2] = 10  # Jump at volume 2

    img = nib.Nifti1Image(data, np.eye(4))
    p = tmp_path / "bold.nii.gz"
    nib.save(img, str(p))

    dvars = compute_dvars(str(p))
    assert dvars.shape == (5,)
    assert (dvars[0] == 0) and (dvars[2] > 0)
