#!/usr/bin/env python3
"""First-level GLM for the SpinePrep analysis.

ANALYSIS module -- not part of the preprocessing toolbox.

Fits a per-voxel task GLM in the cord, so the effect family (Cohen's d,
detectability, focality, laterality, Dice) can be aggregated to any tier. The
design is built from the VERIFIED facts in glm_spec: StartTime subtracted from
every onset, the ds004616 +2.5 s / 16 s correction, conditions from the filename
for ds005884, and TR from the sidecar (never the placeholder 1.0 s header).

Confound handling. The full slice-wise S8 design is rank-deficient on 8.7% of
runs (median 139 regressors vs 227 frames), so the whole-cord GLM uses a lean,
well-conditioned nuisance set by default -- motion, cosine drift, and the
one-hot spike columns. The question of what each confound family adds is a
SEPARATE analysis (confound_benchmark.py); mixing it into effect estimation
would confound the two. The set is configurable so the benchmark can vary it.
"""
from __future__ import annotations

import json
import re
from math import gamma
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from analysis.glm_spec import corrected_events, repetition_time_s


def spm_hrf(dt: float, length: float = 32.0) -> np.ndarray:
    """SPM canonical double-gamma HRF sampled at ``dt`` seconds."""
    t = np.arange(0, length, dt)
    a1, b1, a2, b2, c = 6.0, 1.0, 16.0, 1.0, 1.0 / 6.0
    h = (t ** (a1 - 1) * b1 ** a1 * np.exp(-b1 * t) / gamma(a1)
         - c * t ** (a2 - 1) * b2 ** a2 * np.exp(-b2 * t) / gamma(a2))
    return h / np.max(h)


def build_task_design(events: list[dict], n_vol: int, tr: float,
                      conditions: list[str]) -> tuple[np.ndarray, list[str]]:
    """HRF-convolved task regressors, one column per condition.

    ``events`` must already be corrected (glm_spec.corrected_events): onsets on
    the preprocessed clock, baseline condition removed, durations final.
    """
    dt = 0.1
    grid = np.arange(0, n_vol * tr, dt)
    hk = spm_hrf(dt)
    cols, names = [], []
    for cond in conditions:
        stick = np.zeros_like(grid)
        for e in events:
            if e["trial_type"] != cond:
                continue
            o, d = float(e["onset"]), float(e["duration"])
            stick[(grid >= o) & (grid < o + d)] = 1.0
        conv = np.convolve(stick, hk)[:len(grid)]
        cols.append(np.interp(np.arange(n_vol) * tr, grid, conv))
        names.append(cond)
    if not cols:
        return np.empty((n_vol, 0)), []
    return np.column_stack(cols), names


def lean_confounds(confounds_tsv: Path, n_vol: int) -> tuple[np.ndarray, list[str]]:
    """A well-conditioned nuisance set for a whole-cord GLM.

    Motion + cosine drift + one-hot spikes. Deliberately NOT the full slice-wise
    CSF/RETROICOR design, which is rank-deficient whole-cord; that width is the
    subject of confound_benchmark.py, not effect estimation.
    """
    if not Path(confounds_tsv).exists():
        return np.empty((n_vol, 0)), []
    df = pd.read_csv(confounds_tsv, sep="\t").iloc[:n_vol]
    keep = []
    for c in df.columns:
        cl = c.lower()
        if cl.startswith(("trans_", "rot_")) or cl.startswith("cosine") \
                or "outlier" in cl or "spike" in cl:
            keep.append(c)
    if not keep:
        return np.empty((n_vol, 0)), []
    X = df[keep].to_numpy(dtype=np.float64)
    col_mean = np.nanmean(X, axis=0)
    inds = np.where(np.isnan(X))
    X[inds] = np.take(np.nan_to_num(col_mean), inds[1])
    # drop any zero-variance column so the design stays full rank
    sd = X.std(axis=0)
    live = sd > 1e-12
    return X[:, live], [k for k, ok in zip(keep, live) if ok]


def fit_run(bold_path: Path, events_rows: list[dict], confounds_tsv: Path,
            cord_mask: np.ndarray, dataset: str, run_id: str,
            start_time_s: float,
            confound_builder=lean_confounds) -> Optional[dict]:
    """Fit the per-voxel GLM for one run; return contrast beta/t maps.

    Returns ``{"conditions", "beta", "t", "mask_idx", "shape"}`` where beta/t are
    (n_cord_voxels, n_condition) arrays, or None when the run has no modelled
    task (resting-state) or the design is unusable.
    """
    import nibabel as nib

    tr = repetition_time_s(bold_path)          # sidecar, never the header
    img = nib.load(str(bold_path))
    data = np.asarray(img.dataobj, dtype=np.float32)
    if data.ndim != 4:
        return None
    n_vol = data.shape[3]

    from analysis.glm_spec import conditions_for
    conds = conditions_for(dataset, run_id)
    ev = corrected_events(dataset, events_rows, start_time_s, run_id)
    Xtask, task_names = build_task_design(ev, n_vol, tr, conds)
    if Xtask.shape[1] == 0:
        return None                            # nothing to model (e.g. rest)

    Xn, _ = confound_builder(confounds_tsv, n_vol)
    X = np.column_stack([Xtask, Xn, np.ones(n_vol)]) if Xn.size \
        else np.column_stack([Xtask, np.ones(n_vol)])

    # rank guard: a rank-deficient design gives a non-unique fit
    if np.linalg.matrix_rank(X) < X.shape[1]:
        # fall back to task + intercept only rather than an unstable fit
        X = np.column_stack([Xtask, np.ones(n_vol)])
        if np.linalg.matrix_rank(X) < X.shape[1]:
            return None

    idx = np.argwhere(cord_mask)
    Y = data[cord_mask].T                      # (T, n_vox)
    if Y.shape[0] != n_vol:
        return None
    Y = Y - Y.mean(axis=0, keepdims=True)

    beta, resid, *_ = np.linalg.lstsq(X, Y, rcond=None)
    yhat = X @ beta
    dof = n_vol - X.shape[1]
    if dof <= 0:
        return None
    sigma2 = ((Y - yhat) ** 2).sum(axis=0) / dof
    XtX_inv = np.linalg.pinv(X.T @ X)
    n_task = len(task_names)
    beta_task = beta[:n_task]                   # (n_task, n_vox)
    t_task = np.zeros_like(beta_task)
    for k in range(n_task):
        se = np.sqrt(np.maximum(sigma2 * XtX_inv[k, k], 1e-20))
        t_task[k] = beta_task[k] / se
    return {
        "conditions": task_names,
        "beta": beta_task.T,                    # (n_vox, n_task)
        "t": t_task.T,
        "mask_idx": idx,
        "shape": cord_mask.shape,
    }
