import numpy as np

from spineprep.steps.s8.process import _bandpassed_cardiac_peaks, _pulse_counted_twice


def test_rule_fires_only_on_double_count():
    assert _pulse_counted_twice(170.0, 86.0)
    assert not _pulse_counted_twice(90.0, 88.0)       # normal rate
    assert not _pulse_counted_twice(170.0, 160.0)     # detectors agree: genuinely fast
    assert not _pulse_counted_twice(170.0, 40.0)      # detector far off: no rebuild


def test_bandpassed_detector_counts_one_peak_per_beat_with_dicrotic_notch():
    fs, hr_hz, dur = 400.0, 1.4, 120.0                  # 84 beats/min
    t = np.arange(0, dur, 1 / fs)
    phase = (t * hr_hz) % 1.0
    pulse = np.exp(-((phase - 0.15) / 0.05) ** 2) + 0.8 * np.exp(-((phase - 0.55) / 0.05) ** 2)
    peaks, q = _bandpassed_cardiac_peaks(pulse, fs)
    rate = 60.0 / (np.median(np.diff(peaks)) / (fs / q))
    assert abs(rate - 84.0) < 3.0
