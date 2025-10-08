from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
from typing import Any

from ._version import __version__

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _resolve_config(cli_args: argparse.Namespace) -> dict[str, Any]:
    # minimal merged config: defaults + optional YAML file + CLI overrides if any
    # keep simple for MVP tests
    cfg = {
        "pipeline_version": __version__,
        "paths": {
            "bids_dir": str(pathlib.Path(cli_args.bids).resolve()) if cli_args.bids else "",
            "deriv_dir": str(pathlib.Path(cli_args.out).resolve()) if cli_args.out else "",
            "logs_dir": "",  # may be templated in fixture; left blank if not resolved
        },
    }
    if cli_args.config:
        import yaml  # pinned in project deps

        with open(cli_args.config, encoding="utf-8") as f:
            y = yaml.safe_load(f) or {}
        # shallow merge for tests
        cfg = {**y, **cfg}
    return cfg


def cmd_version(_: argparse.Namespace) -> int:
    print(__version__)
    return 0


def _ensure_out_dirs(out_dir: pathlib.Path) -> None:
    (out_dir / "provenance").mkdir(parents=True, exist_ok=True)
    (out_dir / "logs" / "provenance").mkdir(parents=True, exist_ok=True)


def _export_dag_svg(dry_run: bool, out_dir: pathlib.Path) -> None:
    svg = out_dir / "provenance" / "dag.svg"
    env = os.environ.copy()
    # Ensure workflow modules importable
    env["PYTHONPATH"] = os.pathsep.join([str(REPO_ROOT), env.get("PYTHONPATH", "")])
    # Build snakemake --dag pipeline
    dag_cmd = [
        "snakemake",
        "-n" if dry_run else "-n",
        "--dag",
        "--cores",
        "1",
        "--snakefile",
        str(REPO_ROOT / "workflow" / "Snakefile"),
    ]
    # Get DAG output
    try:
        result = subprocess.run(
            dag_cmd,
            capture_output=True,
            text=True,
            check=True,
            env=env,
        )
        # Extract just the digraph portion (skip snakemake messages)
        lines = result.stdout.splitlines()
        dag_start = next((i for i, line in enumerate(lines) if line.startswith("digraph")), None)
        if dag_start is not None:
            dag_dot = "\n".join(lines[dag_start:])
            
            # Write directly to SVG using dot
            dot_proc = subprocess.run(
                ["dot", "-Tsvg"],
                input=dag_dot,
                capture_output=True,
                text=True,
                check=True,
            )
            
            svg.write_text(dot_proc.stdout)
    except (subprocess.CalledProcessError, StopIteration):
        # Silently skip DAG export if it fails (graceful degradation for MVP)
        pass


def cmd_run(args: argparse.Namespace) -> int:
    out_dir = pathlib.Path(args.out).resolve()
    _ensure_out_dirs(out_dir)

    if args.print_config:
        cfg = _resolve_config(args)
        # pretty YAML-ish output without bringing in heavy deps here
        import yaml

        print(yaml.safe_dump(cfg, sort_keys=False))
        # keep going, tests only require that it prints

    # Always try to export DAG in -n mode per ticket
    _export_dag_svg(dry_run=True, out_dir=out_dir)
    return 0


def cmd_doctor(_: argparse.Namespace) -> int:
    # stub that exits successfully; real checks in separate ticket
    print(json.dumps({"status": "green-stub"}, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        "spineprep", formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("version", help="Print version")
    v.set_defaults(func=cmd_version)

    d = sub.add_parser("doctor", help="Environment diagnostics (stub)")
    d.set_defaults(func=cmd_doctor)

    r = sub.add_parser("run", help="Run pipeline (MVP stub)")
    r.add_argument("--bids", required=False, default="")
    r.add_argument("--out", required=True)
    r.add_argument("--config", required=False, default=None)
    r.add_argument(
        "--print-config", action="store_true", help="Print resolved config and continue"
    )
    r.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Dry-run (accepted but currently always dry-runs)",
    )
    r.set_defaults(func=cmd_run)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
