"""S10: QC aggregation + release readiness.

Spec: .claude/specs/s11-qc-aggregation-and-release.md

14 deliverables across 4 tiers. Read-only consumer of S1–S9 artifacts.
Deterministic: same chain → byte-identical outputs.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import socket
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

ALL_STEPS = [
    ("S1", "S1_input_verify"),
    ("S2", "S2_anat_cordref"),
    # S2B: optional MP-PCA denoise (off by default). Clean PASS passthrough when
    # disabled; its policy SHA + provenance still reach the release receipt.
    ("S2B", "S2B_func_denoise"),
    ("S3", "S3_func_init_and_crop"),
    ("S4", "S4_func_motion_correction"),
    ("S5", "S5_func_distortion_correction"),
    ("S6", "S6_func_to_anat_registration"),
    ("S7", "S7_template_normalization"),
    ("S8", "S8_confounds_and_physio_regressors"),
    ("S9", "S9_primary_functional_derivatives"),
    # The former S10 (ROI timeseries + connectivity, analyst-owned) was removed
    # 2026-06-11; the QC-aggregation/release step was renumbered S11 -> S10.
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


def _norm_subject(sub: Any) -> Optional[str]:
    """Canonical subject label: drop `sub-` prefix; drop synthetic ids.

    S1 (and a few orchestrators) emit ``subject="all"`` as a synthetic
    per-dataset row; that's not a real participant and pollutes
    participant tables + run inventory if kept. Audit ref B2 + B3.
    """
    if sub is None:
        return None
    s = str(sub).strip()
    if s.startswith("sub-"):
        s = s[4:]
    if s in ("", "all", "*", "None"):
        return None
    return s


def _norm_session(ses: Any) -> Optional[str]:
    """Canonical session label: drop `ses-` prefix; empty string → None.

    Upstream steps disagree: S2 emits ``"01"``, S4 emits ``"ses-01"``,
    S1 emits ``None``. Without normalisation, run_inventory groupby
    treats them as distinct rows. Audit ref B3.
    """
    if ses is None:
        return None
    s = str(ses).strip()
    if s.startswith("ses-"):
        s = s[4:]
    if s in ("", "None"):
        return None
    return s


def _flat_run_records(chain_qc: dict[str, dict[str, dict]]) -> list[dict]:
    """Flatten chain_qc into per-(step, run) records.

    Subject + session IDs are normalised to bare labels (no `sub-` /
    `ses-` prefix). Synthetic `subject="all"` records (S1 dataset
    rollups, etc.) are dropped — they're not real participants.
    """
    records: list[dict] = []
    for step_short, by_ds in chain_qc.items():
        for ds_key, qc in by_ds.items():
            for r in qc.get("runs", []):
                sub = _norm_subject(r.get("subject"))
                if sub is None:
                    continue
                rec = {
                    "step": step_short,
                    "dataset_key": ds_key,
                    "subject": sub,
                    "session": _norm_session(r.get("session")),
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


def _build_metrics_index_tsv(records: list[dict], out_path: Path) -> int:
    """Emit metrics_index.tsv in MRIQC long-format:
    ``step, dataset_key, subject, session, run_id, status, metric, value``.

    One row per (record, metric). Numeric values only; non-numeric
    metric dicts are skipped (timeseries paths etc. don't belong here).
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for r in records:
        metrics = r.get("metrics") or {}
        for k, v in metrics.items():
            if v is None:
                continue
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                if not np.isfinite(v):
                    continue
                rows.append({
                    "step": r.get("step"),
                    "dataset_key": r.get("dataset_key"),
                    "subject": r.get("subject"),
                    "session": r.get("session") or "",
                    "run_id": r.get("run_id"),
                    "status": r.get("status"),
                    "metric": k,
                    "value": float(v),
                })
    if not rows:
        out_path.write_text(
            "step\tdataset_key\tsubject\tsession\trun_id\tstatus\tmetric\tvalue\n"
        )
        return 0
    df = pd.DataFrame(rows)
    df.to_csv(out_path, sep="\t", index=False, float_format="%.6g")
    return len(rows)


_BOLD_STEPS = {"S3", "S4", "S5", "S6", "S7", "S8", "S9"}


def _build_run_inventory(
    records: list[dict], out_tsv: Path, out_png: Path,
) -> int:
    """subjects × runs pivot: per-(subject, run) overall pass/warn/fail
    aggregated across steps.

    S1 emits per-dataset summary rows; S2 emits per-anat records. Both
    pollute the BOLD-run inventory. Restrict to S3..S9 (the BOLD chain).
    """
    out_tsv.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(records)
    if df.empty:
        out_tsv.write_text("subject\trun_id\tdataset_key\tn_steps\tworst_status\n")
        return 0
    df = df[df["step"].isin(_BOLD_STEPS)]
    df = df.dropna(subset=["run_id"])
    # session as canonical key — None → empty string so groupby doesn't drop
    df = df.assign(session=df["session"].fillna(""))
    grouped = df.groupby(["dataset_key", "subject", "session", "run_id"],
                         dropna=False)
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
    """Build status-heatmap + per-step pass-rate + per-metric boxplot
    series for the group dashboard (MRIQC convention).
    """
    df = pd.DataFrame(records)
    if df.empty:
        return {"empty": True}
    df = df.dropna(subset=["subject", "step"])
    subjects = sorted(df["subject"].astype(str).unique())
    steps = [s for s, _ in ALL_STEPS]
    # 1. Status matrix: subject × step (worst across runs)
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
    # 2. Per-step pass-rate
    pass_rates: dict[str, float] = {}
    for step in steps:
        col = df[df["step"] == step]["status"].dropna()
        if len(col):
            pass_rates[step] = float((col == "PASS").mean())
    # 3. Per-metric boxplot series (policy-declared)
    metric_paths = (policy.get("aggregation", {})
                          .get("group_dashboard", {})
                          .get("metric_distributions", []) or [])
    metric_series: list[dict] = []
    for path in metric_paths:
        parts = path.split(".")
        if len(parts) != 3 or parts[1] != "metrics":
            continue
        step, _, key = parts
        sel = df[df["step"] == step]
        rows = []
        for _, r in sel.iterrows():
            m = r.get("metrics") or {}
            if not isinstance(m, dict):
                continue
            v = m.get(key)
            if v is None:
                continue
            try:
                vf = float(v)
            except (TypeError, ValueError):
                continue
            if not np.isfinite(vf):
                continue
            rows.append({
                "dataset_key": r.get("dataset_key"),
                "subject": r.get("subject"),
                "value": vf,
            })
        metric_series.append({
            "path": path, "step": step, "key": key,
            "values": rows,
        })
    return {
        "matrix": matrix,
        "pass_rates": pass_rates,
        "metric_series": metric_series,
    }


def _render_metric_boxplots_png(
    metric_series: list[dict], out_path: Path,
) -> Optional[Path]:
    """Render one boxplot per declared metric (MRIQC convention),
    subject dots colored by dataset (Kaptan 2023).
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    valid = [s for s in metric_series if s["values"]]
    if not valid:
        return None
    n = len(valid)
    fig, axes = plt.subplots(1, n, figsize=(max(4, 3.2 * n), 4.2))
    if n == 1:
        axes = [axes]
    # Color palette per dataset_key
    all_ds = sorted({v["dataset_key"] for s in valid for v in s["values"]})
    cmap = plt.get_cmap("tab10")
    ds_color = {ds: cmap(i % 10) for i, ds in enumerate(all_ds)}
    for ax, s in zip(axes, valid):
        vals = [v["value"] for v in s["values"]]
        ax.boxplot(vals, vert=True, widths=0.5,
                   boxprops=dict(facecolor="#eef", color="#444"),
                   medianprops=dict(color="#cc2222"),
                   whiskerprops=dict(color="#444"),
                   capprops=dict(color="#444"),
                   flierprops=dict(marker=""), patch_artist=True)
        # Jittered dots
        rng = np.random.default_rng(42)
        x_jitter = 1 + (rng.random(len(vals)) - 0.5) * 0.20
        colors = [ds_color[v["dataset_key"]] for v in s["values"]]
        ax.scatter(x_jitter, vals, c=colors, s=22, alpha=0.85, edgecolor="white",
                   linewidth=0.4, zorder=3)
        ax.set_title(f"{s['step']} · {s['key']}", fontsize=9)
        ax.set_xticks([])
        ax.grid(axis="y", alpha=0.25)
    # Dataset legend below
    legend_handles = [plt.Line2D([0], [0], marker='o', color='w',
                                 label=ds[:32], markerfacecolor=ds_color[ds],
                                 markersize=7)
                      for ds in all_ds]
    fig.legend(handles=legend_handles, loc="lower center",
               ncol=min(3, len(all_ds)), fontsize=7,
               bbox_to_anchor=(0.5, -0.02))
    fig.suptitle("Per-metric distributions across cohort", fontsize=11)
    fig.tight_layout(rect=(0, 0.07, 1, 0.96))
    fig.savefig(out_path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return out_path


def _render_group_dashboard_html(
    data: dict, out_path: Path,
) -> None:
    """Group QC dashboard HTML: status heatmap + pass-rate bars + per-metric
    boxplot panel (rendered as PNG sibling).
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if data.get("empty"):
        out_path.write_text("<html><body><p>No data.</p></body></html>")
        return
    matrix = data["matrix"]
    pass_rates = data["pass_rates"]
    metric_series = data.get("metric_series", []) or []

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

    box_png = out_path.with_name("group_qc_metric_distributions.png")
    box_out = _render_metric_boxplots_png(metric_series, box_png)
    box_html = (f"<img src='{box_out.name}' alt='metric distributions' "
                f"style='max-width:100%;border:1px solid #ddd' />"
                if box_out is not None else
                "<p><em>No metric distributions available "
                "(policy.aggregation.group_dashboard.metric_distributions empty "
                "or no matching values).</em></p>")

    html = f"""<!DOCTYPE html><html><head><meta charset='utf-8'>
<title>SpinePrep — Group QC Dashboard</title>
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
<h2>Metric distributions</h2>
{box_html}
</body></html>"""
    out_path.write_text(html, encoding="utf-8")


# ---------------------------------------------------------------------------
# Per-subject HTML
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Tier 2: cord-novel cohort views
# ---------------------------------------------------------------------------


def _build_cohort_coverage_matrix(
    out_dir: Path, records: list[dict], policy: dict,
    out_tsv: Path, out_png: Path,
) -> int:
    """Per-(subject,run) vertebral-level coverage from S7's authoritative
    ``vertebral_level_coverage`` metric (audit F6).

    Previously sourced from S9 ``*_desc-tsnr_per_level.tsv``, which
    conflated "level in FOV" with "S9 tSNR was computed at this level"
    — same number most of the time, but the wrong concept for a
    coverage matrix. S7's metric is the registration-confirmed list of
    PAM50 vertebral labels intersecting the warped EPI FOV.

    Each subject × vertebral level cell is GREEN if any run for that
    subject covers it (Principle 10 — heterogeneity is the test).
    """
    out_tsv.parent.mkdir(parents=True, exist_ok=True)
    s7_recs = [r for r in records if r.get("step") == "S7"
               and r.get("status") in ("PASS", "WARN")]
    rows = []
    for r in s7_recs:
        sub = r.get("subject"); ds = r.get("dataset_key"); rid = r.get("run_id")
        m = r.get("metrics") or {}
        levels = m.get("vertebral_level_coverage") or []
        per_level_dice = m.get("cord_dice_per_level") or {}
        for lvl in levels:
            try:
                lvl_i = int(lvl)
            except (TypeError, ValueError):
                continue
            rows.append({
                "dataset_key": ds,
                "subject": sub,
                "run_id": rid,
                "level": lvl_i,
                "cord_dice": float(per_level_dice.get(str(lvl_i),
                                   per_level_dice.get(lvl_i, np.nan))),
            })
    if not rows:
        out_tsv.write_text("dataset_key\tsubject\trun_id\tlevel\tcord_dice\n")
        return 0
    cov_df = pd.DataFrame(rows)
    cov_df.to_csv(out_tsv, sep="\t", index=False)
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        n_levels_policy = int(policy.get("cohort_views", {})
                              .get("coverage_matrix", {})
                              .get("n_levels", 8))
        max_level = max(n_levels_policy, int(cov_df["level"].max()))
        all_levels = list(range(1, max_level + 1))
        # Pivot to (subject) × (level): coverage = any run covers
        pivot = cov_df.pivot_table(
            index=["dataset_key", "subject"], columns="level",
            values="run_id", aggfunc="count",
        ).reindex(columns=all_levels)
        covered = (pivot > 0).astype(int).fillna(0)
        fig, ax = plt.subplots(figsize=(max(7, len(all_levels) * 0.8),
                                        max(3, len(covered) * 0.30 + 1.5)))
        ax.imshow(covered.to_numpy(), cmap="Greens", vmin=0, vmax=1,
                  aspect="auto")
        ax.set_xticks(range(len(all_levels)))
        ax.set_xticklabels([(f"C{l}" if l <= 8 else f"T{l-8}")
                            for l in all_levels])
        ax.set_yticks(range(len(covered)))
        ax.set_yticklabels([f"{ds[:18]}/sub-{sub}"
                            for ds, sub in covered.index], fontsize=7)
        ax.set_xlabel("Vertebral level (S7 vertebral_level_coverage)")
        ax.set_title(f"Cohort coverage matrix — {covered.shape[0]} (dataset, subject) rows")
        # Cell annotations: number of runs covering
        for i in range(covered.shape[0]):
            for j in range(covered.shape[1]):
                n_runs_here = int(pivot.iloc[i, j]) if not pd.isna(pivot.iloc[i, j]) else 0
                if n_runs_here > 0:
                    ax.text(j, i, str(n_runs_here),
                            ha="center", va="center", fontsize=7,
                            color="#0a0" if n_runs_here >= 2 else "#444")
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
    """Cohort tSNR per spinal level — Kaptan 2023 box-plot convention:
    one box per (level), subject dots overlaid, colored by dataset.

    Source: S9 ``*_desc-tsnr_per_level.tsv`` (mean_tsnr per level).
    Color/y-range default 0..30 (cord realistic; previously 0..50 left
    the high end unused).
    """
    out_tsv.parent.mkdir(parents=True, exist_ok=True)
    s9_recs = [r for r in records if r.get("step") == "S9"
               and r.get("status") in ("PASS", "WARN")]
    rows = []
    for r in s9_recs:
        sub = r.get("subject"); ds = r.get("dataset_key"); rid = r.get("run_id")
        tsv = (out_dir / "derivatives" / "spineprep" / ds
               / f"sub-{sub}" / "func"
               / f"{rid}_desc-tsnr_per_level.tsv")
        if not tsv.exists():
            tsv_alt = (out_dir / "derivatives" / "spineprep"
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
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        cr = policy.get("cohort_views", {}).get("tsnr_heatmap", {}).get(
            "color_range", [0, 30])
        levels = sorted(df["level"].unique())
        datasets = sorted(df["dataset_key"].unique())
        cmap = plt.get_cmap("tab10")
        ds_color = {ds: cmap(i % 10) for i, ds in enumerate(datasets)}
        fig, ax = plt.subplots(figsize=(max(7, len(levels) * 0.9), 5.2))
        # Box per level
        per_level = [df[df["level"] == lvl]["mean_tsnr"].to_numpy()
                     for lvl in levels]
        ax.boxplot(per_level, positions=range(len(levels)),
                   widths=0.55,
                   boxprops=dict(facecolor="#eef", color="#444"),
                   medianprops=dict(color="#cc2222"),
                   whiskerprops=dict(color="#444"),
                   capprops=dict(color="#444"),
                   flierprops=dict(marker=""), patch_artist=True)
        rng = np.random.default_rng(7)
        for j, lvl in enumerate(levels):
            sub_df = df[df["level"] == lvl]
            xj = j + (rng.random(len(sub_df)) - 0.5) * 0.30
            ax.scatter(xj, sub_df["mean_tsnr"],
                       c=[ds_color[ds] for ds in sub_df["dataset_key"]],
                       s=22, alpha=0.85, edgecolor="white",
                       linewidth=0.4, zorder=3)
        ax.set_xticks(range(len(levels)))
        ax.set_xticklabels([f"C{lvl}" if lvl <= 8 else f"T{lvl-8}"
                            for lvl in levels])
        ax.set_xlabel("Spinal level")
        ax.set_ylabel("Median tSNR (S9)")
        ax.set_ylim(cr[0], cr[1])
        ax.grid(axis="y", alpha=0.25)
        ax.set_axisbelow(True)
        legend_handles = [plt.Line2D([0], [0], marker='o', color='w',
                                     label=ds[:32], markerfacecolor=ds_color[ds],
                                     markersize=7)
                          for ds in datasets]
        ax.legend(handles=legend_handles, loc="upper right", fontsize=7,
                  frameon=True, framealpha=0.9)
        ax.set_title(f"Cohort cord tSNR by level — {df['subject'].nunique()} "
                     f"subjects, {len(df)} (subject,level) observations")
        fig.tight_layout()
        fig.savefig(out_png, dpi=120, bbox_inches="tight")
        plt.close(fig)
    except Exception:
        pass
    return len(df)


# ---------------------------------------------------------------------------
# Tier 3: publication & reproducibility
# ---------------------------------------------------------------------------


_VERSION_RE = __import__("re").compile(r"^\d+\.\d+(?:\.\d+)?$")


def _parse_version_lines(text: str) -> Optional[str]:
    """Return the first line that looks like a semver-ish version."""
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        if _VERSION_RE.match(line):
            return line
        # Strip a "version: X" prefix
        for prefix in ("version:", "Version:", "FSL version"):
            if line.lower().startswith(prefix.lower()):
                tail = line.split(":", 1)[-1].strip()
                if _VERSION_RE.match(tail):
                    return tail
    return None


def _detect_fsl_version() -> Optional[str]:
    """Canonical: ``$FSLDIR/etc/fslversion``. ``fslversion`` command output
    starts with the env-var banner ``FSLDIR:  /usr/local/fsl`` which used
    to leak into the receipt as the captured version (audit B10).
    """
    fsldir = os.environ.get("FSLDIR")
    if fsldir:
        canon = Path(fsldir) / "etc" / "fslversion"
        if canon.exists():
            v = canon.read_text().strip().split(":", 1)[0].strip()
            if v:
                return v
    try:
        out = subprocess.run(["fslversion"], capture_output=True, text=True, timeout=10)
        merged = (out.stdout or "") + "\n" + (out.stderr or "")
        parsed = _parse_version_lines(merged)
        if parsed:
            return parsed
    except Exception:
        pass
    return None


def _detect_sct_version() -> Optional[str]:
    try:
        out = subprocess.run(["sct_version"], capture_output=True, text=True, timeout=10)
        merged = (out.stdout or "") + "\n" + (out.stderr or "")
        parsed = _parse_version_lines(merged)
        if parsed:
            return parsed
        # Fallback: first non-empty line
        for line in merged.splitlines():
            if line.strip():
                return line.strip()
    except Exception:
        pass
    return None


def _detect_ants_version() -> Optional[str]:
    """ANTs version (S5 SyN distortion correction). Prefers a standalone
    ``antsRegistration``; falls back to the copy SCT bundles as
    ``isct_antsRegistration``. SCT's build strips the version to ``0.0.0.0`` --
    in that case we anchor on the compile date (the real provenance is "the ANTs
    bundled with this SCT", which the receipt already records via sct_version)."""
    import re as _re
    for binary in ("antsRegistration", "isct_antsRegistration"):
        try:
            out = subprocess.run([binary, "--version"], capture_output=True,
                                 text=True, timeout=10)
            merged = (out.stdout or "") + "\n" + (out.stderr or "")
            ver = None
            compiled = None
            for line in merged.splitlines():
                low = line.lower()
                if "ants version" in low:
                    m = _re.search(r"\d+\.\d+(?:\.\d+){0,2}", line)
                    if m:
                        ver = m.group(0)
                elif low.strip().startswith("compiled"):
                    compiled = line.split(":", 1)[-1].strip()
            if ver:
                # SCT's bundled build reports the 0.0.0.0 placeholder; tag it so
                # the receipt isn't misread as a real upstream release.
                if set(ver.split(".")) <= {"0"}:
                    label = "SCT-bundled" if binary.startswith("isct_") else "unknown-build"
                    return (f"{ver} ({label}; compiled {compiled})" if compiled
                            else f"{ver} ({label})")
                return ver
            parsed = _parse_version_lines(merged)
            if parsed:
                return parsed
        except Exception:
            pass
    return None


def _detect_mrtrix_version() -> Optional[str]:
    """MRtrix3 version (used for S2B MP-PCA denoising via dwidenoise). dwidenoise
    -version prints '== dwidenoise <ver> =='."""
    try:
        out = subprocess.run(["dwidenoise", "-version"], capture_output=True,
                             text=True, timeout=10)
        merged = (out.stdout or "") + "\n" + (out.stderr or "")
        import re as _re
        m = _re.search(r"dwidenoise\s+(\d+\.\d+(?:\.\d+)?)", merged)
        if m:
            return m.group(1)
        parsed = _parse_version_lines(merged)
        if parsed:
            return parsed
    except Exception:
        pass
    return None


def _hash_policy_yaml(project_root: Path, step_full: str) -> Optional[str]:
    """SHA256 of the step's policy YAML — source of truth regardless of
    chain-runner symlink topology (audit B6).

    Tries ``policy/<step_full>.yaml`` first; falls back to a single
    glob match of ``policy/<short>_*.yaml`` (S8's file is named
    ``S8_confounds.yaml`` while its step full-name is
    ``S8_confounds_and_physio_regressors``).
    """
    pol_dir = project_root / "policy"
    direct = pol_dir / f"{step_full}.yaml"
    candidates: list[Path] = []
    if direct.exists():
        candidates.append(direct)
    else:
        short = step_full.split("_", 1)[0]
        candidates = sorted(pol_dir.glob(f"{short}_*.yaml"))
    if not candidates:
        return None
    try:
        return hashlib.sha256(candidates[0].read_bytes()).hexdigest()
    except Exception:
        return None


def _build_reproducibility_receipt(
    out_dir: Path, chain_qc: dict, out_path: Path, policy: dict,
) -> dict:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    recipe = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "hostname": socket.gethostname(),
        "os": platform.platform(),
        "python_version": platform.python_version(),
        "sct_version": _detect_sct_version(),
        "fsl_version": _detect_fsl_version(),
        "ants_version": _detect_ants_version(),      # S5 SyN distortion correction
        "mrtrix_version": _detect_mrtrix_version(),   # S2B MP-PCA denoise (dwidenoise)
    }
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
    # Pipeline Git SHA
    project_root = (out_dir.parent.parent if out_dir.name.startswith("wf_")
                    else Path.cwd())
    # Prefer a build-time stamp (baked into the container by the Dockerfile
    # --build-arg GIT_SHA), since the image has no .git to query. Fall back to a
    # live git query for source checkouts.
    env_sha = os.environ.get("SPINEPREP_GIT_SHA")
    if env_sha:
        recipe["pipeline_git_sha"] = env_sha
        recipe["pipeline_git_describe"] = (
            os.environ.get("SPINEPREP_GIT_DESCRIBE") or env_sha)
    else:
        try:
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
    # Per-step policy SHA: hash the YAML directly so symlinked workfolders
    # don't shadow upstream steps.
    recipe["policy_sha256_per_step"] = {
        short: _hash_policy_yaml(project_root, full)
        for short, full in ALL_STEPS + [("S10", "S10_qc_aggregation_and_release")]
    }
    out_path.write_text(json.dumps(recipe, indent=2, default=str))
    return recipe


def _build_citation_cff(
    out_path: Path, recipe: dict, policy: dict,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cff_version = recipe.get("pipeline_git_describe") or "0.0.0"
    cff = f"""cff-version: 1.2.0
message: "If you use SpinePrep, please cite the methods listed in references.bib."
title: SpinePrep
abstract: >
  Cervical spinal cord fMRI preprocessing pipeline. BIDS-Derivatives
  compliant. Integrates SCT, FSL PNM, and PAM50 template.
authors:
  - family-names: Sharifi
    given-names: Kiomars
    affiliation: Balgrist University Hospital / ETH Zurich / UZH
version: {cff_version}
date-released: "{recipe.get('timestamp_utc', '')[:10]}"
"""
    out_path.write_text(cff)


def _build_references_bib(out_path: Path) -> None:
    """Auto-bibliography of every methods reference used in S2..S9."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    bib = r"""@article{kaptan2023,
  title={Reliability of resting-state functional connectivity in the human spinal cord: Assessing the impact of distinct noise sources},
  author={Kaptan, M. and Horn, U. and Vannesjo, S.J. and Mildner, T. and Weiskopf, N. and Finsterbusch, J. and Brooks, J.C.W. and Eippert, F.},
  journal={NeuroImage},
  volume={275},
  pages={120152},
  year={2023},
  doi={10.1016/j.neuroimage.2023.120152}
}

@article{veraart2016,
  title={Denoising of diffusion MRI using random matrix theory},
  author={Veraart, J. and Novikov, D.S. and Christiaens, D. and Ades-Aron, B. and Sijbers, J. and Fieremans, E.},
  journal={NeuroImage},
  volume={142},
  pages={394--406},
  year={2016},
  doi={10.1016/j.neuroimage.2016.08.016}
}

@article{hemmerling2025,
  title={Data-driven denoising in spinal cord fMRI with principal component analysis (SpinalCompCor)},
  author={Hemmerling, K.J. and others},
  journal={bioRxiv},
  year={2025},
  doi={10.1101/2025.01.23.634596}
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

@article{barry2014,
  title={Resting-state functional connectivity in the human spinal cord},
  author={Barry, R.L. and Smith, S.A. and Dula, A.N. and Gore, J.C.},
  journal={eLife},
  volume={3},
  pages={e02812},
  year={2014},
  doi={10.7554/eLife.02812}
}

@article{power2014,
  title={Methods to detect, characterize, and remove motion artifact in resting state fMRI},
  author={Power, J.D. and others},
  journal={NeuroImage},
  year={2014}
}

@article{cospine2025,
  title={CoSpine open access simultaneous cortico-spinal fMRI database of thermal pain and motor tasks},
  author={Wei, Z. and others},
  journal={Scientific Data},
  year={2025},
  doi={10.1038/s41597-025-05982-x}
}

@article{sct2017,
  title={SCT: Spinal Cord Toolbox, an open-source software for processing spinal cord MRI data},
  author={De Leener, B. and others},
  journal={NeuroImage},
  year={2017}
}
"""
    out_path.write_text(bib)


def _detect_code_url(project_root: Path) -> Optional[str]:
    """Resolve the GitHub CodeURL from ``git remote get-url origin``.
    Returns ``None`` when no remote is configured (previous behaviour
    was a placeholder ``[org]`` literal — audit B14).
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(project_root), "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=5,
        )
        url = out.stdout.strip()
        if not url:
            return None
        # Normalise SSH → HTTPS (git@github.com:org/repo.git → https://github.com/org/repo)
        if url.startswith("git@") and ":" in url:
            host, path = url.split(":", 1)
            host = host.split("@", 1)[-1]
            url = f"https://{host}/{path}"
        if url.endswith(".git"):
            url = url[:-4]
        return url
    except Exception:
        return None


def _build_dataset_description(
    out_dir: Path, chain_qc: dict, recipe: dict, out_path: Path,
) -> None:
    """BIDS-Derivatives v1.11 manifest. When CITATION.cff is present
    alongside this file, the spec requires Authors / License /
    HowToAcknowledge / ReferencesAndLinks to live in CFF, not here
    (audit B13). We emit only the GeneratedBy + SourceDatasets fields
    and let CITATION.cff own the rest.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    project_root = (out_dir.parent.parent if out_dir.name.startswith("wf_")
                    else Path.cwd())
    code_url = _detect_code_url(project_root)
    source_datasets: list[dict] = []
    for ds_key, qc in (chain_qc.get("S2") or chain_qc.get("S1") or {}).items():
        br = qc.get("bids_root")
        if br:
            source_datasets.append({"URL": f"file://{br}", "Description": ds_key})
    generated_by: dict[str, Any] = {
        "Name": "SpinePrep",
        "Version": recipe.get("pipeline_git_describe") or "0.0.0",
        "Description": "Cervical spinal cord fMRI preprocessing pipeline",
        "Container": {
            "Type": "host",
            "Tag": recipe.get("pipeline_git_sha") or "unknown",
        },
    }
    if code_url:
        generated_by["CodeURL"] = code_url
    desc = {
        "Name": "SpinePrep derivatives",
        "BIDSVersion": "1.11.0",
        "DatasetType": "derivative",
        "GeneratedBy": [generated_by],
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
    # n_runs is a count of BOLD runs (S3..S9); S1/S2 records pollute it.
    df_runs = df[df["step"].isin(_BOLD_STEPS)].dropna(subset=["run_id"])
    rows = []
    for (sub, ds), g in df.groupby(["subject", "dataset_key"]):
        # Per-run worst status from the BOLD-step subset only.
        g_runs = df_runs[(df_runs["subject"] == sub) & (df_runs["dataset_key"] == ds)]
        run_groups = g_runs.groupby("run_id")
        n_pass = sum(1 for _, gg in run_groups
                     if all(s == "PASS" for s in gg["status"]))
        n_warn = sum(1 for _, gg in run_groups
                     if not all(s == "PASS" for s in gg["status"])
                     and not any(s == "FAIL" for s in gg["status"]))
        n_failed = sum(1 for _, gg in run_groups
                       if any(s == "FAIL" for s in gg["status"]))
        n_runs = run_groups.ngroups
        # Treat None-session as "1 implicit session" (BIDS single-session
        # subjects); count distinct named sessions otherwise.
        named_sessions = {s for s in g_runs["session"].dropna().unique() if s}
        n_sessions = max(1, len(named_sessions))
        # Aggregate metrics
        s4 = g[g["step"] == "S4"]
        s9 = g[g["step"] == "S9"]
        mean_fd = np.nan
        if not s4.empty:
            # S4 emits both mean_fd_mm and max_fd_mm; we want the
            # per-run mean averaged across runs (Power 2014 convention).
            fds = [r.get("mean_fd_mm") for r in s4["metrics"] if isinstance(r, dict)]
            fds = [f for f in fds if f is not None and np.isfinite(f)]
            if fds:
                mean_fd = float(np.mean(fds))
        median_tsnr = np.nan
        if not s9.empty:
            ts = [r.get("tsnr_post_median") for r in s9["metrics"] if isinstance(r, dict)]
            ts = [t for t in ts if t is not None]
            if ts:
                median_tsnr = float(np.median(ts))
        # FD is reported but is NOT an inclusion criterion. The 0.5 mm cut was
        # Power 2012's brain value, mis-attributed to Kaptan 2023 (which uses no
        # FD at all), and it sits at this cohort's own FD median -- it flagged
        # 265/467 runs. S4 removed the equivalent gate on 2026-07-16; the same
        # reasoning applies here. mean_fd_mm stays as a descriptive column.
        recommend = "include"
        if (np.isfinite(median_tsnr) and median_tsnr < tsnr_thresh) or n_failed > 0:
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
            "included_recommendation": recommend,
        })
    out_df = pd.DataFrame(rows).sort_values(["dataset_key", "participant_id"])
    out_df.to_csv(out_tsv, sep="\t", index=False)
    # Sidecar (BIDS spec requires JSON for non-standard columns)
    sidecar = {
        "participant_id": {"Description": "BIDS participant identifier"},
        "dataset_key": {"Description": "SpinePrep dataset key (multi-source aggregation)"},
        "n_runs": {"Description": "Number of BOLD runs successfully processed"},
        "n_sessions": {"Description": "Number of MRI sessions for this participant"},
        "n_passed": {"Description": "Number of runs that PASS across all S2..S9 steps"},
        "n_warn": {"Description": "Number of runs with at least one step WARN"},
        "n_failed": {"Description": "Number of runs with at least one step FAIL"},
        "mean_fd_mm": {
            "Description": ("Mean framewise displacement (mm) across runs. Descriptive "
                            "only: NOT an inclusion criterion. No cord-calibrated FD "
                            "threshold exists; the commonly quoted 0.5 mm is a "
                            "brain-derived value (Power 2012) that sits at this "
                            "cohort's own median."),
            "Units": "mm",
        },
        "median_in_cord_tsnr": {"Description": "Median in-cord tSNR (S9)"},
        "included_recommendation": {
            "Description": "Pipeline recommendation for cohort inclusion: 'include' or 'review'",
            "Levels": {
                "include": "no failed steps and in-cord tSNR above the reporting floor",
                "review": f"tSNR < {tsnr_thresh} OR any failed run",
            },
        },
    }
    out_json.write_text(json.dumps(sidecar, indent=2))
    return len(out_df)


def _read_policy_yaml(project_root: Path, step_full: str) -> dict:
    pol = project_root / "policy" / f"{step_full}.yaml"
    if not pol.exists():
        return {}
    try:
        import yaml as _yaml
        return _yaml.safe_load(pol.read_text()) or {}
    except Exception:
        return {}


def _build_methods_manifest(
    out_dir: Path, recipe: dict, policy: dict,
    out_md: Path, out_tex: Path, out_html: Path,
) -> str:
    """Auto-emit Methods boilerplate as CITATION.{md,tex,html}.

    Naming + location follow the NiPreps convention (logs/CITATION.*;
    fMRIPrep / sMRIPrep / ASLPrep / dMRIPrep / NiBabies all use this).
    Policy values are read from disk so the manifest doesn't drift
    silently from the actual pipeline (audit B9). Pandoc converts
    md → tex/html (audit B8 — the previous regex one-liner produced
    malformed LaTeX).
    """
    project_root = (out_dir.parent.parent if out_dir.name.startswith("wf_")
                    else Path.cwd())
    # Pull live values from the policy files (so the manifest tracks reality)
    s4_pol = _read_policy_yaml(project_root, "S4_func_motion_correction")
    s5_pol = _read_policy_yaml(project_root, "S5_func_distortion_correction")
    s6_pol = _read_policy_yaml(project_root, "S6_func_to_anat_registration")
    s8_pol = _read_policy_yaml(project_root, "S8_confounds_and_physio_regressors")
    s9_pol = _read_policy_yaml(project_root, "S9_primary_functional_derivatives")

    sigma = s9_pol.get("smoothing", {}).get("sigma_mm", [1, 1, 5])
    sigma_str = "×".join(str(s) for s in sigma)
    # These flags decide what the boilerplate may CLAIM. The text below is
    # published as "reuse verbatim", so every sentence has to match what the
    # shipped policy actually does. Before 2026-07-19 it described FD censoring
    # at 0.5 mm (never configured -- both source keys are absent or null, so the
    # `or 0.5` fallback always fired), SyN as the S5 default (now `none`),
    # smoothing and PAM50 4D output (both disabled), and SpinalCompCor (off).
    fd_thr = s8_pol.get("outlier_gating", {}).get("fd_outlier_threshold_mm")
    fd_censoring = fd_thr is not None
    smoothing_on = bool(s9_pol.get("smoothing", {}).get("enabled", False))
    pam50_4d_on = bool(s9_pol.get("pam50_4d_output", {}).get("enabled", False))
    spcc_on = bool(s8_pol.get("spinalcompcor", {}).get("enabled", False))
    s5_fallback = str(s5_pol.get("mode_selection", {}).get("fallback_mode")
                      or s5_pol.get("fallback_mode") or "none")
    csf_n_pc = s8_pol.get("csf_acompcor", {}).get("n_components", 5)

    if s5_fallback == "none":
        s5_fallback_note = (
            "That is, runs without a reversed-phase pair are passed through "
            "uncorrected and reported as distortion-limited rather than "
            "failed, which is the cord field's own practice; held-out "
            "validation against the measured field showed image-based SyN "
            "recovered only part of it and displaced the cord further on a "
            "quarter of runs.")
    else:
        s5_fallback_note = (
            "Runs without a fieldmap that exceed the TopUp-calibrated "
            "displacement ceiling are flagged \"distortion-limited\" rather "
            "than failed.")

    if fd_censoring:
        outlier_desc = (f" (Power 2014 [@power2014], FD > {fd_thr} mm "
                        "+ Tukey IQR DVARS and refRMS)")
    else:
        outlier_desc = (" flagged on Tukey IQR fences over DVARS and refRMS "
                        "(intensity-based, following the cord convention of "
                        "Kaptan 2023 [@kaptan2023] and Dabbagh 2024 "
                        "[@dabbagh2024]; FD does not censor)")

    spcc_clause = ("; (f) SpinalCompCor (Hemmerling 2025 [@hemmerling2025])"
                   if spcc_on else "")
    n_conf_families = "Six" if spcc_on else "Five"

    if smoothing_on:
        s9_desc = (f"Cord-aware Gaussian smoothing via SCT "
                   f"`sct_smooth_spinalcord` (σ = {sigma_str} mm in R-L, A-P, "
                   f"S-I; Eippert 2017 anisotropic principle [@eippert2017]).")
    else:
        s9_desc = ("No spatial smoothing is applied. Smoothing is an analysis "
                   "choice rather than neutral preprocessing and is left to "
                   "the analyst, following fMRIPrep; it is available as an "
                   "opt-in knob.")
    s9_outputs = ("native + PAM50-space BOLD" if pam50_4d_on
                  else "the preprocessed BOLD in native space (no 4D template "
                       "resampling; the bidirectional warps and the PAM50 atlas "
                       "in native space are provided instead)")

    pipeline_v = recipe.get("pipeline_git_describe") or "0.0.0"
    sct_v = recipe.get("sct_version") or "n/a"
    fsl_v = recipe.get("fsl_version") or "n/a"
    mrtrix_v = recipe.get("mrtrix_version") or "n/a"
    nibabel_v = recipe.get("package_versions", {}).get("nibabel") or "n/a"

    # MP-PCA denoising (S2B) is opt-in and per-scope. Only describe it if it
    # actually ran in THIS release -- scan the release's S2B QC rather than the
    # shared policy default (which says off), so the boilerplate stays truthful.
    denoise_ran = False
    s2b_logs = out_dir / "logs" / "S2B_func_denoise"
    if s2b_logs.exists():
        for qc_path in s2b_logs.glob("*/qc.json"):
            try:
                import json as _json
                q = _json.loads(qc_path.read_text())
                if q.get("enabled") and q.get("runs"):
                    denoise_ran = True
                    break
            except Exception:
                continue
    denoise_para = (
        f"""**Thermal-noise denoising (S2B)**: Marchenko-Pastur PCA (MP-PCA)
denoising of the raw 4D BOLD via MRtrix3 `dwidenoise` {mrtrix_v}
(Veraart 2016 [@veraart2016]; Cordero-Grande 2019), applied before any
interpolation/realignment to preserve the i.i.d.-noise assumption, per
the cord-fMRI precedent of Kaptan 2023 [@kaptan2023]. A noise map and
in-cord tSNR gain are emitted per run.

""" if denoise_ran else "")

    md = f"""# Methods boilerplate (auto-generated by SpinePrep S10)

> Reuse this text verbatim in your methods section. Adapt only the
> dataset description and the citation format. Policy values shown
> here reflect what actually ran (read live from policy YAMLs).

**Pipeline**: SpinePrep {pipeline_v}.
**Tools**: Spinal Cord Toolbox {sct_v}; FSL {fsl_v}; NiBabel {nibabel_v}{"; MRtrix3 " + mrtrix_v if denoise_ran else ""}.

## Preprocessing

Cervical spinal cord BOLD data were preprocessed using SpinePrep,
a custom pipeline integrating Spinal Cord Toolbox (SCT) [@sct2017] and
FSL Physiological Noise Modelling [@brooks2008], with templates from
PAM50 [@deleener2018].

**Anatomical (S2)**: T1w / T2w / T2\\*-MEGRE images were segmented via
SCT contrast-agnostic spinal cord segmentation, labeled via
TotalSpineSeg, and registered to PAM50 using rootlets-based
registration [@valosek2024_rootlets] (falling back to disc labels).
Dual-role anatomical model: full-FOV primary anat (T1w/T2w) for
labeling and template registration; T2\\*-MEGRE secondary cordref for
functional registration.

{denoise_para}**Functional initialization (S3)**: BOLD reference image discovered via
fast cord segmentation; volume cropped to a cord-centered FOV.
Frame-level QC metrics (DVARS, refRMS) computed per Power 2014
[@power2014].

**Motion correction (S4)**: 2D slicewise translation (x, y) via SCT
`sct_fmri_moco`, regularized along Z. Per-slice translation parameters
emitted as 4D NIfTI for downstream confound use.

**No slice-timing correction (STC) is performed**, following standard
spinal-cord fMRI practice: the field's reference cord-only pipelines omit
it (Eippert 2017 [@eippert2017]; Kaptan 2023 [@kaptan2023]; Spinal Cord
Toolbox). The rationale is that resting-state and block-design signal is
low-frequency (< 0.1 Hz), where STC has little effect; event-related task
sensitivity is instead recovered with a hemodynamic temporal-derivative
regressor in the GLM; and STC's temporal interpolation interacts poorly
with the slice-wise motion and physiological correction that dominate the
cord noise budget (the reason the HCP minimal pipeline also omits STC).
Slice-timing metadata, when present in the BIDS sidecar, is used only to
assign each slice its cardiac/respiratory phase for the S8 RETROICOR
regressors.

**Distortion correction (S5)**: Per-run mode is chosen automatically from
the available fieldmaps: a reversed-phase EPI pair drives FSL TopUp;
otherwise the configured fallback is `{s5_fallback}`. {s5_fallback_note}
Cord A-P displacement per slice + cord Dice per slice emitted as QC.

**Functional-to-anat registration (S6)**: SCT `sct_register_multimodal`
with a cord-segmentation-driven three-stage recipe:
`centermassrot → columnwise → bsplinesyn`. This composition is SpinePrep's
own; SCT's default template chain is two stages, and the inserted
`columnwise` stage and higher iteration count are SpinePrep tuning for
cord-cropped EPI. Output: bidirectional warp
`from-bold_to-anat_xfm.nii.gz`.

**Template normalization (S7)**: Composed S2 (anat ↔ PAM50) and S6
(bold ↔ anat) warps via `sct_concat_transfo`; refined the composite at
the EPI level via a second `sct_register_multimodal` pass
(`slicereg + bsplinesyn`). PAM50 atlas warped into native func space;
no 4D BOLD resampling.

**Confounds (S8)**: {n_conf_families} families assembled per BIDS-Derivatives
convention: (a) motion (trans_x/y + derivatives + FD); (b)
outlier one-hot regressors{outlier_desc}; (c) slicewise CSF aCompCor,
the top {csf_n_pc} principal components of the CSF signal per slice
(Behzadi 2007 [@behzadi2007]; per-slice cord application after Barry 2014
[@barry2014]); (d) RETROICOR (FSL PNM popp + pnm_evs)
[@brooks2008]; (e) cosine basis up to 1/100 Hz{spcc_clause}. All emitted as
columns; the BOLD itself is not regressed. FD is reported but does not
censor by default: no cord-calibrated FD threshold exists.

**Primary functional derivatives (S9)**: {s9_desc} Output: {s9_outputs},
per-vertebral-level tSNR TSV.

_ROI timeseries, connectivity, and reliability (the removed ROI analysis) are
analyst-owned downstream analysis and are not part of this preprocessing
release as of 2026-06-11._

## Citation

The boilerplate above is licensed CC0 — reuse it verbatim. Cite the
methods listed in `CITATION.bib` (auto-generated alongside this file).

## Reproducibility

Per-step policy SHA256 + pipeline Git SHA captured in
`reproducibility_receipt.json`. Tool versions: SCT {sct_v}, FSL {fsl_v},
NiBabel {nibabel_v}{", MRtrix3 " + mrtrix_v if denoise_ran else ""}. The
JSON receipt additionally records the detected ANTs and MRtrix3 versions
for the full environment inventory.
"""

    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(md)

    # Pandoc → LaTeX + HTML (NiPreps convention)
    def _pandoc(target: Path, fmt: str) -> bool:
        try:
            r = subprocess.run(
                ["pandoc", "-f", "markdown", "-t", fmt, "-o", str(target)],
                input=md, text=True, capture_output=True, timeout=20,
            )
            return r.returncode == 0
        except Exception:
            return False

    if not _pandoc(out_tex, "latex"):
        # Plain-text fallback if Pandoc unavailable — clearly labelled,
        # not malformed LaTeX.
        out_tex.write_text(
            "% Pandoc unavailable; verbatim Markdown follows.\n"
            "\\begin{verbatim}\n" + md + "\n\\end{verbatim}\n"
        )
    if not _pandoc(out_html, "html5"):
        out_html.write_text(
            f"<!DOCTYPE html><html><head><meta charset='utf-8'>"
            f"<title>CITATION</title><style>body{{font-family:serif;"
            f"padding:24px;max-width:900px;margin:auto}}"
            f"pre{{white-space:pre-wrap}}</style></head>"
            f"<body><pre>{md}</pre></body></html>"
        )

    return md


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------


