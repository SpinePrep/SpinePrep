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

# Import registration utilities
try:
    from workflow.lib.registration import (
        collect_registration_files,
        get_registration_status,
    )
except ImportError:
    # Fallback if registration module not available
    def get_registration_status(manifest_tsv: str, sub: str) -> Dict[str, str]:
        return {
            "sct_segmentation": "absent",
            "levels": "absent",
            "warps": "absent",
            "masks": "absent",
        }

    def collect_registration_files(manifest_tsv: str, sub: str) -> List[str]:
        return []


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

    # Prefer motion parameters from motion correction step
    trans_cols = ["trans_x", "trans_y", "trans_z"]
    rot_cols = ["rot_x", "rot_y", "rot_z"]

    if not all(col in conf for col in trans_cols + rot_cols):
        # Fallback: return zeros if motion parameters not available
        n_vols = max(len(conf.get(col, [])) for col in conf.keys()) if conf else 1
        return [0.0] * n_vols

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


def read_motion_params(tsv: str) -> Dict[str, List[float]]:
    """Read motion parameters from motion correction TSV file."""
    motion_params = {}
    try:
        with open(tsv, "r", newline="") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                for col, val in row.items():
                    if col not in motion_params:
                        motion_params[col] = []
                    try:
                        motion_params[col].append(float(val))
                    except (ValueError, TypeError):
                        # Skip non-numeric values
                        pass
    except (FileNotFoundError, IOError):
        # Return empty dict if file doesn't exist
        pass
    return motion_params


def compute_fd_from_motion_params(motion_params_tsv: str) -> List[float]:
    """Compute FD from motion parameters TSV file."""
    motion_params = read_motion_params(motion_params_tsv)
    return compute_fd(motion_params)


def compute_dvars(conf: Dict[str, List[float]]) -> List[float]:
    """Compute DVARS from confounds data."""
    if "dvars" in conf:
        return conf["dvars"]

    # Fallback: return zeros if DVARS not available
    n_vols = max(len(conf.get(col, [])) for col in conf.keys()) if conf else 1
    return [0.0] * n_vols


def plot_series(
    out_png: str, series: List[float], title: str, ylabel: str, censor: List[int] = None
) -> None:
    """Create a time series plot with optional censor overlays and save as PNG."""
    plt.figure(figsize=(10, 4))

    # Plot the main series
    plt.plot(series, linewidth=0.8, color="blue", alpha=0.7)

    # Add censor overlays if provided
    if censor is not None and len(censor) == len(series):
        # Find censored frames
        censored_frames = [i for i, val in enumerate(censor) if val == 1]

        if censored_frames:
            # Plot vertical lines for censored frames
            for frame in censored_frames:
                plt.axvline(x=frame, color="red", alpha=0.6, linewidth=1)

            # Add shaded regions for censored frames
            y_min, y_max = plt.ylim()
            for frame in censored_frames:
                plt.axvspan(frame - 0.4, frame + 0.4, alpha=0.2, color="red")

    plt.title(title, fontsize=12)
    plt.xlabel("Volume", fontsize=10)
    plt.ylabel(ylabel, fontsize=10)
    plt.grid(True, alpha=0.3)
    plt.tight_layout()

    # Ensure output directory exists
    Path(out_png).parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_png, dpi=100, bbox_inches="tight")
    plt.close()


