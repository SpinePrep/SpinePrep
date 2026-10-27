"""A preset that turns on an optional step must find that step's tool in the container.

The clean-room run of 2026-10-26 built the image from the README, selected the cospi preset (S2B MP-PCA on)
and stopped at S2B with "Command not found: dwidenoise": the image had no MRtrix3.
"""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
# step policy file -> (key path that turns the step on, executable the step then needs)
OPTIONAL_TOOLS = {
    "S2B_func_denoise.yaml": (("enabled",), "dwidenoise"),
}


def _get(d, keys):
    for k in keys:
        d = (d or {}).get(k)
    return d


def test_every_tool_a_preset_needs_is_installed_in_the_container():
    dockerfile = (ROOT / "Dockerfile.spineprep").read_text()
    presets = sorted(p for p in (ROOT / "policy" / "presets").iterdir() if p.is_dir())
    assert presets, "no presets found"
    for preset in presets:
        for policy_file, (keys, tool) in OPTIONAL_TOOLS.items():
            over = preset / policy_file
            if over.exists() and _get(yaml.safe_load(over.read_text()), keys):
                assert tool in dockerfile, f"preset {preset.name} turns on {policy_file} but the image lacks {tool}"
