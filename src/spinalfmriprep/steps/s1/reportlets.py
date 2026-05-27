"""S1 reportlet rendering — one polished diagnostic PNG per dataset.

A single figure that a human can absorb in 5 seconds. Layout:

  ┌──────────────────────────────────────────────────────────────┐
  │  S1 INPUT VERIFY  •  <dataset_key>             [STATUS PILL] │
  ├──────────────────────────────────────────────────────────────┤
  │  [Subjects]  [Sessions]  [Func cord]  [Anat]  [FMaps]        │  ← stat cards
  ├──────────────────────────────────────────────────────────────┤
  │                                                              │
  │       SUBJECT × MODALITY                  CHECKS             │
  │   ┌─────┬─────┬─────┬─────┐         PASS  any_runs_present   │
  │   │anat │func │fmap │physi│         PASS  fmap_expected      │
  │   ●  1  │  9  │  -  │  -  │  sub-02  WARN  physio_expected   │
  │   ●  1  │  3  │  -  │  -  │  sub-ZS  ...                     │
  │                                                              │
  └──────────────────────────────────────────────────────────────┘

Design notes (CLAUDE.md principles §4 + §5):
- Status pill in the top-right is the single most important visual
  element — a human glances there first.
- Per-subject "health dot" (green/amber/red) on the left of each row
  encodes "does this subject have the minimum (anat + cord func)?" so
  a row of zeros is impossible to miss.
- Modality matrix shows actual counts, with zeros rendered as a
  desaturated "—" so positive cells pop visually.
- Check list is right-justified to the matrix and uses the same
  badge style as the status pill.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np


# Status palette — pairs of (fill, text). Matches the dashboard CSS
# so banners across the chain are visually consistent.
_STATUS = {
    "PASS":    {"fill": "#14532d", "edge": "#22c55e", "text": "#22c55e"},
    "WARN":    {"fill": "#3a2f00", "edge": "#f59e0b", "text": "#f59e0b"},
    "FAIL":    {"fill": "#3a1010", "edge": "#ef4444", "text": "#ef4444"},
    "UNKNOWN": {"fill": "#1a1d23", "edge": "#666666", "text": "#cccccc"},
}
_BG = "#0f1115"
_CARD_BG = "#1a1d23"
_MUTED = "#9ca3af"
_TEXT = "#e6e8ec"
_BORDER = "#2a2e36"

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


def _subject_health(mat_row: np.ndarray) -> str:
    """Per-subject health: PASS if anat ≥ 1 and func ≥ 1, WARN if one
    missing, FAIL if both missing. Matches the per-subject check logic
    in `validate._apply_session_requirements`.

    mat_row columns are ordered per `_MODALITIES` = anat, func, fmap, physio.
    """
    anat_ok = mat_row[0] > 0
    func_ok = mat_row[1] > 0
    if anat_ok and func_ok:
        return "PASS"
    if not anat_ok and not func_ok:
        return "FAIL"
    return "WARN"


def _draw_pill(
    ax, x: float, y: float, w: float, h: float, label: str, status: str,
    fontsize: int = 9, transform=None,
) -> None:
    """Rounded status pill drawn via FancyBboxPatch."""
    pal = _STATUS.get(status, _STATUS["UNKNOWN"])
    if transform is None:
        transform = ax.transAxes
    box = mpatches.FancyBboxPatch(
        (x, y), w, h, boxstyle="round,pad=0.005,rounding_size=0.012",
        facecolor=pal["fill"], edgecolor=pal["edge"], linewidth=1.0,
        transform=transform, zorder=2,
    )
    ax.add_patch(box)
    ax.text(x + w / 2, y + h / 2, label, ha="center", va="center",
            color=pal["text"], fontsize=fontsize, fontweight="bold",
            transform=transform, zorder=3)


def _draw_stat_card(
    ax, x: float, y: float, w: float, h: float,
    label: str, value: str, accent: str = _MUTED,
) -> None:
    """Card with a big number on top and a small caption below."""
    card = mpatches.FancyBboxPatch(
        (x, y), w, h, boxstyle="round,pad=0.003,rounding_size=0.012",
        facecolor=_CARD_BG, edgecolor=_BORDER, linewidth=1.0,
        transform=ax.transAxes, zorder=1,
    )
    ax.add_patch(card)
    ax.text(x + w / 2, y + h * 0.62, value, ha="center", va="center",
            color=accent, fontsize=22, fontweight="bold",
            transform=ax.transAxes, zorder=2)
    # matplotlib has no letter-spacing; emulate with spaces between chars.
    spaced = " ".join(label.upper())
    ax.text(x + w / 2, y + h * 0.20, spaced, ha="center", va="center",
            color=_MUTED, fontsize=8, fontweight="bold",
            transform=ax.transAxes, zorder=2)


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
        metrics = qc_summary.get("metrics", {}) or {}
        dataset_key = qc_summary.get("dataset_key") or "(unknown)"
        status = qc_summary.get("status", "UNKNOWN")

        # Figure dimensions scale with whichever is taller — the matrix
        # (1 row per subject, plus header row) or the checks list (~0.5"
        # per check including padding).
        n_sub = max(len(subjects), 1)
        n_chk = max(len(checks), 1)
        matrix_h = 0.45 * (n_sub + 1) + 0.4   # header + rows + title pad
        checks_h = 0.50 * n_chk + 0.4         # rows + title pad
        body_h_inches = max(matrix_h, checks_h, 1.6)
        fig_h = 0.55 + 1.0 + body_h_inches + 0.3
        fig_w = 13.0
        fig = plt.figure(figsize=(fig_w, fig_h), facecolor=_BG)
        fig.patch.set_facecolor(_BG)

        # ---- Master grid ----
        gs = fig.add_gridspec(
            3, 2,
            height_ratios=[0.55, 1.0, body_h_inches],
            width_ratios=[6, 5],
            hspace=0.15, wspace=0.08,
            left=0.04, right=0.97, top=0.97, bottom=0.05,
        )

        # ---- Header bar ----
        ax = fig.add_subplot(gs[0, :])
        ax.set_facecolor(_BG); ax.axis("off")
        ax.text(0.0, 0.65, "S1 input verify",
                color=_TEXT, fontsize=15, fontweight="bold",
                transform=ax.transAxes)
        ax.text(0.0, 0.20, dataset_key,
                color=_MUTED, fontsize=10, family="monospace",
                transform=ax.transAxes)
        _draw_pill(ax, 0.88, 0.30, 0.11, 0.55, status, status,
                   fontsize=13)

        # ---- Stat cards ----
        ax = fig.add_subplot(gs[1, :])
        ax.set_facecolor(_BG); ax.axis("off")
        cls = counts.get("classification", {}) or {}
        cards = [
            ("Subjects", counts.get("subjects", 0)),
            ("Sessions", counts.get("sessions", 0)),
            ("Cord func", metrics.get("n_func_cord_runs",
                                       cls.get("cord_likely", 0))),
            ("Anat", metrics.get("n_anat_runs", 0)),
            ("FMaps", metrics.get("n_fmap_runs", 0)),
        ]
        n_cards = len(cards)
        card_w = 0.96 / n_cards - 0.012
        for i, (label, value) in enumerate(cards):
            x = 0.02 + i * (card_w + 0.012)
            accent = _TEXT
            # Highlight "Cord func" red when zero — it's load-bearing.
            if label == "Cord func" and value == 0:
                accent = _STATUS["FAIL"]["text"]
            elif label == "Anat" and value == 0:
                accent = _STATUS["WARN"]["text"]
            _draw_stat_card(ax, x, 0.0, card_w, 1.0, label, str(value), accent)

        # ---- Modality matrix (subject × modality) ----
        ax_grid = fig.add_subplot(gs[2, 0])
        ax_grid.set_facecolor(_BG)
        ax_grid.set_title("Subject × modality (file count)",
                          color=_TEXT, fontsize=11, loc="left", pad=6)

        if subjects:
            n_rows = len(subjects)
            n_cols = len(_MODALITIES) + 1  # +1 for the health dot column
            ax_grid.set_xlim(-0.55, n_cols - 0.45)
            # Include header row at y=-1 inside the visible range.
            ax_grid.set_ylim(n_rows - 0.45, -1.55)  # invert Y

            # Header row at y=-1
            for j, mod in enumerate(_MODALITIES):
                ax_grid.text(j + 1, -1.0, mod, ha="center", va="center",
                             color=_MUTED, fontsize=10, fontweight="bold")
            ax_grid.text(0, -1.0, "OK", ha="center", va="center",
                         color=_MUTED, fontsize=9, fontweight="bold")
            # Thin separator under the header
            ax_grid.plot([-0.45, n_cols - 0.55], [-0.55, -0.55],
                         color=_BORDER, linewidth=0.8, zorder=1)

            # Per-row health dot + per-cell counts
            for i, sub in enumerate(subjects):
                row = mat[i]
                health = _subject_health(row)
                pal = _STATUS[health]
                # Health dot
                ax_grid.scatter([0], [i], s=160, c=pal["edge"],
                                edgecolors=pal["edge"], linewidths=1.5,
                                zorder=3)
                # Subject label, just left of the dot
                ax_grid.annotate(
                    sub, xy=(0, i), xycoords="data",
                    xytext=(-10, 0), textcoords="offset points",
                    ha="right", va="center", color=_TEXT, fontsize=9,
                )
                # Modality cells
                for j, mod in enumerate(_MODALITIES):
                    v = row[j]
                    cx = j + 1
                    if v > 0:
                        ax_grid.add_patch(mpatches.FancyBboxPatch(
                            (cx - 0.40, i - 0.32), 0.80, 0.64,
                            boxstyle="round,pad=0.005,rounding_size=0.08",
                            facecolor="#1e3a5f", edgecolor="#3b82f6",
                            linewidth=0.9, zorder=2,
                        ))
                        ax_grid.text(cx, i, str(v), ha="center", va="center",
                                     color=_TEXT, fontsize=10,
                                     fontweight="bold", zorder=3)
                    else:
                        ax_grid.text(cx, i, "·", ha="center", va="center",
                                     color="#4b5563", fontsize=18, zorder=2)

            ax_grid.set_xticks([])
            ax_grid.set_yticks([])
            for s in ax_grid.spines.values():
                s.set_visible(False)
        else:
            ax_grid.axis("off")
            ax_grid.text(0.5, 0.5, "no subjects detected",
                         ha="center", va="center", color=_STATUS["FAIL"]["text"],
                         fontsize=12, transform=ax_grid.transAxes)

        # ---- Checks list ----
        ax_chk = fig.add_subplot(gs[2, 1])
        ax_chk.set_facecolor(_BG); ax_chk.axis("off")
        ax_chk.set_title("Checks", color=_TEXT, fontsize=11, loc="left",
                         pad=6)
        if checks:
            # Each check row gets a fixed slice of the axes — generous
            # enough for two text lines without overlap.
            n_chk_actual = len(checks)
            usable_top = 0.92
            usable_bottom = 0.04
            row_h = (usable_top - usable_bottom) / n_chk_actual
            row_h = min(row_h, 0.22)  # cap so badges don't get huge
            badge_h = min(0.6 * row_h, 0.10)
            for i, c in enumerate(checks):
                sev = c.get("severity", "UNKNOWN")
                passed = c.get("passed", False)
                badge = "PASS" if passed else sev
                # Top of row i (0 = top)
                y_top = usable_top - i * row_h
                y_center = y_top - row_h / 2.0
                _draw_pill(ax_chk, 0.0, y_center - badge_h / 2.0,
                           0.10, badge_h, badge, badge, fontsize=8)
                name = c.get("name", "?")
                msg = c.get("message", "")
                if len(name) > 30:
                    name = name[:28] + "…"
                if len(msg) > 80:
                    msg = msg[:78] + "…"
                # Name above message
                ax_chk.text(0.12, y_center + row_h * 0.20, name,
                            ha="left", va="center", color=_TEXT,
                            fontsize=9, fontweight="bold",
                            family="monospace",
                            transform=ax_chk.transAxes)
                ax_chk.text(0.12, y_center - row_h * 0.20, msg,
                            ha="left", va="center", color=_MUTED,
                            fontsize=8, transform=ax_chk.transAxes)
        else:
            ax_chk.text(0.5, 0.5, "no checks recorded",
                        ha="center", va="center", color=_MUTED,
                        fontsize=10, transform=ax_chk.transAxes)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path, dpi=130, facecolor=_BG,
                    bbox_inches="tight", pad_inches=0.15)
        plt.close(fig)
    except Exception:
        # Never let the reportlet fail S1; emit a stub.
        try:
            fig, ax = plt.subplots(figsize=(8, 3), facecolor=_BG)
            ax.set_facecolor(_BG); ax.axis("off")
            ax.text(0.5, 0.5, "S1 reportlet render failed",
                    ha="center", va="center", color=_TEXT, fontsize=12)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            fig.savefig(output_path, dpi=100, facecolor=_BG,
                        bbox_inches="tight")
            plt.close(fig)
        except Exception:
            pass
