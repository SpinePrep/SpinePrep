import numpy as np
import pytest
from scipy.ndimage import gaussian_filter

from spineprep.steps.s9.process import _estimate_fwhm_axis


@pytest.mark.parametrize("fwhm", [1.5, 2.0, 3.0, 4.0])
def test_recovers_known_kernel_fwhm(fwhm):
    rng = np.random.default_rng(0)
    s = fwhm / np.sqrt(8 * np.log(2))
    x = gaussian_filter(rng.standard_normal((48, 48, 48, 20)), sigma=(s, s, s, 0))
    x -= x.mean(axis=3, keepdims=True)
    mask = np.ones(x.shape[:3], bool)
    for ax in range(3):
        est = _estimate_fwhm_axis(x, mask, axis=ax, zoom_mm=2.0)
        assert est == pytest.approx(2.0 * fwhm, abs=0.25)


def test_smoother_data_reports_larger_fwhm():
    rng = np.random.default_rng(1)
    n = rng.standard_normal((40, 40, 40, 10))
    mask = np.ones((40, 40, 40), bool)
    lo = _estimate_fwhm_axis(gaussian_filter(n, (0.8, 0.8, 0.8, 0)), mask, 0, 1.0)
    hi = _estimate_fwhm_axis(gaussian_filter(n, (1.6, 1.6, 1.6, 0)), mask, 0, 1.0)
    assert hi > lo
