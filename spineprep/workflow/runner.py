"""Snakemake workflow runner."""

from __future__ import annotations

import subprocess
from pathlib import Path


def run_workflow(
    bids_dir: Path,
    out_dir: Path,
    manifest_csv: Path,
    cores: int = 1,
    dry_run: bool = False,
    export_dag: Path | None = None,
) -> int:
    """
    Execute Snakemake workflow.

    Args:
        bids_dir: Path to BIDS directory
        out_dir: Path to output directory
        manifest_csv: Path to manifest CSV
        cores: Number of cores to use
        dry_run: If True, dry-run only (no execution)
        export_dag: If provided, export DAG to this path

    Returns:
        Exit code from Snakemake
    """
    # Find Snakefile
    repo_root = Path(__file__).resolve().parents[2]
    snakefile = repo_root / "workflow" / "Snakefile"

    if not snakefile.exists():
        print(f"ERROR: Snakefile not found at {snakefile}")
        return 1

    # Build Snakemake command
    cmd = [
        "snakemake",
        "--snakefile",
        str(snakefile),
        "--cores",
        str(cores),
        "--config",
        f"bids_dir={bids_dir}",
        f"out_dir={out_dir}",
        f"manifest_csv={manifest_csv}",
    ]

    # Handle DAG export
    if export_dag:
        cmd.extend(["--dag"])

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
            )

            # Parse DAG from output
            dag_dot = result.stdout

            # Write DAG based on extension
            if export_dag.suffix == ".svg":
                # Convert to SVG using graphviz
                dot_proc = subprocess.run(
                    ["dot", "-Tsvg"],
                    input=dag_dot,
                    capture_output=True,
                    text=True,
                    check=True,
                )
                export_dag.write_text(dot_proc.stdout)
                print(f"[dag] Exported to {export_dag}")
            else:
                # Write .dot format
                export_dag.write_text(dag_dot)
                print(f"[dag] Exported to {export_dag}")

            return 0

        except subprocess.CalledProcessError as e:
            print(f"ERROR: DAG export failed: {e.stderr}")
            return 1
        except FileNotFoundError as e:
            print(f"ERROR: {e} (graphviz 'dot' not found)")
            return 1

    # Handle dry-run
    if dry_run:
        cmd.append("-n")

    # Execute Snakemake
    try:
        result = subprocess.run(cmd, check=False)
        return result.returncode
    except FileNotFoundError:
        print("ERROR: snakemake command not found. Install with: pip install snakemake")
        return 1
