#!/usr/bin/env python3
"""Distortion falsification: does image-based SyN improve fidelity or change it?

ANALYSIS module -- not part of the preprocessing toolbox. Candidate C4.

The one candidate that is a re-processing experiment, not an analysis over
existing outputs. On the CoSpine reversed-phase-encode runs (ds005883, ds005884)
the same run is corrected two ways:

  topup   the measured field from the reversed-PE pair -- the REFERENCE. This is
          the physics; where the cord should land.
  syn     image-based SyN, pretending no fieldmap exists -- the fallback most
          cord studies fall back on because they ship no fieldmap.

S5 already reports, per slice, the A-P displacement of the cord centreline from
its anat boundary, Before and After correction (displacement = 0 is perfect
alignment). Running the same run in both modes gives two After fields against the
one Before, and the falsification asks whether SyN lands where the measured field
says.

Statistics, per slice then aggregated per run:

  gap_closed_topup = disp_before - disp_after_topup        (the reference gain)
  gap_closed_syn   = disp_before - disp_after_syn
  syn_fidelity     = gap_closed_syn / gap_closed_topup     (1 = matches physics;
                     < 1 under-corrects; < 0 moves the cord the WRONG way)
  worsened_frac    = fraction of slices where SyN increased displacement

A SyN that recovers only part of the measured field, and displaces the cord
FURTHER from anatomy on a share of slices, is the falsification -- and the reason
the shipped default is `none` passthrough, not SyN.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import numpy as np

# The only datasets with reversed-PE pairs (measured field available).
REVERSED_PE_DATASETS = (
    "openneuro_ds005883_cospine_pain",
    "openneuro_ds005884_cospine_motor",
)


def _by_run(qc_path: Path) -> dict[str, dict]:
    """Map run_id -> metrics dict from an S5 qc.json."""
    out = {}
    for r in json.loads(Path(qc_path).read_text()).get("runs", []):
        rid = r.get("run_id")
        if rid and r.get("metrics"):
            out[rid] = r["metrics"]
    return out


def _aligned(topup_m: dict, syn_m: dict):
    """Per-slice (before, after_topup, after_syn) on the slices both modes
    scored. Returns three equal-length arrays or None if they do not overlap."""
    zt = topup_m.get("per_slice_z")
    zs = syn_m.get("per_slice_z")
    if not zt or not zs:
        return None
    bt = dict(zip(zt, topup_m.get("displacement_before_mm", [])))
    at = dict(zip(zt, topup_m.get("displacement_after_mm", [])))
    as_ = dict(zip(zs, syn_m.get("displacement_after_mm", [])))

    def ok(z):
        return all(z in dd and dd[z] is not None and np.isfinite(dd[z])
                   for dd in (bt, at, as_))
    zc = [z for z in zt if ok(z)]
    if not zc:
        return None
    before = np.array([bt[z] for z in zc], float)
    a_topup = np.array([at[z] for z in zc], float)
    a_syn = np.array([as_[z] for z in zc], float)
    return before, a_topup, a_syn


def compare_run(topup_m: dict, syn_m: dict, run_id: str,
                dataset: str) -> Optional[dict]:
    """One run's falsification statistics from its two corrected qc metrics."""
    al = _aligned(topup_m, syn_m)
    if al is None:
        return None
    before, a_topup, a_syn = al
    # magnitudes: displacement is a distance from the anat boundary
    b, t, s = np.abs(before), np.abs(a_topup), np.abs(a_syn)
    gap_topup = b - t                       # per slice, the reference gain
    gap_syn = b - s
    # run-level fidelity on summed gains (robust to per-slice sign noise)
    denom = gap_topup.sum()
    fidelity = float(gap_syn.sum() / denom) if abs(denom) > 1e-6 else None
    worsened = float(np.mean(s > b))        # SyN pushed further from anatomy
    return {
        "dataset": dataset, "run_id": run_id, "n_slices": int(b.size),
        "disp_before_mm": float(b.mean()),
        "disp_after_topup_mm": float(t.mean()),
        "disp_after_syn_mm": float(s.mean()),
        "gap_closed_topup_mm": float(gap_topup.mean()),
        "gap_closed_syn_mm": float(gap_syn.mean()),
        "syn_fidelity": fidelity,
        "worsened_frac": worsened,
    }


def compare_cohort(topup_qc: Path, syn_qc: Path, dataset: str) -> list[dict]:
    """Every run scored in both modes: the per-run falsification table."""
    tu, sy = _by_run(topup_qc), _by_run(syn_qc)
    rows = []
    for rid in sorted(set(tu) & set(sy)):
        r = compare_run(tu[rid], sy[rid], rid, dataset)
        if r is not None:
            rows.append(r)
    return rows


def summarise(rows: list[dict]) -> dict:
    """Cohort headline: median SyN fidelity and the worsened-slice share."""
    if not rows:
        return {"n_runs": 0}

    def med(key):
        v = [r[key] for r in rows if r.get(key) is not None and np.isfinite(r[key])]
        return float(np.median(v)) if v else None
    return {
        "n_runs": len(rows),
        "median_syn_fidelity": med("syn_fidelity"),
        "median_worsened_frac": med("worsened_frac"),
        "median_disp_after_topup_mm": med("disp_after_topup_mm"),
        "median_disp_after_syn_mm": med("disp_after_syn_mm"),
    }
