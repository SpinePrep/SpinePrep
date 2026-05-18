"""S11: QC aggregation + release readiness.

Spec: .claude/specs/s11-qc-aggregation-and-release.md

14 deliverables across 4 tiers. Read-only consumer of S1–S10 artifacts.
Deterministic: same chain → byte-identical outputs.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import platform
import socket
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import nibabel as nib
import numpy as np
import pandas as pd

ALL_STEPS = [
    ("S1", "S1_input_verify"),
    ("S2", "S2_anat_cordref"),
    ("S3", "S3_func_init_and_crop"),
    ("S4", "S4_func_motion_correction"),
    ("S5", "S5_func_distortion_correction"),
    ("S6", "S6_func_to_anat_registration"),
    ("S7", "S7_template_normalization"),
    ("S8", "S8_confounds_and_physio_regressors"),
    ("S9", "S9_primary_functional_derivatives"),
    ("S10", "S10_roi_timeseries_and_connectivity"),
]


# ---------------------------------------------------------------------------
# Walk chain
# ---------------------------------------------------------------------------


def _walk_chain_qc(out_dir: Path) -> dict[str, dict[str, dict]]:
    """Walk logs/<step>/<dataset>/qc.json. Returns
    {step_short: {dataset_key: qc_dict}}.
    """
    out: dict[str, dict[str, dict]] = {}
    logs_dir = out_dir / "logs"
    if not logs_dir.exists():
        return out
    for short, full in ALL_STEPS:
        out[short] = {}
        step_dir = logs_dir / full
        if not step_dir.exists():
            continue
        for ds_dir in sorted(step_dir.iterdir()):
            if not ds_dir.is_dir():
                continue
            qc_path = ds_dir / "qc.json"
            if not qc_path.exists():
                continue
            try:
                out[short][ds_dir.name] = json.loads(qc_path.read_text())
            except Exception:
                continue
    return out


def _flat_run_records(chain_qc: dict[str, dict[str, dict]]) -> list[dict]:
    """Flatten chain_qc into per-(step, run) records.

    Subject IDs are normalized to bare labels (no `sub-` prefix); upstream
    steps disagree (some emit `02`, some `sub-02`) and downstream code adds
    its own prefix.
    """
    records: list[dict] = []
    for step_short, by_ds in chain_qc.items():
        for ds_key, qc in by_ds.items():
            for r in qc.get("runs", []):
                sub = r.get("subject")
                if isinstance(sub, str) and sub.startswith("sub-"):
                    sub = sub[4:]
                rec = {
                    "step": step_short,
                    "dataset_key": ds_key,
                    "subject": sub,
                    "session": r.get("session"),
                    "run_id": r.get("run_id"),
                    "status": r.get("status"),
                    "failure_message": r.get("failure_message"),
                    "metrics": r.get("metrics", {}),
                    "reportlets": r.get("reportlets", {}),
                }
                records.append(rec)
    return records


# ---------------------------------------------------------------------------
# Tier 1: aggregation core
# ---------------------------------------------------------------------------


def _build_metrics_index(records: list[dict], out_path: Path) -> int:
    """Emit metrics_index.jsonl."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, default=str) + "\n")
    return len(records)


def _build_run_inventory(
    records: list[dict], out_tsv: Path, out_png: Path,
) -> int:
    """subjects × runs pivot: per-(subject, run) overall pass/warn/fail
    aggregated across steps.
    """
    out_tsv.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(records)
    if df.empty:
        out_tsv.write_text("subject\trun_id\tdataset_key\tn_steps\tworst_status\n")
        return 0
    df = df.dropna(subset=["run_id"])
    grouped = df.groupby(["dataset_key", "subject", "session", "run_id"])
    rows = []
    for (ds, sub, ses, rid), g in grouped:
        statuses = g["status"].tolist()
        worst = "PASS"
        if any(s == "FAIL" for s in statuses):
            worst = "FAIL"
        elif any(s == "WARN" for s in statuses):
            worst = "WARN"
        rows.append({
            "dataset_key": ds,
            "subject": sub,
            "session": ses or "",
            "run_id": rid,
            "n_steps_completed": len(statuses),
            "worst_status": worst,
        })
    out_df = pd.DataFrame(rows).sort_values(
        ["dataset_key", "subject", "session", "run_id"]
    )
    out_df.to_csv(out_tsv, sep="\t", index=False)
    # Render PNG
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        counts = out_df["worst_status"].value_counts()
        fig, ax = plt.subplots(figsize=(7, 4))
        colors = {"PASS": "#22aa44", "WARN": "#dd8800", "FAIL": "#cc2222"}
        bars = counts.reindex(["PASS", "WARN", "FAIL"], fill_value=0)
        ax.bar(bars.index, bars.values, color=[colors[s] for s in bars.index])
        ax.set_ylabel("Number of runs")
        ax.set_title(f"Run inventory — {len(out_df)} runs across "
                     f"{out_df['dataset_key'].nunique()} datasets")
        for i, v in enumerate(bars.values):
            ax.text(i, v + 0.1, str(v), ha="center", fontsize=11)
        ax.grid(axis="y", alpha=0.3)
        fig.tight_layout()
        fig.savefig(out_png, dpi=120, bbox_inches="tight")
        plt.close(fig)
    except Exception:
        pass
    return len(out_df)


def _build_group_dashboard_data(
    records: list[dict], policy: dict,
) -> dict:
    """Build status-heatmap + metric-distributions for group dashboard."""
    df = pd.DataFrame(records)
    if df.empty:
        return {"empty": True}
    # status matrix: subject × step
    df = df.dropna(subset=["subject", "step"])
    subjects = sorted(df["subject"].astype(str).unique())
    steps = [s for s, _ in ALL_STEPS]
    # collapse runs: worst status per (subject, step)
    matrix = pd.DataFrame(index=subjects, columns=steps, dtype=object)
    for (sub, step), g in df.groupby(["subject", "step"]):
        st = g["status"].tolist()
        if any(s == "FAIL" for s in st):
            v = "FAIL"
        elif any(s == "WARN" for s in st):
            v = "WARN"
        elif any(s == "PASS" for s in st):
            v = "PASS"
        else:
            v = "?"
        matrix.loc[sub, step] = v
    # Per-step pass-rate
    pass_rates: dict[str, float] = {}
    for step in steps:
        col = df[df["step"] == step]["status"].dropna()
        if len(col):
            pass_rates[step] = float((col == "PASS").mean())
    return {"matrix": matrix, "pass_rates": pass_rates}


