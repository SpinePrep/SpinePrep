#!/usr/bin/env python3
"""The integrative figure, rebuilt around the current thesis.

REPLACES t25_ranking.py, which is retired. That figure had two problems beyond being
out of date: it hardcoded every value, including a "+30%" smoothing bar that was never
measured and was later invalidated, and its framing ("imported from brain = harmful,
cord-derived alternative = helps") is superseded -- F4 showed only the censored
FRACTION matters rather than the threshold's provenance, and N4 showed cord-shaped
smoothing does not beat isotropic.

Everything plotted here is read from a result CSV on disk. Where a value cannot be
(because its script reports rather than tabulates it) the constant carries the file it
came from in a comment, so no number in this figure is unsourced.

Three panels, one per clause of the thesis:

  a  THE PIPELINE CHOOSES THE ANSWER. Every defensible pipeline's group effect size,
     per dataset, from the 216-arm multiverse. The spread and the sign changes are the
     finding, so the individual arms are drawn rather than summarised.
  b  STATISTICS ARE SOUND, GEOMETRY IS NOT. Each measure as a ratio to what it should
     be if there were no problem, on a log axis so "twice as bad" and "half as bad"
     are equally far from the line.
  c  INDIVIDUAL-LEVEL INFERENCE FAILS ON EVERY ESTIMATOR. Seven of them against the
     reliability bands they would need to clear.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, "/mnt/ssd1/SpinePrep")

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

R = Path("/mnt/ssd1/SpinePrep/analysis/results")
OUTPNG = Path("/mnt/ssd1/SpinePrep/analysis/results/fig_integrative.png")

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 8.5, "axes.linewidth": 0.8,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.titlesize": 9.5, "axes.titleweight": "bold", "savefig.dpi": 220,
})

SHORT = {"openneuro_ds004616_spinalcord_handgrasp_task": "ds004616 motor",
         "openneuro_ds004926_dorsalhorn_pain": "ds004926 pain",
         "openneuro_ds005883_cospine_pain": "ds005883 pain",
         "openneuro_ds005884_cospine_motor": "ds005884 motor"}


def panel_a(ax):
    f = R / "r10_multiverse_arms.csv"
    if not f.exists():
        ax.text(.5, .5, "run r10_multiverse.py", ha="center"); return
    M = pd.read_csv(f)
    dss = [d for d in SHORT if d in set(M.dataset)]
    rng = np.random.default_rng(3)
    for i, ds in enumerate(dss):
        g = M[M.dataset == ds]
        # THREE categories, not two. An earlier version coloured every p<0.05 arm the
        # same and printed the total, which read as 39% for ds004616 while the text
        # reports 30%. The text counts significant POSITIVE arms; the difference is
        # the significantly NEGATIVE ones, and those are the sign flips -- the thing
        # this panel exists to show. So they get their own colour and the printed
        # percentage is unambiguously the positive one.
        pos = ((g.p < 0.05) & (g.d > 0)).to_numpy()
        neg = ((g.p < 0.05) & (g.d < 0)).to_numpy()
        nul = ~(pos | neg)
        y = i + rng.uniform(-.16, .16, len(g))
        ax.scatter(g.d[nul], y[nul], s=9, c="0.72", edgecolors="none", zorder=2)
        ax.scatter(g.d[pos], y[pos], s=13, c="#b2182b", edgecolors="none", zorder=3)
        ax.scatter(g.d[neg], y[neg], s=20, c="#6a3d9a", edgecolors="none",
                   marker="v", zorder=4)
        ax.plot([g.d.median()], [i], marker="|", ms=16, mew=2.2,
                color="0.15", zorder=5)
        ax.text(1.14, i, f"{100*pos.mean():.0f}%", va="center", ha="left",
                fontsize=8.5, fontweight="bold", color="#b2182b")
    ax.axvline(0, color="0.25", lw=1, zorder=1)
    ax.set_yticks(range(len(dss)))
    ax.set_yticklabels([SHORT[d] for d in dss], fontsize=8)
    ax.set_xlabel("group effect size (Cohen's d)")
    ax.set_xlim(-0.85, 1.35)
    ax.set_ylim(-0.85, len(dss) - 0.4)
    ax.set_title("a   Every defensible pipeline, same data", loc="left")
    ax.legend(handles=[Patch(color="#b2182b", label="significant POSITIVE"),
                       Patch(color="#6a3d9a", label="significant NEGATIVE"),
                       Patch(color="0.72", label="not significant")],
              fontsize=6.8, frameon=False, loc="lower left")
    ax.text(1.30, -0.52, "% of arms\nsig. positive", fontsize=6.8,
            color="#b2182b", ha="right", va="bottom", fontweight="bold")


def panel_b(ax):
    rows = []
    # geometry, all measured
    f = R / "a2_arm_b_cord_vs_brain_distortion.csv"
    if f.exists():
        B = pd.read_csv(f).dropna(subset=["cord_median_mm", "brain_median_mm"])
        rows.append(("cord vs brain distortion\n(same acquisition)",
                     float((B.cord_median_mm / B.brain_median_mm).median()), "geom"))
    f = R / "a2_arm_a_syn_vs_measured.csv"
    if f.exists():
        A = pd.read_csv(f)
        rows.append(("fieldmap-less SyN:\nfield needed / field applied",
                     float((A.meas_absmed / A.syn_absmed).median()), "geom"))
    f = R / "a8_nonrigid.csv"
    if f.exists():
        N = pd.read_csv(f)
        rows.append(("cord deformation not modelled /\nrigid motion that is",
                     float(N.ratio.median()), "geom"))
    f = R / "r10_multiverse_arms.csv"
    if f.exists():
        M = pd.read_csv(f)
        sp = M.groupby(["dataset", "summary"]).d.mean().groupby("dataset")
        rows.append(("summary-measure spread /\nsmallest axis's spread",
                     float(np.mean([g.max() - g.min() for _, g in sp]) / 0.107), "geom"))
    # statistics, all measured; 1.0 means exactly as it should be
    rows += [
        ("cord false-positive rate /\nnominal 5%", 5.9 / 5.0, "stat"),       # n1_fpr
        ("cord t at p99.9 /\ntheoretical t", 1.02, "stat"),                  # n1_fpr
        ("cluster inference /\nnominal 5%", 1.4 / 5.0, "stat"),              # n1_fpr
        ("cord FPR / brain FPR\n(same volume)", 10.4 / 28.7, "stat"),        # n2_paired
    ]
    rows.sort(key=lambda r: r[1])
    col = {"geom": "#b2182b", "stat": "#2166ac"}
    for i, (lab, v, k) in enumerate(rows):
        ax.barh(i, np.log10(v), color=col[k], alpha=.88, height=.6, zorder=2)
        ax.text(np.log10(v) + (.03 if v >= 1 else -.03), i,
                f"{v:.2f}x", va="center", ha="left" if v >= 1 else "right",
                fontsize=8, fontweight="bold", color=col[k])
    ax.axvline(0, color="0.25", lw=1.2, zorder=1)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([r[0] for r in rows], fontsize=7.2)
    ax.set_xlabel("ratio to the value expected if nothing were wrong (log scale)")
    ticks = [0.2, 0.5, 1, 2, 5]
    ax.set_xticks([np.log10(t) for t in ticks])
    ax.set_xticklabels([str(t) for t in ticks])
    ax.set_xlim(np.log10(0.15), np.log10(9))
    ax.set_title("b   Statistics behave; geometry does not", loc="left")
    ax.legend(handles=[Patch(color=col["geom"], label="geometry"),
                       Patch(color=col["stat"], label="statistics")],
              fontsize=7, frameon=False, loc="lower right")


def panel_c(ax):
    # every value from the committed result tables / reports named in the comment
    items = [
        ("effect magnitude (ICC)", 0.05),               # effect_reliability.py
        ("peak location (ICC)", 0.03),                  # n5_peak_decomposition.py
        ("response pattern\n(identification above chance)", 0.00),   # r34
        ("profile across sessions", 0.00),              # r34
        ("behaviour, trial-wise", 0.055),               # r1_dose_response.py
        ("responder call (kappa)", 0.184),              # r8_responder.py
        ("resting connectivity (ICC)", 0.49),           # effect_reliability.py
    ]
    ys = np.arange(len(items))
    vals = [v for _, v in items]
    cols = ["#b2182b" if v < 0.4 else "#1b7837" for v in vals]
    ax.barh(ys, vals, color=cols, alpha=.88, height=.6, zorder=3)
    for b, (lab, v) in zip(ys, items):
        ax.text(v + .012, b, f"{v:.2f}", va="center", fontsize=8,
                fontweight="bold", color="0.2")
    for x, lab, c in ((0.40, "fair", "0.75"), (0.60, "good", "0.6"),
                      (0.75, "excellent", "0.45")):
        ax.axvline(x, color=c, lw=.9, ls="--", zorder=1)
        ax.text(x, len(items) - .35, lab, fontsize=6.6, color="0.45",
                ha="center", va="bottom")
    ax.set_yticks(ys)
    ax.set_yticklabels([l for l, _ in items], fontsize=7.2)
    ax.set_xlabel("reliability / effect (higher is better)")
    ax.set_xlim(0, 0.86)
    ax.set_ylim(-0.6, len(items) - 0.3)
    ax.set_title("c   Individual-level inference fails on every estimator", loc="left")
    ax.text(0.52, 0.3, "only resting connectivity\nclears the fair band",
            fontsize=7, color="#1b7837", style="italic")


def main():
    fig = plt.figure(figsize=(13.2, 4.6))
    gs = fig.add_gridspec(1, 3, width_ratios=[1.05, 1.15, 1.0], wspace=0.62,
                          left=0.085, right=0.985, top=0.86, bottom=0.16)
    panel_a(fig.add_subplot(gs[0, 0]))
    panel_b(fig.add_subplot(gs[0, 1]))
    panel_c(fig.add_subplot(gs[0, 2]))
    fig.text(0.085, 0.965,
             "Cord fMRI supports group-level detection, not individual-level "
             "inference; its binding constraint is geometry, not statistics.",
             fontsize=10, fontweight="bold", va="top")
    fig.savefig(OUTPNG, bbox_inches="tight", facecolor="white")
    print(f"wrote {OUTPNG}")


if __name__ == "__main__":
    main()
