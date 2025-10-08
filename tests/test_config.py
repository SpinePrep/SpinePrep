from __future__ import annotations
import yaml
from pathlib import Path
import pytest
from spineprep.config import resolve_config, print_config
from jsonschema import ValidationError

def test_valid_defaults(tmp_path: Path):
    cfg = resolve_config(None, None, None)
    assert "pipeline" in cfg and "registration" in cfg

def test_yaml_overrides(tmp_path: Path):
    y = tmp_path/"cfg.yaml"
    y.write_text("output_dir: './custom'\nconfounds:\n  acompcor:\n    n_components: 8\n")
    cfg = resolve_config(None, None, y)
    assert cfg["output_dir"] == "./custom"
    assert cfg["confounds"]["acompcor"]["n_components"] == 8

def test_cli_precedence_over_yaml(tmp_path: Path):
    y = tmp_path/"cfg.yaml"
    y.write_text("output_dir: './yaml_out'\n")
    cfg = resolve_config(None, "./cli_out", y)
    assert cfg["output_dir"] == "./cli_out"

def test_schema_validation_error(tmp_path: Path):
    y = tmp_path/"bad.yaml"
    y.write_text("confounds:\n  acompcor:\n    n_components: 0\n")  # invalid: min 1
    with pytest.raises(ValidationError):
        resolve_config(None, None, y)

def test_print_config_roundtrip():
    cfg = resolve_config("/bids", "./out", None)
    dumped = print_config(cfg)
    reloaded = yaml.safe_load(dumped)
    assert reloaded["output_dir"] == "./out"

