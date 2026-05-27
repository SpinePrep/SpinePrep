"""S1 reportlet rendering — one diagnostic PNG per dataset.

The reportlet is a single 3-panel figure that lets a human eyeball the
input inventory and verification status without reading the JSON:

  Left   — Subject × modality presence matrix (anat/func/fmap/physio).
           Colored cell = file count > 0.
  Centre — Check status table (one row per check, PASS/WARN/FAIL badge).
  Right  — Counts summary (files, runs, subjects, sessions, classification).

This satisfies the SpinalfMRIprep dev principles §4 and §5 (one
diagnostic reportlet per step; visual QC is the validator). When the
inventory is empty the figure is still emitted with a clear "no runs
detected" message so the dashboard reflects the failure mode.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


_STATUS_COLOR = {
    "PASS": "#14532d",
    "WARN": "#7c5e00",
    "FAIL": "#7f1d1d",
    "UNKNOWN": "#333333",
}
_MODALITIES = ["anat", "func", "fmap", "physio"]


def _modality_grid(inventory: dict) -> tuple[list[str], np.ndarray]:
    """Build subject × modality count matrix from the raw inventory."""
    files = inventory.get("files", [])
    runs = inventory.get("runs", [])
    counts: dict[tuple[str, str], int] = defaultdict(int)
    subjects = set()
    # Use runs (already classified by modality) when available; fall back
    # to a path-based heuristic for orphan files.
    for r in runs:
        sub = r.get("subject") or "unknown"
        mod = r.get("modality") or "other"
        subjects.add(sub)
        if mod in _MODALITIES:
            counts[(sub, mod)] += 1
    # Capture physio coverage even though it lives in `files` not `runs`
    # for some datasets.
    for f in files:
        sub = f.get("subject") or "unknown"
        path = str(f.get("path", "")).lower()
        if "physio" in path:
            subjects.add(sub)
            counts[(sub, "physio")] += 1
    subjects_sorted = sorted(s for s in subjects if s != "unknown") + (
        ["unknown"] if "unknown" in subjects else [])
    if not subjects_sorted:
        return [], np.zeros((0, len(_MODALITIES)), dtype=int)
    mat = np.zeros((len(subjects_sorted), len(_MODALITIES)), dtype=int)
    for i, sub in enumerate(subjects_sorted):
        for j, mod in enumerate(_MODALITIES):
            mat[i, j] = counts.get((sub, mod), 0)
    return subjects_sorted, mat


def render_s1_dataset_summary(
    inventory: dict,
    qc_summary: dict,
    output_path: Path,
) -> None:
    """Render the per-dataset S1 reportlet PNG. Never raises."""
    try:
        subjects, mat = _modality_grid(inventory)
        checks = qc_summary.get("checks", []) or []
        counts = qc_summary.get("counts", {}) or {}
        dataset_key = qc_summary.get("dataset_key") or "(unknown)"
        status = qc_summary.get("status", "UNKNOWN")

        fig = plt.figure(figsize=(13, max(4.5, 0.35 * len(subjects) + 3)),
                         facecolor="black")
        gs = fig.add_gridspec(1, 3, width_ratios=[3, 3, 2])

        # --- Left: subject × modality presence -----------------------
        ax = fig.add_subplot(gs[0, 0])
        ax.set_facecolor("black")
        if subjects:
            ax.imshow(mat > 0, cmap="Blues", aspect="auto",
                      vmin=0, vmax=1, interpolation="nearest")
            for i in range(mat.shape[0]):
                for j in range(mat.shape[1]):
                    v = mat[i, j]
                    if v:
                        ax.text(j, i, str(v), ha="center", va="center",
                                color="white", fontsize=8)
            ax.set_xticks(range(len(_MODALITIES)))
            ax.set_xticklabels(_MODALITIES, color="white", rotation=0)
            ax.set_yticks(range(len(subjects)))
            ax.set_yticklabels(subjects, color="white", fontsize=8)
        else:
            ax.text(0.5, 0.5, "no subjects detected",
                    ha="center", va="center", color="white")
            ax.set_xticks([]); ax.set_yticks([])
        for s in ax.spines.values():
            s.set_color("#666666")
        ax.tick_params(colors="white")
        ax.set_title("Subject × modality (file count)",
                     color="white", fontsize=11)

        # --- Centre: check status table -------------------------------
        ax = fig.add_subplot(gs[0, 1])
        ax.set_facecolor("black")
        ax.axis("off")
        if checks:
            lines_y = np.linspace(0.95, 0.05, max(len(checks), 1))
            for y, c in zip(lines_y, checks):
                sev = c.get("severity", "UNKNOWN")
                passed = c.get("passed", False)
                badge = sev if not passed else "PASS"
                color = _STATUS_COLOR.get(badge, "#333")
                ax.add_patch(plt.Rectangle((0.02, y - 0.018), 0.10, 0.036,
                                            facecolor=color, edgecolor="none",
                                            transform=ax.transAxes))
                ax.text(0.07, y, badge, ha="center", va="center",
                        color="white", fontsize=8, fontweight="bold",
                        transform=ax.transAxes)
                msg = c.get("message", "")
                ax.text(0.14, y, f"{c.get('name', '?')}: {msg[:60]}",
                        ha="left", va="center", color="white", fontsize=8,
                        transform=ax.transAxes)
        else:
            ax.text(0.5, 0.5, "no checks recorded",
                    ha="center", va="center", color="white",
                    transform=ax.transAxes)
        ax.set_title("Checks", color="white", fontsize=11)

        # --- Right: counts summary -----------------------------------
        ax = fig.add_subplot(gs[0, 2])
        ax.set_facecolor("black")
        ax.axis("off")
        cls = counts.get("classification", {}) or {}
        rows = [
            ("files", counts.get("files", 0)),
            ("runs", counts.get("runs", 0)),
            ("subjects", counts.get("subjects", 0)),
            ("sessions", counts.get("sessions", 0)),
            ("cord_likely", cls.get("cord_likely", 0)),
            ("non_cord_likely", cls.get("non_cord_likely", 0)),
            ("unknown", cls.get("unknown", 0)),
        ]
        ys = np.linspace(0.92, 0.08, len(rows))
        for y, (k, v) in zip(ys, rows):
            ax.text(0.05, y, k, ha="left", va="center", color="#cccccc",
                    fontsize=9, transform=ax.transAxes)
            ax.text(0.95, y, str(v), ha="right", va="center", color="white",
                    fontsize=10, fontweight="bold",
                    transform=ax.transAxes)
        ax.set_title("Counts", color="white", fontsize=11)

        suptitle_color = _STATUS_COLOR.get(status, "#333")
        fig.suptitle(
            f"S1 input verify — {dataset_key}    [{status}]",
            color="white", fontsize=12, fontweight="bold",
            bbox=dict(facecolor=suptitle_color, edgecolor="none", pad=4),
        )
        fig.tight_layout(rect=(0, 0, 1, 0.94))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path, dpi=120, facecolor="black",
                    bbox_inches="tight")
        plt.close(fig)
    except Exception:
        # Never let the reportlet fail S1; emit a stub.
        try:
            fig, ax = plt.subplots(figsize=(8, 3), facecolor="black")
            ax.set_facecolor("black"); ax.axis("off")
            ax.text(0.5, 0.5, "S1 reportlet render failed",
                    ha="center", va="center", color="white", fontsize=12)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            fig.savefig(output_path, dpi=100, facecolor="black",
                        bbox_inches="tight")
            plt.close(fig)
        except Exception:
            pass
