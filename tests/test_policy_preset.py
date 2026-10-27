from pathlib import Path

import pytest
import yaml

from spineprep.lib.policy import read_policy_yaml

POLICY = Path(__file__).resolve().parents[1] / "policy"
P1_PATCH_VALUES = {
    "S2B_func_denoise.yaml": [(("enabled",), True), (("nthreads",), 8)],
    "S5_func_distortion_correction.yaml": [(("distortion_correction", "prefer_mode"), "none")],
    "S9_primary_functional_derivatives.yaml": [(("smoothing", "enabled"), True)],
}


def _get(d, keys):
    for k in keys:
        d = d[k]
    return d


def test_defaults_unchanged_without_preset(monkeypatch):
    monkeypatch.delenv("SPINEPREP_PRESET", raising=False)
    for name in P1_PATCH_VALUES:
        assert read_policy_yaml(POLICY / name) == yaml.safe_load((POLICY / name).read_text())


@pytest.mark.parametrize("name", list(P1_PATCH_VALUES))
def test_cospi_preset_gives_p1_settings_and_keeps_the_rest(monkeypatch, name):
    monkeypatch.setenv("SPINEPREP_PRESET", "cospi")
    merged = read_policy_yaml(POLICY / name)
    base = yaml.safe_load((POLICY / name).read_text())
    for keys, value in P1_PATCH_VALUES[name]:
        assert _get(merged, keys) == value
    assert set(merged) == set(base)  # nothing added or dropped at top level


def test_cospi_keeps_smoothing_kernel(monkeypatch):
    monkeypatch.setenv("SPINEPREP_PRESET", "cospi")
    merged = read_policy_yaml(POLICY / "S9_primary_functional_derivatives.yaml")
    assert merged["smoothing"]["sigma_mm"] == [1.0, 1.0, 5.0]


def test_unknown_preset_refused(monkeypatch):
    monkeypatch.setenv("SPINEPREP_PRESET", "no-such-preset")
    with pytest.raises(ValueError):
        read_policy_yaml(POLICY / "S5_func_distortion_correction.yaml")
