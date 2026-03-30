
import json
import os
from pathlib import Path

work_dir = Path("/mnt/ssd1/SpinalfMRIprep/work/wf_reg_033")
logs_dir = work_dir / "logs"

print(f"Checking logs in: {logs_dir}")

for step_dir in logs_dir.glob("S*"):
    if not step_dir.is_dir(): continue
    print(f"\nScanning Step: {step_dir.name}")
    
    # Check for qc.json files (recursively or flat?)
    # Usually structure is logs/STEP/dataset/qc.json OR logs/STEP/qc.json (agg)
    # spinalfmriprep puts per-run qc.json in subdirectories?
    
    qc_files = list(step_dir.glob("**/qc.json"))
    if not qc_files:
        print(f"  No qc.json found in {step_dir}")
        continue
        
    for qc_file in qc_files:
        try:
            with open(qc_file) as f:
                data = json.load(f)
            
            # Check reportlets
            if "runs" in data:
                # Aggregate/Dataset qc.json
                for run in data["runs"]:
                    reportlets = run.get("reportlets", {})
                    run_id = run.get("run_id", "unknown")
                    if not reportlets:
                        print(f"  Run {run_id}: No reportlets")
                        continue
                        
                    for key, rel_path in reportlets.items():
                        # Path relative to work_dir?
                        full_path = work_dir / rel_path
                        if not full_path.exists():
                            print(f"  [MISSING] {key}: {rel_path}")
                            # Check if it exists relative to the qc_file? NO, standard is work root.
                        else:
                            print(f"  [OK] {key}")
            elif "reportlets" in data:
                # Per-run qc.json
                # (S4 output might be this format?)
                reportlets = data["reportlets"]
                for key, rel_path in reportlets.items():
                    full_path = work_dir / rel_path
                    if not full_path.exists():
                        print(f"  [MISSING] {key}: {rel_path}")
                    else:
                        print(f"  [OK] {key}")
                        
        except Exception as e:
            print(f"  Error reading {qc_file}: {e}")
