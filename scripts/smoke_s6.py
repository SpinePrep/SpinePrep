#!/usr/bin/env python3
"""
S6 Smoke Test Script.

Pick the first regression dataset that has an S5 PASS/WARN result on the
chain. Allocate a smoke workfolder, link S1-S5 predecessors via symlinks,
run S6, validate qc.json against the schema.
"""

import json
import subprocess
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from spineprep.workfolder import get_next_workfolder


def main():
    project_root = Path(__file__).parent.parent
    policy_path = project_root / "policy" / "datasets.yaml"
    if not policy_path.exists():
        print(f"Policy not found: {policy_path}", file=sys.stderr)
        return 1
    policy = yaml.safe_load(policy_path.read_text())

    s5_done = project_root / "work" / "done" / "reg" / "S5"
    if not s5_done.exists():
        print("work/done/reg/S5 missing - run S5 smoke/reg first", file=sys.stderr)
        return 1
    s5_wf = s5_done.resolve()

    # Pick first regression dataset with a S5 qc.json showing PASS/WARN runs
    dataset_key = None
    for ds in policy.get("datasets", []):
        if "regression" not in ds.get("intended_use", []):
            continue
        qc = (s5_wf / "logs" / "S5_func_distortion_correction" / ds["key"]
              / "qc.json")
        if not qc.exists():
            continue
        try:
            q = json.loads(qc.read_text())
        except Exception:
            continue
        if any(r.get("status") in ("PASS", "WARN") for r in q.get("runs", [])):
            dataset_key = ds["key"]
            break
    if not dataset_key:
        print("No regression dataset with PASS/WARN S5 runs", file=sys.stderr)
        return 1
    print(f"Target dataset: {dataset_key}")

    # Allocate smoke workfolder
    work_root = project_root / "work"
    wf = get_next_workfolder("smoke", work_root)
    wf.mkdir(parents=True)
    print(f"New workfolder: {wf}")

    # Link S1-S5 logs + S1 work tree + S5 derivatives + S3 runs (for funccrop_mask)
    def link_logs_from(src_wf: Path):
        src = src_wf / "logs"
        if not src.exists():
            return
        (wf / "logs").mkdir(parents=True, exist_ok=True)
        for item in src.iterdir():
            t = wf / "logs" / item.name
            if not t.exists() and not t.is_symlink():
                t.symlink_to(item)
        print(f"  linked logs from {src.parent}")

    for k in ("S1", "S2", "S3", "S4", "S5"):
        d = project_root / "work" / "done" / "reg" / k
        if d.exists():
            link_logs_from(d.resolve())

    s1_wf = (project_root / "work" / "done" / "reg" / "S1").resolve()
    s3_wf = (project_root / "work" / "done" / "reg" / "S3").resolve()
    s5_wf_resolved = (project_root / "work" / "done" / "reg" / "S5").resolve()

    (wf / "work").symlink_to(s1_wf / "work")
    (wf / "derivatives").symlink_to(s5_wf_resolved / "derivatives")
    # Provide chain access to S3 funccrop_mask via the project-level done dir
    # (S6 already looks there via its fallback chain)
    print(f"  linked work <- {s1_wf}/work")
    print(f"  linked derivatives <- {s5_wf_resolved}/derivatives")

    # Run S6
    cmd = [
        "poetry", "run", "spineprep", "run",
        "S6_func_to_anat_registration",
        "--dataset-key", dataset_key,
        "--out", str(wf),
        "--datasets-local", str(project_root / "config" / "datasets_local.yaml"),
    ]
    print(f"Executing: {' '.join(cmd)}")
    res = subprocess.run(cmd, cwd=project_root)
    if res.returncode != 0:
        print("S6 smoke FAILED", file=sys.stderr)
        return 1

    # Schema validation
    qc_path = (wf / "logs" / "S6_func_to_anat_registration" / dataset_key
               / "qc.json")
    if not qc_path.exists():
        print(f"qc.json missing at {qc_path}", file=sys.stderr)
        return 1
    schema_path = project_root / "schemas" / "qc_S6_func_to_anat_registration.schema.json"
    if schema_path.exists():
        from jsonschema import Draft7Validator
        schema = json.loads(schema_path.read_text())
        v = Draft7Validator(schema)
        d = json.loads(qc_path.read_text())
        errors = list(v.iter_errors(d))
        if errors:
            print(f"Schema validation: {len(errors)} errors", file=sys.stderr)
            for e in errors[:5]:
                print(f"  - {e.message[:160]}", file=sys.stderr)
            return 1
        print("Schema validation: PASS")

    q = json.loads(qc_path.read_text())
    print(f"\nS6 smoke status: {q.get('status')}")
    for r in q.get("runs", []):
        m = r.get("metrics", {})
        print(f"  {r.get('run_id'):50s} {r.get('status'):5s}  "
              f"dice={m.get('cord_dice')}  hd95={m.get('cord_hd95_mm')}  "
              f"rt_med={m.get('centerline_round_trip_med_vox')}")
    print(f"\nS6 smoke PASSED. Output: {wf}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