def plot_ev_series(out_png: str, ev_data: Dict[str, List[float]], title: str) -> None:
    """
    Plot explained variance for aCompCor components.

    Args:
        out_png: Output PNG path
        ev_data: Dictionary with tissue names as keys and explained variance lists as values
        title: Plot title
    """
    fig, ax = plt.subplots(figsize=(10, 6))

    colors = ["blue", "green", "red", "orange", "purple"]
    for i, (tissue, ev) in enumerate(ev_data.items()):
        if ev:  # Only plot if we have data
            ax.plot(
                range(1, len(ev) + 1),
                ev,
                "o-",
                color=colors[i % len(colors)],
                label=f"{tissue} (n={len(ev)})",
                linewidth=2,
                markersize=4,
            )

    ax.set_title(title)
    ax.set_xlabel("Component")
    ax.set_ylabel("Explained Variance")
    ax.legend()
    ax.grid(True, alpha=0.3)
    ax.set_ylim(0, 1)

    plt.tight_layout()
    plt.savefig(out_png, dpi=150, bbox_inches="tight")
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

        # Prefer motion parameters from motion correction step
        motion_params_tsv = row.get("deriv_motion_params_tsv", "")
        if motion_params_tsv and Path(motion_params_tsv).exists():
            fd = compute_fd_from_motion_params(motion_params_tsv)
        else:
            fd = compute_fd(conf)

        dvars = compute_dvars(conf)

        # Get censor information if available
        censor = conf.get("frame_censor", None)
        if censor is not None:
            censor = [int(x) for x in censor]  # Convert to int list

        # Compute summary stats
        n_vols = len(fd)
        mean_fd = stats.mean(fd) if fd else 0.0
        mean_dvars = stats.mean(dvars) if dvars else 0.0

        # Add censor stats
        n_censored = sum(censor) if censor else 0
        n_kept = n_vols - n_censored
        pct_censored = (n_censored / n_vols * 100) if n_vols > 0 else 0.0

        # Read aCompCor metadata from JSON if available
        acompcor_info = None
        if Path(confounds_json).exists():
            import json

            with open(confounds_json, "r") as f:
                meta = json.load(f)
                if "aCompCor" in meta:
                    acompcor_info = meta["aCompCor"]

        # Create plots
        fd_plot = figures_dir / f"{sub}_run-{run_id}_fd.png"
        dvars_plot = figures_dir / f"{sub}_run-{run_id}_dvars.png"

        plot_series(str(fd_plot), fd, f"{sub} run-{run_id} FD", "FD (mm)", censor)
        plot_series(
            str(dvars_plot), dvars, f"{sub} run-{run_id} DVARS", "DVARS", censor
        )

        all_fd_plots.append(fd_plot.name)
        all_dvars_plots.append(dvars_plot.name)

        # Create aCompCor EV plot if available
        ev_plot = None
        if acompcor_info:
            ev_plot = figures_dir / f"{sub}_run-{run_id}_acompcor_ev.png"
            ev_data = {}
            for tissue, tissue_info in acompcor_info.items():
                if (
                    isinstance(tissue_info, dict)
                    and "explained_variance" in tissue_info
                ):
                    ev_data[tissue] = tissue_info["explained_variance"]

            if ev_data:
                plot_ev_series(
                    str(ev_plot),
                    ev_data,
                    f"{sub} run-{run_id} aCompCor Explained Variance",
                )

        # Check if this run used grouped motion
        motion_group = row.get("motion_group", "")
        group_info = None
        if motion_group and not motion_group.startswith("per-run-"):
            # Count other runs in the same group
            group_size = sum(
                1 for r in subject_rows if r.get("motion_group", "") == motion_group
            )
            group_info = {
                "group": motion_group,
                "group_size": group_size,
                "is_grouped": True,
            }
        else:
            group_info = {"group": motion_group, "group_size": 1, "is_grouped": False}

        # Check temporal crop information
        crop_from = row.get("crop_from", 0)
        crop_to = row.get("crop_to", n_vols)
        trim_info = {
            "from": crop_from,
            "to": crop_to,
            "trimmed_start": crop_from,
            "trimmed_end": n_vols - crop_to,
            "is_trimmed": crop_from > 0 or crop_to < n_vols,
        }

        # Extract aCompCor PC counts
        acompcor_pc_counts = {}
        if acompcor_info:
            for tissue, tissue_info in acompcor_info.items():
                if isinstance(tissue_info, dict) and "n_components" in tissue_info:
                    acompcor_pc_counts[tissue] = tissue_info["n_components"]

        run_summaries.append(
            {
                "run": run_id,
                "task": task,
                "n_vols": n_vols,
                "mean_fd": round(mean_fd, 3),
                "mean_dvars": round(mean_dvars, 3),
                "n_censored": n_censored,
                "n_kept": n_kept,
                "pct_censored": round(pct_censored, 1),
                "confounds_tsv": confounds_tsv,
                "confounds_json": confounds_json,
                "fd_plot": fd_plot.name,
                "dvars_plot": dvars_plot.name,
                "ev_plot": ev_plot.name if ev_plot else None,
                "motion_group": group_info,
                "temporal_crop": trim_info,
                "acompcor": acompcor_info,
                "acompcor_pc_counts": acompcor_pc_counts,
            }
        )

    # Collect provenance files
    prov_files = collect_provenance(subject_rows)

    # Get registration status
    reg_status = get_registration_status(manifest_tsv, sub)
    reg_files = collect_registration_files(manifest_tsv, sub)

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
        reg_status=reg_status,
        reg_files=reg_files,
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

    methods = f"""SpinePrep preprocessing pipeline (version {cfg.get("pipeline_version", "unknown")}) was applied to {n_runs} functional runs from subject {sub}.

Preprocessing steps included:
- MP-PCA denoising: {"enabled" if opts.get("denoise_mppca", False) else "disabled"}
- Motion correction: enabled
- Confounds extraction: motion parameters, framewise displacement, DVARS

Acquisition parameters:
- TR: {acq.get("tr", "unknown")} s
- Slice timing: {acq.get("slice_timing", "unknown")}
- Phase encoding direction: {acq.get("pe_dir", "unknown")}

Tool versions:
- SCT: {tools.get("sct", "unknown")}
- FSL: {tools.get("fsl", "unknown")}
- ANTs: {tools.get("ants", "unknown")}

All outputs follow BIDS-derivatives specification and include provenance metadata."""

    return methods
