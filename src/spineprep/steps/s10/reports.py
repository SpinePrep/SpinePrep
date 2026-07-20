"""S10 report layer — subject-level and group-level HTML reports.

Read-only consumer of the flattened chain records (+ chain_qc, recipe). Builds a
report model then renders self-contained static HTML. No new image metrics are
computed here; group statistics (distributions, attrition) are aggregations.

Spec: .claude/specs/s10-reports-redesign.md
Design: figure-first (visual QC is the validator); per-dataset, not pooled;
flag-don't-gate; truthful provenance.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

import numpy as np

# ---------------------------------------------------------------------------
# Shared styling + small helpers
# ---------------------------------------------------------------------------

CSS = """
body { font-family: -apple-system, Segoe UI, Roboto, sans-serif; color:#1d2530;
       background:#f5f6f8; margin:0; padding:0 0 60px 0; }
.wrap { max-width:1120px; margin:0 auto; padding:24px; }
h1 { font-size:1.6em; margin:0 0 4px 0; }
h2 { font-size:1.2em; margin:26px 0 8px 0; border-bottom:2px solid #e2e6ea; padding-bottom:5px; }
h3 { font-size:1.02em; margin:14px 0 6px 0; }
.muted { color:#7a828c; font-size:0.9em; }
.card { background:#fff; border:1px solid #e2e6ea; border-radius:8px; padding:16px 20px; margin:12px 0;
        box-shadow:0 1px 2px rgba(0,0,0,0.04); }
.chip { display:inline-block; padding:2px 9px; border-radius:11px; font-size:0.78em; font-weight:600;
        color:#fff; font-family:ui-monospace, monospace; }
.PASS { background:#1f9d57; } .WARN { background:#e08a00; } .FAIL { background:#cc2a2a; }
.NA   { background:#9aa3ad; }
.strip .chip { margin:1px; min-width:34px; text-align:center; }
.rec-include { color:#1f9d57; } .rec-review { color:#e08a00; } .rec-exclude { color:#cc2a2a; }
.big { font-size:1.9em; font-weight:700; line-height:1.1; }
.kv { display:flex; gap:30px; flex-wrap:wrap; margin:6px 0; }
.kv > div { min-width:120px; }
table { border-collapse:collapse; margin:8px 0; font-size:0.9em; }
th,td { border:1px solid #dde2e6; padding:5px 9px; text-align:left; }
th { background:#eef1f4; }
td.num { text-align:right; font-family:ui-monospace, monospace; }
tr.flag-review td { background:#fff6e6; } tr.flag-exclude td { background:#fdecec; }
img.fig { max-width:100%; border:1px solid #dde2e6; border-radius:4px; background:#fff; display:block; margin:6px 0; }
.figcap { font-size:0.82em; color:#7a828c; margin:0 0 10px 2px; }
.figrow { display:flex; gap:14px; flex-wrap:wrap; }
.figrow > figure { margin:0; flex:1 1 340px; }
.runcard { border-left:4px solid #cdd4da; padding-left:14px; margin:18px 0; }
.runcard.PASS { border-left-color:#1f9d57; } .runcard.WARN { border-left-color:#e08a00; }
.runcard.FAIL { border-left-color:#cc2a2a; }
.reason { background:#fdf2f2; border:1px solid #f3cccc; border-radius:6px; padding:8px 12px; margin:8px 0; font-size:0.9em; }
.reason.warn { background:#fff8ec; border-color:#f0ddb0; }
a { color:#0a6cc4; text-decoration:none; } a:hover { text-decoration:underline; }
ul.links { columns:2; }
details summary { cursor:pointer; font-weight:600; padding:6px 0; }
.smallnote { font-size:0.8em; color:#9aa3ad; }
"""

# Headline reportlets are EMBEDDED; the rest are LINKED. desc token = "<STEP>_<key>".
HEADLINE_FIG = {
    "S2": ["cordmask_montage", "pam50"],
    "S4": ["motion_traces", "tsnr_comparison"],
    "S5": ["distortion_effectiveness"],
    "S9": ["tsnr_map_axial", "tsnr_per_level"],
}
SECONDARY_FIG = {
    "S2": ["totalspineseg", "rootlets", "crop_box"],
    "S3": ["func_localization", "funcref", "frame_metrics", "crop_box"],
    "S4": ["dvars"],
    "S5": ["slice_displacement", "cord_dice_per_slice"],
    "S6": ["bold_on_anat", "cord_dice"],
    "S7": ["pam50_on_func", "pam50_overlay", "cord_dice_per_level"],
    "S8": ["carpet", "fd_dvars", "confound_columns", "correlation"],
    "S9": ["smoothness"],
}

# Reference lines for distribution plots (literature guides, NOT gates).
DIST_METRICS = [
    ("S4", "mean_fd_mm", "Mean FD (mm)", [0.5], "lower"),
    ("S5", "displacement_mean_after_mm", "S5 A-P displacement (mm)", [1.0, 2.0], "lower"),
    ("S6", "cord_dice", "S6 func->anat cord Dice", [0.30, 0.50], "higher"),
    ("S7", "cord_dice_native_func", "S7 PAM50 cord Dice", [0.30, 0.50], "higher"),
    ("S8", "condition_number", "S8 design condition number", [], "lower"),
    ("S9", "tsnr_post_median", "S9 median in-cord tSNR", [3.0, 5.0], "higher"),
]

STEPS = ["S1", "S2", "S2B", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10"]
_BOLD_STEPS = {"S3", "S4", "S5", "S6", "S7", "S8", "S9"}


def _chip(status: Optional[str], label: Optional[str] = None) -> str:
    s = status if status in ("PASS", "WARN", "FAIL") else "NA"
    return f"<span class='chip {s}'>{label or status or '–'}</span>"


def _fmt(v: Any, prec: int = 2) -> str:
    if v is None:
        return "–"
    try:
        f = float(v)
        if not np.isfinite(f):
            return "–"
        return f"{f:.{prec}f}"
    except (TypeError, ValueError):
        return str(v)


def _worst(statuses: list[str]) -> str:
    if any(s == "FAIL" for s in statuses):
        return "FAIL"
    if any(s == "WARN" for s in statuses):
        return "WARN"
    if any(s == "PASS" for s in statuses):
        return "PASS"
    return "NA"


# ---------------------------------------------------------------------------
# Figure resolution (by filename convention {run_id}_desc-<STEP>_<key>.png)
# ---------------------------------------------------------------------------


def _fig_dirs(out_dir: Path, dataset: str, subject: str) -> list[Path]:
    """Every figures/ directory under a sub-<subject> tree, resolving the
    chain-linked derivatives symlink. Robust to all layouts seen across the
    cohort: ``<dataset>/sub-XX/figures``, ``sub-XX/figures``,
    session-based ``sub-XX/ses-YY/figures``, and ``sub-XX/anat/figures``.
    """
    roots: list[Path] = []
    seen: set[Path] = set()
    for base in (out_dir / "derivatives" / "spineprep", out_dir / "release"):
        try:
            rb = base.resolve()
        except Exception:
            continue
        if not rb.is_dir():
            continue
        # `**` matches zero or more intermediate dirs, so this single pattern
        # covers sub-XX/figures, sub-XX/ses-YY/figures, sub-XX/anat/figures, etc.
        for fd in rb.glob(f"**/sub-{subject}/**/figures"):
            if fd.is_dir() and fd not in seen:
                seen.add(fd)
                roots.append(fd)
    return roots


def _step_figs(fig_dirs: list[Path], run_id: str, step: str) -> dict[str, Path]:
    """All reportlet PNGs for (run, step): {key_after_step: path}."""
    found: dict[str, Path] = {}
    prefix = f"{run_id}_desc-{step}_"
    for d in fig_dirs:
        for p in sorted(d.glob(f"{prefix}*.png")):
            key = p.name[len(prefix):-4] if p.name.startswith(prefix) else p.stem
            found.setdefault(key, p)
    return found


def _pick(figs: dict[str, Path], wanted: list[str]) -> list[tuple[str, Path]]:
    """Pick figures whose key contains any wanted substring, in wanted order;
    de-duplicated by path."""
    out: list[tuple[str, Path]] = []
    seen: set[Path] = set()
    for w in wanted:
        for key, p in figs.items():
            if w in key and p not in seen:
                out.append((key, p))
                seen.add(p)
    return out


def _img(report_dir: Path, key: str, path: Path, embed: bool) -> str:
    rel = os.path.relpath(path, report_dir)
    label = key.replace("_", " ")
    if embed:
        return (f"<figure><a href='{rel}' target='_blank'>"
                f"<img class='fig' src='{rel}' alt='{label}'></a>"
                f"<figcaption class='figcap'>{label}</figcaption></figure>")
    return f"<a href='{rel}' target='_blank'>{label}</a>"


# ---------------------------------------------------------------------------
# Per-subject model + recommendation
# ---------------------------------------------------------------------------


def _recommendation(mean_fd, median_tsnr, n_failed, fd_thr, tsnr_thr) -> tuple[str, str]:
    """(recommendation, plain reason). Flag, don't gate — advice only.

    FD deliberately does NOT contribute. This report used to add
    ``mean FD ... exceeds 0.5 mm (Kaptan 2023)``, which was wrong three times
    over: Kaptan 2023 computes no FD at all (it censors on DVARS/refRMS at
    2 SD); 0.5 mm is Power 2012's BRAIN value; and it sits at this cohort's own
    FD median (0.494 mm), so it flagged 265 of 467 runs -- 57% -- as exclusion
    candidates. S4 removed the equivalent gate on 2026-07-16 with the rationale
    that "reporting a fraction-above-an-invalid-threshold is a claim, and it was
    a claim above its evidence"; that reasoning applies identically here and the
    fix simply had not propagated. Mean FD is still reported as a descriptive
    number in the metrics table -- it is just no longer a verdict.

    ``fd_thr`` is retained in the signature for callers/tests and is unused.
    """
    del fd_thr  # intentionally not a criterion; see docstring
    reasons = []
    if n_failed > 0:
        reasons.append(f"{n_failed} run(s) failed a pipeline step")
    if (median_tsnr is not None and np.isfinite(median_tsnr)
            and median_tsnr < tsnr_thr):
        reasons.append(f"median in-cord tSNR {median_tsnr:.1f} below {tsnr_thr}")
    if not reasons:
        return "include", "no failed steps; in-cord tSNR above the reporting floor"
    rec = "exclude" if n_failed > 0 and len(reasons) >= 2 else "review"
    return rec, "; ".join(reasons)


def _subject_runs(records: list[dict], dataset: str, subject: str) -> dict[str, dict]:
    """{run_id: {step: record}} for one subject, BOLD steps + anat."""
    runs: dict[str, dict] = {}
    for r in records:
        if r.get("dataset_key") != dataset or r.get("subject") != subject:
            continue
        rid = r.get("run_id")
        if rid is None:
            continue
        runs.setdefault(rid, {})[r.get("step")] = r
    return runs


def _metric(run_steps: dict, step: str, key: str) -> Any:
    rec = run_steps.get(step)
    if not rec:
        return None
    return (rec.get("metrics") or {}).get(key)


# ---------------------------------------------------------------------------
# Subject report
# ---------------------------------------------------------------------------


def build_subject_report(
    out_dir: Path, deriv_root: Path, dataset: str, subject: str,
    records: list[dict], policy: dict, recipe: dict,
    citation_html: Optional[str] = None,
) -> Optional[Path]:
    runs = _subject_runs(records, dataset, subject)
    if not runs:
        return None
    report_dir = deriv_root / dataset / f"sub-{subject}"
    report_dir.mkdir(parents=True, exist_ok=True)
    out_path = report_dir / f"sub-{subject}_qc_report.html"
    fig_dirs = _fig_dirs(out_dir, dataset, subject)

    p_thr = policy.get("publication", {}).get("participants_tsv", {})
    fd_thr = float(p_thr.get("include_threshold_fd", 0.5))
    tsnr_thr = float(p_thr.get("include_threshold_tsnr", 5.0))

    # --- headline numbers + recommendation ---
    bold_run_ids = [rid for rid, steps in runs.items()
                    if _BOLD_STEPS & set(steps.keys())]
    fds, tsnrs, n_failed = [], [], 0
    for rid in bold_run_ids:
        steps = runs[rid]
        statuses = [rec.get("status") for s, rec in steps.items() if s in _BOLD_STEPS]
        if any(s == "FAIL" for s in statuses):
            n_failed += 1
        fd = _metric(steps, "S4", "mean_fd_mm")
        if fd is not None:
            fds.append(float(fd))
        ts = _metric(steps, "S9", "tsnr_post_median")
        if ts is not None:
            tsnrs.append(float(ts))
    mean_fd = float(np.mean(fds)) if fds else None
    median_tsnr = float(np.median(tsnrs)) if tsnrs else None
    n_pass = sum(1 for rid in bold_run_ids
                 if _worst([runs[rid][s].get("status") for s in runs[rid]
                            if s in _BOLD_STEPS]) == "PASS")
    rec, reason = _recommendation(mean_fd, median_tsnr, n_failed, fd_thr, tsnr_thr)

    # step strip (worst across all runs per step)
    strip = []
    for st in STEPS:
        sts = [runs[rid][st].get("status") for rid in runs if st in runs[rid]]
        if not sts:
            continue
        strip.append(_chip(_worst(sts), st))

    h = [f"<!DOCTYPE html><html><head><meta charset='utf-8'>",
         f"<title>QC — sub-{subject} ({dataset})</title><style>{CSS}</style>",
         "</head><body><div class='wrap'>"]
    h.append(f"<h1>Subject QC report — sub-{subject}</h1>")
    h.append(f"<p class='muted'>Dataset <code>{dataset}</code> · "
             f"{len(bold_run_ids)} functional run(s)</p>")

    # A. Summary card
    h.append("<div class='card'>")
    h.append(f"<div class='big rec-{rec}'>{rec.upper()}</div>")
    h.append(f"<p>{reason}.</p>")
    h.append("<div class='kv'>"
             f"<div><div class='muted'>mean FD</div><b>{_fmt(mean_fd)} mm</b></div>"
             f"<div><div class='muted'>median in-cord tSNR</div><b>{_fmt(median_tsnr,1)}</b></div>"
             f"<div><div class='muted'>runs PASS</div><b>{n_pass}/{len(bold_run_ids)}</b></div>"
             "</div>")
    h.append("<div class='strip'>" + " ".join(strip) + "</div>")
    h.append("</div>")

    # B. Anatomical (S2)
    s2_figs = {}
    for d in fig_dirs:
        for p in sorted(d.glob(f"sub-{subject}_*_desc-S2_*.png")):
            key = p.name.split("_desc-S2_", 1)[-1][:-4]
            s2_figs.setdefault(key, p)
    if s2_figs:
        h.append("<div class='card'><h2>Anatomical reference (S2)</h2>")
        h.append("<p class='figcap'>Cord segmentation + vertebral labelling and "
                 "PAM50 registration. Look for: the cord contour hugging the cord "
                 "across all slices, and PAM50 levels landing on the right vertebrae.</p>")
        picks = _pick(s2_figs, HEADLINE_FIG["S2"]) or list(s2_figs.items())[:2]
        h.append("<div class='figrow'>"
                 + "".join(_img(report_dir, k, p, True) for k, p in picks[:2])
                 + "</div>")
        h.append("</div>")

    # C. Per-run functional cards
    h.append("<h2>Functional runs</h2>")
    for rid in sorted(bold_run_ids):
        steps = runs[rid]
        statuses = [rec.get("status") for s, rec in steps.items() if s in _BOLD_STEPS]
        worst = _worst(statuses)
        h.append(f"<div class='runcard {worst}'>")
        h.append(f"<h3>{rid} &nbsp; {_chip(worst, worst)}</h3>")
        # per-step chips
        h.append("<div class='strip'>"
                 + " ".join(_chip(steps[s].get("status"), s)
                            for s in STEPS if s in steps and s in _BOLD_STEPS)
                 + "</div>")
        # failure / warn explanation
        for s in ("S3", "S4", "S5", "S6", "S7", "S8", "S9"):
            rec_s = steps.get(s)
            if rec_s and rec_s.get("status") in ("FAIL", "WARN") and rec_s.get("failure_message"):
                cls = "" if rec_s["status"] == "FAIL" else " warn"
                h.append(f"<div class='reason{cls}'><b>{s} {rec_s['status']}:</b> "
                         f"{rec_s['failure_message']}</div>")
        # metric micro-table
        disp = _metric(steps, "S5", "displacement_mean_after_mm")
        s5_mode = (steps.get("S5", {}).get("metrics") or {}).get("mode") or \
                  (steps.get("S5", {}).get("metrics") or {}).get("distortion_correction_mode")
        disp_note = ""
        s5_reasons = steps.get("S5", {}).get("failure_message") or ""
        if "distortion-limited" in s5_reasons:
            disp_note = " <span class='smallnote'>(distortion-limited, no fieldmap)</span>"
        # FD is reported threshold-free (median/max describe the motion without
        # judging it). The censored fraction is read from S8, the step that
        # actually censors, on the intensity metrics. This row previously showed
        # S4's `high_motion_fraction` under the label "% frames censored", which
        # was wrong twice over: S4 does not censor, and the fraction was computed
        # against a 0.5 mm reference that sits at the cohort's own FD median.
        # See .claude/specs/s4-fd-threshold.md.
        mt = [
            ("Median FD (mm)", _fmt(_metric(steps, "S4", "median_fd_mm"))),
            ("Max FD (mm)", _fmt(_metric(steps, "S4", "max_fd_mm"))),
            ("% frames censored", _fmt(
                (_metric(steps, "S8", "outlier_fraction") or 0) * 100, 1)),
            ("S5 cord Dice", _fmt(_metric(steps, "S5", "dice_mean_after"))),
            ("S5 A-P disp (mm)", _fmt(disp) + disp_note),
            ("S6 cord Dice", _fmt(_metric(steps, "S6", "cord_dice"))),
            ("S7 PAM50 Dice", _fmt(_metric(steps, "S7", "cord_dice_native_func"))),
            ("S8 condition #", _fmt(_metric(steps, "S8", "condition_number"), 1)),
            ("S9 tSNR pre→post", f"{_fmt(_metric(steps, 'S9', 'tsnr_pre_median'),1)}"
                                 f"→{_fmt(_metric(steps, 'S9', 'tsnr_post_median'),1)}"),
        ]
        h.append("<table><tr><th>metric</th><th>value</th></tr>"
                 + "".join(f"<tr><td>{k}</td><td class='num'>{v}</td></tr>" for k, v in mt)
                 + "</table>")
        # embedded headline figures + linked secondary
        embedded = []
        linked = []
        for s in ("S4", "S5", "S9"):
            figs = _step_figs(fig_dirs, rid, s)
            embedded += _pick(figs, HEADLINE_FIG.get(s, []))
        for s in ("S3", "S5", "S6", "S7", "S8", "S9"):
            figs = _step_figs(fig_dirs, rid, s)
            linked += [(f"{s}·{k}", p) for k, p in _pick(figs, SECONDARY_FIG.get(s, []))]
        if embedded:
            h.append("<div class='figrow'>"
                     + "".join(_img(report_dir, k, p, True) for k, p in embedded)
                     + "</div>")
        if linked:
            h.append("<p class='figcap'>More figures: "
                     + " · ".join(_img(report_dir, k, p, False) for k, p in linked)
                     + "</p>")
        h.append("</div>")

    # D. Confound model (S8) — use the first run that has S8 metrics
    s8 = next((runs[rid]["S8"] for rid in bold_run_ids
               if "S8" in runs[rid]), None)
    if s8:
        m = s8.get("metrics") or {}
        h.append("<div class='card'><h2>Confound model (S8) — for your GLM</h2>")
        h.append("<p>The pipeline did not regress the BOLD; it emitted these "
                 "nuisance regressors for you to include in your model:</p>")
        rows = [
            ("Total regressors", m.get("n_columns_total")),
            ("Motion (trans + derivatives + FD)", m.get("n_columns_motion")),
            ("CSF / aCompCor", m.get("n_columns_csf")),
            ("RETROICOR (physio)", m.get("n_columns_retroicor")),
            ("SpinalCompCor", m.get("n_columns_spinalcompcor")),
            ("Cosine drift", m.get("n_columns_cosine")),
            ("Outlier spikes", m.get("n_columns_outliers")),
            ("Design condition number", m.get("condition_number")),
        ]
        h.append("<table><tr><th>family</th><th>columns</th></tr>"
                 + "".join(f"<tr><td>{k}</td><td class='num'>{_fmt(v,1) if 'condition' in k else (v if v is not None else '–')}</td></tr>"
                           for k, v in rows) + "</table>")
        h.append("</div>")

    # E. Methods (collapsible)
    if citation_html:
        h.append("<div class='card'><details><summary>Methods boilerplate "
                 "(auto-generated, CC0 — reuse verbatim)</summary>"
                 f"<div>{citation_html}</div></details></div>")

    # F. Provenance footer
    h.append("<p class='smallnote'>SpinePrep "
             f"{recipe.get('pipeline_git_describe','?')} "
             f"(git {str(recipe.get('pipeline_git_sha',''))[:10]}) · "
             f"SCT {recipe.get('sct_version','?')} · FSL {recipe.get('fsl_version','?')} · "
             f"generated {str(recipe.get('timestamp_utc',''))[:19]}Z · "
             "QC is advisory — the reader makes the final call.</p>")
    h.append("</div></body></html>")
    out_path.write_text("\n".join(h), encoding="utf-8")
    return out_path


# ---------------------------------------------------------------------------
# Group report figures
# ---------------------------------------------------------------------------


def _attrition_waterfall_png(records: list[dict], dataset: str, out_png: Path) -> Optional[dict]:
    """Run-count waterfall S3->S9 with per-step drop counts. Returns the
    step->count + drop reasons dict (also drives the HTML table)."""
    chain = ["S3", "S4", "S5", "S6", "S7", "S8", "S9"]
    ds_recs = [r for r in records if r.get("dataset_key") == dataset
               and r.get("step") in _BOLD_STEPS and r.get("run_id")]
    if not ds_recs:
        return None
    counts, fails = {}, {}
    for st in chain:
        rr = [r for r in ds_recs if r.get("step") == st]
        counts[st] = len({r["run_id"] for r in rr})
        fails[st] = len({r["run_id"] for r in rr if r.get("status") == "FAIL"})
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(max(7, len(chain) * 1.05), 3.8))
        vals = [counts[s] for s in chain]
        ax.bar(range(len(chain)), vals, color="#5b8def", width=0.62)
        for i, s in enumerate(chain):
            ax.text(i, vals[i] + max(vals) * 0.01, str(vals[i]), ha="center", fontsize=9)
            if i > 0:
                drop = counts[chain[i - 1]] - counts[s]
                if drop > 0:
                    ax.text(i - 0.5, max(vals) * 0.5, f"−{drop}", ha="center",
                            color="#cc2a2a", fontsize=9, fontweight="bold")
        ax.set_xticks(range(len(chain)))
        ax.set_xticklabels(chain)
        ax.set_ylabel("runs entering step")
        ax.set_title(f"{dataset} — run attrition through the chain")
        ax.grid(axis="y", alpha=0.25); ax.set_axisbelow(True)
        fig.tight_layout(); fig.savefig(out_png, dpi=120, bbox_inches="tight")
        plt.close(fig)
    except Exception:
        pass
    return {"counts": counts, "fails": fails, "chain": chain}


def _dist_panel_png(records: list[dict], dataset: str, out_png: Path) -> Optional[Path]:
    """MRIQC-style distribution panel for one dataset: one box+dots per headline
    metric, threshold reference lines drawn."""
    series = []
    for step, key, label, thr, _dir in DIST_METRICS:
        vals = []
        for r in records:
            if r.get("dataset_key") != dataset or r.get("step") != step:
                continue
            v = (r.get("metrics") or {}).get(key)
            if v is None:
                continue
            try:
                vf = float(v)
            except (TypeError, ValueError):
                continue
            if np.isfinite(vf):
                vals.append(vf)
        if vals:
            series.append((label, vals, thr))
    if not series:
        return None
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        n = len(series)
        fig, axes = plt.subplots(1, n, figsize=(max(5, 2.6 * n), 4.0))
        if n == 1:
            axes = [axes]
        rng = np.random.default_rng(11)
        for ax, (label, vals, thr) in zip(axes, series):
            ax.boxplot(vals, widths=0.5, patch_artist=True,
                       boxprops=dict(facecolor="#eef2fb", color="#445"),
                       medianprops=dict(color="#cc2a2a"),
                       flierprops=dict(marker=""))
            xj = 1 + (rng.random(len(vals)) - 0.5) * 0.22
            ax.scatter(xj, vals, s=20, alpha=0.8, color="#5b8def",
                       edgecolor="white", linewidth=0.4, zorder=3)
            for t in thr:
                ax.axhline(t, color="#e08a00", ls="--", lw=1, alpha=0.8)
            ax.set_title(label, fontsize=8.5)
            ax.set_xticks([])
            ax.grid(axis="y", alpha=0.25); ax.set_axisbelow(True)
        fig.suptitle(f"{dataset} — QC metric distributions "
                     "(dashed = literature reference)", fontsize=10)
        fig.tight_layout(rect=(0, 0, 1, 0.95))
        fig.savefig(out_png, dpi=120, bbox_inches="tight")
        plt.close(fig)
        return out_png
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Group report (per dataset)
# ---------------------------------------------------------------------------


def build_group_report(
    out_dir: Path, deriv_root: Path, dataset: str,
    records: list[dict], policy: dict, recipe: dict,
    participants_rows: list[dict], subject_reports: dict[str, Path],
) -> Optional[Path]:
    ds_recs = [r for r in records if r.get("dataset_key") == dataset]
    if not ds_recs:
        return None
    out_path = deriv_root / f"group_report_{dataset}.html"
    subjects = sorted({r["subject"] for r in ds_recs if r.get("subject")})

    # run tallies
    run_worst = {}
    for r in ds_recs:
        if r.get("step") in _BOLD_STEPS and r.get("run_id"):
            key = (r["subject"], r.get("session"), r["run_id"])
            run_worst.setdefault(key, []).append(r.get("status"))
    worsts = [_worst(v) for v in run_worst.values()]
    n_pass = worsts.count("PASS"); n_warn = worsts.count("WARN"); n_fail = worsts.count("FAIL")

    h = [f"<!DOCTYPE html><html><head><meta charset='utf-8'>",
         f"<title>Group QC — {dataset}</title><style>{CSS}</style></head>",
         "<body><div class='wrap'>"]
    h.append(f"<h1>Group QC report — {dataset}</h1>")
    h.append("<p class='muted'><a href='release_report.html'>&larr; cohort overview</a></p>")

    # A. Cohort summary
    p_rows = [p for p in participants_rows if p.get("dataset_key") == dataset]
    n_inc = sum(1 for p in p_rows if p.get("included_recommendation") == "include")
    n_rev = sum(1 for p in p_rows if p.get("included_recommendation") == "review")
    h.append("<div class='card'><h2>Cohort summary</h2>")
    h.append("<div class='kv'>"
             f"<div><div class='muted'>subjects</div><b>{len(subjects)}</b></div>"
             f"<div><div class='muted'>runs</div><b>{len(run_worst)}</b></div>"
             f"<div><div class='muted'>runs PASS/WARN/FAIL</div><b>{n_pass}/{n_warn}/{n_fail}</b></div>"
             f"<div><div class='muted'>recommend include</div><b>{n_inc}</b></div>"
             f"<div><div class='muted'>recommend review</div><b class='rec-review'>{n_rev}</b></div>"
             "</div></div>")

    # E. Attrition waterfall (computed early; reused in summary truthfulness)
    waterfall_png = out_path.with_name(f"attrition_{dataset}.png")
    wf = _attrition_waterfall_png(records, dataset, waterfall_png)

    # B. Inclusion table
    if p_rows:
        h.append("<div class='card'><h2>Inclusion table</h2>")
        h.append("<p class='figcap'>Advisory recommendation per subject. "
                 "Review/exclude rows shaded. Click a subject to open its report.</p>")
        h.append("<table><tr><th>subject</th><th>runs</th><th>PASS</th><th>WARN</th>"
                 "<th>FAIL</th><th>mean FD (mm)</th><th>median tSNR</th><th>recommendation</th></tr>")
        for p in sorted(p_rows, key=lambda x: x["participant_id"]):
            recm = p.get("included_recommendation", "include")
            cls = f" class='flag-{recm}'" if recm != "include" else ""
            sub = p["participant_id"].replace("sub-", "")
            link = subject_reports.get(sub)
            sub_cell = (f"<a href='{os.path.relpath(link, out_path.parent)}'>{p['participant_id']}</a>"
                        if link else p["participant_id"])
            h.append(f"<tr{cls}><td>{sub_cell}</td>"
                     f"<td class='num'>{p.get('n_runs')}</td>"
                     f"<td class='num'>{p.get('n_passed')}</td>"
                     f"<td class='num'>{p.get('n_warn')}</td>"
                     f"<td class='num'>{p.get('n_failed')}</td>"
                     f"<td class='num'>{p.get('mean_fd_mm')}</td>"
                     f"<td class='num'>{p.get('median_in_cord_tsnr')}</td>"
                     f"<td class='rec-{recm}'>{recm}</td></tr>")
        h.append("</table></div>")

    # C. Metric distributions
    dist_png = _dist_panel_png(records, dataset, out_path.with_name(f"dist_{dataset}.png"))
    if dist_png:
        h.append("<div class='card'><h2>QC metric distributions</h2>")
        h.append(f"<img class='fig' src='{dist_png.name}'>")
        h.append("<p class='figcap'>One dot per run; dashed lines are the "
                 "pipeline's own reporting reference values (CoSpine 2025 for "
                 "displacement and Dice; SpinePrep's operating points for tSNR). "
                 "No FD reference line is drawn: the only published cord value is "
                 "brain-derived and sits at this cohort's own median. "
                 "Spot the outliers — they are advisory, not gated.</p>")
        h.append("</div>")

    # D. Per-vertebral-level views (embed cohort PNGs if present)
    level_imgs = []
    for nm, fn in [("Cord tSNR by vertebral level", "cohort_tsnr_heatmap.png"),
                   ("Vertebral coverage matrix", "cohort_coverage_matrix.png")]:
        fp = deriv_root / fn
        if fp.exists():
            level_imgs.append((nm, fp))
    if level_imgs:
        h.append("<div class='card'><h2>Per-vertebral-level cohort views</h2>")
        for nm, fp in level_imgs:
            h.append(f"<h3>{nm}</h3><img class='fig' src='{fp.name}'>")
        h.append("<p class='figcap'>Cord-specific quality resolved per vertebral "
                 "level (pooled across datasets in this release).</p></div>")

    # E. Attrition table + figure
    if wf:
        h.append("<div class='card'><h2>Run attrition through the chain</h2>")
        if waterfall_png.exists():
            h.append(f"<img class='fig' src='{waterfall_png.name}'>")
        h.append("<table><tr><th>step</th><th>runs entering</th><th>dropped here</th>"
                 "<th>(= step FAILs)</th></tr>")
        chain = wf["chain"]
        for i, st in enumerate(chain):
            drop = (wf["counts"][chain[i - 1]] - wf["counts"][st]) if i > 0 else 0
            h.append(f"<tr><td>{st}</td><td class='num'>{wf['counts'][st]}</td>"
                     f"<td class='num'>{drop if i>0 else '–'}</td>"
                     f"<td class='num'>{wf['fails'][chain[i-1]] if i>0 else '–'}</td></tr>")
        h.append("</table>")
        h.append("<p class='figcap'>Every drop equals the prior step's FAIL count — "
                 "no run is silently lost.</p></div>")

    # F. Failure stratification
    strat = {}
    for r in ds_recs:
        if r.get("status") in ("WARN", "FAIL") and r.get("step") in _BOLD_STEPS:
            strat.setdefault(r["step"], {"WARN": 0, "FAIL": 0})[r["status"]] += 1
    if strat:
        h.append("<div class='card'><h2>WARN / FAIL by step</h2>")
        h.append("<table><tr><th>step</th><th>WARN</th><th>FAIL</th></tr>"
                 + "".join(f"<tr><td>{s}</td><td class='num'>{c['WARN']}</td>"
                           f"<td class='num'>{c['FAIL']}</td></tr>"
                           for s, c in sorted(strat.items()))
                 + "</table></div>")

    # G. Reproducibility panel
    h.append("<div class='card'><h2>Reproducibility</h2>")
    h.append("<div class='kv'>"
             f"<div><div class='muted'>pipeline</div><b>{recipe.get('pipeline_git_describe','?')}</b></div>"
             f"<div><div class='muted'>git SHA</div><code>{str(recipe.get('pipeline_git_sha',''))[:12]}</code></div>"
             f"<div><div class='muted'>SCT</div><b>{recipe.get('sct_version','?')}</b></div>"
             f"<div><div class='muted'>FSL</div><b>{recipe.get('fsl_version','?')}</b></div>"
             "</div>")
    shas = recipe.get("policy_sha256_per_step", {}) or {}
    if shas:
        h.append("<details><summary>Per-step policy SHA-256</summary><table>"
                 + "".join(f"<tr><td>{k}</td><td><code>{str(v)[:16] if v else '–'}</code></td></tr>"
                           for k, v in shas.items()) + "</table></details>")
    h.append("<p class='figcap'>Same chain + same policy SHAs + same git SHA → "
             "byte-identical re-run. Full inventory in reproducibility_receipt.json.</p>")
    h.append("</div>")

    # H. Methods boilerplate + references
    cit_html = deriv_root / "logs" / "CITATION.html"
    cit_bib = deriv_root / "logs" / "CITATION.bib"
    if cit_html.exists() or cit_bib.exists():
        h.append("<div class='card'><h2>Methods &amp; references</h2>")
        links = []
        if cit_html.exists():
            links.append(f"<a href='{os.path.relpath(cit_html, out_path.parent)}'>"
                         "methods boilerplate (auto-generated, CC0)</a>")
        if cit_bib.exists():
            links.append(f"<a href='{os.path.relpath(cit_bib, out_path.parent)}'>"
                         "references (BibTeX)</a>")
        h.append("<p>" + " · ".join(links) + "</p>")
        h.append("<p class='figcap'>Reuse the boilerplate verbatim; it is generated "
                 "from the live policy values, so it tracks what actually ran.</p>")
        h.append("</div>")

    h.append("<p class='smallnote'>Generated by SpinePrep S10 · QC is advisory.</p>")
    h.append("</div></body></html>")
    out_path.write_text("\n".join(h), encoding="utf-8")
    return out_path


# ---------------------------------------------------------------------------
# Cross-dataset overview (release_report.html)
# ---------------------------------------------------------------------------


def build_overview(
    out_dir: Path, deriv_root: Path, records: list[dict],
    group_reports: dict[str, Path], subject_reports: dict[tuple, Path],
    deliverables: dict, recipe: dict, out_path: Path,
) -> None:
    datasets = sorted({r.get("dataset_key") for r in records if r.get("dataset_key")})
    rel = {k: (os.path.relpath(out_dir / v, out_path.parent) if v else "#")
           for k, v in deliverables.items()}
    h = [f"<!DOCTYPE html><html><head><meta charset='utf-8'>",
         f"<title>SpinePrep — Release</title><style>{CSS}</style></head>",
         "<body><div class='wrap'>"]
    h.append("<h1>SpinePrep — Release report</h1>")
    n_sub = len({(r.get("dataset_key"), r.get("subject")) for r in records if r.get("subject")})
    h.append(f"<p class='muted'>{len(datasets)} dataset(s) · {n_sub} subjects. "
             "Per-dataset group reports below; QC is advisory (the reader rates).</p>")

    # Run-level QC rollup, up front. This page used to be a pure link index: a
    # reviewer saw a healthy-looking list and had to open run_inventory.tsv
    # unaided to discover that most runs were WARN or worse.
    _rank = {"PASS": 0, "WARN": 1, "FAIL": 2}
    _worst: dict[tuple, str] = {}
    for r in records:
        if r.get("step") not in _BOLD_STEPS or not r.get("run_id"):
            continue
        st = r.get("status")
        if st not in _rank:
            continue
        k = (r.get("dataset_key"), r.get("subject"), r.get("session"), r.get("run_id"))
        if k not in _worst or _rank[st] > _rank[_worst[k]]:
            _worst[k] = st
    if _worst:
        n_tot = len(_worst)
        n_p = sum(1 for v in _worst.values() if v == "PASS")
        n_w = sum(1 for v in _worst.values() if v == "WARN")
        n_f = sum(1 for v in _worst.values() if v == "FAIL")
        h.append("<div class='card'><h2>Run QC summary</h2>")
        h.append(f"<p><strong>{n_tot}</strong> runs · "
                 f"<span style='color:#16a34a'>{n_p} PASS</span> · "
                 f"<span style='color:#d97706'>{n_w} WARN</span> · "
                 f"<span style='color:#dc2626'>{n_f} FAIL</span> "
                 f"({100.0*n_f/n_tot:.0f}% failed)</p>")
        h.append("<p class='muted'>Worst status across S3–S9 per run. "
                 "Per-run detail is in <code>run_inventory.tsv</code>.</p>")
        h.append("</div>")

    # Per-dataset group reports
    h.append("<div class='card'><h2>Datasets</h2><ul class='links'>")
    for ds in datasets:
        gr = group_reports.get(ds)
        link = os.path.relpath(gr, out_path.parent) if gr else "#"
        subs = sorted({s for (d, s) in subject_reports if d == ds})
        h.append(f"<li><a href='{link}'><b>{ds}</b></a> — group report "
                 f"({len(subs)} subjects)</li>")
    h.append("</ul></div>")

    # Subject reports grouped by dataset
    h.append("<div class='card'><h2>Per-subject reports</h2>")
    for ds in datasets:
        subs = sorted([(s, p) for (d, s), p in subject_reports.items() if d == ds])
        if not subs:
            continue
        h.append(f"<h3>{ds}</h3><ul class='links'>"
                 + "".join(f"<li><a href='{os.path.relpath(p, out_path.parent)}'>sub-{s}</a></li>"
                           for s, p in subs) + "</ul>")
    h.append("</div>")

    # Pooled cohort views
    h.append("<div class='card'><h2>Cohort views (pooled)</h2><ul class='links'>"
             f"<li><a href='{rel.get('group_dashboard','#')}'>Status dashboard</a></li>"
             f"<li><a href='{rel.get('coverage_matrix_png','#')}'>Vertebral coverage matrix</a></li>"
             f"<li><a href='{rel.get('tsnr_heatmap_png','#')}'>Cord tSNR by level</a></li>"
             f"<li><a href='{rel.get('run_inventory_png','#')}'>Run inventory</a></li>"
             "</ul></div>")

    # Release artifacts
    h.append("<div class='card'><h2>Release artifacts</h2><ul class='links'>"
             f"<li><a href='{rel.get('citation_cff','#')}'>CITATION.cff</a> · "
             f"<a href='{rel.get('citation_bib','#')}'>CITATION.bib</a></li>"
             f"<li><a href='{rel.get('citation_html','#')}'>Methods boilerplate</a></li>"
             f"<li><a href='{rel.get('dataset_description','#')}'>dataset_description.json</a></li>"
             f"<li><a href='{rel.get('participants_tsv','#')}'>participants.tsv</a></li>"
             f"<li><a href='{rel.get('reproducibility_receipt','#')}'>reproducibility_receipt.json</a></li>"
             f"<li><a href='{rel.get('metrics_index_tsv','#')}'>metrics_index.tsv</a></li>"
             "</ul></div>")
    h.append(f"<p class='smallnote'>SpinePrep {recipe.get('pipeline_git_describe','?')} · "
             f"generated {str(recipe.get('timestamp_utc',''))[:19]}Z</p>")
    h.append("</div></body></html>")
    out_path.write_text("\n".join(h), encoding="utf-8")
