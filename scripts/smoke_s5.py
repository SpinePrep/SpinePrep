#!/usr/bin/env python3
"""
S5 Smoke Test Script.
Executes S5_func_distortion_correction on the first regression dataset
that has reversed-phase EPI fmaps (so topup mode actually exercises).
"""

import subprocess
import sys
from pathlib import Path

import yaml

# Add src to path for workfolder helper
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from spineprep.workfolder import get_next_workfolder


def main():
    project_root = Path(__file__).parent.parent

    # 1. Load datasets policy
    policy_path = project_root / "policy" / "datasets.yaml"
    if not policy_path.exists():
        print(f"Policy not found: {policy_path}", file=sys.stderr)
        return 1
    policy = yaml.safe_load(policy_path.read_text())

    # 2. Pick first regression dataset that has reversed-phase EPI fmaps
    # so we exercise the topup branch (not the syn fallback).
    s1_done = project_root / "work" / "done" / "reg" / "S1"
    if not s1_done.exists():
        print("work/done/reg/S1 missing - run S1 smoke/reg first", file=sys.stderr)
        return 1
    s1_work_root = s1_done.resolve() / "work" / "S1_input_verify"

    dataset_key = None
    for ds in policy.get("datasets", []):
        if "regression" not in ds.get("intended_use", []):
            continue
        inv = s1_work_root / ds["key"] / "bids_inventory.json"
        if not inv.exists():
            continue
        try:
            import json
            d = json.loads(inv.read_text())
        except Exception:
            continue
        fmap_runs = [r for r in d.get("runs", []) if r.get("modality") == "fmap"]
        pe_dirs = set()
        for f in fmap_runs:
            if f.get("path", "").endswith(("_epi.nii.gz", "_epi.nii")):
                pe = f.get("acquisition", {}).get("PhaseEncodingDirection")
                if pe:
                    pe_dirs.add(pe)
        # Need at least one opposite-PE pair (any axis)
        axes = {p.rstrip("-"): set() for p in pe_dirs}
        for p in pe_dirs:
            axes[p.rstrip("-")].add(p)
        if any(len(s) >= 2 for s in axes.values()):
            dataset_key = ds["key"]
            break

    if not dataset_key:
        # Fall back to first regression dataset (will exercise SyN mode)
        for ds in policy.get("datasets", []):
            if "regression" in ds.get("intended_use", []):
                dataset_key = ds["key"]; break

    if not dataset_key:
        print("No regression dataset found in policy", file=sys.stderr)
        return 1

    print(f"Target dataset: {dataset_key}")

    # 3. Allocate new smoke workfolder
    work_root = project_root / "work"
    wf = get_next_workfolder("smoke", work_root)
    wf.mkdir(parents=True)
    print(f"New workfolder: {wf}")

    # 4. Locate predecessor: S5 needs S4 outputs (mocoref BOLD) + S1 inventory
    s4_done = project_root / "work" / "done" / "smoke" / "S4"
    if not s4_done.exists():
        s4_done = project_root / "work" / "done" / "reg" / "S4"
        if not s4_done.exists():
            print("S4 output not found in smoke or reg chain", file=sys.stderr)
            return 1
    s4_wf = s4_done.resolve()
    print(f"Using S4 input from: {s4_wf}")

    # 5. Link the necessary inputs into the new workfolder
    # S5 reads:
    #   logs/S1_input_verify/.../bids_inventory.json (chain)
    #   logs/S4_func_motion_correction/<ds>/qc.json
    #   derivatives/spineprep/sub-XX/[ses-YY/]func/*_desc-mocoref_bold.nii.gz
    #   derivatives/spineprep/sub-XX/[ses-YY/]anat/*.nii.gz
    # plus the S1 work/ tree for bids_inventory.

    def link_tree(source_wf: Path, sub: str):
        src = source_wf / sub
        if not src.exists():
            return
        dst = wf / sub
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.exists() and not dst.is_symlink():
            dst.symlink_to(src)
            print(f"  linked {sub} <- {src}")

    # logs chain (S1 + S2 + S3 + S4 outputs that S5 + dashboard will read)
    def link_logs_from(source_wf: Path):
        src_logs = source_wf / "logs"
        if not src_logs.exists():
            return
        (wf / "logs").mkdir(parents=True, exist_ok=True)
        for item in src_logs.iterdir():
            target = wf / "logs" / item.name
            if not target.exists() and not target.is_symlink():
                target.symlink_to(item)
        print(f"  linked logs from {src_logs}")

    for k in ("S1", "S2", "S3", "S4"):
        d = (project_root / "work" / "done" / "reg" / k)
        if d.exists():
            link_logs_from(d.resolve())

    # S1 work tree (bids_inventory.json) needed for fmap PE metadata
    link_tree(s1_done.resolve(), "work")
    # S4 derivatives (the mocoref_bold inputs)
    link_tree(s4_wf, "derivatives")

    # 6. Run S5
    cmd = [
        "poetry", "run", "spineprep", "run", "S5_func_distortion_correction",
        "--dataset-key", dataset_key,
        "--out", str(wf),
        "--datasets-local", str(project_root / "config" / "datasets_local.yaml"),
    ]
    print(f"Executing: {' '.join(cmd)}")
    res = subprocess.run(cmd, cwd=project_root)
    if res.returncode != 0:
        print("S5 smoke FAILED", file=sys.stderr)
        return 1

    print("\nS5 smoke PASSED")
    print(f"Output: {wf}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
