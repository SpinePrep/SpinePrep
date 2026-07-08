"""Test-retest reliability of task ACTIVATION (T2/R4).

For task datasets with two sessions, fit a first-level GLM per vertebral level
(task vs rest, canonical HRF; motion + outlier confounds as nuisance) on the
per-level mean BOLD time-series, take the task-activation beta per level, and
compute ICC(2,1) of those betas across sessions. Asks: is the localised task
response reproducible across sessions? Benchmark module, not a pipeline step.

Usage: poetry run python validation/reliability_activation.py [scope ...]
"""
from __future__ import annotations

import glob
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reliability_tsnr import icc_2_1, _level_name           # noqa: E402
from reliability_connectivity import _per_level_timeseries   # noqa: E402

TASK_SCOPES = {  # scope -> (raw-dataset glob for events, TR seconds)
    "handgrasp": ("datasets/openneuro_ds004616*", 2.0),
    "dorsalhorn": ("datasets/openneuro_ds004926*", None),  # TR from sidecar
}
REST_LABELS = {"rest", "baseline", "fixation", "off", "null"}


def _task_regressor(events_tsv: Path, n_vol: int, tr: float) -> np.ndarray | None:
    """Canonical-HRF task (active-vs-rest) regressor sampled at the TR grid."""
    try:
        from nilearn.glm.first_level import make_first_level_design_matrix
        ev = pd.read_csv(events_tsv, sep="\t")
    except Exception:
        return None
    ev = ev.dropna(subset=["onset", "duration"]).copy()
    # collapse every non-rest condition into one "task" condition
    ev["trial_type"] = ev["trial_type"].astype(str).apply(
        lambda t: "rest" if t.strip().lower() in REST_LABELS else "task")
    ev = ev[ev["trial_type"] == "task"]
    if ev.empty:
        return None
    frame_times = np.arange(n_vol) * tr
    dm = make_first_level_design_matrix(frame_times, ev, hrf_model="glover",
                                        drift_model=None)
    if "task" not in dm.columns:
        return None
    return dm["task"].to_numpy()


def _activation_betas(bold: Path, atlas: Path, events: Path, confounds: Path,
                      tr: float) -> dict[int, float]:
    """{level: task beta} from an OLS GLM (task + nuisance) on per-level means."""
    ts = _per_level_timeseries(bold, atlas)  # z-scored per-level means
    if len(ts) < 2:
        return {}
    n_vol = len(next(iter(ts.values())))
    task = _task_regressor(events, n_vol, tr)
    if task is None or len(task) != n_vol:
        return {}
    # nuisance: motion + outliers (numeric confound columns), trimmed/padded to n_vol
    nuis = np.ones((n_vol, 1))
    try:
        cf = pd.read_csv(confounds, sep="\t").select_dtypes("number")
        keep = [c for c in cf.columns if c.startswith(("trans_", "rot_", "motion_outlier"))]
        if keep:
            m = cf[keep].to_numpy()[:n_vol]
            if m.shape[0] == n_vol:
                nuis = np.column_stack([nuis, np.nan_to_num(m)])
    except Exception:
        pass
    X = np.column_stack([task - task.mean(), nuis])
    betas = {}
    for lvl, y in ts.items():
        try:
            beta, *_ = np.linalg.lstsq(X, y, rcond=None)
            betas[lvl] = float(beta[0])  # task regressor coefficient
        except Exception:
            continue
    return betas


def _runs(scope: str, ev_glob: str, tr_default):
    s9 = Path(f"work/done/{scope}/S9/derivatives/spineprep")
    s7 = Path(f"work/done/{scope}/S7/derivatives/spineprep")
    s8 = Path(f"work/done/{scope}/S8/derivatives/spineprep")
    for bold in glob.glob(str(s9 / "**" / "*_desc-preproc_bold.nii.gz"), recursive=True):
        if "PAM50" in Path(bold).name:
            continue
        rid = Path(bold).name.replace("_desc-preproc_bold.nii.gz", "")
        m = re.search(r"(sub-[A-Za-z0-9]+)_ses-([0-9]+)", rid)
        if not m:
            continue
        sub, ses = m.group(1), m.group(2)
        atlas = glob.glob(str(s7 / "**" / f"{rid}_desc-PAM50spinallevels.nii.gz"), recursive=True)
        conf = glob.glob(str(s8 / "**" / f"{rid}_desc-confounds_timeseries.tsv"), recursive=True)
        # events live in the raw dataset (task is shared across sessions/runs)
        task = re.search(r"task-([A-Za-z0-9]+)", rid)
        ev = glob.glob(f"{ev_glob}/{sub}/**/*task-{task.group(1) if task else ''}*events.tsv",
                       recursive=True) if task else []
        if atlas and conf and ev:
            yield sub, ses, Path(bold), Path(atlas[0]), Path(ev[0]), Path(conf[0])


def run(scopes: list[str], out_tsv: Path | None = None) -> pd.DataFrame:
    results = []
    for scope in scopes:
        ev_glob, tr = TASK_SCOPES.get(scope, (f"datasets/*{scope}*", None))
        per_ss: dict[tuple[str, str], dict[int, float]] = {}
        for sub, ses, bold, atlas, ev, conf in _runs(scope, ev_glob, tr):
            t = tr or 2.0
            betas = _activation_betas(bold, atlas, ev, conf, t)
            if betas:
                # average runs within a (sub, ses)
                d = per_ss.setdefault((sub, ses), {})
                for lvl, b in betas.items():
                    d[lvl] = (d.get(lvl, b) + b) / 2 if lvl in d else b
        if not per_ss:
            print(f"  {scope}: no usable task runs")
            continue
        subs = sorted({s for s, _ in per_ss})
        sess = sorted({se for _, se in per_ss})[:2]
        levels = sorted({lvl for d in per_ss.values() for lvl in d})
        iccs = []
        for lvl in levels:
            rows = [[per_ss.get((s, se), {}).get(lvl) for se in sess] for s in subs]
            rows = [r for r in rows if all(x is not None for x in r)]
            if len(rows) >= 3:
                icc, n = icc_2_1(np.array(rows, dtype=float))
                if not np.isnan(icc):
                    iccs.append(icc)
                    results.append({"scope": scope, "level": _level_name(lvl),
                                    "icc_2_1": round(icc, 3), "n": n})
        if iccs:
            print(f"  {scope}: task-activation test-retest ICC mean={np.mean(iccs):.2f} "
                  f"(max {np.max(iccs):.2f}), {len(iccs)} levels, sessions {sess}")
    df = pd.DataFrame(results)
    if out_tsv is not None and not df.empty:
        out_tsv.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out_tsv, sep="\t", index=False)
        print(f"wrote {out_tsv}")
    return df


if __name__ == "__main__":
    scopes = sys.argv[1:] or list(TASK_SCOPES)
    print("Task-activation test-retest reliability — ICC(2,1) of per-level task beta")
    run(scopes, out_tsv=Path("validation/results/reliability_activation.tsv"))
