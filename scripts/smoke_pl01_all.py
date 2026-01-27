#!/usr/bin/env python
"""
Smoke runner for S1_input_verify across v1_validation datasets.
Uses config/datasets_local.yaml for path resolution.
"""
from pathlib import Path
import subprocess
import sys
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = PROJECT_ROOT / "policy" / "datasets.yaml"
LOCAL_MAP = PROJECT_ROOT / "config" / "datasets_local.yaml"


def main():
    if not LOCAL_MAP.exists():
        print(f"Missing datasets_local mapping: {LOCAL_MAP}", file=sys.stderr)
        return 1
    with POLICY_PATH.open("r", encoding="utf-8") as f:
        policy = yaml.safe_load(f)
    keys = [ds["key"] for ds in policy.get("datasets", []) if "v1_validation" in ds.get("intended_use", [])]
    failures = []
    for key in keys:
        cmd = [
            "poetry",
            "run",
            "spinalfmriprep",
            "run",
            "S1_input_verify",
            "--dataset-key",
            key,
            "--datasets-local",
            str(LOCAL_MAP),
            "--out",
            str(PROJECT_ROOT),
        ]
        print("Running:", " ".join(cmd))
        result = subprocess.run(cmd, cwd=PROJECT_ROOT)
        if result.returncode != 0:
            failures.append(key)
    if failures:
        print("Smoke failures:", ", ".join(failures), file=sys.stderr)
        return 1
    print("Smoke S1 passed for:", ", ".join(keys))
    return 0


if __name__ == "__main__":
    sys.exit(main())
