"""Quality control and reporting utilities for SpinePrep."""

from __future__ import annotations

import csv
import statistics as stats
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import matplotlib

matplotlib.use("Agg")  # Use non-interactive backend
import matplotlib.pyplot as plt
from jinja2 import Environment, FileSystemLoader


def subjects_from_manifest(manifest_tsv: str) -> List[str]:
    """Extract unique subject IDs from manifest_deriv.tsv."""
    subjects = set()
    with open(manifest_tsv, "r", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            subjects.add(row["sub"])
    return sorted(list(subjects))


def rows_for_subject(manifest_tsv: str, sub: str) -> List[dict]:
    """Get all rows for a specific subject from manifest_deriv.tsv."""
    rows = []
    with open(manifest_tsv, "r", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            if row["sub"] == sub:
                rows.append(row)
    return rows


def read_confounds_tsv(tsv: str) -> Dict[str, List[float]]:
    """Read confounds TSV and return as dict of column_name -> list of values."""
    confounds = {}
    with open(tsv, "r", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            for col, val in row.items():
                if col not in confounds:
                    confounds[col] = []
                try:
                    confounds[col].append(float(val))
                except (ValueError, TypeError):
                    # Skip non-numeric values
                    pass
    return confounds


def compute_fd(conf: Dict[str, List[float]]) -> List[float]:
    """Compute Framewise Displacement (Power) from motion parameters."""
    if "framewise_displacement" in conf:
        return conf["framewise_displacement"]

    # Fallback: compute FD from motion parameters
    trans_cols = ["trans_x", "trans_y", "trans_z"]
    rot_cols = ["rot_x", "rot_y", "rot_z"]

    if not all(col in conf for col in trans_cols + rot_cols):
        return [0.0] * max(len(conf.get(col, [])) for col in trans_cols + rot_cols)

    n_vols = len(conf["trans_x"])
    fd = [0.0]  # First volume has FD = 0

    for i in range(1, n_vols):
        # Translation differences
        trans_diff = sum((conf[col][i] - conf[col][i - 1]) ** 2 for col in trans_cols)
        # Rotation differences (convert to mm using 50mm radius)
        rot_diff = sum((conf[col][i] - conf[col][i - 1]) ** 2 for col in rot_cols) * (
            50.0**2
        )  # 50mm radius assumption

        fd.append((trans_diff + rot_diff) ** 0.5)

    return fd


def compute_dvars(conf: Dict[str, List[float]]) -> List[float]:
    """Compute DVARS from confounds data."""
    if "dvars" in conf:
        return conf["dvars"]

    # Fallback: return zeros if DVARS not available
    n_vols = max(len(conf.get(col, [])) for col in conf.keys()) if conf else 1
    return [0.0] * n_vols


def plot_series(out_png: str, series: List[float], title: str, ylabel: str) -> None:
    """Create a time series plot and save as PNG."""
    plt.figure(figsize=(10, 4))
    plt.plot(series, linewidth=0.8)
    plt.title(title, fontsize=12)
    plt.xlabel("Volume", fontsize=10)
    plt.ylabel(ylabel, fontsize=10)
    plt.grid(True, alpha=0.3)
    plt.tight_layout()

    # Ensure output directory exists
    Path(out_png).parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_png, dpi=100, bbox_inches="tight")
    plt.close()


def module_decisions(cfg: dict) -> Dict[str, str]:
    """Extract module decisions from config."""
    opts = cfg.get("options", {})
    return {
        "MP-PCA": "enabled" if opts.get("denoise_mppca", False) else "disabled",
        "Smoothing": (
            "enabled" if opts.get("smoothing", {}).get("enable", False) else "disabled"
        ),
        "SDC": opts.get("sdc", {}).get("mode", "auto"),
        "First-level": opts.get("first_level", {}).get("engine", "feat"),
    }


def collect_provenance(entries: List[dict]) -> List[str]:
    """Collect provenance file paths from manifest entries."""
    prov_paths = []
    for entry in entries:
        # Look for .prov.json files next to the confounds files
        confounds_tsv = entry.get("deriv_confounds_tsv", "")
        if confounds_tsv:
            prov_path = confounds_tsv.replace(".tsv", ".tsv.prov.json")
            if Path(prov_path).exists():
                prov_paths.append(prov_path)
    return prov_paths


def render_subject_report(
    sub: str, manifest_tsv: str, cfg: dict, deriv_root: str
) -> str:
    """
    Generate HTML report for a subject.

    Returns:
        Path to the generated HTML report
    """
    # Get subject data
    subject_rows = rows_for_subject(manifest_tsv, sub)
    if not subject_rows:
        raise ValueError(f"No data found for subject {sub}")

    # Create output directories
    deriv_path = Path(deriv_root)
    figures_dir = deriv_path / sub / "figures"
    reports_dir = deriv_path / sub / "reports"
    figures_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    # Process each run
    run_summaries = []
    all_fd_plots = []
    all_dvars_plots = []

    for i, row in enumerate(subject_rows):
        run_id = row["run"]
        task = row.get("task", "")

        # Read confounds
        confounds_tsv = row["deriv_confounds_tsv"]
        confounds_json = row["deriv_confounds_json"]

        if not Path(confounds_tsv).exists():
            continue

        conf = read_confounds_tsv(confounds_tsv)
        fd = compute_fd(conf)
        dvars = compute_dvars(conf)

        # Compute summary stats
        n_vols = len(fd)
        mean_fd = stats.mean(fd) if fd else 0.0
        mean_dvars = stats.mean(dvars) if dvars else 0.0

        # Create plots
        fd_plot = figures_dir / f"{sub}_run-{run_id}_fd.png"
        dvars_plot = figures_dir / f"{sub}_run-{run_id}_dvars.png"

        plot_series(str(fd_plot), fd, f"{sub} run-{run_id} FD", "FD (mm)")
        plot_series(str(dvars_plot), dvars, f"{sub} run-{run_id} DVARS", "DVARS")

        all_fd_plots.append(fd_plot.name)
        all_dvars_plots.append(dvars_plot.name)

        run_summaries.append(
            {
                "run": run_id,
                "task": task,
                "n_vols": n_vols,
                "mean_fd": round(mean_fd, 3),
                "mean_dvars": round(mean_dvars, 3),
                "confounds_tsv": confounds_tsv,
                "confounds_json": confounds_json,
                "fd_plot": fd_plot.name,
                "dvars_plot": dvars_plot.name,
            }
        )

    # Collect provenance files
    prov_files = collect_provenance(subject_rows)

    # Generate methods boilerplate
    methods = generate_methods_boilerplate(cfg, sub, len(subject_rows))

    # Render HTML template
    template_dir = Path(__file__).parent.parent / "templates"
    env = Environment(loader=FileSystemLoader(str(template_dir)))
    template = env.get_template("report_subject.html.j2")

    html_content = template.render(
        sub=sub,
        pipeline_version=cfg.get("pipeline_version", "unknown"),
        project_name=cfg.get("project_name", "SpinePrep"),
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        run_summaries=run_summaries,
        fd_plots=all_fd_plots,
        dvars_plots=all_dvars_plots,
        module_decisions=module_decisions(cfg),
        prov_files=prov_files,
        methods_boilerplate=methods,
    )

    # Write HTML report
    report_path = reports_dir / f"{sub}_desc-qc.html"
    with open(report_path, "w") as f:
        f.write(html_content)

    return str(report_path)


def generate_methods_boilerplate(cfg: dict, sub: str, n_runs: int) -> str:
    """Generate methods boilerplate text."""
    opts = cfg.get("options", {})
    acq = cfg.get("acq", {})
    tools = cfg.get("tools", {})

    methods = f"""SpinePrep preprocessing pipeline (version {cfg.get('pipeline_version', 'unknown')}) was applied to {n_runs} functional runs from subject {sub}.

Preprocessing steps included:
- MP-PCA denoising: {'enabled' if opts.get('denoise_mppca', False) else 'disabled'}
- Motion correction: enabled
- Confounds extraction: motion parameters, framewise displacement, DVARS

Acquisition parameters:
- TR: {acq.get('tr', 'unknown')} s
- Slice timing: {acq.get('slice_timing', 'unknown')}
- Phase encoding direction: {acq.get('pe_dir', 'unknown')}

Tool versions:
- SCT: {tools.get('sct', 'unknown')}
- FSL: {tools.get('fsl', 'unknown')}
- ANTs: {tools.get('ants', 'unknown')}

All outputs follow BIDS-derivatives specification and include provenance metadata."""

    return methods
