from __future__ import annotations

import argparse
from pathlib import Path

from jsonschema import ValidationError

from .config import print_config, resolve_config
from .doctor import cmd_doctor


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser("spineprep")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("doctor", help="Check environment and dependencies")
    d.add_argument("--out", type=Path, default=Path("./out"))
    d.add_argument("--pam50", type=str, default=None)
    d.add_argument(
        "--bids-dir",
        type=Path,
        default=None,
        help="Optional BIDS directory to validate",
    )
    d.add_argument(
        "--json",
        type=str,
        default=None,
        help="Write JSON report to file or '-' for stdout",
    )
    d.add_argument("--strict", action="store_true")

    r = sub.add_parser("run", help="Resolve config and run pipeline (stub)")
    r.add_argument("--bids", dest="bids_root", type=str, default=None)
    r.add_argument("--out", dest="output_dir", type=str, default=None)
    r.add_argument("--config", type=Path, default=None, help="YAML config path")
    r.add_argument(
        "--print-config", action="store_true", help="Print resolved config and exit"
    )
    r.add_argument(
        "-n", "--dry-run", action="store_true", dest="dry_run", help="Dry-run mode"
    )
    r.add_argument(
        "--save-dag",
        type=Path,
        default=None,
        help="Export DAG to SVG or DOT file and exit",
    )

    sub.add_parser("version", help="Show version")
    return p


def main(argv=None) -> int:
    p = build_parser()
    a = p.parse_args(argv)
    if a.cmd == "doctor":
        # Handle --json argument: convert to Path unless it's "-"
        json_arg = None
        if a.json:
            json_arg = Path(a.json) if a.json != "-" else a.json
        bids_dir = getattr(a, "bids_dir", None)
        return cmd_doctor(a.out, a.pam50, json_arg, a.strict, bids_dir)
    if a.cmd == "run":
        try:
            cfg = resolve_config(a.bids_root, a.output_dir, a.config)
        except ValidationError as e:
            print(f"[config] ERROR: {e.message}")
            return 1
        if a.print_config:
            print(print_config(cfg))
            # Don't return yet if also dry-run

        # Handle dry-run: generate manifest, optionally export DAG
        if getattr(a, "dry_run", False):
            # First generate BIDS manifest if BIDS directory specified
            if a.bids_root:
                from spineprep.ingest import scan_bids_directory, write_manifest

                try:
                    bids_path = Path(a.bids_root)
                    print(f"[dry-run] Scanning BIDS directory: {bids_path}")

                    rows = scan_bids_directory(bids_path)

                    if rows:
                        # Determine output directory
                        if a.output_dir:
                            out_dir = Path(a.output_dir)
                        else:
                            out_dir = Path(cfg.get("output_dir", "./out"))

                        manifest_path = out_dir / "manifest.csv"
                        write_manifest(rows, manifest_path)
                        print(
                            f"[dry-run] Manifest written: {manifest_path} ({len(rows)} series)"
                        )
                    else:
                        print(
                            "[dry-run] Warning: No imaging files found in BIDS directory"
                        )
                        # Still write empty manifest
                        out_dir = (
                            Path(a.output_dir)
                            if a.output_dir
                            else Path(cfg.get("output_dir", "./out"))
                        )
                        manifest_path = out_dir / "manifest.csv"
                        write_manifest([], manifest_path)
                        print(f"[dry-run] Empty manifest written: {manifest_path}")

                except (FileNotFoundError, ValueError) as e:
                    print(f"[dry-run] ERROR: {e}")
                    return 1
            import os
            import subprocess as sp

            # Determine output directory from config
            # Handle both old-style (paths.deriv_dir) and new-style (output_dir)
            if "output_dir" in cfg:
                out_dir = Path(cfg["output_dir"])
            elif "paths" in cfg and "deriv_dir" in cfg["paths"]:
                out_dir = Path(cfg["paths"]["deriv_dir"])
            else:
                out_dir = Path("./out")

            prov_dir = out_dir / "derivatives" / "spineprep" / "logs" / "provenance"
            prov_dir.mkdir(parents=True, exist_ok=True)

            dag_svg = prov_dir / "dag.svg"
            env = os.environ.copy()
            repo_root = Path(__file__).resolve().parents[1]
            env["PYTHONPATH"] = os.pathsep.join(
                [str(repo_root), env.get("PYTHONPATH", "")]
            )

            try:
                dag_result = sp.run(
                    [
                        "snakemake",
                        "-n",
                        "--dag",
                        "--cores",
                        "1",
                        "--snakefile",
                        str(repo_root / "workflow" / "Snakefile"),
                    ],
                    capture_output=True,
                    text=True,
                    env=env,
                )
                # Extract digraph from output
                lines = dag_result.stdout.splitlines()
                dag_start = next(
                    (i for i, line in enumerate(lines) if line.startswith("digraph")),
                    None,
                )
                if dag_start is not None:
                    dag_dot = "\n".join(lines[dag_start:])
                    dot_proc = sp.run(
                        ["dot", "-Tsvg"],
                        input=dag_dot,
                        capture_output=True,
                        text=True,
                        check=True,
                    )
                    dag_svg.write_text(dot_proc.stdout)
                    print(f"[dry-run] DAG exported to {dag_svg}")
            except Exception as e:
                print(f"[dry-run] Warning: Could not export DAG: {e}")

            if a.print_config:
                return 0  # Already printed config above

            print("[dry-run] Pipeline check complete")
            return 0

        # Handle actual workflow execution
        if not a.bids_root or not a.output_dir:
            print("[run] ERROR: --bids and --out are required for workflow execution")
            return 1

        from spineprep.ingest import scan_bids_directory, write_manifest
        from spineprep.workflow.runner import run_workflow

        bids_path = Path(a.bids_root)
        out_path = Path(a.output_dir)

        # Ensure manifest exists
        manifest_path = out_path / "manifest.csv"
        if not manifest_path.exists():
            print(f"[run] Generating manifest from {bids_path}")
            try:
                rows = scan_bids_directory(bids_path)
                write_manifest(rows, manifest_path)
                print(f"[run] Manifest written: {manifest_path} ({len(rows)} series)")
            except (FileNotFoundError, ValueError) as e:
                print(f"[run] ERROR: {e}")
                return 1

        # Handle --save-dag
        if getattr(a, "save_dag", None):
            print(f"[run] Exporting DAG to {a.save_dag}")
            return run_workflow(
                bids_path, out_path, manifest_path, cores=1, export_dag=a.save_dag
            )

        # Execute workflow
        print("[run] Executing minimal workflow")
        print(f"[run] BIDS: {bids_path}")
        print(f"[run] Output: {out_path}")
        print(f"[run] Manifest: {manifest_path}")

        return run_workflow(bids_path, out_path, manifest_path, cores=1)
    if a.cmd == "version":
        from importlib.metadata import PackageNotFoundError, version

        try:
            print(f"spineprep {version('spineprep')}")
        except PackageNotFoundError:
            print("spineprep 0.0.0")
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
