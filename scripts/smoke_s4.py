#!/usr/bin/env python3
"""
S4 Smoke Test Script.
Executes S4_func_motion_correction on the first regression dataset.
"""

import sys
import subprocess
from pathlib import Path
import yaml
import shutil

# Add src to path for workfolder helper
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from spinalfmriprep.workfolder import get_next_workfolder

def main():
    project_root = Path(__file__).parent.parent
    
    # 1. Load datasets policy
    policy_path = project_root / "policy" / "datasets.yaml"
    if not policy_path.exists():
        print(f"Policy not found: {policy_path}", file=sys.stderr)
        return 1
        
    policy = yaml.safe_load(policy_path.read_text())
    
    # 2. Find first regression dataset
    dataset_key = None
    for ds in policy.get("datasets", []):
        if "regression" in ds.get("intended_use", []):
            dataset_key = ds["key"]
            break
            
    if not dataset_key:
        print("No regression dataset found in policy", file=sys.stderr)
        return 1
        
    print(f"Target Dataset: {dataset_key}")
    
    # 3. Setup smoke workfolder (incremental numbering)
    work_root = project_root / "work"
    wf = get_next_workfolder("smoke", work_root)
    wf.mkdir(parents=True)
    
    # 4. Check predecessors (S3)
    # Smoke usually runs locally, but depends on S3 outputs.
    # We can use S3 from 'reg' chain or just assume previous smoke left artifacts?
    # Better: Use 'work/done/reg/S3' as base if available, or 'work/done/smoke/S3'
    # The integration test mocked S3. Here we need real S3 output.
    # The user manual says: "Previous step done... work/done/{scope}/S{N-1}"
    # So we check work/done/smoke/S3
    
    s3_done = project_root / "work" / "done" / "smoke" / "S3"
    if not s3_done.exists():
        # Try regression chain S3?
        s3_done = project_root / "work" / "done" / "reg" / "S3"
        if not s3_done.exists():
             print("S3 output not found in smoke or reg chain. Run S3 smoke first.", file=sys.stderr)
             return 1
    
    print(f"Using S3 input from: {s3_done.resolve()}")
    
    # Link input logs/work from S3 to smoke folder?
    # spinalfmriprep usually expects input in 'work/S1...' or 'derivatives'.
    # If S3 is done, its outputs are in S3's workfolder.
    # We need to point S4 to that output?
    # spinalfmriprep CLI doesn't easily chain diff workfolders unless we init new WF with old data?
    # Actually, CLI usually takes `--out` and works within it.
    # But if S3 is in `wf_smoke_s3`, and we run S4 in `wf_smoke_s4`...
    # S4 needs S3 derivatives.
    # We can symlink S3 derivatives into `wf_smoke_s4/derivatives`?
    # Or just reuse S3 workfolder?
    # DEV_CYCLE says: "WF=$(python3 scripts/get_next_workfolder.py reg)" ... new folder.
    # spinalfmriprep likely resolves inputs via `layout` or `out` dir containing previous steps?
    # If we run with `--out wf_smoke_s4`, it looks for S3 in `wf_smoke_s4`.
    # So we MUST copy/symlink S3 outputs to `wf_smoke_s4`.
    
    print("Linking S3 outputs...")
    # S3 workfolder is real path of s3_done
    s3_wf = s3_done.resolve()
    
    # S4 reads from: out/runs/S3_func_init_and_crop/<run_name>/funccrop_bold.nii.gz
    # Link S3's runs directory into the S4 workfolder
    s3_runs_src = s3_wf / "runs" / "S3_func_init_and_crop"
    if not s3_runs_src.exists():
        print(f"ERROR: S3 runs directory not found: {s3_runs_src}", file=sys.stderr)
        return 1
    
    (wf / "runs").mkdir(parents=True, exist_ok=True)
    s4_runs_target = wf / "runs" / "S3_func_init_and_crop"
    if not s4_runs_target.exists():
        s4_runs_target.symlink_to(s3_runs_src)
    print(f"Linked S3 runs: {s3_runs_src} -> {s4_runs_target}")
    
    # Link previous logs for Dashboard (S1, S2, S3)
    # Check work/done/reg for S1, S2
    def link_logs_from(source_wf):
        src_logs = source_wf / "logs"
        if src_logs.exists():
            (wf / "logs").mkdir(parents=True, exist_ok=True)
            for item in src_logs.iterdir():
                target = wf / "logs" / item.name
                if not target.exists():
                    target.symlink_to(item)
            print(f"Linked logs from {src_logs}")

    # Try to link S1 logs
    s1_done = project_root / "work" / "done" / "reg" / "S1"
    if s1_done.exists():
        link_logs_from(s1_done.resolve())
        
    # Try to link S2 logs
    s2_done = project_root / "work" / "done" / "reg" / "S2"
    if s2_done.exists():
        link_logs_from(s2_done.resolve())

    # Link S3 logs (use the S3 source we identified)
    link_logs_from(s3_wf) # Typically implies S3 logs are here
    
    # 5. Run S4
    cmd = [
        "poetry", "run", "spinalfmriprep", "run", "S4_func_motion_correction",
        "--dataset-key", dataset_key,
        "--out", str(wf),
        "--datasets-local", str(project_root / "config" / "datasets_local.yaml")
    ]
    
    print(f"Executing: {' '.join(cmd)}")
    res = subprocess.run(cmd, cwd=project_root)
    
    if res.returncode != 0:
        print("S4 Failed", file=sys.stderr)
        return 1
        
    print("S4 Smoke Test Passed")
    print(f"Output: {wf}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
