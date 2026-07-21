#!/usr/bin/env python3
"""Confound-family importance: the cord-first Ciric 2017 / Parkes 2018 benchmark.

ANALYSIS module -- not part of the preprocessing toolbox. Candidate C5.

S8 EMITS six confound families into the timeseries table WITHOUT regressing them
from the BOLD (the pipeline keeps the signal clean of nuisance choices). That
makes the whole importance grid an analysis over the existing table: fix
everything upstream, vary only the confound model, refit, and score on
ground-truth-free metrics. No re-runs.

The families, from the real column names in the S8 table:

  motion     trans_* / rot_* and their derivatives     (rigid-body + temporal)
  spike      motion_outlier_*                           (one-hot frame censors)
  cosine     cosine_*                                   (high-pass drift basis)
  csf        csf_sliceNN_pc*                            (slice-wise aCompCor)
  retroicor  retroicor_*                                (RETROICOR physio)
  (spinalcompcor: shipped OFF -- Hemmerling 2025 found no task benefit)

Scoring, both sides always (Bright & Murphy 2015: every gain is reported net of
the degrees of freedom it spends, because even random regressors remove
structured variance):

  sensitivity     mean top-decile |t| of the task contrast in the cord (TASK)
  dvars_resid     median DVARS of the GLM residual (noise left behind)
  dof_spent       regressors + censored frames
  benefit_per_dof (sensitivity gain over the motion-only baseline) / dof_spent

QC-FC and its distance dependence need resting-state connectivity and only two
datasets have rest, so they run as a separate rest-only sub-analysis, not forced
onto the task cohort.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

import numpy as np
import pandas as pd

from analysis.glm import fit_run

# family name -> predicate on a lower-cased column name
FAMILIES: dict[str, Callable[[str], bool]] = {
    "motion":    lambda c: c.startswith(("trans_", "rot_")),
    "spike":     lambda c: "motion_outlier" in c or "outlier" in c or "spike" in c,
    "cosine":    lambda c: c.startswith("cosine"),
    "csf":       lambda c: c.startswith("csf_slice") or "a_comp_cor" in c,
    "retroicor": lambda c: c.startswith("retroicor"),
}

# The grids reported: an add-one ladder from the motion baseline, and a
# leave-one-out from the full model. "motion" always stays in (rigid-body motion
# is not an optional family for cord fMRI).
BASELINE = ("motion", "spike", "cosine")
FULL = ("motion", "spike", "cosine", "csf", "retroicor")


def family_builder(families: tuple) -> Callable[[Path, int], tuple]:
    """A confound_builder for glm.fit_run that keeps only the named families."""
    preds = [FAMILIES[f] for f in families if f in FAMILIES]

    def build(confounds_tsv: Path, n_vol: int):
        if not Path(confounds_tsv).exists():
            return np.empty((n_vol, 0)), []
        df = pd.read_csv(confounds_tsv, sep="\t").iloc[:n_vol]
        keep = [c for c in df.columns
                if any(p(c.lower()) for p in preds)]
        if not keep:
            return np.empty((n_vol, 0)), []
        X = df[keep].to_numpy(dtype=np.float64)
        col_mean = np.nanmean(X, axis=0)
        nanpos = np.where(np.isnan(X))
        X[nanpos] = np.take(np.nan_to_num(col_mean), nanpos[1])
        sd = X.std(axis=0)
        live = sd > 1e-12
        return X[:, live], [k for k, ok in zip(keep, live) if ok]

    return build


def _sensitivity(glm: dict) -> Optional[float]:
    """Mean of the top-decile |t| across cord voxels and conditions."""
    if glm is None:
        return None
    t = np.abs(glm["t"]).ravel()
    if t.size == 0:
        return None
    k = max(1, int(0.10 * t.size))
    return float(np.sort(t)[-k:].mean())


def _dvars_resid(bold_path: Path, cord_mask: np.ndarray, X: np.ndarray) -> Optional[float]:
    """Median DVARS of the residual after projecting the design out of the cord."""
    import nibabel as nib
    data = np.asarray(nib.load(str(bold_path)).dataobj, dtype=np.float32)
    if data.ndim != 4 or data.shape[3] != X.shape[0]:
        return None
    Y = data[cord_mask].T.astype(np.float64)        # (T, vox)
    Y = Y - Y.mean(axis=0, keepdims=True)
    resid = Y - X @ np.linalg.lstsq(X, Y, rcond=None)[0]
    d = np.sqrt((np.diff(resid, axis=0) ** 2).mean(axis=1))
    return float(np.median(d)) if d.size else None


def benchmark_run(bold_path, events_rows, confounds_tsv, cord_mask,
                  dataset, run_id, start_time_s,
                  grids: Optional[list[tuple]] = None) -> list[dict]:
    """Score each confound configuration on one run.

    Returns one row per configuration with sensitivity, residual DVARS, DOF
    spent, and benefit-per-DOF relative to the motion-only baseline.
    """
    if grids is None:
        # add-one ladder + leave-one-out from FULL
        grids = [("motion",), BASELINE, FULL]
        for f in ("csf", "retroicor", "spike", "cosine"):
            grids.append(tuple(x for x in FULL if x != f))
    rows: list[dict] = []
    base_sens = None
    n_vol_holder = {}
    for fams in grids:
        builder = family_builder(fams)
        glm = fit_run(bold_path, events_rows, confounds_tsv, cord_mask,
                      dataset, run_id, start_time_s, confound_builder=builder)
        if glm is None:
            continue
        n_vol = _nvol(bold_path)
        Xn, names = builder(confounds_tsv, n_vol)
        sens = _sensitivity(glm)
        dof = len(names)
        # rebuild the actual fitted design to score residual DVARS honestly
        dv = None
        if sens is not None:
            dv = _dvars_resid(bold_path, cord_mask, _design_for(
                bold_path, events_rows, confounds_tsv, cord_mask, dataset,
                run_id, start_time_s, builder))
        if fams == ("motion",):
            base_sens = sens
        bpd = None
        if sens is not None and base_sens not in (None, 0) and dof > 0:
            bpd = (sens - base_sens) / dof
        rows.append({
            "dataset": dataset, "run_id": run_id,
            "families": "+".join(fams), "n_families": len(fams),
            "sensitivity": sens, "dvars_resid": dv,
            "dof_spent": dof, "benefit_per_dof": bpd,
        })
    return rows


def _nvol(bold_path) -> int:
    import nibabel as nib
    return int(nib.load(str(bold_path)).shape[3])


def _design_for(bold_path, events_rows, confounds_tsv, cord_mask, dataset,
                run_id, start_time_s, builder) -> np.ndarray:
    """Reconstruct the exact design fit_run used, for residual scoring."""
    from analysis.glm import build_task_design
    from analysis.glm_spec import conditions_for, corrected_events, repetition_time_s
    n_vol = _nvol(bold_path)
    tr = repetition_time_s(bold_path)
    conds = conditions_for(dataset, run_id)
    ev = corrected_events(dataset, events_rows, start_time_s, run_id)
    Xtask, _ = build_task_design(ev, n_vol, tr, conds)
    Xn, _ = builder(confounds_tsv, n_vol)
    X = np.column_stack([Xtask, Xn, np.ones(n_vol)]) if Xn.size \
        else np.column_stack([Xtask, np.ones(n_vol)])
    if np.linalg.matrix_rank(X) < X.shape[1]:
        X = np.column_stack([Xtask, np.ones(n_vol)])
    return X
