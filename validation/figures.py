"""Publication figures from the validation results (T2/R5 + T3 packaging).

Reads validation/results/*.tsv (produced by reliability_*.py + normative_qc_db.py)
and renders paper-ready PNGs to validation/results/figures/. Figure-first +
truthful: shows the full per-edge ICC spread (not just a headline mean) and
annotates n. Numbers refresh after the locked-σ re-run; this is the figure
machinery.

Usage: poetry run python validation/figures.py
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

RES = Path("validation/results")
FIG = RES / "figures"


def fig_connectivity_reliability(out: Path) -> bool:
    f = RES / "reliability_connectivity.tsv"
    if not f.exists():
        return False
    df = pd.read_csv(f, sep="\t")
    groups = list(df.groupby(["scope", "type"]))
    if not groups:
        return False
    fig, ax = plt.subplots(figsize=(max(5, 1.7 * len(groups)), 4.2))
    rng = np.random.default_rng(3)
    labels = []
    for i, ((scope, rtype), g) in enumerate(groups):
        vals = g["icc_2_1"].to_numpy(dtype=float)
        ax.boxplot(vals, positions=[i], widths=0.5, patch_artist=True,
                   boxprops=dict(facecolor="#eef2fb", color="#445"),
                   medianprops=dict(color="#cc2a2a"), flierprops=dict(marker=""))
        ax.scatter(i + (rng.random(len(vals)) - 0.5) * 0.2, vals, s=18,
                   color="#5b8def", edgecolor="white", linewidth=0.4, zorder=3)
        ax.text(i, 0.92, f"mean {vals.mean():.2f}\nn={int(g['n'].median())}",
                ha="center", fontsize=8, color="#333")
        labels.append(f"{scope}\n({rtype})")
    for y, c in [(0.4, "#888"), (0.6, "#888"), (0.75, "#888")]:
        ax.axhline(y, color=c, ls=":", lw=0.8, alpha=0.6)
    ax.set_xticks(range(len(groups)))
    ax.set_xticklabels(labels, fontsize=8)
    ax.set_ylabel("per-edge connectivity ICC(2,1)")
    ax.set_ylim(-1.0, 1.0)
    ax.set_title("Intra-cord connectivity reliability (each dot = one level-pair edge)",
                 fontsize=10)
    ax.grid(axis="y", alpha=0.25); ax.set_axisbelow(True)
    fig.tight_layout(); FIG.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=130, bbox_inches="tight"); plt.close(fig)
    return True


def fig_normative_tsnr_per_level(out: Path) -> bool:
    f = RES / "normative_tsnr_per_level.tsv"
    if not f.exists():
        return False
    df = pd.read_csv(f, sep="\t")
    # cervical->thoracic order
    order = [f"C{i}" for i in range(1, 9)] + [f"T{i}" for i in range(1, 6)]
    df["ord"] = df["level"].map({l: i for i, l in enumerate(order)})
    df = df.dropna(subset=["ord"]).sort_values("ord")
    fig, ax = plt.subplots(figsize=(8, 4.2))
    x = range(len(df))
    ax.errorbar(x, df["mean"], yerr=df["sd"], fmt="o-", color="#1f6fc4",
                ecolor="#9bb8d8", capsize=3, lw=1.5, ms=5)
    for xi, (_, r) in zip(x, df.iterrows()):
        ax.annotate(f"n={int(r['n'])}", (xi, r["mean"] + r["sd"] + 1.5),
                    ha="center", fontsize=7, color="#777")
    ax.set_xticks(list(x)); ax.set_xticklabels(df["level"])
    ax.set_xlabel("vertebral level"); ax.set_ylabel("median in-cord tSNR (mean ± SD)")
    ax.set_title("Normative per-vertebral-level cord tSNR across the cohort "
                 "(post smoothing σ 1/1/8)", fontsize=10)
    ax.grid(axis="y", alpha=0.25); ax.set_axisbelow(True)
    fig.tight_layout(); FIG.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=130, bbox_inches="tight"); plt.close(fig)
    return True


def fig_tsnr_reliability_per_level(out: Path) -> bool:
    f = RES / "reliability_tsnr.tsv"
    if not f.exists():
        return False
    df = pd.read_csv(f, sep="\t")
    fig, ax = plt.subplots(figsize=(7, 4))
    for scope, g in df.groupby("scope"):
        ax.plot(g["level"], g["icc_2_1"], "o-", label=scope, lw=1.4, ms=5)
    ax.axhline(0.5, color="#888", ls=":", lw=0.8)
    ax.set_ylabel("tSNR test-retest ICC(2,1)"); ax.set_xlabel("vertebral level")
    ax.set_ylim(-0.5, 1.0); ax.legend(fontsize=8)
    ax.set_title("Per-level cord tSNR test-retest reliability", fontsize=10)
    ax.grid(axis="y", alpha=0.25); ax.set_axisbelow(True)
    fig.tight_layout(); FIG.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=130, bbox_inches="tight"); plt.close(fig)
    return True


def main():
    made = []
    if fig_connectivity_reliability(FIG / "reliability_connectivity.png"):
        made.append("reliability_connectivity.png")
    if fig_normative_tsnr_per_level(FIG / "normative_tsnr_per_level.png"):
        made.append("normative_tsnr_per_level.png")
    if fig_tsnr_reliability_per_level(FIG / "reliability_tsnr_per_level.png"):
        made.append("reliability_tsnr_per_level.png")
    print("figures written:", ", ".join(made) if made else "(none — run the "
          "reliability_*.py / normative_qc_db.py first)")


if __name__ == "__main__":
    main()
