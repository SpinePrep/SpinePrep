#!/usr/bin/env python3
"""Figure generators for the SpinePrep analysis.

ANALYSIS module -- not part of the preprocessing toolbox.

Each generator reads one result table written by run_all.py and renders one PNG
under analysis/results/figures/. Generators are independent: a missing or empty
table produces a labelled placeholder, never a crash, so the figure set can be
built before the whole cohort has run.

Figures, keyed to the outline:
  fig_reliability_scale   F4 (PRIMARY) reliability vs parcel size, per dataset
  fig_tsnr_per_level      F5 normative per-level tSNR envelope
  fig_confound_pareto     F8 confound-family importance: sensitivity vs DOF
  fig_biological          C3 laterality per subject + dorsal/ventral group
  fig_distortion          F6 SyN vs TopUp fidelity (guarded on the dual run)

Style is deliberately plain: one panel per figure, measured axes, no chartjunk.
"""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

RESULTS = Path(__file__).resolve().parent / "results"
FIGDIR = RESULTS / "figures"

# nominal tier sizes (voxels), for the reliability x-axis
TIER_ORDER = ["cord", "hemicord", "spinallevel", "gmhorn"]
TIER_VOX = {"cord": 462, "hemicord": 230, "spinallevel": 50, "gmhorn": 8.5}


def _short(ds: str) -> str:
    """A distinct short label per dataset (the openneuro accession, or the
    internal paradigm), so the three internal 'balgrist' sets do not collide."""
    parts = ds.split("_")
    for p in parts:
        if p.startswith("ds") and p[2:].isdigit():
            return p
    # internal_balgrist_<paradigm>_NN -> the paradigm token
    return parts[2] if len(parts) > 2 else ds


def _read(name: str) -> list[dict]:
    p = RESULTS / name
    if not p.exists() or p.stat().st_size == 0:
        return []
    with open(p) as fh:
        return list(csv.DictReader(fh))


def _f(x) -> Optional[float]:
    try:
        v = float(x)
        return v if np.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def _placeholder(ax, msg: str):
    ax.text(0.5, 0.5, msg, ha="center", va="center", wrap=True,
            transform=ax.transAxes, fontsize=11, color="0.4")
    ax.set_xticks([]); ax.set_yticks([])


def fig_reliability_scale(path: Path = None):
    """F4: split-half (Spearman-Brown) vs parcel size, one line per dataset."""
    rows = _read("endpoints_long.csv")
    fig, ax = plt.subplots(figsize=(6, 4.2))
    # mean SB reliability per (dataset, tier)
    acc = defaultdict(list)
    for r in rows:
        if r.get("metric") != "splithalf_r_sb":
            continue
        v = _f(r.get("value"))
        if v is not None and r.get("tier") in TIER_VOX:
            acc[(r["dataset"], r["tier"])].append(v)
    if not acc:
        _placeholder(ax, "reliability endpoints not present\n(split-half needs the re-run)")
    else:
        datasets = sorted({k[0] for k in acc})
        for ds in datasets:
            xs, ys = [], []
            for tier in TIER_ORDER:
                vals = acc.get((ds, tier))
                if vals:
                    xs.append(TIER_VOX[tier]); ys.append(float(np.mean(vals)))
            if len(xs) >= 2:
                ax.plot(xs, ys, "-o", ms=4, lw=1, alpha=0.8,
                        label=_short(ds))
        ax.set_xscale("log")
        ax.set_xlabel("parcel size (voxels, log scale)")
        ax.set_ylabel("split-half reliability (Spearman-Brown)")
        ax.axhline(0.5, ls="--", lw=0.8, color="0.6")
        ax.legend(fontsize=7, ncol=2, frameon=False)
    ax.set_title("Reliability degrades with spatial scale", fontsize=11)
    fig.tight_layout()
    _save(fig, path or FIGDIR / "F4_reliability_vs_scale.png")


def fig_tsnr_per_level(path: Path = None):
    """F5: per-spinal-level tSNR distribution across the cohort."""
    rows = _read("endpoints_long.csv")
    fig, ax = plt.subplots(figsize=(6, 4.2))
    by_level = defaultdict(list)
    for r in rows:
        if r.get("metric") != "tsnr_median" or r.get("tier") != "spinallevel":
            continue
        v = _f(r.get("value"))
        parcel = r.get("parcel") or ""
        if v is not None and parcel.startswith("spinal-"):
            try:
                by_level[int(parcel.split("-")[1])].append(v)
            except (IndexError, ValueError):
                pass
    if not by_level:
        _placeholder(ax, "per-level tSNR not present")
    else:
        levels = sorted(by_level)
        data = [by_level[l] for l in levels]
        ax.boxplot(data, positions=levels, widths=0.6, showfliers=False)
        ax.set_xlabel("spinal level (PAM50 index)")
        ax.set_ylabel("median tSNR")
    ax.set_title("Quality envelope: tSNR by spinal level", fontsize=11)
    fig.tight_layout()
    _save(fig, path or FIGDIR / "F5_tsnr_per_level.png")


