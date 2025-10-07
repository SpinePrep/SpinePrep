from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from spineprep.config import load_config

DESCRIPTION = "CLI utilities for the SpinePrep workflow."


def which(cmd: str) -> Optional[str]:
    return shutil.which(cmd)


def run_cmd_get_version(cmd: list[str]) -> str:
    try:
        out = subprocess.check_output(
            cmd, stderr=subprocess.STDOUT, text=True, timeout=10
        )
        return out.strip().splitlines()[0]
    except Exception:
        return "version unavailable"


def cmd_doctor(_: argparse.Namespace) -> int:
    checks = [
        ("Spinal Cord Toolbox", "sct_deepseg_sc", ["sct_deepseg_sc", "-h"]),
        ("FSL", "fslmaths", ["fslmaths", "-version"]),
        ("ANTs", "antsRegistration", ["antsRegistration", "--version"]),
        ("dcm2niix", "dcm2niix", ["dcm2niix", "-v"]),
    ]
    ok = True
    for label, exe, ver_cmd in checks:
        path = which(exe)
        if path:
            v = run_cmd_get_version(ver_cmd)
            extra = ""
            if label == "FSL" and os.environ.get("FSLDIR"):
                extra = f"; FSLDIR={os.environ['FSLDIR']}"
            print(f"[OK] {label}: {path} ({v}){extra}")
        else:
            print(f"[MISSING] {label}: install and ensure `{exe}` is in PATH.")
            ok = False
    return 0 if ok else 2


def cmd_validate(ns: argparse.Namespace) -> int:
    schema = ns.schema
    try:
        _ = load_config(ns.config, schema)
        print("Configuration is valid.")
        return 0
    except Exception as e:
        print(f"Schema/Config validation failed: {e}")
        return 1


def cmd_plan(ns: argparse.Namespace) -> int:
    try:
        cfg = load_config(ns.config, ns.schema)
    except Exception as e:
        print(f"Config error: {e}")
        return 1

    bids_dir = cfg["paths"]["bids_dir"]
    try:
        from spineprep.adapters.bids import discover  # packaged adapter
    except Exception as e:
        print(f"Import error (spineprep.adapters.bids): {e}")
        return 1

    task = getattr(ns, "task", None)
    summary = discover(bids_dir, task=task)
    counts = summary.get("counts", {})
    opts = cfg.get("options", {})
    print("=== SpinePrep plan ===")
    print(f"Study: {cfg.get('study', {}).get('name', 'Unnamed')}")
    print(f"BIDS:  {bids_dir}")
    print(
        f"Subs:  {counts.get('subjects', 0)} | Sessions: {counts.get('sessions', 0)} | Runs: {counts.get('runs', 0)}"
    )
    print(
        f"MP-PCA: {opts.get('denoise_mppca', False)} | Smoothing: {opts.get('smoothing', {}).get('enable', False)} "
        f"| SDC: {opts.get('sdc', {}).get('mode', 'auto')}"
    )
    print(f"First-level engine: {opts.get('first_level', {}).get('engine', 'feat')}")
    return 0


def cmd_run(ns: argparse.Namespace) -> int:
    try:
        cfg = load_config(ns.config, ns.schema)
    except Exception as e:
        print(f"Config error: {e}")
        return 1

    snakefile = Path("workflow/Snakefile")
    if not snakefile.exists():
        print("workflow/Snakefile not found. Add it before running the workflow.")
        return 2

    cores = (
        int(ns.jobs) if ns.jobs else cfg.get("resources", {}).get("default_threads", 8)
    )
    profile = ns.profile or "local"
    cmd = [
        "snakemake",
        "--snakefile",
        str(snakefile),
        "--cores",
        str(cores),
        "--profile",
        profile,
    ]
    print("Running:", " ".join(cmd))
    try:
        return subprocess.call(cmd)
    except FileNotFoundError:
        print("snakemake not found in PATH. Install it: pip install snakemake")
        return 2


def cmd_qc(ns: argparse.Namespace) -> int:
    out = Path(ns.out).with_suffix(".html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("<html><body><h1>SpinePrep QC</h1><p>Stub report.</p></body></html>")
    print(f"Wrote {out}")
    return 0


def cmd_clean(ns: argparse.Namespace) -> int:
    stage = ns.stage or "run"
    print(f"[noop] Would clean stage: {stage}")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser("spineprep", description=DESCRIPTION)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("doctor", help="Verify external dependencies.")
    s.set_defaults(func=cmd_doctor)

    s = sub.add_parser("validate", help="Validate a configuration file.")
    s.add_argument("--config", required=True)
    s.add_argument("--schema")
    s.set_defaults(func=cmd_validate)

    s = sub.add_parser("plan", help="Summarize planned workflow inputs.")
    s.add_argument("--config", required=True)
    s.add_argument("--schema")
    s.add_argument("--task", help="Filter for a specific task label.", default=None)
    s.set_defaults(func=cmd_plan)

    s = sub.add_parser("run", help="Execute the Snakemake workflow.")
    s.add_argument("--config", required=True)
    s.add_argument("--schema")
    s.add_argument("--profile", default=None)
    s.add_argument("--jobs", default=None)
    s.set_defaults(func=cmd_run)

    s = sub.add_parser("qc", help="Generate a QC HTML stub.")
    s.add_argument("--config", required=True)
    s.add_argument("--schema")
    s.add_argument("--out", default="qc_subject")
    s.set_defaults(func=cmd_qc)

    s = sub.add_parser("clean", help="Clean workflow outputs.")
    s.add_argument("--config", required=False)
    s.add_argument("--stage", choices=["run", "sub", "group"], default="run")
    s.set_defaults(func=cmd_clean)

    args = p.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
