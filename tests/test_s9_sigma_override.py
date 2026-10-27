"""SPINEPREP_SIGMA_MM: three numbers override the policy sigma; anything else is refused, never ignored."""

import pytest

from spineprep.steps.s9.process import _sigma_override


def test_unset_keeps_the_policy_sigma():
    assert _sigma_override(None) is None
    assert _sigma_override("  ") is None


@pytest.mark.parametrize("value", ["1,1,5", "1 1 5", "1.0, 1.0, 5.0"])
def test_three_numbers_override(value):
    assert _sigma_override(value) == [1.0, 1.0, 5.0]


@pytest.mark.parametrize("value", ["1,1", "1,1,5,7", "1,x,5", "1,-1,5"])
def test_malformed_value_is_refused(value):
    with pytest.raises(ValueError, match="SPINEPREP_SIGMA_MM"):
        _sigma_override(value)
