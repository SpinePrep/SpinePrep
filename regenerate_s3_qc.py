#!/usr/bin/env python3
import sys
import json
from pathlib import Path
import yaml

# Add source to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from spineprep.S3_func_init_and_crop import _summarise_s3_runs

def regenerate_s3_qc(dataset_out_dir: Path):
    print(f"Processing {dataset_out_dir}")
    runs_path = dataset_out_dir / "logs" / "S3_func_init_and_crop_runs.jsonl"
    qc_path = dataset_out_dir / "logs" / "S3_func_init_and_crop_qc.json"
    inventory_path = dataset_out_dir / "work" / "S1_input_verify" / "bids_inventory.json"
    
    if not runs_path.exists():
        print(f"  No runs log found at {runs_path}")
        return

    if not inventory_path.exists():
        print(f"  No inventory found at {inventory_path}")
        return

    try:
        inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
        runs = []
        with open(runs_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                     runs.append(json.loads(line))
                     
        policy = {} # Not using policy for summary content much
        
        # Regenerate summary
        qc_summary = _summarise_s3_runs(inventory, policy, runs, out_path=dataset_out_dir)
        
        # Write back
        with qc_path.open("w", encoding="utf-8") as f:
            json.dump(qc_summary, f, indent=2)
            
        print(f"  Updated {qc_path}")
        
    except Exception as e:
        print(f"  Failed: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: regenerate_s3_qc.py <dataset_out_dir> [dataset_out_dir2 ...]")
        sys.exit(1)
        
    for arg in sys.argv[1:]:
        regenerate_s3_qc(Path(arg))