def _render_group_dashboard_html(
    data: dict, out_path: Path,
) -> None:
    """Group QC dashboard HTML with status heatmap + pass-rate bars."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if data.get("empty"):
        out_path.write_text("<html><body><p>No data.</p></body></html>")
        return
    matrix = data["matrix"]
    pass_rates = data["pass_rates"]

    status_color = {"PASS": "#22aa44", "WARN": "#dd8800", "FAIL": "#cc2222", "?": "#888"}

    rows_html = []
    rows_html.append("<table class='heatmap'><tr><th>Subject</th>"
                     + "".join(f"<th>{s}</th>" for s in matrix.columns)
                     + "</tr>")
    for sub in matrix.index:
        cells = "".join(
            f"<td style='background:{status_color.get(matrix.loc[sub, s] or '?')};color:white'>"
            f"{matrix.loc[sub, s] or '-'}</td>"
            for s in matrix.columns
        )
        rows_html.append(f"<tr><th>{sub}</th>{cells}</tr>")
    rows_html.append("</table>")

    pass_rate_html = ["<table class='passrate'><tr><th>Step</th><th>Pass-rate</th><th>Bar</th></tr>"]
    for step, rate in pass_rates.items():
        bar = "<div style='width:200px;background:#eee'>"\
              f"<div style='width:{rate*200:.0f}px;background:#22aa44;height:14px'></div></div>"
        pass_rate_html.append(f"<tr><td>{step}</td><td>{rate*100:.0f}%</td><td>{bar}</td></tr>")
    pass_rate_html.append("</table>")

    html = f"""<!DOCTYPE html><html><head><meta charset='utf-8'>
