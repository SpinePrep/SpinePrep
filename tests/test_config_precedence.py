"""Tests for config precedence: defaults < YAML < CLI."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
import yaml

from spineprep.config import load_defaults, resolve_config


def test_load_defaults():
    """Test that defaults can be loaded."""
    cfg = load_defaults()

    assert cfg is not None
    assert isinstance(cfg, dict)

    # Should have required top-level keys per ticket
    assert "motion" in cfg
    assert "confounds" in cfg
    assert "registration" in cfg
    assert "qc" in cfg


def test_defaults_have_required_values():
    """Test that defaults contain all required config values per ticket."""
    cfg = load_defaults()

    # Motion defaults (per ticket)
    assert cfg["motion"]["fd"]["threshold"] == 0.5
    assert cfg["motion"]["dvars"]["threshold"] == 1.5
    assert cfg["motion"]["highpass"]["hz"] == 0.008

    # Confounds defaults (per ticket)
    assert cfg["confounds"]["acompcor"]["n_components"] == 6
    assert cfg["confounds"]["tcompcor"]["n_components"] == 0
    assert cfg["confounds"]["censor"]["method"] == "fd"

    # Registration defaults (per ticket)
    assert cfg["registration"]["pam50"]["spacing"] == "0.5mm"
    assert cfg["registration"]["resample"]["to"] == "native"
    assert cfg["registration"]["deformable"]["enabled"] is False

    # QC defaults (per ticket)
    assert cfg["qc"]["ssim"]["min"] == 0.85
    assert cfg["qc"]["psnr"]["min"] == 20.0
    assert cfg["qc"]["report"]["embed_assets"] is True


def test_yaml_overrides_defaults():
    """Test that YAML config overrides defaults."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(
            {
                "motion": {
                    "fd": {"threshold": 0.8},  # Override default 0.5
                },
                "qc": {
                    "ssim": {"min": 0.9},  # Override default 0.85
                },
            },
            f,
        )
        yaml_path = Path(f.name)

    try:
        cfg = resolve_config(
            bids_root="/tmp/bids",
            out_dir="/tmp/out",
            yaml_path=yaml_path,
        )

        # YAML should override defaults
        assert cfg["motion"]["fd"]["threshold"] == 0.8
        assert cfg["qc"]["ssim"]["min"] == 0.9

        # But other defaults should remain
        assert cfg["motion"]["dvars"]["threshold"] == 1.5
        assert cfg["confounds"]["acompcor"]["n_components"] == 6
    finally:
        yaml_path.unlink(missing_ok=True)


def test_cli_overrides_yaml_and_defaults():
    """Test that CLI overrides trump YAML and defaults."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(
            {
                "motion": {
                    "fd": {"threshold": 0.8},
                },
            },
            f,
        )
        yaml_path = Path(f.name)

    try:
        cfg = resolve_config(
            bids_root="/tmp/bids",
            out_dir="/tmp/out",
            yaml_path=yaml_path,
            cli_overrides={
                "motion": {
                    "fd": {"threshold": 1.2},  # Override YAML value
                },
            },
        )

        # CLI should override both YAML and defaults
        assert cfg["motion"]["fd"]["threshold"] == 1.2
    finally:
        yaml_path.unlink(missing_ok=True)


def test_precedence_order_full():
    """Test full precedence chain: defaults < YAML < CLI."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(
            {
                "motion": {
                    "fd": {"threshold": 0.7},
                    "dvars": {"threshold": 2.0},
                },
                "qc": {
                    "psnr": {"min": 25.0},
                },
            },
            f,
        )
        yaml_path = Path(f.name)

    try:
        cfg = resolve_config(
            bids_root="/tmp/bids",
            out_dir="/tmp/out",
            yaml_path=yaml_path,
            cli_overrides={
                "motion": {
                    "fd": {"threshold": 0.9},  # CLI wins
                },
            },
        )

        # CLI overrides YAML
        assert cfg["motion"]["fd"]["threshold"] == 0.9

        # YAML overrides defaults
        assert cfg["motion"]["dvars"]["threshold"] == 2.0
        assert cfg["qc"]["psnr"]["min"] == 25.0

        # Defaults remain for untouched values
        assert cfg["confounds"]["acompcor"]["n_components"] == 6
        assert cfg["registration"]["pam50"]["spacing"] == "0.5mm"
    finally:
        yaml_path.unlink(missing_ok=True)


def test_bids_root_and_output_dir_injection():
    """Test that bids_root and output_dir are injected from CLI args."""
    cfg = resolve_config(
        bids_root="/path/to/bids",
        out_dir="/path/to/out",
        yaml_path=None,
    )

    assert cfg["bids_root"] == "/path/to/bids"
    assert cfg["output_dir"] == "/path/to/out"


def test_config_validates_against_schema():
    """Test that resolved config is validated against JSON schema."""
    # Valid config should pass
    cfg = resolve_config(
        bids_root="/tmp/bids",
        out_dir="/tmp/out",
        yaml_path=None,
    )

    # Should not raise ValidationError
    assert cfg is not None

    # Invalid config should raise ValidationError
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(
            {
                "motion": {
                    "fd": {"threshold": "not_a_number"},  # Invalid type
                },
            },
            f,
        )
        yaml_path = Path(f.name)

    try:
        from jsonschema import ValidationError

        with pytest.raises(ValidationError):
            resolve_config(
                bids_root="/tmp/bids",
                out_dir="/tmp/out",
                yaml_path=yaml_path,
            )
    finally:
        yaml_path.unlink(missing_ok=True)


def test_deep_merge_preserves_nested_values():
    """Test that deep merge preserves nested values not being overridden."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(
            {
                "motion": {
                    "fd": {"threshold": 0.7},  # Override only fd.threshold
                    # dvars.threshold should remain from defaults
                },
            },
            f,
        )
        yaml_path = Path(f.name)

    try:
        cfg = resolve_config(
            bids_root="/tmp/bids",
            out_dir="/tmp/out",
            yaml_path=yaml_path,
        )

        # Overridden value
        assert cfg["motion"]["fd"]["threshold"] == 0.7

        # Default value should still be there
        assert cfg["motion"]["dvars"]["threshold"] == 1.5
    finally:
        yaml_path.unlink(missing_ok=True)
