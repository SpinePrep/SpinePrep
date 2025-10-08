from __future__ import annotations

import argparse
from pathlib import Path

from jsonschema import ValidationError

from .config import print_config, resolve_config
from .confounds import process as confounds_process
from .doctor import cmd_doctor
from .ingest import ingest
from .motion import process_from_manifest


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser("spineprep")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("doctor", help="Check environment and dependencies")
    d.add_argument("--out", type=Path, default=Path("./out"))
    d.add_argument("--pam50", type=str, default=None)
    d.add_argument("--json", type=Path, default=None)
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

    sub.add_parser("version", help="Show version")
    return p


def main(argv=None) -> int:
    p = build_parser()
    a = p.parse_args(argv)
    if a.cmd == "doctor":
        return cmd_doctor(a.out, a.pam50, a.json, a.strict)
    if a.cmd == "run":
        try:
            cfg = resolve_config(a.bids_root, a.output_dir, a.config)
        except ValidationError as e:
            print(f"[config] ERROR: {e.message}")
            return 1
        if a.print_config:
            print(print_config(cfg))
            # Don't return yet if also dry-run

        # Handle dry-run (export DAG only)
        if getattr(a, "dry_run", False):
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

        # Run ingest (non-dry-run)
        out_dir = Path(cfg["output_dir"])
        stats = ingest(Path(cfg["bids_root"]), out_dir, hash_large=False)
        print(
            f"[ingest] {stats['total']} files indexed ({stats['func']} func, {stats['anat']} anat, {stats['other']} other) → {stats['manifest']}"
        )

        # Run motion processing
        manifest_path = out_dir / "manifest.csv"
        motion_stats = process_from_manifest(manifest_path, out_dir)
        print(
            f"[motion] {motion_stats['processed']} runs processed → confounds TSVs and plots"
        )

        # Run confounds processing
        confounds_stats = confounds_process(manifest_path, out_dir, cfg)
        print(
            f"[confounds] {confounds_stats['runs']} runs updated, {confounds_stats['skipped']} skipped, "
            f"{confounds_stats['censored']} frames censored total"
        )

        print("[run] config resolved ✓")
        return 0
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