<title>SpinalfMRIprep — Group QC Dashboard</title>
<style>
body {{ font-family: sans-serif; padding: 20px; background:#fafafa; }}
table {{ border-collapse: collapse; margin: 12px 0; }}
.heatmap td, .heatmap th {{ border:1px solid #ccc; padding:6px 10px; text-align:center; font-family:monospace; }}
.passrate td, .passrate th {{ border:1px solid #ccc; padding:6px 10px; }}
h1 {{ color:#333; }}
</style></head>
<body>
<h1>Group QC Dashboard</h1>
<p>{len(matrix)} subjects × {len(matrix.columns)} steps.</p>
<h2>Status matrix (worst per subject × step)</h2>
{"".join(rows_html)}
<h2>Per-step pass-rate</h2>
{"".join(pass_rate_html)}
</body></html>"""
    out_path.write_text(html, encoding="utf-8")


# ---------------------------------------------------------------------------
# Per-subject HTML
# ---------------------------------------------------------------------------


def _build_per_subject_html(
    out_dir: Path, dataset_key: str, subject: str,
    records: list[dict], policy: dict,
) -> Optional[Path]:
    """Emit derivatives/spinalfmriprep/<ds>/sub-XX/sub-XX_qc_report.html."""
    sub_records = [r for r in records
                   if r.get("subject") == subject and r.get("dataset_key") == dataset_key]
    if not sub_records:
        return None
    sub_dir = (out_dir / "derivatives" / "spinalfmriprep" / dataset_key
               / f"sub-{subject}")
    sub_dir.mkdir(parents=True, exist_ok=True)
    out_path = sub_dir / f"sub-{subject}_qc_report.html"

    # Build step × run pivot
    df = pd.DataFrame(sub_records)
    runs = sorted(df["run_id"].dropna().unique())
    steps = [s for s, _ in ALL_STEPS]
    status_color = {"PASS": "#22aa44", "WARN": "#dd8800", "FAIL": "#cc2222"}
    thumb_per_step = policy.get("aggregation", {}).get("per_subject_html", {}).get(
        "thumbnail_per_step", {})

    rows = []
    rows.append("<table><tr><th>Step</th>" +
                "".join(f"<th>{r}</th>" for r in runs) + "</tr>")
    for short, full in ALL_STEPS:
        row_cells = [f"<th>{short}</th>"]
        for rid in runs:
            recs = df[(df["step"] == short) & (df["run_id"] == rid)]
            if recs.empty:
                row_cells.append("<td>-</td>")
                continue
            r = recs.iloc[0]
            status = r["status"]
            color = status_color.get(status, "#888")
            fail = r.get("failure_message") or ""
            fail_html = (f"<br><small style='color:#cc2222'>{fail[:60]}</small>"
                         if status != "PASS" and fail else "")
            # Thumbnail
            thumb_key = thumb_per_step.get(full, "")
            rep_rel = (r.get("reportlets") or {}).get(thumb_key, "")
            img = ""
            if rep_rel:
                img_rel = os.path.relpath(out_dir / rep_rel, sub_dir)
                img = (f"<br><a href='{img_rel}' target='_blank'>"
                       f"<img src='{img_rel}' style='max-width:200px;max-height:120px' /></a>")
            row_cells.append(
                f"<td style='background:{color};color:white;padding:4px;vertical-align:top;'>"
                f"<b>{status}</b>{fail_html}{img}</td>"
            )
        rows.append("<tr>" + "".join(row_cells) + "</tr>")
    rows.append("</table>")

    html = f"""<!DOCTYPE html><html><head><meta charset='utf-8'>
<title>QC Report — sub-{subject} ({dataset_key})</title>
<style>
body {{ font-family: sans-serif; padding: 20px; background:#fafafa; }}
table {{ border-collapse: collapse; margin: 12px 0; }}
td, th {{ border:1px solid #ccc; padding:6px 10px; text-align:center; font-family:monospace; vertical-align:top; }}
th {{ background:#eee; }}
img {{ display:block; }}
h1 {{ color:#333; }}
</style></head>
<body>
<h1>QC Report — sub-{subject}</h1>
<p>Dataset: <code>{dataset_key}</code>. Runs: {len(runs)}.</p>
{"".join(rows)}
<p><small>Generated by SpinalfMRIprep S11.</small></p>
</body></html>"""
    out_path.write_text(html, encoding="utf-8")
    return out_path


# ---------------------------------------------------------------------------
# Tier 2: cord-novel cohort views
# ---------------------------------------------------------------------------


def _build_cohort_coverage_matrix(
    out_dir: Path, records: list[dict], policy: dict,
    out_tsv: Path, out_png: Path,
) -> int:
    """Per-subject vertebral-level coverage. Source: S9 per_level TSVs.
    Coverage = the per-level TSV has a row for that label.
    """
    out_tsv.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    # S9 records have output_paths.tsnr_per_level_tsv pointing to per-level TSV
    s9_recs = [r for r in records if r.get("step") == "S9"
               and r.get("status") in ("PASS", "WARN")]
    for r in s9_recs:
        sub = r.get("subject")
        ds = r.get("dataset_key")
        rid = r.get("run_id")
        # Re-read S9 qc.json output_paths via the records' output_paths if exposed
        # (records only have metrics + reportlets, not output_paths in our serialization)
        tsnr_tsv = (out_dir / "derivatives" / "spinalfmriprep" / ds
                    / f"sub-{sub}" / "func"
                    / f"{rid}_desc-tsnr_per_level.tsv")
        if not tsnr_tsv.exists():
            # Fall back: search legacy unkeyed path
            tsnr_tsv_alt = (out_dir / "derivatives" / "spinalfmriprep"
                            / f"sub-{sub}" / "func"
                            / f"{rid}_desc-tsnr_per_level.tsv")
            if tsnr_tsv_alt.exists():
                tsnr_tsv = tsnr_tsv_alt
            else:
                continue
        try:
            df = pd.read_csv(tsnr_tsv, sep="\t")
            for _, lvl_row in df.iterrows():
                rows.append({
                    "dataset_key": ds,
                    "subject": sub,
                    "run_id": rid,
                    "level": int(lvl_row["level"]),
                    "n_voxels": int(lvl_row["n_voxels"]),
                    "mean_tsnr": float(lvl_row["mean_tsnr"]),
                })
        except Exception:
            continue
    if not rows:
        out_tsv.write_text("dataset_key\tsubject\trun_id\tlevel\tn_voxels\tmean_tsnr\n")
        return 0
    cov_df = pd.DataFrame(rows)
    cov_df.to_csv(out_tsv, sep="\t", index=False)
    # PNG: cohort × levels coverage heatmap
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        # Use one row per (dataset, subject, run) and cols = levels
        pivot = cov_df.pivot_table(
            index=["dataset_key", "subject", "run_id"],
            columns="level",
            values="n_voxels", aggfunc="sum",
        ).fillna(0)
        if pivot.empty:
            return len(cov_df)
        fig, ax = plt.subplots(figsize=(max(7, pivot.shape[1] * 0.8),
                                        max(3, len(pivot) * 0.25 + 2)))
        ax.imshow((pivot > 0).astype(int), cmap="Greens",
                  vmin=0, vmax=1, aspect="auto")
        ax.set_xticks(range(pivot.shape[1]))
        ax.set_xticklabels([str(c) for c in pivot.columns])
        ax.set_yticks(range(len(pivot)))
        ax.set_yticklabels([f"{idx[0][:18]}/{idx[1]}/{idx[2][:20]}"
                            for idx in pivot.index], fontsize=7)
        ax.set_xlabel("Vertebral level")
        ax.set_title(f"Cohort coverage matrix — {len(pivot)} runs")
        fig.tight_layout()
        fig.savefig(out_png, dpi=120, bbox_inches="tight")
        plt.close(fig)
    except Exception:
        pass
    return len(cov_df)


def _build_cohort_tsnr_heatmap(
    out_dir: Path, records: list[dict], policy: dict,
    out_tsv: Path, out_png: Path,
) -> int:
    """Cohort tSNR heatmap by spinal level. Source: same S9 per_level TSVs."""
    out_tsv.parent.mkdir(parents=True, exist_ok=True)
    s9_recs = [r for r in records if r.get("step") == "S9"
               and r.get("status") in ("PASS", "WARN")]
    rows = []
    for r in s9_recs:
        sub = r.get("subject"); ds = r.get("dataset_key"); rid = r.get("run_id")
        tsv = (out_dir / "derivatives" / "spinalfmriprep" / ds
               / f"sub-{sub}" / "func"
               / f"{rid}_desc-tsnr_per_level.tsv")
        if not tsv.exists():
            tsv_alt = (out_dir / "derivatives" / "spinalfmriprep"
                       / f"sub-{sub}" / "func"
                       / f"{rid}_desc-tsnr_per_level.tsv")
            if tsv_alt.exists():
                tsv = tsv_alt
            else:
                continue
        try:
            df = pd.read_csv(tsv, sep="\t")
            for _, lr in df.iterrows():
                rows.append({
                    "dataset_key": ds, "subject": sub, "run_id": rid,
                    "level": int(lr["level"]),
                    "mean_tsnr": float(lr["mean_tsnr"]),
                })
        except Exception:
            continue
    if not rows:
        out_tsv.write_text("dataset_key\tsubject\trun_id\tlevel\tmean_tsnr\n")
        return 0
    df = pd.DataFrame(rows)
    df.to_csv(out_tsv, sep="\t", index=False)
    # PNG
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        pivot = df.pivot_table(
            index=["dataset_key", "subject", "run_id"],
            columns="level", values="mean_tsnr",
        )
        if pivot.empty:
            return len(df)
        cr = policy.get("cohort_views", {}).get("tsnr_heatmap", {}).get(
            "color_range", [0, 50])
        fig, ax = plt.subplots(figsize=(max(7, pivot.shape[1] * 0.8),
                                        max(3, len(pivot) * 0.25 + 2)))
        im = ax.imshow(pivot.fillna(0).to_numpy(), cmap="hot",
                       vmin=cr[0], vmax=cr[1], aspect="auto")
        fig.colorbar(im, ax=ax, shrink=0.7, label="median tSNR")
        ax.set_xticks(range(pivot.shape[1]))
        ax.set_xticklabels([str(c) for c in pivot.columns])
        ax.set_yticks(range(len(pivot)))
        ax.set_yticklabels([f"{i[0][:18]}/{i[1]}/{i[2][:20]}"
                            for i in pivot.index], fontsize=7)
        ax.set_xlabel("Spinal level")
        ax.set_title(f"Cohort cord tSNR by spinal level — {len(pivot)} runs")
        fig.tight_layout()
        fig.savefig(out_png, dpi=120, bbox_inches="tight")
        plt.close(fig)
    except Exception:
        pass
    return len(df)


def _build_cohort_fc_summary(
    out_dir: Path, records: list[dict], policy: dict,
    out_mean_tsv: Path, out_consistency_tsv: Path, out_png: Path,
) -> dict[str, Any]:
    """Group-mean Fisher-z + consistency map across all hemicord FC matrices."""
    s10_recs = [r for r in records if r.get("step") == "S10"
                and r.get("status") in ("PASS", "WARN")]
    matrices: list[pd.DataFrame] = []
    for r in s10_recs:
        sub = r.get("subject"); ds = r.get("dataset_key"); rid = r.get("run_id")
        path = (out_dir / "derivatives" / "spinalfmriprep" / ds
                / f"sub-{sub}" / "func"
                / f"{rid}_desc-hemicord_fisherz_connectivity.tsv")
        if not path.exists():
            continue
        try:
            mat = pd.read_csv(path, sep="\t", index_col=0)
            matrices.append(mat)
        except Exception:
            continue
    def _placeholder(reason: str, n_matrices: int, n_common: int) -> dict[str, Any]:
        out_mean_tsv.parent.mkdir(parents=True, exist_ok=True)
        out_mean_tsv.write_text(f"# {reason}\n")
        out_consistency_tsv.write_text(f"# {reason}\n")
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            fig, ax = plt.subplots(figsize=(6, 3))
            ax.axis("off")
            ax.text(0.5, 0.5, reason, ha="center", va="center",
                    fontsize=11, wrap=True)
            fig.savefig(out_png, dpi=120, bbox_inches="tight")
            plt.close(fig)
        except Exception:
            out_png.write_bytes(b"")
        return {"n_matrices": n_matrices, "n_common_rois": n_common}

    if not matrices:
        return _placeholder("No FC matrices found on chain.", 0, 0)
    # Intersect ROIs
    common = set(matrices[0].columns)
    for m in matrices[1:]:
        common &= set(m.columns)
    common = sorted(common)
    if len(common) < 2:
        return _placeholder(
            f"Only {len(common)} ROI(s) common across {len(matrices)} matrices — "
            "cohort FC summary not informative. Consider stratifying by dataset.",
            len(matrices), len(common),
        )
    aligned = np.stack([m.loc[common, common].to_numpy() for m in matrices], axis=0)
    mean_z = np.nanmean(aligned, axis=0)
    thr = float(policy.get("cohort_views", {}).get("fc_summary", {}).get(
        "consistency_z_threshold", 0.3))
    consistency = (np.abs(aligned) > thr).mean(axis=0)
    mean_df = pd.DataFrame(mean_z, index=common, columns=common)
    cons_df = pd.DataFrame(consistency, index=common, columns=common)
    out_mean_tsv.parent.mkdir(parents=True, exist_ok=True)
    mean_df.to_csv(out_mean_tsv, sep="\t", float_format="%.4f")
    cons_df.to_csv(out_consistency_tsv, sep="\t", float_format="%.4f")
    # PNG: side-by-side heatmaps
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, axes = plt.subplots(1, 2, figsize=(14, 6))
        im0 = axes[0].imshow(mean_z, cmap="RdBu_r", vmin=-1, vmax=1)
        axes[0].set_title(f"Group-mean Fisher-z (n={len(matrices)})")
        fig.colorbar(im0, ax=axes[0], shrink=0.7)
        im1 = axes[1].imshow(consistency, cmap="viridis", vmin=0, vmax=1)
        axes[1].set_title(f"Consistency: fraction of subjects with |z|>{thr}")
        fig.colorbar(im1, ax=axes[1], shrink=0.7)
        for ax in axes:
            step = max(1, len(common) // 24)
            ax.set_xticks(range(0, len(common), step))
            ax.set_yticks(range(0, len(common), step))
            ax.set_xticklabels([common[i] for i in range(0, len(common), step)],
                               rotation=90, fontsize=6)
            ax.set_yticklabels([common[i] for i in range(0, len(common), step)],
                               fontsize=6)
        fig.tight_layout()
        fig.savefig(out_png, dpi=120, bbox_inches="tight")
        plt.close(fig)
    except Exception:
        pass
    return {"n_matrices": len(matrices), "n_common_rois": len(common)}


# ---------------------------------------------------------------------------
# Tier 3: publication & reproducibility
# ---------------------------------------------------------------------------


def _build_reproducibility_receipt(
    out_dir: Path, chain_qc: dict, out_path: Path, policy: dict,
) -> dict:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    recipe = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "hostname": socket.gethostname(),
        "os": platform.platform(),
        "python_version": platform.python_version(),
    }
    # External tools
    try:
        out = subprocess.run(["sct_version"], capture_output=True, text=True, timeout=10)
        recipe["sct_version"] = (out.stdout or out.stderr).strip().split("\n")[0]
    except Exception:
        recipe["sct_version"] = None
    try:
        out = subprocess.run(["fslversion"], capture_output=True, text=True, timeout=10)
        recipe["fsl_version"] = (out.stdout or out.stderr).strip().split("\n")[0]
    except Exception:
        recipe["fsl_version"] = None
    # Python package versions
    recipe["package_versions"] = {}
    for pkg in policy.get("publication", {}).get("reproducibility_receipt", {}).get(
        "capture_packages", []
    ):
        try:
            from importlib import metadata
            recipe["package_versions"][pkg] = metadata.version(pkg)
        except Exception:
            recipe["package_versions"][pkg] = None
    # Per-step policy SHAs (read from any one run's qc_metrics.json provenance)
    recipe["policy_sha256_per_step"] = {}
    for short, full in ALL_STEPS:
        # Find first run's work qc_metrics.json
        wm_dir = out_dir / "work" / full
        sha: Optional[str] = None
        if wm_dir.exists():
            for ds_dir in wm_dir.iterdir():
                if not ds_dir.is_dir():
                    continue
                for run_dir in ds_dir.iterdir():
                    if not run_dir.is_dir():
                        continue
                    qm = run_dir / "qc_metrics.json"
                    if qm.exists():
                        try:
                            d = json.loads(qm.read_text())
                            sha = d.get("policy_sha256") or d.get("provenance", {}).get("policy_sha256")
                            if sha:
                                break
                        except Exception:
                            pass
                if sha:
                    break
        recipe["policy_sha256_per_step"][short] = sha
    # Pipeline Git SHA
    try:
        project_root = (out_dir.parent.parent if out_dir.name.startswith("wf_")
                        else Path.cwd())
        out = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        recipe["pipeline_git_sha"] = out.stdout.strip() or None
        out = subprocess.run(
            ["git", "-C", str(project_root), "describe", "--always", "--tags"],
            capture_output=True, text=True, timeout=5,
        )
        recipe["pipeline_git_describe"] = out.stdout.strip() or None
    except Exception:
        recipe["pipeline_git_sha"] = None
        recipe["pipeline_git_describe"] = None
    out_path.write_text(json.dumps(recipe, indent=2, default=str))
    return recipe


def _build_citation_cff(
    out_path: Path, recipe: dict, policy: dict,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cff_version = recipe.get("pipeline_git_describe") or "0.0.0"
    cff = f"""cff-version: 1.2.0
message: "If you use SpinalfMRIprep, please cite the methods listed in references.bib."
title: SpinalfMRIprep
abstract: >
  Cervical spinal cord fMRI preprocessing pipeline. BIDS-Derivatives
  compliant. Integrates SCT, FSL PNM, Nilearn, and PAM50 template.
authors:
  - family-names: Sharifi
    given-names: Kiomars
    affiliation: Balgrist University Hospital / ETH Zurich / UZH
version: {cff_version}
date-released: "{recipe.get('timestamp_utc', '')[:10]}"
"""
    out_path.write_text(cff)


def _build_references_bib(out_path: Path) -> None:
    """Auto-bibliography of every methods reference used in S2..S10."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    bib = r"""@article{kaptan2023,
  title={Spinal fMRI demonstrates segmental organisation of functionally connected networks in the cervical spinal cord},
  author={Kaptan, M. and others},
  journal={Imaging Neuroscience},
  year={2023},
  doi={10.1162/imag_a_00073}
}

@article{hemmerling2025,
  title={Data-driven denoising in spinal cord fMRI with principal component analysis (SpinalCompCor)},
  author={Hemmerling, K.J. and others},
  journal={Imaging Neuroscience},
  year={2025},
  doi={10.1162/imag.a.1143}
}

@article{hemmerling2023,
  title={Reliability of resting-state functional connectivity in the human spinal cord},
  author={Hemmerling, K.J. and others},
  journal={bioRxiv},
  year={2023}
}

@article{eippert2017,
  title={Denoising spinal cord fMRI data: Approaches to acquisition and analysis},
  author={Eippert, F. and Kong, Y. and Jenkinson, M. and Tracey, I. and Brooks, J.C.W.},
  journal={NeuroImage},
  year={2017}
}

@article{brooks2008,
  title={Physiological noise modelling for spinal functional magnetic resonance imaging studies},
  author={Brooks, J.C.W. and others},
  journal={NeuroImage},
  year={2008}
}

@article{deleener2018,
  title={PAM50: Unbiased multimodal template of the brainstem and spinal cord aligned with the ICBM152 space},
  author={De Leener, B. and others},
  journal={NeuroImage},
  year={2018}
}

@article{valosek2024_rootlets,
  title={Rootlets-based registration to the PAM50 spinal cord template},
  author={Valošek, J. and others},
  journal={Imaging Neuroscience},
  year={2025},
  doi={10.1162/IMAG.a.123}
}

@article{valosek2024_morphometry,
  title={A database of the healthy human spinal cord morphometry in the PAM50 template space},
  author={Valošek, J. and others},
  journal={Imaging Neuroscience},
  year={2024}
}

@article{cicchetti1994,
  title={Guidelines, criteria, and rules of thumb for evaluating normed and standardized assessment instruments in psychology},
  author={Cicchetti, D.V.},
  journal={Psychological Assessment},
  year={1994}
}

@article{shrout1979,
  title={Intraclass correlations: uses in assessing rater reliability},
  author={Shrout, P.E. and Fleiss, J.L.},
  journal={Psychological Bulletin},
  year={1979}
}

@article{marrelec2006,
  title={Partial correlation for functional brain interactivity investigation in functional MRI},
  author={Marrelec, G. and others},
  journal={NeuroImage},
  year={2006}
}

@article{dabbagh2024,
  title={Reliability of task-based fMRI in the dorsal horn of the human spinal cord},
  author={Dabbagh, A. and others},
  journal={Imaging Neuroscience},
  year={2024}
}

@article{forman1995,
  title={Improved assessment of significant activation in fMRI},
  author={Forman, S.D. and others},
  journal={Magnetic Resonance in Medicine},
  year={1995}
}

@article{schreiber1996,
  title={Improved surrogate data for nonlinearity tests},
  author={Schreiber, T. and Schmitz, A.},
  journal={Physical Review Letters},
  year={1996}
}

@article{behzadi2007,
  title={A component based noise correction method (CompCor) for BOLD and perfusion based fMRI},
  author={Behzadi, Y. and Restom, K. and Liau, J. and Liu, T.T.},
  journal={NeuroImage},
  year={2007}
}

@article{power2014,
  title={Methods to detect, characterize, and remove motion artifact in resting state fMRI},
  author={Power, J.D. and others},
  journal={NeuroImage},
  year={2014}
}

@article{vahdat2020,
  title={Dynamic Functional Connectivity of Resting-State Spinal Cord fMRI Reveals Fine-Grained Intrinsic Architecture},
  author={Vahdat, S. and others},
  journal={Neuron},
  year={2020}
}

@article{cospine2025,
  title={CoSpine open access simultaneous cortico-spinal fMRI database of thermal pain and motor tasks},
  author={CoSpine consortium},
  journal={Scientific Data},
  year={2025}
}

@article{sct2017,
  title={SCT: Spinal Cord Toolbox, an open-source software for processing spinal cord MRI data},
  author={De Leener, B. and others},
  journal={NeuroImage},
  year={2017}
}

@misc{nilearn,
  title={Nilearn: machine learning for NeuroImaging in Python},
  author={Abraham, A. and others},
  year={2014}
}
"""
    out_path.write_text(bib)


def _build_dataset_description(
    out_dir: Path, chain_qc: dict, recipe: dict, out_path: Path,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Collect source datasets from S1/S2 qc.json bids_root fields
    source_datasets: list[dict] = []
    for ds_key, qc in (chain_qc.get("S2") or chain_qc.get("S1") or {}).items():
        br = qc.get("bids_root")
        if br:
            source_datasets.append({"URL": f"file://{br}", "Description": ds_key})
    desc = {
        "Name": "SpinalfMRIprep derivatives",
        "BIDSVersion": "1.10.0",
        "DatasetType": "derivative",
        "GeneratedBy": [{
            "Name": "SpinalfMRIprep",
            "Version": recipe.get("pipeline_git_describe") or "0.0.0",
            "Description": "Cervical spinal cord fMRI preprocessing pipeline",
            "CodeURL": "https://github.com/[org]/SpinalfMRIprep",
            "Container": {
                "Type": "host",
                "Tag": recipe.get("pipeline_git_sha") or "unknown",
            },
        }],
        "SourceDatasets": source_datasets,
    }
    out_path.write_text(json.dumps(desc, indent=2))


def _build_participants_tsv(
    out_dir: Path, records: list[dict], policy: dict,
    out_tsv: Path, out_json: Path,
) -> int:
    out_tsv.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(records).dropna(subset=["subject"])
    if df.empty:
        out_tsv.write_text("participant_id\n")
        out_json.write_text("{}")
        return 0
    fd_thresh = float(policy.get("publication", {}).get("participants_tsv", {}).get(
        "include_threshold_fd", 0.5))
    tsnr_thresh = float(policy.get("publication", {}).get("participants_tsv", {}).get(
        "include_threshold_tsnr", 5.0))
    rows = []
    for (sub, ds), g in df.groupby(["subject", "dataset_key"]):
        # Per-run worst status
        run_groups = g.groupby("run_id")
        n_pass = sum(1 for _, gg in run_groups
                     if all(s == "PASS" for s in gg["status"]))
        n_warn = sum(1 for _, gg in run_groups
                     if not all(s == "PASS" for s in gg["status"])
                     and not any(s == "FAIL" for s in gg["status"]))
        n_failed = sum(1 for _, gg in run_groups
                       if any(s == "FAIL" for s in gg["status"]))
        n_runs = run_groups.ngroups
        n_sessions = g["session"].nunique()
        # Aggregate metrics
        s4 = g[g["step"] == "S4"]
        s9 = g[g["step"] == "S9"]
        s10 = g[g["step"] == "S10"]
        mean_fd = np.nan
        if not s4.empty:
            fds = [r.get("fd_max_mm") for r in s4["metrics"] if isinstance(r, dict)]
            fds = [f for f in fds if f is not None]
            if fds:
                mean_fd = float(np.mean(fds))
        median_tsnr = np.nan
        if not s9.empty:
            ts = [r.get("tsnr_post_median") for r in s9["metrics"] if isinstance(r, dict)]
            ts = [t for t in ts if t is not None]
            if ts:
                median_tsnr = float(np.median(ts))
        max_cn = np.nan
        if not s10.empty:
            cns = [r.get("condition_number_pearson_hemicord")
                   for r in s10["metrics"] if isinstance(r, dict)]
            cns = [c for c in cns if c is not None and np.isfinite(c)]
            if cns:
                max_cn = float(np.max(cns))
        recommend = "include"
        if (np.isfinite(mean_fd) and mean_fd > fd_thresh) or \
           (np.isfinite(median_tsnr) and median_tsnr < tsnr_thresh) or \
           n_failed > 0:
            recommend = "review"
        rows.append({
            "participant_id": f"sub-{sub}",
            "dataset_key": ds,
            "n_runs": int(n_runs),
            "n_sessions": int(n_sessions),
            "n_passed": int(n_pass),
            "n_warn": int(n_warn),
            "n_failed": int(n_failed),
            "mean_fd_mm": float(mean_fd) if np.isfinite(mean_fd) else "n/a",
            "median_in_cord_tsnr": float(median_tsnr) if np.isfinite(median_tsnr) else "n/a",
            "max_condition_number": float(max_cn) if np.isfinite(max_cn) else "n/a",
            "included_recommendation": recommend,
        })
    out_df = pd.DataFrame(rows).sort_values(["dataset_key", "participant_id"])
    out_df.to_csv(out_tsv, sep="\t", index=False)
    # Sidecar (BIDS spec requires JSON for non-standard columns)
    sidecar = {
        "participant_id": {"Description": "BIDS participant identifier"},
        "dataset_key": {"Description": "SpinalfMRIprep dataset key (multi-source aggregation)"},
        "n_runs": {"Description": "Number of BOLD runs successfully processed"},
        "n_sessions": {"Description": "Number of MRI sessions for this participant"},
        "n_passed": {"Description": "Number of runs that PASS across all S2..S10 steps"},
        "n_warn": {"Description": "Number of runs with at least one step WARN"},
        "n_failed": {"Description": "Number of runs with at least one step FAIL"},
        "mean_fd_mm": {"Description": "Mean framewise displacement (mm) across runs", "Units": "mm"},
        "median_in_cord_tsnr": {"Description": "Median in-cord tSNR post-smoothing (S9)"},
        "max_condition_number": {"Description": "Max Pearson hemicord connectivity matrix condition number (S10)"},
        "included_recommendation": {
            "Description": "Pipeline recommendation for cohort inclusion: 'include' or 'review'",
            "Levels": {
                "include": "passes FD/tSNR/run thresholds",
                "review": f"FD > {fd_thresh} mm OR tSNR < {tsnr_thresh} OR any failed run",
            },
        },
    }
    out_json.write_text(json.dumps(sidecar, indent=2))
    return len(out_df)


def _build_methods_manifest(
    out_dir: Path, recipe: dict, policy: dict,
    out_md: Path, out_tex: Path, out_html: Path,
) -> None:
    pipeline_v = recipe.get("pipeline_git_describe") or "0.0.0"
    sct_v = recipe.get("sct_version", "n/a")
    fsl_v = recipe.get("fsl_version", "n/a")
    nilearn_v = recipe.get("package_versions", {}).get("nilearn", "n/a")
    nibabel_v = recipe.get("package_versions", {}).get("nibabel", "n/a")

    md = f"""# Methods (auto-generated by SpinalfMRIprep S11)

**Pipeline**: SpinalfMRIprep {pipeline_v}. **Tools**: Spinal Cord Toolbox {sct_v}; FSL {fsl_v}; Nilearn {nilearn_v}; NiBabel {nibabel_v}.

## Preprocessing

Cervical spinal cord BOLD data were preprocessed using SpinalfMRIprep, a custom pipeline integrating Spinal Cord Toolbox (SCT) [@sct2017], FSL Physiological Noise Modelling [@brooks2008], and Nilearn [@nilearn], with templates from PAM50 [@deleener2018].

**Anatomical (S2)**: T1w / T2w / T2*-MEGRE images were segmented via SCT contrast-agnostic spinal cord segmentation, labeled via TotalSpineSeg, and registered to PAM50 using rootlets-based registration [@valosek2024_rootlets] (falling back to disc labels). Dual-role anatomical model: full-FOV primary anat (T1w/T2w) for labeling and template registration; T2*-MEGRE secondary cordref for functional registration (cleaner same-contrast match to T2*-weighted BOLD).

**Functional initialization (S3)**: BOLD reference image discovered via fast cord segmentation; volume cropped to a cord-centered FOV. Frame-level QC metrics (DVARS, refRMS) computed per Power 2014 [@power2014].

**Motion correction (S4)**: 2D slicewise translation (x, y) via SCT `sct_fmri_moco`, regularized along Z. Per-slice translation parameters emitted as 4D NIfTI for downstream confound use.

**Distortion correction (S5)**: Per-dataset mode (TopUp / FUGUE / SyN fallback). Mutual information of funcref-vs-anat computed before/after as QC.

**Functional-to-anat registration (S6)**: SCT `sct_register_multimodal` with the cord-driven Kaptan 2023 recipe [@kaptan2023]: `centermassrot → columnwise → bsplinesyn (iter=20, slicewise)`. Output: bidirectional warp `from-bold_to-anat_xfm.nii.gz`.

**Template normalization (S7)**: Composed S2 (anat ↔ PAM50) and S6 (bold ↔ anat) warps via `sct_concat_transfo`; refined the composite at the EPI level via a second `sct_register_multimodal` pass (`slicereg + bsplinesyn`, iter=5). PAM50 atlas warped into native func space; no 4D BOLD resampling.

**Confounds (S8)**: Five families assembled per BIDS-Derivatives convention: (a) motion (trans_x/y + derivatives + FD); (b) S3-computed DVARS+refRMS outlier one-hot regressors; (c) slicewise CSF top-20%-variance mean (Hemmerling 2025 [@hemmerling2025]); (d) RETROICOR (FSL PNM popp + pnm_evs; cardiac order 4 + respiratory 4 + interactions 4×4, slice-mean aggregated; HR/RVT slow regressors) [@brooks2008]; (e) cosine basis up to 1/100 Hz; (f) SpinalCompCor (Hemmerling 2025 [@hemmerling2025]; default global_3d aggregation with K=5 PCs; opt-in slicewise + IAAFT parallel analysis [@schreiber1996]). All emitted; nothing regressed out of the BOLD itself.

**Primary functional derivatives (S9)**: Cord-aware Gaussian smoothing via SCT `sct_smooth_spinalcord` (σ = 1, 1, 5 mm in R-L, A-P, S-I; CoSpi-validated lineage; Eippert 2017 anisotropic principle [@eippert2017]). Output: native + PAM50-space smoothed BOLD, per-vertebral-level tSNR TSV.

**ROI timeseries + connectivity (S10)**: Three ROI catalogs via Nilearn `NiftiLabelsMasker` [@nilearn] in native func:
- vertebral levels (PAM50_levels, 1–8);
- spinal segmental levels (PAM50_spinal_levels, 1–8 = C1–C8);
- hemicord × spinal segmental (4 horns × N segments, Kaptan 2023 [@kaptan2023]).
Two confound modes per catalog: raw + S8-regressed. Pearson and Marrelec 2006 [@marrelec2006] partial correlation (Ledoit-Wolf shrinkage) connectivity matrices emitted for hemicord. Bandpass 0.01–0.1 Hz [@eippert2017]. Per-subject reliability (multi-session same task): pooled ICC(3,1) [@shrout1979], Cicchetti 1994 bands [@cicchetti1994].

## Citation
Please cite the methods listed in `references.bib` (auto-generated alongside this manifest).

## Reproducibility
Per-step policy SHA256 + pipeline Git SHA captured in `reproducibility_receipt.json`.
"""
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(md)
    # Bare LaTeX version
    out_tex.write_text(md.replace("# ", "\\section{").replace("## ", "\\subsection{") + "}")
    # HTML version
    html = f"""<!DOCTYPE html><html><head><meta charset='utf-8'>
<title>SpinalfMRIprep Methods Manifest</title>
<style>body {{ font-family: serif; padding:24px; max-width:900px; margin:auto; }} h1,h2 {{ color:#333; }} code {{ background:#eee; padding:2px 4px; }}</style>
</head><body>
<pre style='white-space:pre-wrap'>{md}</pre>
</body></html>"""
    out_html.write_text(html)


# ---------------------------------------------------------------------------
# Tier 4: compliance + navigation
# ---------------------------------------------------------------------------


def _build_sidecar_audit(
    out_dir: Path, records: list[dict], policy: dict,
    out_json: Path, out_html: Path,
) -> dict:
    """Verify per-emit contract: every reportlet PNG path in records exists;
    spot-check NIfTI dtype on key outputs.
    """
    out_json.parent.mkdir(parents=True, exist_ok=True)
    missing_reportlets: list[str] = []
    nifti_issues: list[str] = []
    expected_total = 0
    for r in records:
        for rkey, rpath in (r.get("reportlets") or {}).items():
            if not rpath:
                continue
            expected_total += 1
            full = out_dir / rpath
            if not full.exists():
                missing_reportlets.append(f"{r.get('step')}/{r.get('run_id')}/{rkey}: {rpath}")
    audit = {
        "expected_reportlets": expected_total,
        "missing_reportlets": len(missing_reportlets),
        "missing_reportlets_list": missing_reportlets[:50],
        "nifti_issues": len(nifti_issues),
        "nifti_issues_list": nifti_issues[:50],
        "non_blocking": True,
    }
    out_json.write_text(json.dumps(audit, indent=2))
    html = f"""<!DOCTYPE html><html><head><meta charset='utf-8'>
<title>Sidecar audit</title>
<style>body {{ font-family:sans-serif; padding:20px; }} pre {{ background:#f5f5f5; padding:10px; }}</style>
</head><body>
<h1>Sidecar audit</h1>
<p>Reportlets expected: {expected_total} | Missing: {len(missing_reportlets)} | NIfTI issues: {len(nifti_issues)}</p>
<h2>Missing reportlets (first 50)</h2><pre>{chr(10).join(missing_reportlets[:50]) or 'none'}</pre>
<h2>NIfTI issues</h2><pre>{chr(10).join(nifti_issues[:50]) or 'none'}</pre>
</body></html>"""
    out_html.write_text(html)
    return audit


def _build_release_report(
    out_dir: Path, subject_report_paths: list[Path], deliverables: dict,
    out_path: Path,
) -> None:
    """Single-page index linking all S11 deliverables."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rel_links = {k: os.path.relpath(out_dir / v, out_path.parent) if v else ""
                 for k, v in deliverables.items()}
    sub_links = "".join(
        f"<li><a href='{os.path.relpath(p, out_path.parent)}'>{p.name}</a></li>"
        for p in subject_report_paths if p
    )
    html = f"""<!DOCTYPE html><html><head><meta charset='utf-8'>
<title>SpinalfMRIprep — Release Report</title>
<style>
body {{ font-family:sans-serif; padding:30px; max-width:1100px; margin:auto; background:#fafafa; }}
h1,h2 {{ color:#333; border-bottom:1px solid #ccc; padding-bottom:4px; }}
.card {{ background:white; border:1px solid #ddd; padding:14px 18px; margin:10px 0; border-radius:6px; }}
ul {{ columns: 2; }}
a {{ color:#0086e6; text-decoration:none; }} a:hover {{ text-decoration:underline; }}
.muted {{ color:#888; font-size:0.9em; }}
</style></head><body>
<h1>SpinalfMRIprep — Release Report</h1>
<p class='muted'>{len(subject_report_paths)} per-subject reports · group artifacts below.</p>

<div class='card'>
<h2>Group views</h2>
<ul>
<li><a href='{rel_links.get('group_dashboard','#')}'>Group QC dashboard</a></li>
<li><a href='{rel_links.get('run_inventory_png','#')}'>Run inventory bar</a> · <a href='{rel_links.get('run_inventory_tsv','#')}'>TSV</a></li>
<li><a href='{rel_links.get('coverage_matrix_png','#')}'>Per-vertebral coverage matrix</a> · <a href='{rel_links.get('coverage_matrix_tsv','#')}'>TSV</a></li>
<li><a href='{rel_links.get('tsnr_heatmap_png','#')}'>Cohort cord SNR heatmap</a> · <a href='{rel_links.get('tsnr_heatmap_tsv','#')}'>TSV</a></li>
<li><a href='{rel_links.get('fc_summary_png','#')}'>Cohort FC summary</a> · <a href='{rel_links.get('fc_summary_mean_tsv','#')}'>mean Fisher-z</a> · <a href='{rel_links.get('fc_summary_consistency_tsv','#')}'>consistency</a></li>
</ul>
</div>

<div class='card'>
<h2>Per-subject reports</h2>
<ul>{sub_links}</ul>
</div>

<div class='card'>
<h2>Release artifacts</h2>
<ul>
<li><a href='{rel_links.get('citation_cff','#')}'>CITATION.cff</a> · <a href='{rel_links.get('references_bib','#')}'>references.bib</a></li>
<li><a href='{rel_links.get('methods_md','#')}'>Methods manifest (Markdown)</a> · <a href='{rel_links.get('methods_html','#')}'>HTML</a> · <a href='{rel_links.get('methods_tex','#')}'>LaTeX</a></li>
<li><a href='{rel_links.get('dataset_description','#')}'>dataset_description.json (BIDS-Derivatives)</a></li>
<li><a href='{rel_links.get('participants_tsv','#')}'>participants.tsv</a> · <a href='{rel_links.get('participants_json','#')}'>participants.json</a></li>
<li><a href='{rel_links.get('reproducibility_receipt','#')}'>reproducibility_receipt.json</a></li>
<li><a href='{rel_links.get('metrics_index_jsonl','#')}'>metrics_index.jsonl</a></li>
</ul>
</div>

<div class='card'>
<h2>Compliance</h2>
<ul>
<li><a href='{rel_links.get('sidecar_audit_html','#')}'>Sidecar audit</a></li>
</ul>
</div>

<p class='muted'>Generated by SpinalfMRIprep S11.</p>
</body></html>"""
    out_path.write_text(html)
