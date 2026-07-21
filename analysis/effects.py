#!/usr/bin/env python3
"""Effect-family endpoints, aggregated from the first-level GLM to the tiers.

ANALYSIS module -- not part of the preprocessing toolbox.

Consumes glm.fit_run output + the tier parcels from driver.build_parcels, and
emits the effect family through the registry. Two levels:

  run_effects   -- per parcel, the run's contrast magnitude (parcel-mean beta/t);
                   plus cord-level focality and hemicord laterality for the run.
  group_effects -- across subjects: Cohen's d and detection fraction per parcel.

The side of a condition is read from its name (left/right, motorL/motorR), so
laterality is only emitted for conditions that carry a side. Everything returns
through record(), so an unregistered metric or an illegal tier fails loudly.
"""
from __future__ import annotations

import collections
import re
from typing import Optional

import numpy as np

from analysis.endpoints import record
from analysis import estimators as ES

# Which condition names carry a lateralised side, and which side.
_SIDE = {
    "left": "L", "right": "R",
    "motorl": "L", "motorr": "R",
    "handgraspl": "L", "handgraspr": "R",
}


def _condition_side(cond: str) -> Optional[str]:
    return _SIDE.get(cond.lower().replace("-", "").replace("_", ""))


def _parcel_mean(vec_by_voxel: np.ndarray, mask_idx: np.ndarray,
                 parcel_mask: np.ndarray) -> Optional[float]:
    """Mean of a per-cord-voxel vector over the voxels inside a parcel."""
    flat_parcel = parcel_mask[tuple(mask_idx.T)]     # (n_cord_vox,) bool
    if not flat_parcel.any():
        return None
    return float(vec_by_voxel[flat_parcel].mean())


def run_effects(glm: dict, parcels: dict, rows: list[dict], *,
                dataset: str, subject: str, session, run_id: str,
                t_threshold: float = 2.0) -> list[dict]:
    """Emit the run's effect endpoints across every tier."""
    common = dict(dataset=dataset, subject=subject, session=session,
                  run_id=run_id, mask_source="PAM50_warped")
    conds = glm["conditions"]
    beta, tmap, midx = glm["beta"], glm["t"], glm["mask_idx"]

    # per-parcel contrast magnitude, per condition
    for ci, cond in enumerate(conds):
        for tier, pmap in parcels.items():
            for pname, pmask in pmap.items():
                b = _parcel_mean(beta[:, ci], midx, pmask)
                t = _parcel_mean(tmap[:, ci], midx, pmask)
                if b is None:
                    continue
                nvox = int(pmask[tuple(midx.T)].sum())
                record(rows, **common, tier=tier, parcel=pname,
                       metric="effect_t", value=t, n=nvox, condition=cond)

    # focality: cord-level only, on the strongest condition's beta
    if "cord" in parcels:
        cordmask = parcels["cord"]["cord"]
        cord_flat = cordmask[tuple(midx.T)]
        peak = np.max(np.abs(beta), axis=1)          # per voxel, across conditions
        g = ES.gini(peak[cord_flat])
        if g is not None:
            record(rows, **common, tier="cord", parcel="cord",
                   metric="focality_gini", value=g, n=int(cord_flat.sum()))

    # Laterality: for each sided condition, ipsi vs contra hemicord ACTIVATION.
    # Computed on the count of suprathreshold (t > threshold) voxels per
    # hemicord, following Hemmerling 2023 -- NOT the mean beta over the whole
    # hemicord, which dilutes the effect across the ~230 mostly-inactive voxels
    # and drives LI toward zero. This is an activation asymmetry, not a mean.
    if "hemicord" in parcels:
        L = parcels["hemicord"].get("hemicord-L")
        R = parcels["hemicord"].get("hemicord-R")
        if L is not None and R is not None:
            for ci, cond in enumerate(conds):
                side = _condition_side(cond)
                if side is None:
                    continue
                # unilateral limb -> IPSILATERAL hemicord (same side as the limb)
                ipsi_mask = L if side == "L" else R
                contra_mask = R if side == "L" else L
                active = tmap[:, ci] > t_threshold          # positive activation
                ipsi = float(active[ipsi_mask[tuple(midx.T)]].sum())
                contra = float(active[contra_mask[tuple(midx.T)]].sum())
                li = ES.laterality_index(ipsi, contra)
                if li is not None:
                    record(rows, **common, tier="hemicord",
                           parcel=f"ipsi-{side}", metric="laterality_index",
                           value=li, n=int(ipsi + contra), condition=cond)
    return rows


def group_effects(effect_rows: list[dict], *, t_threshold: float = 2.0) -> list[dict]:
    """Across subjects: Cohen's d and detection fraction per (dataset, tier,
    parcel, condition), from the per-run effect_t rows already emitted."""
    out: list[dict] = []
    by = collections.defaultdict(dict)
    for r in effect_rows:
        if r.get("metric") != "effect_t" or r.get("value") is None:
            continue
        key = (r["dataset"], r["tier"], r["parcel"], r.get("condition"))
        # one value per subject (mean over that subject's runs)
        by[key].setdefault(r["subject"], []).append(r["value"])

    for (ds, tier, parcel, cond), subs in sorted(by.items(), key=lambda x: str(x[0])):
        vals = [float(np.mean(v)) for v in subs.values()]
        common = dict(dataset=ds, subject=None, session=None, run_id=None,
                      mask_source="PAM50_warped", condition=cond)
        d = ES.cohens_d(vals)
        if d is not None:
            record(out, **common, tier=tier, parcel=parcel,
                   metric="effect_d", value=d, n=len(vals))
        det = ES.detection_fraction(np.abs(vals), t_threshold)
        if det is not None:
            record(out, **common, tier=tier, parcel=parcel,
                   metric="detect_frac", value=det, n=len(vals),
                   threshold=t_threshold)
    return out