def fig_confound_pareto(path: Path = None):
    """F8: confound-family importance -- task sensitivity vs DOF spent."""
    rows = _read("confound_benchmark.csv")
    fig, ax = plt.subplots(figsize=(6, 4.2))
    pts = defaultdict(lambda: {"sens": [], "dof": [], "bpd": []})
    for r in rows:
        s, d = _f(r.get("sensitivity")), _f(r.get("dof_spent"))
        if s is not None and d is not None:
            k = r.get("families", "?")
            pts[k]["sens"].append(s); pts[k]["dof"].append(d)
    if not pts:
        _placeholder(ax, "confound benchmark not present")
    else:
        for fam, v in sorted(pts.items(), key=lambda x: np.mean(x[1]["dof"])):
            ax.scatter(np.mean(v["dof"]), np.mean(v["sens"]), s=40)
            ax.annotate(fam.replace("motion+", "").replace("+", "+\n"),
                        (np.mean(v["dof"]), np.mean(v["sens"])),
                        fontsize=6, xytext=(4, 0), textcoords="offset points",
                        va="center")
        ax.set_xlabel("degrees of freedom spent (regressors)")
        ax.set_ylabel("task sensitivity (top-decile |t|)")
    ax.set_title("Confound families: sensitivity vs DOF cost", fontsize=11)
    fig.tight_layout()
    _save(fig, path or FIGDIR / "F8_confound_pareto.png")


def fig_biological(path: Path = None):
    """C3: laterality per dataset (bar) + dorsal/ventral group dissociation."""
    rows = _read("biological.csv")
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(8, 3.8))
    lat = [(r["dataset"], _f(r["value"]), _f(r["n"]))
           for r in rows if r.get("metric") == "laterality_ipsi_frac"]
    if lat:
        labels = [_short(d) for d, _, _ in lat]
        a1.bar(range(len(lat)), [v for _, v, _ in lat], color="#3b6")
        a1.set_xticks(range(len(lat))); a1.set_xticklabels(labels, rotation=30, fontsize=7)
        a1.set_ylim(0, 1.05); a1.axhline(0.5, ls="--", lw=0.8, color="0.6")
        a1.set_ylabel("fraction of subjects ipsi-dominant")
    else:
        _placeholder(a1, "no laterality rows")
    a1.set_title("Laterality (single-subject)", fontsize=10)

    dv = [(r["dataset"], _f(r["value"]))
          for r in rows if r.get("metric") == "horn_dissociation_d"]
    if dv:
        labels = [_short(d) for d, _ in dv]
        a2.bar(range(len(dv)), [v for _, v in dv], color="#63b")
        a2.set_xticks(range(len(dv))); a2.set_xticklabels(labels, rotation=30, fontsize=7)
        a2.axhline(0, lw=0.8, color="0.6")
        a2.set_ylabel("expected-horn effect (group Cohen's d)")
    else:
        _placeholder(a2, "dorsal/ventral gated on\nPAM50atlas_probseg (re-run)")
    a2.set_title("Dorsal/ventral (group)", fontsize=10)
    fig.tight_layout()
    _save(fig, path or FIGDIR / "F6_biological_validity.png")


def fig_distortion(path: Path = None):
    """F6/F7: SyN fidelity vs the measured TopUp field, per run."""
    rows = _read("distortion.csv")
    fig, ax = plt.subplots(figsize=(6, 4.2))
    fid = [_f(r.get("syn_fidelity")) for r in rows]
    fid = [v for v in fid if v is not None]
    if not fid:
        _placeholder(ax, "distortion falsification pending\n(needs the SyN-mode dual run)")
    else:
        ax.hist(fid, bins=20, color="#c63", alpha=0.8)
        ax.axvline(1.0, ls="--", color="0.3", label="matches measured field")
        ax.axvline(0.0, ls=":", color="0.6", label="no correction")
        ax.set_xlabel("SyN fidelity (fraction of measured field recovered)")
        ax.set_ylabel("runs")
        ax.legend(fontsize=8, frameon=False)
    ax.set_title("Does image-based SyN land where the physics says?", fontsize=11)
    fig.tight_layout()
    _save(fig, path or FIGDIR / "F7_distortion_fidelity.png")


def _save(fig, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {path}")


ALL = [fig_reliability_scale, fig_tsnr_per_level, fig_confound_pareto,
       fig_biological, fig_distortion]


def main() -> int:
    for gen in ALL:
        try:
            gen()
        except Exception as e:                 # a figure must never sink the set
            print(f"FAILED {gen.__name__}: {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
